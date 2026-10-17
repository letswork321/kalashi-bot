"""Executable-depth economics. Scenarios are conditional, never guaranteed fills."""
import statistics
from scanner import fee,Book

def executable(book,side,action,quantity=1,slippage=.002):
    if not book or quantity<=0:raise ValueError('Book/quantity unavailable')
    levels=(book.no if side=='UP' else book.yes) if action=='buy' else (book.yes if side=='UP' else book.no)
    remaining=quantity;cost=0
    for price,size in levels:
        taken=min(remaining,size);cost+=taken*((1-price) if action=='buy' else price);remaining-=taken
        if remaining<=1e-9:
            value=cost/quantity+(slippage if action=='buy' else -slippage)
            if not 0<value<1:raise ValueError('Slippage-adjusted price outside valid contract bounds')
            return value
    raise ValueError('Insufficient visible executable depth')

def side_history(s,side,seconds=60):
    return [r for r in s.get('book_history',[]) if r['ticker']==s['market']['ticker'] and s['now']-seconds<=r['ts']<=s['now'] and r.get('side')==side]

def flip_radar(s):
    output=[];now=s['now'];m=s.get('market',{})
    for side in ('UP','DOWN'):
        r={'side':side,'status':'STALE','timestamp':now,'reason':'Fresh two-sided executable book required','risk':'HIGH','time_remaining':m.get('closed',now)-now}
        try:
            if s.get('fee_valid') is False:raise ValueError('Current fee schedule unverified; cost analytics unavailable')
            if now-s.get('book_ts',0)>3 or not 0<=now-s.get('quote_ts',0)<=3:raise ValueError('Fresh inputs unavailable')
            raw_entry=executable(s['book'],side,'buy',slippage=0);raw_exit=executable(s['book'],side,'sell',slippage=0)
            entry=raw_entry+.002;exit=raw_exit-.002
            if not 0<exit<1 or not 0<entry<1:raise ValueError('Slippage-adjusted price outside contract bounds')
            mult=s.get('fee_multiplier',1)
            f1=fee(entry,1,.07,mult);f2=fee(exit,1,.07,mult)
            history=side_history(s,side)
            velocity=(history[-1]['bid']-history[0]['bid'])/(history[-1]['ts']-history[0]['ts']) if len(history)>=3 and history[-1]['ts']-history[0]['ts']>=20 else None
            movement=max(.03,min(.15,(velocity or 0)*60))
            target=min(.999,raw_exit+movement)
            hypothetical=target-.002-entry-f1-fee(target-.002,1,.07,mult)
            immediate=exit-entry-f1-f2
            spread=s['book'].spread
            technical=(s.get('baseline') or {}).get('features',{})
            momentum=technical.get('momentum_3m');volatility=technical.get('volatility_1m')
            aligned=momentum is not None and momentum*(1 if side=='UP' else -1)>=0
            status='NOT ECONOMIC' if hypothetical<=0 or spread>.08 or r['time_remaining']<120 else 'POTENTIAL OPPORTUNITY' if velocity and velocity>0 and hypothetical>=.01 and movement<=velocity*60 and len(history)>=3 else 'WATCH'
            if status=='POTENTIAL OPPORTUNITY' and not aligned:status='WATCH'
            r.update(observed_entry_ask=raw_entry,observed_exit_bid=raw_exit,slippage_per_leg=.002,btc_momentum_3m=momentum,btc_volatility_1m=volatility,orderbook_imbalance=s['book'].imbalance,btc_direction_aligned=aligned,execution_latency=s.get('book_latency'),status=status,entry=entry,executable_exit=exit,entry_fee=f1,exit_fee=f2,immediate_net=immediate,possible_exit_target=target,required_bid_movement=target-raw_exit,conditional_net=hypothetical,holding_seconds=60,quantity=1,spread=spread,price_velocity_per_second=velocity,risk='HIGH' if spread>.03 or not aligned or (volatility or 0)>.001 else 'MEDIUM',reason='Conditional target based on observed bid velocity; it is not an executable future quote or a calibrated profit prediction. Both legs pay estimated taker fees/slippage.',liquidity='One contract depth verified',book_age=now-s['book_ts'],execution_delay_seconds=2)
        except (ValueError,KeyError,TypeError) as exc:r['reason']=str(exc)
        output.append(r)
    return {'name':'FLIP RADAR','rows':output,'timestamp':now,'source':s.get('book_source','REST'),'note':'56 cents has no special economic status. Only observed bids can realize simulated exits.'}

def scalp_radar(s):
    rows=[]
    history=s.get('book_history',[])
    update_times=sorted({r['ts'] for r in history if r['ts']>=s['now']-20})
    cadence_ok=len(update_times)>=20 and update_times[-1]-update_times[0]>=10 and max(b-a for a,b in zip(update_times,update_times[1:]))<=2
    highrate=cadence_ok and s.get('tick_metrics') is not None and s.get('book_latency',99)<=1 and s.get('book_source')=='websocket' and s['now']-s.get('book_ts',0)<=1 and s.get('ws_sequence_valid') and len({r['ts'] for r in history if r['ts']>=s['now']-20})>=20
    for hold in (20,40,60):
        if not highrate:
            rows.append({'window':hold,'status':'FASTER MARKET DATA REQUIRED','reason':'Public REST cadence does not validate sub-minute executable exits; authenticated sequenced Kalshi book updates and sufficient observed cadence required.'});continue
        r=flip_radar(s)
        best=max((x for x in r['rows'] if 'conditional_net' in x),key=lambda x:x['conditional_net'],default=None)
        if not best:rows.append({'window':hold,'status':'AVOID','reason':'Fresh executable quotes unavailable'});continue
        velocity=best.get('price_velocity_per_second') or 0
        target=min(.999,best['observed_exit_bid']+min(.15,max(0,velocity*hold)))
        net=target-.002-best['entry']-best['entry_fee']-fee(target-.002,1,.07,s.get('fee_multiplier',1))
        status='OPPORTUNITY' if net>=.01 and best['spread']<=.02 and best['time_remaining']>hold+20 else 'WATCH' if velocity>0 and best['spread']<=.04 else 'AVOID'
        rows.append({**best,'btc_tick_metrics':s.get('tick_metrics'),'window':hold,'status':status,'possible_exit_target':target,'required_bid_movement':target-best['observed_exit_bid'],'holding_seconds':hold,'conditional_net':net,'reason':'Sequenced live-book cadence verified; extrapolated exit remains conditional. Fill only after observed delayed ask/bid with depth.'})
    return {'name':'SCALP RADAR','rows':rows,'timestamp':s['now'],'validated_profitability':False}

def fair_value(s,candidate):
    if not 0<=s['now']-s.get('quote_ts',0)<=3 or not 0<=s['now']-s.get('book_ts',0)<=3:return {'status':'INSUFFICIENT DATA','reason':'Stale executable inputs','rows':[]}
    if not candidate or not candidate.get('validated') or candidate.get('probability') is None:
        return {'status':'INSUFFICIENT DATA','reason':'A defensible out-of-sample, calibrated candidate is required. Baseline heuristic is shown separately, not asserted as fair value.','sample_size':(candidate or {}).get('sample_size',0),'baseline_estimate':(s.get('baseline') or {}).get('p_up'),'rows':[]}
    if s.get('fee_valid') is False:return {'status':'INSUFFICIENT DATA','reason':'Current fee schedule unverified','rows':[]}
    rows=[]
    for side,p in [('UP',candidate['probability']),('DOWN',1-candidate['probability'])]:
        try:
            price=executable(s['book'],side,'buy');f=fee(price,1,.07,s.get('fee_multiplier',1));edge=p-price-f
            rows.append({'side':side,'estimated_probability':p,'observed_entry_ask':executable(s['book'],side,'buy',slippage=0),'entry_slippage':.002,'executable_entry':price,'taker_fee':f,'estimated_edge':edge,'status':'POTENTIALLY UNDERPRICED' if edge>=.05 else 'OVERPRICED' if edge<0 else 'NEAR ESTIMATED VALUE','maker_comparison':'Passive quote not simulated as filled; no queue/fill evidence available.'})
        except (ValueError,KeyError):rows.append({'side':side,'status':'INSUFFICIENT DEPTH'})
    return {'status':'SHADOW MODEL — NOT PROMOTED','version':candidate.get('version'),'sample_size':candidate['sample_size'],'calibration':candidate.get('calibration'),'rows':rows,'probability_status':'Out-of-sample evidence, still uncertain'}

class Simulator:
    def __init__(self,db):self.db=db
    def propose(self,key,kind,strategy,s,side,hold):
        if s.get('fee_valid') is False or s.get('mode')=='mock' or s['now']-s.get('book_ts',0)>3:return
        active=self.db.execute("SELECT count(*) FROM intel_sim WHERE state IN ('PENDING_ENTRY','OPEN')").fetchone()[0]
        if active>=6:return
        if s['market']['closed']-s['now']<(hold or 90)+10:return
        try:executable(s['book'],side,'buy')
        except ValueError:return
        with self.db:self.db.execute('INSERT OR IGNORE INTO intel_sim(key,kind,strategy,ticker,side,quantity,signal_ts,entry_due,hold,state,reason) VALUES(?,?,?,?,?,?,?,?,?,?,?)',(key,kind,strategy,s['market']['ticker'],side,1,s['now'],s['now']+2,hold,'PENDING_ENTRY','2s delay; actual next available ask required within 3s'))
    def update(self,s):
        if s.get('fee_valid') is False:return
        now=s['now'];ticker=s['market']['ticker']
        positions=self.db.execute("SELECT * FROM intel_sim WHERE ticker=? AND state IN ('PENDING_ENTRY','OPEN') ORDER BY id",(ticker,)).fetchall()
        source=s.get('book')
        if not source:return
        remaining_book=Book([list(r) for r in source.yes],[list(r) for r in source.no])
        for p in positions:
            entry=p['state']=='PENDING_ENTRY';due=p['entry_due'] if entry else p['exit_due']
            if due is None or now<due:continue
            if now>due+3:
                with self.db:self.db.execute('UPDATE intel_sim SET state=?,reason=? WHERE id=?',('CANCELLED' if entry else 'MISSED_EXIT','Executable timed observation missed; no fill fabricated',p['id']))
                continue
            if not 0<=now-s.get('book_ts',0)<=1 or s.get('book_ts',0)<due or s.get('book_latency',99)>1:continue
            try:price=executable(remaining_book,p['side'],'buy' if entry else 'sell',p['quantity'])
            except (ValueError,KeyError):continue
            f=fee(price,p['quantity'],.07,s.get('fee_multiplier',1))
            # Competing intents cannot reuse the same displayed quantity in one book.
            levels=(remaining_book.no if p['side']=='UP' else remaining_book.yes) if entry else (remaining_book.yes if p['side']=='UP' else remaining_book.no)
            needed=p['quantity']
            for level in levels:
                take=min(needed,level[1]);level[1]-=take;needed-=take
                if needed<=1e-9:break
            with self.db:
                if entry:self.db.execute("UPDATE intel_sim SET state='OPEN',entry_ts=?,entry=?,entry_fee=?,exit_due=?,entry_book=?,reason='Observed delayed executable ask; estimate only' WHERE id=?",(now,price,f,now+p['hold'] if p['hold'] else None,s.get('book_id'),p['id']))
                else:self.db.execute("UPDATE intel_sim SET state='CLOSED',exit_ts=?,exit=?,exit_fee=?,pnl=?,exit_book=?,reason='Observed executable bid; both fees and slippage deducted' WHERE id=?",(now,price,f,p['quantity']*(price-p['entry'])-p['entry_fee']-f,s.get('book_id'),p['id']))
    def settle(self,m,now):
        if m.get('result') not in ('yes','no') or m.get('status') not in ('finalized','settled'):return
        with self.db:
            for p in self.db.execute("SELECT * FROM intel_sim WHERE ticker=? AND state='OPEN' AND kind='directional'",(m['ticker'],)).fetchall():
                payout=int((p['side']=='UP')==(m['result']=='yes'))
                self.db.execute("UPDATE intel_sim SET state='CLOSED',exit_ts=?,exit=?,exit_fee=0,pnl=?,reason='Official settlement; no settlement fee' WHERE id=?",(now,payout,p['quantity']*(payout-p['entry'])-p['entry_fee'],p['id']))
    def summary(self,start=0):
        groups={}
        for kind in ('directional','flip','scalp'):
            rows=[dict(r) for r in self.db.execute('SELECT * FROM intel_sim WHERE kind=? AND signal_ts>=? ORDER BY signal_ts DESC',(kind,start))]
            settled=[r for r in rows if r['state']=='CLOSED'];cost=sum(r['quantity']*r['entry']+r['entry_fee'] for r in settled)
            equity=peak=drawdown=0
            for r in reversed(settled):equity+=r['pnl'];peak=max(peak,equity);drawdown=max(drawdown,peak-equity)
            groups[kind]={'closed':len(settled),'open':sum(r['state'] in ('OPEN','MISSED_EXIT') for r in rows),'unresolved_exit':sum(r['state']=='MISSED_EXIT' for r in rows),'open_cost':sum(r['quantity']*r['entry']+r['entry_fee'] for r in rows if r['state'] in ('OPEN','MISSED_EXIT')),'performance_status':'INCOMPLETE — UNRESOLVED EXIT(S)' if any(r['state']=='MISSED_EXIT' for r in rows) else 'Closed positions only; open risk excluded','net_pnl':sum(r['pnl'] for r in settled),'roi':sum(r['pnl'] for r in settled)/cost if cost else None,'drawdown':drawdown,'win_rate':sum(r['pnl']>0 for r in settled)/len(settled) if settled else None,'rows':rows[:200],'history_display_limit':200,'not_real_money':True}
        return groups
