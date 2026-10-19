"""Immutable PATH-target callouts, distinct from legacy exact-endpoint metrics."""
import math
from .storage import dumps

VERSION='caller-path-v3'

def record(db,c,key):
    price=c['btc_price'];target=price*(1+c['minimum_move']*(1 if c['direction']=='UP' else -1))
    with db:
        cursor=db.execute("""INSERT OR IGNORE INTO intel_callouts(key,ticker,observed,direction,btc_price,quote_ts,horizon,due,minimum_move,reason,state,metric,target_price,source,version)
        VALUES(?,?,?,?,?,?,?,?,?,?,'QUEUED','path-after-ack-v3',?,?,?)""",(key,c['ticker'],c['observed'],c['direction'],price,c['quote_ts'],c['horizon'],c['observed']+c['horizon'],c['minimum_move'],c['reason'],target,c.get('source','Coinbase WebSocket'),VERSION))
        if cursor.rowcount:db.execute('INSERT OR IGNORE INTO v3_call_paths(key,last_event) VALUES(?,?)',(key,c['observed']))
    return bool(cursor.rowcount)

def observe(db,ticks,now):
    rows=db.execute("SELECT c.*,p.last_event,p.last_id,p.gaps,p.hit_ts FROM intel_callouts c JOIN v3_call_paths p USING(key) WHERE c.metric='path-after-ack-v3' AND c.sent IS NOT NULL AND c.outcome IS NULL").fetchall()
    for r in rows:
        gaps=r['gaps'];last_event=max(r['last_event'],r['sent']);last_id=r['last_id'];hit=None
        if r['sent']>r['observed']+3:gaps+=1
        for t in sorted((t for t in ticks if r['sent']<=t['ts']<=r['due'] and t['received']>=r['observed'] and t['received']<=now and 0<=t['received']-t['ts']<=2),key=lambda x:(x['ts'],x['id'])):
            if last_id is not None and t['id']<=last_id:continue
            if t['ts']<last_event:continue
            if t['ts']-last_event>3 or last_id is not None and t['id']!=last_id+1:gaps+=1
            if not t.get('continuous',False):gaps+=1
            last_event=t['ts'];last_id=t['id']
            crossed=t['price']>=r['target_price'] if r['direction']=='UP' else t['price']<=r['target_price']
            if crossed and not hit:
                hit=t;break  # A proven hit before a later outage is batch-order invariant.
        # A streaming outage invalidates this prospective path; it cannot be backfilled.
        if not hit and now<r['due'] and now-last_event>3:gaps+=1
        if gaps:
            with db:
                db.execute("UPDATE intel_callouts SET state='UNSCORED',outcome='MISSED' WHERE key=? AND outcome IS NULL",(r['key'],))
                db.execute("UPDATE v3_call_paths SET state='GAPPED',gaps=?,last_event=?,last_id=? WHERE key=?",(gaps,last_event,last_id,r['key']))
        elif hit:
            with db:
                db.execute("UPDATE intel_callouts SET state='SCORED',outcome='HIT',outcome_ts=?,outcome_price=? WHERE key=? AND outcome IS NULL",(hit['ts'],hit['price'],r['key']))
                db.execute("UPDATE v3_call_paths SET state='HIT',hit_ts=?,hit_price=?,last_event=?,last_id=? WHERE key=?",(hit['ts'],hit['price'],last_event,last_id,r['key']))
        elif now>=r['due']+2:
            after=sorted((t for t in ticks if r['due']<t['ts']<=r['due']+2 and t['received']<=now and 0<=t['received']-t['ts']<=2),key=lambda t:(t['ts'],t['id']))
            bridge=bool(after and last_id is not None and after[0]['id']==last_id+1 and after[0].get('continuous') and after[0]['ts']-last_event<=3)
            complete=last_event>=r['due'] or bridge
            with db:db.execute("UPDATE intel_callouts SET state=?,outcome=?,outcome_ts=? WHERE key=? AND outcome IS NULL",('SCORED' if complete else 'UNSCORED','NOT_HIT' if complete else 'MISSED',last_event,r['key']))
        else:
            with db:db.execute('UPDATE v3_call_paths SET last_event=?,last_id=? WHERE key=?',(last_event,last_id,r['key']))

def summary(db):
    metrics=[]
    for r in db.execute("SELECT metric,count(*) total,sum(outcome='HIT') hits,sum(outcome='NOT_HIT') not_hits,sum(outcome='MISSED') missed,sum(outcome IS NULL) pending FROM intel_callouts WHERE sent IS NOT NULL GROUP BY metric"):
        d={k:r[k] or 0 for k in ('total','hits','not_hits','missed','pending')};n=d['hits']+d['not_hits'];d.update(metric=r['metric'],hit_rate=d['hits']/n if n else None);metrics.append(d)
    selected=next((r for r in metrics if r['metric']=='path-after-ack-v3'),{'hits':0,'not_hits':0,'missed':0,'pending':0,'hit_rate':None,'metric':'path-after-ack-v3'})
    return {**selected,'metrics':metrics,'definition':'PATH v3: >=0.05% spot target touch AFTER Telegram acknowledgement and by original call+180s; observed contiguous live trades, max3s gap, send acknowledgement <=3s. Gaps/late/unacknowledged calls are UNSCORED. Legacy 3-minute endpoint scores remain separate. Not trading returns.','rows':[dict(r) for r in db.execute('SELECT key,ticker,observed,sent,direction,btc_price,target_price,due,metric,version,source,outcome,state FROM intel_callouts ORDER BY observed DESC LIMIT 50')]}
