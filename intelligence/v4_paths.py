"""Prospective triple-barrier BID paths; delayed asks, no future-selected entries."""
from scanner import fee
from .economics import executable
from .early_exit import settings,target_bid
from .storage import dumps


def verified(s):
    return bool(s and s.get('book') and s.get('book_event_verified') and s.get('fee_valid') and s.get('spot_status')=='LIVE' and 0<=s['now']-s.get('book_event_ts',0)<=1 and 0<=s['now']-s.get('quote_ts',0)<=3)


def quotes(s,quantity=1,goal=.65):
    out=[]
    for side in ('UP','DOWN'):
        r={'side':side,'status':'UNVERIFIED','guidance':'WAIT','horizon':None,'estimated_exit_bid':None,'confidence':'INSUFFICIENT FORWARD VALIDATION'}
        if verified(s):
            try:
                ask=executable(s['book'],side,'buy',quantity,slippage=0);entry=executable(s['book'],side,'buy',quantity);bid=executable(s['book'],side,'sell',quantity);ef=fee(entry,quantity,.07,s['fee_multiplier']);xf=fee(bid,quantity,.07,s['fee_multiplier']);cost=entry*quantity+ef;net=bid*quantity-xf-cost;target=target_bid(entry,quantity,ef,goal,s['fee_multiplier'])
                r.update(status='LIVE OBSERVED QUOTES — TARGET UNVALIDATED',ask=ask,bid=bid,entry_cost=cost,entry_fee=ef,exit_fee=xf,net=net,roi=net/cost,gross_roi=(bid-entry)/entry,goal=goal,target_bid=target,spread=s['book'].spread,depth_quantity_checked=quantity,remaining=s['market']['closed']-s['now'],target_status='IMPOSSIBLE' if target is None else 'CONDITIONAL REQUIRED BID',gross_settlement_multiplier=1/ask,guidance='AVOID' if target is None else 'WAIT')
            except ValueError:r['status']='INSUFFICIENT EXECUTABLE DEPTH'
        out.append(r)
    return out


def observe(db,s):
    now=s['now'];ticker=s['market']['ticker'];valid=verified(s);event=s.get('book_event_ts')
    pending=db.execute("SELECT * FROM v4_profit_paths WHERE state IN ('WAIT_ENTRY','OPEN') ORDER BY id").fetchall()
    for r in pending:
        if r['ticker']!=ticker:
            if now>=r['closed']:
                with db:db.execute("UPDATE v4_profit_paths SET state='UNVERIFIED',coverage='MISSING_FINAL_OR_ROLLOVER' WHERE id=?",(r['id'],))
            continue
        if r['state']=='WAIT_ENTRY':
            if now>r['entry_due']+2:
                with db:db.execute("UPDATE v4_profit_paths SET state='UNVERIFIED',coverage='MISSED_DELAYED_ENTRY' WHERE id=?",(r['id'],))
            elif valid and event>=r['entry_due']:
                try:entry=executable(s['book'],r['side'],'buy',r['quantity'])
                except ValueError:continue
                with db:db.execute("UPDATE v4_profit_paths SET state='OPEN',entry=?,filled=?,last_event=?,coverage='CONTINUOUS OBSERVED BOOK' WHERE id=?",(entry,event,event,r['id']))
            continue
        if not valid or event<r['last_event'] or event-r['last_event']>2:
            if now-r['last_event']>2:
                with db:db.execute("UPDATE v4_profit_paths SET state='UNVERIFIED',coverage='BOOK_GAP' WHERE id=?",(r['id'],))
            continue
        try:bid=executable(s['book'],r['side'],'sell',r['quantity'])
        except ValueError:
            with db:db.execute("UPDATE v4_profit_paths SET state='UNVERIFIED',coverage='INSUFFICIENT_EXIT_DEPTH' WHERE id=?",(r['id'],))
            continue
        cost=r['entry']*r['quantity']+fee(r['entry'],r['quantity'],.07,r['multiplier']);net=bid*r['quantity']-fee(bid,r['quantity'],.07,r['multiplier'])-cost;roi=net/cost
        top=max(r['max_roi'] if r['max_roi'] is not None else roi,roi);state='OPEN';barrier=None
        if roi>=r['goal']:state='GOAL HIT';barrier='TARGET_FIRST'
        elif roi<=r['stop']:state='NO PROFIT';barrier='STOP_FIRST'
        elif event>=r['closed']-2:state='PROFITABLE' if top>0 else 'NO PROFIT';barrier='TIME'
        with db:db.execute('UPDATE v4_profit_paths SET state=?,last_event=?,max_roi=?,hit=?,barrier=?,last_bid=? WHERE id=?',(state,event,top,event if state=='GOAL HIT' else None,barrier,bid,r['id']))
    # Predeclared sampling: both sides once per market-minute, even if outcome unfavorable.
    if valid and s['market']['closed']-now>=30:
        bucket=int(now//60)*60
        for r in quotes(s,goal=settings(db)['target_roi']):
            if 'ask' not in r:continue
            exists=db.execute('SELECT 1 FROM v4_profit_paths WHERE ticker=? AND side=? AND issued>=?',(ticker,r['side'],bucket)).fetchone()
            if exists:continue
            with db:db.execute('INSERT INTO v4_profit_paths(ticker,side,issued,entry_due,closed,ask,quantity,entry_fee,multiplier,goal,stop,version,provenance) VALUES(?,?,?,?,?,?,1,?,?,?,-.25,?,?)',(ticker,r['side'],now,now+2,s['market']['closed'],r['ask'],r['entry_fee'],s['fee_multiplier'],r['goal'],'triple-barrier-bid-v4','Sequenced event-time Kalshi book; 2s delayed ask; taker fees + .002 slippage per fill'))


def summary(db):
    return {'definition':'Prospective both-side, once/minute hypotheses; 2s delayed actual ask, verified sellable bid, goal / -25% stop / round end first. A goal touch is not a realized sale. Book gaps unverified. Correlated samples are not independent trading wins.','counts':[dict(r) for r in db.execute('SELECT state,count(*) n FROM v4_profit_paths GROUP BY state')],'rows':[dict(r) for r in db.execute('SELECT * FROM v4_profit_paths ORDER BY id DESC LIMIT 50')]}


def path_forecast(db,s,side,goal):
    """Research-only first-barrier frequency, one predeclared observation per market.
    Entry and remaining-time bins are fixed ex ante; no best-horizon hunting.
    """
    import statistics,math
    q=next(r for r in quotes(s,goal=goal) if r['side']==side)
    if 'ask' not in q:return {'status':'INSUFFICIENT DATA','validated':False}
    bucket=int(q['ask']*10);timebin=int((s['market']['closed']-s['now'])//300)
    rows=db.execute("SELECT * FROM v4_profit_paths WHERE side=? AND goal=? AND issued<? ORDER BY issued",(side,goal,s['now'])).fetchall();selected={}
    for r in rows:
        if int(r['ask']*10)!=bucket or int((r['closed']-r['issued'])//300)!=timebin:continue
        selected.setdefault(r['ticker'],r)
    allrows=list(selected.values());complete=[r for r in allrows if r['state'] in ('GOAL HIT','PROFITABLE','NO PROFIT') and r['last_bid'] is not None and r['entry'] is not None]
    base={'validated':False,'status':'INSUFFICIENT INDEPENDENT FORWARD MARKETS','n':len(complete),'required':200,'definition':'Target before -25% stop or round end; not settlement accuracy; one earliest comparable hypothesis per market','production':'SHADOW ONLY — no automatic model promotion'}
    if len(complete)<200 or len(complete)/max(1,len(allrows))<.98:return base
    split=int(len(complete)*.7);train,test=complete[:split],complete[split:]
    # Prior labels must be final before held-out decisions. Purge overlapping market windows.
    train=[r for r in train if r['closed']<test[0]['issued']]
    if len(train)<100 or len(test)<60:return base
    p=sum(r['state']=='GOAL HIT' for r in train)/len(train);actual=sum(r['state']=='GOAL HIT' for r in test)/len(test)
    returns=[]
    for r in test:
        cost=r['entry']*r['quantity']+fee(r['entry'],r['quantity'],.07,r['multiplier']);net=r['last_bid']*r['quantity']-fee(r['last_bid'],r['quantity'],.07,r['multiplier'])-cost;returns.append(net/cost)
    uncertainty=1.96*math.sqrt(max(.001,p*(1-p))/len(test));calibrated=abs(p-actual)<=.15
    base.update(validated=calibrated,status='HELD-OUT RESEARCH ONLY' if calibrated else 'CALIBRATION FAILED',train_n=len(train),test_n=len(test),p_goal_before_stop=p,heldout_frequency=actual,uncertainty=uncertainty,heldout_mean_roi=statistics.mean(returns),heldout_roi_lower=statistics.mean(returns)-1.96*statistics.stdev(returns)/math.sqrt(len(returns)),train_end=max(r['closed'] for r in train),test_start=test[0]['issued'])
    return base
