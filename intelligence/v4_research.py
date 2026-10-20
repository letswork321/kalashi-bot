"""Bounded read-only, column-allowlisted exports and immutable mistake research."""
import json
import math
from pathlib import Path
import sqlite3
import time
from .storage import dumps,loads

from research_export import export


def investigate(db,now,limit=10):
    rows=db.execute("SELECT l.* FROM intel_locks l LEFT JOIN v4_mistakes v USING(ticker) WHERE v.ticker IS NULL AND l.state='LOCKED' AND l.result IN ('yes','no') AND ((l.direction='UP')!=(l.result='yes')) ORDER BY l.scheduled DESC LIMIT ?",(limit,)).fetchall()
    for r in rows:
        m=db.execute('SELECT closed FROM intel_markets WHERE ticker=?',(r['ticker'],)).fetchone();close=m['closed'] if m else r['scheduled']+840
        warnings=[dict(x) for x in db.execute("SELECT observed,kind,state,side FROM v4_events WHERE ticker=? AND observed>? AND observed<? ORDER BY observed LIMIT 100",(r['ticker'],r['observed'],close))]
        paths=[dict(x) for x in db.execute('SELECT state,issued,side,max_roi,coverage FROM v4_profit_paths WHERE ticker=? AND side=? ORDER BY issued LIMIT 30',(r['ticker'],r['direction']))]
        attempts=db.execute('SELECT count(*) FROM intel_lock_attempts WHERE ticker=?',(r['ticker'],)).fetchone()[0]
        evidence={'historical_quote_audit':historical_cashout(db,r['ticker'],r['direction'],r['observed'],close),'original':{k:r[k] for k in ('ticker','observed','direction','p_up','features','model','result')},'warnings':warnings,'cashout_paths':paths,'rejected_attempts':attempts,'classification':'OBSERVED LATER REVERSAL' if any('REVERSAL' in x['state'] for x in warnings) else 'INSUFFICIENT DATA','cashout_audit':'VERIFIED PROSPECTIVE GOAL TOUCH' if any(x['state']=='GOAL HIT' for x in paths) else 'UNVERIFIED — no complete historical executable bid/depth paths','explanation':'Settlement prediction was wrong. Later warnings are recorded at their actual issue times; they are not credited as earlier predictions. No causal explanation is claimed without contemporaneous evidence.'}
        with db:db.execute('INSERT OR IGNORE INTO v4_mistakes VALUES(?,?,?)',(r['ticker'],now,dumps(evidence)))


def diagnostics(db):
    return {'lock_rejections':[dict(r) for r in db.execute('SELECT reason,count(*) attempts,count(DISTINCT ticker) markets FROM intel_lock_attempts GROUP BY reason')],'gap_states':[dict(r) for r in db.execute('SELECT state,count(*) n FROM v3_call_paths GROUP BY state')],'missed_markets':[dict(r) for r in db.execute("SELECT ticker,scheduled,reason FROM intel_locks WHERE state='MISSED' ORDER BY scheduled DESC LIMIT 50")],'warning':'These are this database only. Reported Windows statistics cannot be verified without an uploaded sanitized export.'}


def historical_cashout(db,ticker,side,issued,closed,goal=.65):
    """Retrospective quote audit only; not a newly forecast past opportunity."""
    from scanner import Book,fee
    from .economics import executable
    rows=db.execute('SELECT * FROM intel_books WHERE ticker=? AND event_ts>=? AND event_ts<? ORDER BY event_ts LIMIT 6000',(ticker,issued+2,closed)).fetchall()
    entry=None;last=None;peak=None;covered=True;count=0
    for r in rows:
        if r['source']!='websocket' or r['event_ts'] is None or r['fee_multiplier'] is None:covered=False;continue
        if last is not None and r['event_ts']-last>2:covered=False
        last=r['event_ts']
        try:
            book=Book.parse({'yes_dollars':loads(r['yes']),'no_dollars':loads(r['no'])})
            if entry is None:
                if r['event_ts']>issued+4:return {'status':'UNVERIFIED','reason':'No observed delayed entry near original decision'}
                entry=executable(book,side,'buy');cost=entry+fee(entry,1,.07,r['fee_multiplier']);continue
            bid=executable(book,side,'sell');roi=(bid-fee(bid,1,.07,r['fee_multiplier'])-cost)/cost;peak=max(peak if peak is not None else roi,roi);count+=1
        except ValueError:covered=False;continue
        if covered and roi>=goal:return {'status':'RETROSPECTIVE VERIFIED GOAL TOUCH','observed':r['event_ts'],'net_roi':roi,'quantity':1,'goal':goal,'note':'Historical study, not a timely issued opportunity or actual sale'}
    return {'status':'UNVERIFIED' if not covered or not last or last<closed-2 else 'NO OBSERVED GOAL','observations':count,'max_observed_roi':peak,'goal':goal,'reason':'Historical gaps/depth/entry cannot be invented'}
