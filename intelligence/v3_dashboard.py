"""Compact read-only V3 state. Stale masking is rechecked on EVERY request."""
import time
from .storage import loads
from .path_scoring import summary
from .early_exit import settings

def snapshot(db,now=None):
    now=time.time() if now is None else now
    row=db.execute("SELECT ts,payload FROM v3_state WHERE name='dashboard'").fetchone()
    live=loads(row['payload']) if row else {'caller':{'guidance':'WAIT','reason':'V3 collector warming up'},'spot':{},'brti':{},'market':{}}
    event=live.get('spot',{}).get('event_ts');age=now-event if event is not None else None
    fresh=bool(row and 0<=now-row['ts']<=2 and age is not None and 0<=age<=3 and live['spot'].get('status')=='LIVE')
    if not fresh:
        live['caller'].update(guidance='WAIT',confidence='STALE / STREAM UNAVAILABLE — no recommendation',contract_forecast=None)
        live['spot']['status']='REST_FALLBACK' if live['spot'].get('status')=='REST_FALLBACK' and age is not None and 0<=age<=3 else 'STALE' if event else 'STREAM UNAVAILABLE'
    live['spot']['age']=age
    b=live.get('book')
    if b:
        b['age']=now-b['event_ts'] if b.get('event_ts') is not None else None
        if b['age'] is None or not 0<=b['age']<=1:
            if live['caller'].get('guidance') in ('ENTER','AVOID'):live['caller'].update(guidance='WAIT',entry='Executable stream quote is not current')
    benchmark=live.get('brti',{})
    if benchmark.get('event_ts') is not None and now-benchmark['event_ts']>3:benchmark['status']='STALE'
    counts=settlement_summary(db)
    live.update(now=now,status='LIVE' if fresh else 'WAIT / STALE',settlement_score=counts,caller_score=summary(db),settings=settings(db),watch_positions=[dict(r) for r in db.execute("SELECT * FROM v3_watch_positions WHERE state='WATCHING' ORDER BY id")])
    boost=db.execute('SELECT version,created,payload FROM v3_model_comparisons ORDER BY created DESC LIMIT 1').fetchone()
    if boost:
        report=loads(boost['payload']);report.pop('folds',None);report.pop('forecasts',None);live['boosted_comparison']={'version':boost['version'],'created':boost['created'],**report}
    else:live['boosted_comparison']={'status':'INSUFFICIENT DATA — gradient-boosted candidate not fitted yet'}
    live['paper_profit']=[dict(r) for r in db.execute("SELECT kind,count(*) closed,sum(pnl) net FROM intel_sim WHERE state='CLOSED' GROUP BY kind")]
    live['module_performance']=[dict(r) for r in db.execute("SELECT e.module,e.regime,count(*) n,sum((e.direction='UP')=(m.result='yes')) correct FROM v3_module_events e JOIN intel_markets m USING(ticker) WHERE e.direction IS NOT NULL AND m.result IN ('yes','no') GROUP BY e.module,e.regime")]
    return live


def settlement_summary(db):
    """Lifetime immutable locks and official results, including imported V3 rows."""
    counts=dict(db.execute("""SELECT sum(state='LOCKED' AND result IN ('yes','no') AND ((direction='UP')=(result='yes'))) wins,
       sum(state='LOCKED' AND result IN ('yes','no') AND ((direction='UP')!=(result='yes'))) losses,
       sum(state='LOCKED' AND result IS NULL) pending,sum(state='MISSED') missed FROM intel_locks""").fetchone())
    counts={k:int(v or 0) for k,v in counts.items()};n=counts['wins']+counts['losses'];counts['accuracy']=counts['wins']/n if n else None
    return counts
