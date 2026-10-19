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

def fast_scalp_data(s):
    """Fail closed: local receipt times alone do not verify exchange freshness."""
    now=s['now'];ticker=s.get('market',{}).get('ticker')
    history=[r for r in s.get('book_history',[]) if r.get('ticker')==ticker and now-20<=r['ts']<=now]
    times=sorted({r['ts'] for r in history})
    cadence=len(times)>=20 and times[-1]-times[0]>=10 and times[-1]>=now-1 and max(b-a for a,b in zip(times,times[1:]))<=2
    ticks=s.get('tick_metrics') or {}
    return bool(s.get('mode')=='live' and s.get('fee_valid') is not False and cadence and ticks and 0<=now-ticks.get('last_trade_timestamp',now-ticks.get('age',99))<=1
                and s.get('book_source')=='websocket' and s.get('ws_sequence_valid') and s.get('book_latency',99)<=1
                and 0<=now-s.get('book_ts',0)<=1 and 0<=now-s.get('quote_ts',0)<=1)

def scalp_radar(s):
    rows=[];now=s['now'];highrate=fast_scalp_data(s)
    flip_rows=flip_radar(s)['rows'] if highrate else []
    for hold in (20,40,60):
        for side in ('UP','DOWN'):
            if not highrate:
                rows.append({'side':side,'window':hold,'status':'FASTER MARKET DATA REQUIRED','reason':'FASTER DATA REQUIRED: sequenced Kalshi updates, >=20 events spanning >=10s with no >2s gap, <=1s exchange latency and fresh BTC ticks/quote required.'});continue
            best=next((r for r in flip_rows if r['side']==side),{})
            if 'conditional_net' not in best:
                rows.append({'side':side,'window':hold,'status':'AVOID','reason':'Fresh executable depth and verified fees required'});continue
            history=side_history(s,side,20)
            velocity=(history[-1]['bid']-history[0]['bid'])/(history[-1]['ts']-history[0]['ts']) if len(history)>=3 and history[-1]['ts']>history[0]['ts'] else 0
            last=[r for r in history if r['ts']>=now-5]
            recent=(last[-1]['bid']-last[0]['bid'])/(last[-1]['ts']-last[0]['ts']) if len(last)>=2 and last[-1]['ts']>last[0]['ts'] else 0
            sign=1 if side=='UP' else -1;tm=s['tick_metrics'];aligned=tm.get('velocity',0)*sign>=.0001
            reversal=recent<0 or tm.get('acceleration',0)*sign<-.00005
            imbalance=s['book'].imbalance*sign
            target=min(.999,best['observed_exit_bid']+min(.15,max(0,velocity*hold)))
            net=target-.002-best['entry']-best['entry_fee']-fee(target-.002,1,.07,s.get('fee_multiplier',1))
            enough_time=best['time_remaining']>hold+20
            status='OPPORTUNITY' if net>=.01 and best['spread']<=.02 and enough_time and aligned and recent>0 and not reversal and imbalance>=-.2 else 'WATCH' if velocity>0 and best['spread']<=.04 and enough_time and aligned and not reversal else 'AVOID'
            research_candidate=status=='OPPORTUNITY'
            evidence=s.get('scalp_evidence',{}).get(side+':'+str(hold),{})
            if status=='OPPORTUNITY' and not evidence.get('validated'):status='WATCH'
            asks=[r['ask'] for r in history if r.get('ask') is not None]
            spreads=[r['spread'] for r in history if r.get('spread') is not None]
            rows.append({**best,'research_candidate':research_candidate,'historical':evidence,'entry_validation':'FORWARD HOLDOUT SUPPORTED' if evidence.get('validated') else 'UNVALIDATED — WATCH ONLY','btc_volume_60s':tm.get('volume_btc'),'btc_tick_metrics':tm,'window':hold,'status':status,'possible_exit_target':target,'required_bid_movement':target-best['observed_exit_bid'],'holding_seconds':hold,'conditional_net':net,'price_velocity_per_second':velocity,'recent_bid_velocity':recent,'reversal_risk':reversal,'btc_direction_aligned':aligned,'ask_change':asks[-1]-asks[0] if len(asks)>1 else None,'spread_change':spreads[-1]-spreads[0] if len(spreads)>1 else None,'opportunity_window_seconds':3,'reason':'Live BTC/contract momentum, recent reversal checks and executable depth evaluated independently by side and horizon. Target is conditional, not validated profit. Timed paper exits require observed bids after costs.'})
    return {'name':'SCALP RADAR','rows':rows,'timestamp':now,'validated_profitability':False}

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
        existing=self.db.execute('SELECT id FROM intel_sim WHERE key=?',(key,)).fetchone()
        if existing:return existing['id']
        active=self.db.execute("SELECT count(*) FROM intel_sim WHERE state IN ('PENDING_ENTRY','OPEN')").fetchone()[0]
        if active>=6:return
        if s['market']['closed']-s['now']<(hold or 90)+10:return
        try:executable(s['book'],side,'buy')
        except ValueError:return
        with self.db:self.db.execute('INSERT OR IGNORE INTO intel_sim(key,kind,strategy,ticker,side,quantity,signal_ts,entry_due,hold,state,reason) VALUES(?,?,?,?,?,?,?,?,?,?,?)',(key,kind,strategy,s['market']['ticker'],side,1,s['now'],s['now']+2,hold,'PENDING_ENTRY','2s delay; actual next available ask required within 3s'))
        return self.db.execute('SELECT id FROM intel_sim WHERE key=?',(key,)).fetchone()['id']
    def update(self,s):
        if s.get('fee_valid') is False:return
        now=s['now'];ticker=s['market']['ticker']
        positions=self.db.execute("SELECT * FROM intel_sim WHERE ticker=? AND state IN ('PENDING_ENTRY','OPEN') ORDER BY id",(ticker,)).fetchall()
        source=s.get('book')
        if not source:return
        remaining_book=Book([list(r) for r in source.yes],[list(r) for r in source.no])
        # Repeated observer polls cannot spend the same visible size twice.
        bid=s.get('book_id')
        if bid is not None:
            used=self.db.execute("""SELECT side,quantity,'buy' action FROM intel_sim WHERE entry_book=? OR entry_book IN
                (SELECT id FROM intel_books WHERE ticker=? AND ts=? AND source=?) UNION ALL
                SELECT side,quantity,'sell' action FROM intel_sim WHERE exit_book=? OR exit_book IN
                (SELECT id FROM intel_books WHERE ticker=? AND ts=? AND source=?)""",(bid,ticker,s.get('book_ts'),s.get('book_source'),bid,ticker,s.get('book_ts'),s.get('book_source'))).fetchall()
            for fill in used:
                levels=(remaining_book.no if fill['side']=='UP' else remaining_book.yes) if fill['action']=='buy' else (remaining_book.yes if fill['side']=='UP' else remaining_book.no)
                needed=fill['quantity']
                for level in levels:
                    take=min(needed,level[1]);level[1]-=take;needed-=take
                    if needed<=1e-9:break
        for p in positions:
            entry=p['state']=='PENDING_ENTRY';due=p['entry_due'] if entry else p['exit_due']
            if not entry and due is None and p['strategy']=='v3_early_exit':
                rule=self.db.execute('SELECT * FROM v3_paper_rules WHERE sim_id=?',(p['id'],)).fetchone()
                if rule and s.get('book_event_verified') and s.get('fee_valid') and 0<=now-s.get('book_ts',0)<=1:
                    try:
                        observed=executable(remaining_book,p['side'],'sell',p['quantity']);f=fee(observed,p['quantity'],.07,s['fee_multiplier'])
                        net=p['quantity']*(observed-p['entry'])-p['entry_fee']-f;roi=net/(p['quantity']*p['entry']+p['entry_fee'])
                        opposite=s.get('caller_direction') in ('UP','DOWN') and s['caller_direction']!=p['side'] and now-p['entry_ts']>=5
                        reason='net goal reached' if roi>=rule['target_roi'] else 'net risk limit reached' if roi<=rule['stop_roi'] else 'trend deteriorated' if opposite else 'settlement averaging window approaching' if s['market']['closed']-now<90 else None
                        if reason:
                            with self.db:
                                self.db.execute('UPDATE intel_sim SET exit_due=?,reason=? WHERE id=?',(now+2,'V3 paper exit decision: '+reason+'; observed bid required after2s',p['id']))
                                self.db.execute('UPDATE v3_paper_rules SET exit_decision=?,exit_reason=? WHERE sim_id=?',(now,reason,p['id']))
                    except ValueError:pass
                continue
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


def compare_flips(db,s,radar):
    """Compare costs and forward paper evidence, never rank by baseline probability."""
    for r in radar['rows']:
        rows=[dict(x) for x in db.execute("SELECT signal_ts,state,pnl,exit_ts FROM intel_flip_followups WHERE side=? AND signal='POTENTIAL OPPORTUNITY' AND signal_ts<? ORDER BY signal_ts",(r['side'],s['now']))]
        closed=[];last_exit=0
        for x in rows:
            if x['state']=='CLOSED' and x['exit_ts']<=s['now'] and x['signal_ts']>=last_exit:
                closed.append(x);last_exit=x['exit_ts']
        n=len(closed);test=closed[int(n*.7):] if n>=100 else []
        mean=statistics.mean(x['pnl'] for x in test) if test else None
        lower=mean-1.96*statistics.stdev(x['pnl'] for x in test)/(len(test)**.5) if len(test)>1 else None
        unresolved=sum(x['state'] in ('MISSED_EXIT','MISSED_ENTRY') for x in rows)
        validated=n>=100 and len(test)>=30 and lower is not None and lower>0 and unresolved==0
        r['historical']={'closed_samples':n,'holdout_samples':len(test),'success_rate':sum(x['pnl']>0 for x in test)/len(test) if test else None,'mean_net':mean,'mean_net_95_lower':lower,'unresolved':unresolved,'validated':validated,'status':'FORWARD HOLDOUT EVIDENCE — REGIME RISK REMAINS' if validated else 'NOT VALIDATED','definition':'Net-positive after observed delayed ask/bid, both fees and slippage; nonoverlapping per-side signals, last 30% chronological holdout, >=100 closed/30 holdout, positive mean lower bound, no unresolved exits. Overlapping trials are correlated.'}
        r['expected_value_status']='NOT ESTABLISHED — conditional target net is a scenario'
    fresh=[r for r in radar['rows'] if r['status']!='STALE']
    candidates=[r for r in fresh if r['status']=='POTENTIAL OPPORTUNITY' and r['historical']['validated'] and r.get('risk')=='MEDIUM']
    if not fresh:assessment='DATA UNAVAILABLE';reason='Fresh executable quotes and verified costs unavailable.'
    elif len(candidates)==1:
        assessment='POTENTIAL '+candidates[0]['side']+' OPPORTUNITY';reason='Current momentum/cost checks and forward holdout evidence agree. Historical results do not guarantee current expected value.'
    elif len(candidates)>1:
        assessment='WATCH';reason='Both sides qualify under different scenarios. No defensible single-side preference; compare execution risk.'
    elif any(r['status'] in ('WATCH','POTENTIAL OPPORTUNITY') for r in fresh):
        assessment='WATCH';reason='A conditional target may clear costs, but sufficient independent forward evidence is not yet available. This is not a demonstrated positive-EV recommendation.'
    else:assessment='NO CLEAR OPPORTUNITY';reason='Current costs, spread or remaining time do not support the observed scenarios.'
    return {**radar,'assessment':assessment,'assessment_reason':reason}


def evaluate_flips(db,s):
    """Every recorded live flip state/heartbeat gets an independent forward quote study.
    These overlap: never sum them as a fundable portfolio or assume passive fills.
    """
    now=s['now']
    with db:
        db.execute("UPDATE intel_flip_followups SET state='MISSED_ENTRY',reason='No observed delayed ask by deadline' WHERE state='WAIT_ENTRY' AND entry_due+3<?",(now,))
        db.execute("UPDATE intel_flip_followups SET state='MISSED_EXIT',reason='No observed executable 60s exit by deadline' WHERE state='OPEN' AND exit_due+3<?",(now,))
    if s.get('mode')!='live' or s.get('fee_valid') is False or not 0<=now-s.get('book_ts',0)<=1 or s.get('book_latency',99)>1:return
    rows=db.execute("SELECT * FROM intel_flip_followups WHERE ticker=? AND state IN ('WAIT_ENTRY','OPEN') ORDER BY radar_id",(s['market']['ticker'],)).fetchall()
    for r in rows:
        entering=r['state']=='WAIT_ENTRY';due=r['entry_due'] if entering else r['exit_due']
        try:
            bid=executable(s['book'],r['side'],'sell',slippage=0)
            if not entering and bid>=r['target'] and not r['target_seen']:
                with db:db.execute('UPDATE intel_flip_followups SET target_seen=? WHERE radar_id=?',(now,r['radar_id']))
            if now<due or s['book_ts']<due:continue
            price=executable(s['book'],r['side'],'buy' if entering else 'sell');f=fee(price,1,.07,s.get('fee_multiplier',1))
        except (ValueError,KeyError):continue
        with db:
            if entering:db.execute("UPDATE intel_flip_followups SET state='OPEN',entry_ts=?,entry=?,entry_fee=?,exit_due=?,reason='Independent one-contract event study; observed ask after 2s; overlapping studies are not a portfolio' WHERE radar_id=?",(now,price,f,now+60,r['radar_id']))
            else:db.execute("UPDATE intel_flip_followups SET state='CLOSED',exit_ts=?,exit=?,exit_fee=?,pnl=?,reason='Observed 60s bid minus both taker fees/slippage; conditional target was not assumed filled' WHERE radar_id=?",(now,price,f,price-r['entry']-r['entry_fee']-f,r['radar_id']))


def scalp_evidence(db,now):
    result={}
    for side in ('UP','DOWN'):
        for hold in (20,40,60):
            rows=[dict(r) for r in db.execute("SELECT state,signal_ts,exit_ts,pnl FROM intel_sim WHERE kind='scalp' AND strategy='scalp' AND side=? AND hold=? AND signal_ts<? ORDER BY signal_ts",(side,hold,now))]
            closed=[];last=0
            for r in rows:
                if r['state']=='CLOSED' and r['exit_ts']<=now and r['signal_ts']>=last:closed.append(r);last=r['exit_ts']
            test=closed[int(.7*len(closed)):] if len(closed)>=100 else []
            mean=statistics.mean(r['pnl'] for r in test) if test else None
            lower=mean-1.96*statistics.stdev(r['pnl'] for r in test)/len(test)**.5 if len(test)>1 else None
            unresolved=sum(r['state']=='MISSED_EXIT' for r in rows)
            result[side+':'+str(hold)]={'validated':len(test)>=30 and lower is not None and lower>0 and unresolved==0,'samples':len(closed),'holdout_samples':len(test),'holdout_mean_net':mean,'lower_95_mean_net':lower,'unresolved':unresolved,'definition':'Fixed-rule nonoverlapping chronological 70/30 forward split; >=100 closed, >=30 holdout, positive lower mean-net bound, zero unresolved exits. Historical support, not a guaranteed future bid.'}
    return result
