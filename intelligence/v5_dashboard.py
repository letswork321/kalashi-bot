"""Read-only V5 API projection; never starts workers or mutates history."""
import threading
_cache={}
_cache_lock=threading.Lock()
from .storage import loads
from .v5_storage import summary,settings
from .v3_dashboard import settlement_summary

def snapshot(db,now,selection='all'):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='v5_checkpoints'").fetchone():return {'status':'V5 NOT STARTED','history':[],'scores':[],'health':[],'historical':settlement_summary(db)}
    current=db.execute('SELECT ticker,opened,closed,strike FROM intel_markets WHERE opened<=? AND closed>? ORDER BY closed LIMIT 1',(now,now)).fetchone()
    rows=db.execute('SELECT v.*,m.result FROM v5_checkpoints v LEFT JOIN intel_markets m USING(ticker) ORDER BY scheduled DESC LIMIT 128').fetchall()
    history=[{**dict(r),'payload':loads(r['payload']) if r['payload'] else None} for r in rows]
    active=[r for r in history if current and r['ticker']==current['ticker']]
    original=next((r for r in active if r['checkpoint']==60),None);latest=next((r for r in active if r['state']=='FORECAST'),None)
    health=[{'name':r['name'],'observed':r['observed'],'age':now-r['observed'],**loads(r['payload'])} for r in db.execute('SELECT * FROM v5_health')]
    context=next((h for h in health if h['name']=='live_context'),None)
    if context:context={**context,'fresh':context.get('ok') and 0<=context['age']<=4 and 0<=now-context.get('reference_ts',0)<=3}
    evaluation=db.execute('SELECT payload FROM v5_evaluations ORDER BY created DESC LIMIT 1').fetchone()
    evaluation=loads(evaluation['payload']) if evaluation else {'status':'WARMING UP — requires 100 settled forecasts per checkpoint'};evaluation.pop('artifacts',None)
    states=[dict(r) for r in db.execute('SELECT state,count(*) n FROM v5_outbox GROUP BY state')]
    for row in active:
        row['forecast_age']=now-row['observed'] if row['observed'] else None
    from .v5_paper import summary as paper_summary
    key=(db.execute('PRAGMA database_list').fetchone()[2],selection)
    with _cache_lock:
        cached=_cache.get(key)
        if not cached or now-cached[0]>=10 or now<cached[0]:
            cached=(now,summary(db,now,selection));_cache[key]=cached
            if len(_cache)>16:_cache.pop(next(iter(_cache)))
    compact=[{**r,'payload':{k:r['payload'].get(k) for k in ('direction','p_up','version','conviction','source')} if r['payload'] else None} for r in history[:80]]
    return {'live_context':context,'paper':paper_summary(db),'status':'PAPER / EXPERIMENTAL','now':now,'range':selection,'market':dict(current) if current else None,'original':original,'latest':latest,'scores':cached[1],'historical':settlement_summary(db),'history':compact,'settings':settings(db),'health':health,'delivery':states,'evaluation':evaluation,'warning':'Checkpoint forecasts are immutable historical opinions, not current executable trade advice. Uncalibrated estimates; no proven accuracy improvement.'}
