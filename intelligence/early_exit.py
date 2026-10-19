"""Net-on-stake goals and prospective executable-bid endpoint research. No orders."""
import math
import statistics
from scanner import fee
from .economics import executable
from .storage import dumps,loads

HORIZONS=(20,40,60,120,180)

def target_bid(entry,quantity=1,entry_fee=None,roi=.65,multiplier=1,slippage=.002):
    if not 0<entry<1 or quantity<=0 or not 0<=roi<=3:raise ValueError('Invalid entry, quantity or ROI')
    ef=fee(entry,quantity,.07,multiplier) if entry_fee is None else entry_fee
    cost=entry*quantity+ef
    def net(bid):
        exit=max(.000001,bid-slippage);return quantity*(exit-entry)-ef-fee(exit,quantity,.07,multiplier)
    if net(.999)<roi*cost:return None
    lo,hi=.001,.999
    for _ in range(45):
        mid=(lo+hi)/2
        if net(mid)>=roi*cost:hi=mid
        else:lo=mid
    return hi

def settings(db):
    out={'target_roi':.65,'milestones':[.1,.25,.5,.6,.65,.75,.9]}
    for r in db.execute('SELECT name,value FROM v3_settings'):
        if r['name']=='target_roi':out['target_roi']=float(loads(r['value']))
    return out

def set_target(db,value,now):
    if type(value) not in (int,float) or not math.isfinite(value) or not .05<=value<=.9:raise ValueError('Net-on-stake target must be between5% and90%')
    with db:db.execute("INSERT INTO v3_settings VALUES('target_roi',?,?) ON CONFLICT(name) DO UPDATE SET value=excluded.value,updated=excluded.updated",(dumps(value),now))
    return settings(db)

def add_watch(db,values,now):
    if not isinstance(values,dict) or set(values)-{'ticker','side','entry','quantity','entry_fee','target_roi'}:raise ValueError('Unknown watch-position fields')
    ticker=values.get('ticker','');side=values.get('side');entry=values.get('entry');q=values.get('quantity',1);ef=values.get('entry_fee');roi=values.get('target_roi',settings(db)['target_roi'])
    if not isinstance(ticker,str) or not ticker.startswith('KXBTC15M-') or len(ticker)>100 or side not in ('UP','DOWN'):raise ValueError('A valid KXBTC15M ticker and UP/DOWN side are required')
    if any(type(x) not in (int,float) or not math.isfinite(x) for x in (entry,q,ef,roi)) or not 0<entry<1 or not 0<q<=10000 or ef<0 or ef>q or not .05<=roi<=.9:raise ValueError('Supply entry price, quantity, total entry fee and5–90% net goal; no account data is read')
    if db.execute("SELECT count(*) FROM v3_watch_positions WHERE state='WATCHING'").fetchone()[0]>=10:raise ValueError('At most10 watch positions')
    with db:
        cur=db.execute('INSERT INTO v3_watch_positions(ticker,side,entry,quantity,entry_fee,created,target_roi) VALUES(?,?,?,?,?,?,?)',(ticker,side,entry,q,ef,now,roi))
    return cur.lastrowid

def watches(db,s,notify=None):
    output=[]
    for row in db.execute("SELECT * FROM v3_watch_positions WHERE state='WATCHING' ORDER BY id").fetchall():
        r=dict(row);r['status']='QUOTE UNAVAILABLE';r['target_bid']=None
        if s and s['market']['ticker']==r['ticker'] and s.get('fee_valid') and s.get('book_event_verified') and 0<=s['now']-s.get('book_ts',0)<=1:
            try:
                bid=executable(s['book'],r['side'],'sell',r['quantity'],slippage=0);exit=executable(s['book'],r['side'],'sell',r['quantity'])
                f=fee(exit,r['quantity'],.07,s['fee_multiplier']);net=r['quantity']*(exit-r['entry'])-r['entry_fee']-f;cost=r['entry']*r['quantity']+r['entry_fee'];roi=net/cost
                target=target_bid(r['entry'],r['quantity'],r['entry_fee'],r['target_roi'],s['fee_multiplier'])
                r.update(status='LIVE USER-SUPPLIED BASIS',bid=bid,net=net,roi=roi,target_bid=target,time_remaining=s['market']['closed']-s['now'])
                notified=set(loads(r['notified']));milestones=settings(db)['milestones']+[r['target_roi']]
                for milestone in sorted(set(milestones)):
                    key='roi:'+str(milestone)
                    if roi>=milestone and key not in notified:
                        if notify:
                            text=f"EXIT WATCH · {r['side']} · +{roi:.0%} net on supplied stake\nSellable bid ${bid:.3f}; net ${net:.2f} after estimated exit costs.\nGoal +{r['target_roi']:.0%}; recheck current bid/depth. Manual exit only.\n{r['ticker']} · {r['time_remaining']:.0f}s left · book age {s['now']-s['book_ts']:.1f}s"
                            if notify.enqueue('exit',r['ticker'],f"watch:{r['id']}:{key}",text,s['now'],s['now']+5,scope=f"watch:{r['id']}:{key}"):notified.add(key)
                # Risk warning is based on the entered basis, not on an account position.
                if (roi<=-.25 or r['time_remaining']<90) and 'risk' not in notified and notify:
                    if notify.enqueue('exit',r['ticker'],f"watch:{r['id']}:risk",f"RISK WATCH · {r['side']}\nSupplied-basis return {roi:.0%}; {r['time_remaining']:.0f}s left. Recheck liquidity and your exit plan.\n{r['ticker']} · manual only",s['now'],s['now']+5,scope=f"watch:{r['id']}:risk"):notified.add('risk')
                with db:db.execute('UPDATE v3_watch_positions SET last_bid=?,last_ts=?,last_net=?,last_roi=?,notified=? WHERE id=?',(bid,s['now'],net,roi,dumps(sorted(notified)),r['id']))
            except (ValueError,TypeError):r['status']='INSUFFICIENT EXECUTABLE DEPTH'
        output.append(r)
    return output

class BidResearch:
    def __init__(self,db):self.db=db;self.last_sample={};self.last_event={};self.cache={};self.refreshed=0
    def observe(self,s):
        now=s['now'];ticker=s['market']['ticker'];event=s.get('book_event_ts');valid=s.get('book_event_verified') and s.get('fee_valid') and event is not None and 0<=now-event<=1
        with self.db:
            self.db.execute("UPDATE v3_contract_samples SET state='MISSED' WHERE state='PENDING' AND due+2<?",(now,))
            if not valid:
                self.db.execute("UPDATE v3_contract_samples SET state='GAPPED' WHERE ticker=? AND state='PENDING' AND observed+2<?",(ticker,now));return
        previous=self.last_event.get(ticker)
        if previous is not None and event-previous>2:
            with self.db:self.db.execute("UPDATE v3_contract_samples SET state='GAPPED' WHERE ticker=? AND state='PENDING'",(ticker,))
        self.last_event[ticker]=event
        for r in self.db.execute("SELECT * FROM v3_contract_samples WHERE ticker=? AND state='PENDING' AND due<=?",(ticker,event)).fetchall():
            if event>r['due']+2:continue
            try:
                bid=executable(s['book'],r['side'],'sell',slippage=0);exit=executable(s['book'],r['side'],'sell');ef=fee(exit,1,.07,r['multiplier']);net=exit-r['entry_ask']-.002-r['entry_fee']-ef
            except ValueError:continue
            with self.db:self.db.execute("UPDATE v3_contract_samples SET state='OBSERVED',bid=?,exit_fee=?,outcome_ts=?,net=? WHERE id=?",(bid,ef,event,net,r['id']))
        if now-self.last_sample.get(ticker,0)<30:return
        self.last_sample[ticker]=now
        for side in ('UP','DOWN'):
            try:ask=executable(s['book'],side,'buy',slippage=0);entry=executable(s['book'],side,'buy');ef=fee(entry,1,.07,s['fee_multiplier'])
            except ValueError:continue
            for horizon in HORIZONS:
                if s['market']['closed']-now<horizon+30:continue
                with self.db:self.db.execute('INSERT OR IGNORE INTO v3_contract_samples(ticker,side,observed,entry_ask,entry_fee,multiplier,horizon,due,spread,imbalance,btc_velocity,regime) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(ticker,side,now,ask,ef,s['fee_multiplier'],horizon,now+horizon,s['book'].spread,s['book'].imbalance,(s.get('tick_metrics') or {}).get('velocity'),(s.get('regime') or {}).get('regime','UNKNOWN')))
    def forecast(self,s):
        if not s.get('fee_valid') or not s.get('book_event_verified'):
            return {side:{'validated':False,'reason':'Verified event-time orderbook and fees required'} for side in ('UP','DOWN')}
        now=s['now'];out={};goal=settings(self.db)['target_roi']
        for side in ('UP','DOWN'):
            try:ask=executable(s['book'],side,'buy',slippage=0);bid=executable(s['book'],side,'sell',slippage=0);executable(s['book'],side,'buy');executable(s['book'],side,'sell')
            except (ValueError,KeyError):out[side]={'validated':False,'reason':'Executable depth unavailable'};continue
            possibilities=[]
            for horizon in HORIZONS:
                rows=[dict(r) for r in self.db.execute("SELECT * FROM v3_contract_samples WHERE side=? AND horizon=? AND due<? AND entry_ask>=? AND entry_ask<? ORDER BY observed DESC LIMIT 3000",(side,horizon,now,math.floor(ask*10)/10,math.floor(ask*10)/10+.1))][::-1]
                selected=[];end=0
                for r in rows:
                    if r['state']=='OBSERVED' and r['outcome_ts']<now and r['observed']>end:selected.append(r);end=r['outcome_ts']
                item={'validated':False,'horizon':horizon,'samples':len(selected),'reason':'Need200 nonoverlapping observed comparable entry-price-bin samples,60 chronological test outcomes and >=98% coverage','target_roi':goal}
                if len(selected)<200 or sum(r['state']=='OBSERVED' for r in rows)/max(1,len(rows))<.98:possibilities.append(item);continue
                n=int(len(selected)*.7);train,test=selected[:n],selected[n:]
                # Predict executable future bid relative to the signal-time ask. Fit TRAIN only.
                returns=sorted(r['bid']-r['entry_ask'] for r in train)
                lo,mid,hi=returns[int(.1*(len(returns)-1))],statistics.median(returns),returns[int(.9*(len(returns)-1))]
                coverage=sum(lo<=r['bid']-r['entry_ask']<=hi for r in test)/len(test)
                nets=[r['net'] for r in test];mean=statistics.mean(nets);margin=1.96*statistics.stdev(nets)/len(nets)**.5
                validated=.7<=coverage<=.98 and len(test)>=60
                target=target_bid(ask+.002,roi=goal,multiplier=s.get('fee_multiplier',1))
                goal_frequency=sum(v>=target-ask for v in returns)/len(returns) if target is not None else 0
                goal_test=sum(r['bid']-r['entry_ask']>=target-ask for r in test)/len(test) if target is not None else 0
                validated=validated and abs(goal_frequency-goal_test)<=.15
                current_nets=[]
                for delta in returns:
                    sell=max(.001,min(.997,ask+delta-.002));current_nets.append(sell-ask-.002-fee(ask+.002,1,.07,s.get('fee_multiplier',1))-fee(sell,1,.07,s.get('fee_multiplier',1)))
                current_mean=statistics.mean(current_nets)
                # Penalize train/test drift instead of advertising the best held-out horizon.
                drift=abs(statistics.mean(r['net'] for r in train)-mean);lower=min(mean-margin,current_mean-margin-drift);upper=current_mean+margin+drift
                item.update(validated=validated,reason='Train-only empirical bid-return interval; chronological held-out coverage checked. Comparable prices do not eliminate regime risk.',holdout=len(test),coverage=coverage,expected_net_lower=lower,expected_net_upper=upper,mean_net=current_mean,median_exit_bid=max(.001,min(.999,ask+mid)),exit_bid_range=[max(.001,ask+lo),min(.999,ask+hi)],target_bid=target,goal_endpoint_frequency=goal_frequency,probability_label='Training frequency at the ENDPOINT, not probability of touching target anytime',entry_ask=ask,current_bid=bid,entry_multiplier=1/ask,exit_multiplier=1/max(.001,ask+mid),test_start=test[0]['observed'],trained_through=train[-1]['outcome_ts'])
                possibilities.append(item)
            supported=[r for r in possibilities if r.get('validated')]
            out[side]=min(supported,key=lambda r:((60,40,20,120,180).index(r['horizon']))) if supported else {'validated':False,'reason':'Insufficient validated sellable-bid outcomes','horizons':possibilities}
        return out
