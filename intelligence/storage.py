"""Additive schema, online backups, immutable forecasts, UTC storage / ET views."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
import json
import math
import sqlite3
import time

ET = ZoneInfo('America/New_York')
SCHEMA = '''
CREATE TABLE IF NOT EXISTS intel_schema(version INTEGER PRIMARY KEY, applied REAL NOT NULL, backup TEXT);
CREATE TABLE IF NOT EXISTS intel_markets(ticker TEXT PRIMARY KEY,opened REAL NOT NULL,closed REAL NOT NULL,strike REAL,result TEXT,status TEXT,payload TEXT NOT NULL,seen REAL NOT NULL,settled_at REAL);
CREATE INDEX IF NOT EXISTS im_close ON intel_markets(closed);
CREATE TABLE IF NOT EXISTS intel_locks(ticker TEXT PRIMARY KEY,scheduled REAL NOT NULL,deadline REAL NOT NULL,state TEXT NOT NULL CHECK(state IN ('PENDING','LOCKED','MISSED')),direction TEXT,p_up REAL,observed REAL,features TEXT,model TEXT,reason TEXT,result TEXT,regime TEXT,entry_up REAL,entry_down REAL,fee_multiplier REAL);
CREATE INDEX IF NOT EXISTS il_time ON intel_locks(scheduled,state);
CREATE TRIGGER IF NOT EXISTS immutable_locked_forecast BEFORE UPDATE OF direction,p_up,observed,features,model,state,scheduled,deadline ON intel_locks WHEN OLD.state IN ('LOCKED','MISSED') BEGIN SELECT RAISE(ABORT,'Forecast decision is immutable'); END;
CREATE TABLE IF NOT EXISTS intel_candles(source TEXT NOT NULL,period INTEGER NOT NULL,ts REAL NOT NULL,low REAL,high REAL,open REAL,close REAL,volume REAL,received REAL NOT NULL,PRIMARY KEY(source,period,ts));
CREATE TABLE IF NOT EXISTS intel_btc_trades(id INTEGER PRIMARY KEY,ts REAL NOT NULL,price REAL NOT NULL,size REAL NOT NULL,received REAL NOT NULL);
CREATE INDEX IF NOT EXISTS ibt_time ON intel_btc_trades(ts);
CREATE TABLE IF NOT EXISTS intel_coverage(start REAL NOT NULL,end REAL NOT NULL,source TEXT NOT NULL,PRIMARY KEY(source,start,end));
CREATE TABLE IF NOT EXISTS intel_kalshi_trades(id TEXT PRIMARY KEY,ticker TEXT,ts REAL,price REAL,quantity REAL,payload TEXT,received REAL);
CREATE INDEX IF NOT EXISTS ikt_time ON intel_kalshi_trades(ticker,ts);
CREATE TABLE IF NOT EXISTS intel_books(id INTEGER PRIMARY KEY,ticker TEXT NOT NULL,ts REAL NOT NULL,event_ts REAL,source TEXT NOT NULL,yes TEXT NOT NULL,no TEXT NOT NULL,spread REAL,imbalance REAL,latency REAL,fee_multiplier REAL);
CREATE INDEX IF NOT EXISTS ib_ticker_time ON intel_books(ticker,ts);
CREATE TABLE IF NOT EXISTS intel_engines(id INTEGER PRIMARY KEY,engine TEXT NOT NULL,ticker TEXT NOT NULL,bar REAL NOT NULL,observed REAL NOT NULL,signal TEXT,direction TEXT,quality TEXT,payload TEXT NOT NULL,result TEXT,regime TEXT,UNIQUE(engine,ticker,bar,signal));
CREATE TABLE IF NOT EXISTS intel_reversals(ticker TEXT PRIMARY KEY,target REAL NOT NULL,state TEXT NOT NULL,observed REAL,price REAL,band TEXT,lower REAL,upper REAL,mean REAL,direction TEXT,outcome_target REAL,outcome_price REAL,outcome TEXT,reason TEXT);
CREATE TABLE IF NOT EXISTS intel_snapshots(id INTEGER PRIMARY KEY,ts REAL NOT NULL,ticker TEXT,payload TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS isn_time ON intel_snapshots(ts);
CREATE TABLE IF NOT EXISTS intel_radars(id INTEGER PRIMARY KEY,kind TEXT,ticker TEXT,observed REAL,side TEXT,status TEXT,payload TEXT);
CREATE INDEX IF NOT EXISTS ir_time ON intel_radars(observed,kind);
CREATE TABLE IF NOT EXISTS intel_sim(id INTEGER PRIMARY KEY,key TEXT UNIQUE,kind TEXT NOT NULL,strategy TEXT,ticker TEXT NOT NULL,side TEXT NOT NULL,quantity REAL NOT NULL,signal_ts REAL NOT NULL,entry_due REAL NOT NULL,exit_due REAL,hold REAL,state TEXT NOT NULL,entry_ts REAL,entry REAL,entry_fee REAL,exit_ts REAL,exit REAL,exit_fee REAL,pnl REAL,reason TEXT,entry_book INTEGER,exit_book INTEGER);
CREATE INDEX IF NOT EXISTS isim_state ON intel_sim(state,ticker);
CREATE TABLE IF NOT EXISTS intel_models(version TEXT PRIMARY KEY,created REAL,train_end REAL,artifact TEXT,report TEXT);
CREATE TABLE IF NOT EXISTS intel_shadow(ticker TEXT PRIMARY KEY,version TEXT NOT NULL,observed REAL NOT NULL,p_up REAL NOT NULL,result TEXT);
CREATE TABLE IF NOT EXISTS intel_jobs(id INTEGER PRIMARY KEY,kind TEXT,started REAL,ended REAL,start_ts REAL,end_ts REAL,status TEXT,rows INTEGER,message TEXT);
CREATE TABLE IF NOT EXISTS intel_alerts(id INTEGER PRIMARY KEY,key TEXT UNIQUE,category TEXT,ticker TEXT,created REAL,expires REAL,message TEXT,state TEXT DEFAULT 'pending',attempts INTEGER DEFAULT 0,next_try REAL DEFAULT 0,sent REAL);
CREATE TABLE IF NOT EXISTS intel_late_locks(ticker TEXT PRIMARY KEY,scheduled REAL NOT NULL,deadline REAL NOT NULL,state TEXT NOT NULL DEFAULT 'LATE',direction TEXT NOT NULL,p_up REAL NOT NULL,observed REAL NOT NULL,features TEXT NOT NULL,model TEXT NOT NULL,reason TEXT NOT NULL,result TEXT,regime TEXT,strike REAL NOT NULL,btc_price REAL NOT NULL);
CREATE TRIGGER IF NOT EXISTS immutable_late_forecast BEFORE UPDATE OF direction,p_up,observed,features,model,state,scheduled,deadline,strike,btc_price ON intel_late_locks BEGIN SELECT RAISE(ABORT,'Late forecast decision is immutable'); END;
CREATE TABLE IF NOT EXISTS intel_flip_followups(radar_id INTEGER PRIMARY KEY,ticker TEXT NOT NULL,side TEXT NOT NULL,signal_ts REAL NOT NULL,entry_due REAL NOT NULL,target REAL NOT NULL,state TEXT NOT NULL DEFAULT 'WAIT_ENTRY',entry_ts REAL,entry REAL,entry_fee REAL,exit_due REAL,exit_ts REAL,exit REAL,exit_fee REAL,pnl REAL,target_seen REAL,reason TEXT,signal TEXT);
CREATE INDEX IF NOT EXISTS iff_state ON intel_flip_followups(state,ticker);
CREATE TABLE IF NOT EXISTS intel_entry_state(ticker TEXT PRIMARY KEY,side TEXT,key TEXT NOT NULL,issued REAL NOT NULL,expires REAL NOT NULL,active INTEGER NOT NULL DEFAULT 1,withdrawn REAL);
CREATE TABLE IF NOT EXISTS intel_lock_attempts(id INTEGER PRIMARY KEY,ticker TEXT NOT NULL,observed REAL NOT NULL,reason TEXT NOT NULL,outcome TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ila_ticker_time ON intel_lock_attempts(ticker,observed);
CREATE TABLE IF NOT EXISTS intel_alert_settings(category TEXT PRIMARY KEY,enabled INTEGER NOT NULL CHECK(enabled IN (0,1)),updated REAL NOT NULL);
CREATE TABLE IF NOT EXISTS intel_alert_evidence(key TEXT PRIMARY KEY,alert_id INTEGER UNIQUE,category TEXT NOT NULL,ticker TEXT NOT NULL,created REAL NOT NULL,side TEXT,hold REAL,snapshot TEXT NOT NULL,sent REAL,sim_key TEXT UNIQUE,evaluation TEXT NOT NULL DEFAULT 'AWAITING_DELIVERY');
CREATE TRIGGER IF NOT EXISTS immutable_alert_evidence BEFORE UPDATE OF key,alert_id,category,ticker,created,side,hold,snapshot ON intel_alert_evidence BEGIN SELECT RAISE(ABORT,'Alert decision evidence is immutable'); END;
CREATE INDEX IF NOT EXISTS iae_time ON intel_alert_evidence(created,category);
CREATE TABLE IF NOT EXISTS intel_kalshi_candles(ticker TEXT,ts REAL,payload TEXT,PRIMARY KEY(ticker,ts));
CREATE TABLE IF NOT EXISTS intel_health(name TEXT PRIMARY KEY,ts REAL,payload TEXT);
CREATE TABLE IF NOT EXISTS intel_hourly(hour_utc REAL PRIMARY KEY,n INTEGER,spread_sum REAL,spread_n INTEGER,depth_sum REAL,depth_n INTEGER,velocity_sum REAL,tick_n INTEGER,volatility_sum REAL,vol_n INTEGER,flip_moves INTEGER,kalshi_velocity_sum REAL,kalshi_velocity_n INTEGER);

'''

def connect(path, readonly=False):
    path = Path(path).resolve()
    if not readonly:
        path.parent.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(path.as_uri()+'?mode=ro' if readonly else path,uri=readonly,timeout=15)
    db.row_factory=sqlite3.Row
    db.execute('PRAGMA busy_timeout=15000')
    if not readonly: db.execute('PRAGMA journal_mode=WAL')
    return db

def backup_database(path, destination=None):
    path=Path(path).resolve()
    if not path.exists(): return None
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    target=Path(destination) if destination else path.parent/'backups'/('pre-intelligence-'+stamp+'.sqlite3')
    target.parent.mkdir(parents=True,exist_ok=True)
    if target.exists(): raise FileExistsError('Backup destination already exists')
    source=connect(path,True);out=sqlite3.connect(target)
    try:
        source.backup(out)
        if out.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise RuntimeError('Backup integrity failed')
    finally:out.close();source.close()
    return str(target)

def migrate(path):
    db=connect(path)
    if db.execute("SELECT 1 FROM sqlite_master WHERE name='metadata'").fetchone():
        mode=db.execute("SELECT value FROM metadata WHERE key='mode'").fetchone()
        if mode and mode['value']=='mock':
            db.close();raise ValueError('Intelligence refuses to mix genuine collection with the mock database')
    exists=db.execute("SELECT 1 FROM sqlite_master WHERE name='intel_schema'").fetchone()
    if exists and db.execute('SELECT 1 FROM intel_schema WHERE version=7').fetchone():return db
    # No migration writes until a complete online backup of pre-existing history exists.
    tables=db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    saved=backup_database(path) if tables else None
    try:
        db.executescript('BEGIN IMMEDIATE;\n'+SCHEMA)
        if 'settled_at' not in {r['name'] for r in db.execute('PRAGMA table_info(intel_markets)')}:
            db.execute('ALTER TABLE intel_markets ADD COLUMN settled_at REAL')
        columns=list(db.execute('PRAGMA table_info(intel_books)'))
        if any(r['name']=='fee_multiplier' and r['notnull'] for r in columns):
            db.execute('ALTER TABLE intel_books RENAME TO intel_books_previous')
            db.execute('DROP INDEX IF EXISTS ib_ticker_time')
            db.execute('CREATE TABLE intel_books(id INTEGER PRIMARY KEY,ticker TEXT NOT NULL,ts REAL NOT NULL,event_ts REAL,source TEXT NOT NULL,yes TEXT NOT NULL,no TEXT NOT NULL,spread REAL,imbalance REAL,latency REAL,fee_multiplier REAL)')
            db.execute('INSERT INTO intel_books SELECT * FROM intel_books_previous')
            db.execute('DROP TABLE intel_books_previous')
            db.execute('CREATE INDEX ib_ticker_time ON intel_books(ticker,ts)')
        if 'scope' not in {r['name'] for r in db.execute('PRAGMA table_info(intel_alerts)')}:
            db.execute('ALTER TABLE intel_alerts ADD COLUMN scope TEXT')
        for column in ('strike','btc_price'):
            if column not in {r['name'] for r in db.execute('PRAGMA table_info(intel_locks)')}:
                db.execute('ALTER TABLE intel_locks ADD COLUMN '+column+' REAL')
        db.execute('DROP TRIGGER IF EXISTS immutable_locked_forecast')
        db.execute("CREATE TRIGGER immutable_locked_forecast BEFORE UPDATE OF direction,p_up,observed,features,model,state,scheduled,deadline,strike,btc_price ON intel_locks WHEN OLD.state IN ('LOCKED','MISSED') BEGIN SELECT RAISE(ABORT,'Forecast decision is immutable'); END;")
        db.execute('INSERT OR IGNORE INTO intel_schema VALUES(7,?,?)',(time.time(),saved))
        db.commit()
    except Exception:db.rollback();db.close();raise
    return db

def dumps(value):return json.dumps(value,allow_nan=False,separators=(',',':'))
def loads(value):return json.loads(value) if value else None

def window_start(selection,now):
    local=datetime.fromtimestamp(now,ET)
    if selection=='today':return local.replace(hour=0,minute=0,second=0,microsecond=0).timestamp()
    if selection in ('7','30','90'):return (local-timedelta(days=int(selection))).timestamp()
    if selection=='all':return 0
    raise ValueError('Unsupported time range')

def tracker_summary(db,selection='today',now=None,offset=0,limit=100):
    now=time.time() if now is None else now
    start=window_start(selection,now)
    rows=[dict(r) for r in db.execute('SELECT l.*,m.opened,m.closed FROM intel_locks l JOIN intel_markets m USING(ticker) WHERE scheduled>=? AND scheduled<=? ORDER BY scheduled DESC',(start,now))]
    settled=[r for r in rows if r['state']=='LOCKED' and r['result'] in ('yes','no')]
    for r in rows:
        r.pop('features',None)
        r['correct']=None if r['state']!='LOCKED' or r['result'] not in ('yes','no') else (r['direction']=='UP')==(r['result']=='yes')
        r['predicted_probability']=r['p_up'] if r['direction']=='UP' else 1-r['p_up'] if r['direction']=='DOWN' and r['p_up'] is not None else None
        r['time_et']=datetime.fromtimestamp(r['scheduled'],ET).isoformat()
    late_rows=[dict(r) for r in db.execute('SELECT l.*,m.opened,m.closed FROM intel_late_locks l JOIN intel_markets m USING(ticker) WHERE scheduled>=? AND observed<=? ORDER BY observed DESC',(start,now))]
    for r in late_rows:
        r.pop('features',None);r['correct']=None if r['result'] not in ('yes','no') else (r['direction']=='UP')==(r['result']=='yes')
        r['predicted_probability']=r['p_up'] if r['direction']=='UP' else 1-r['p_up'];r['time_et']=datetime.fromtimestamp(r['observed'],ET).isoformat()
    late_settled=[r for r in late_rows if r['correct'] is not None];late_wins=sum(r['correct'] for r in late_settled)
    rows=sorted(rows+late_rows,key=lambda r:r.get('observed') or r['scheduled'],reverse=True)
    attempts=[dict(r) for r in db.execute('SELECT ticker,observed,reason,outcome FROM intel_lock_attempts ORDER BY id DESC LIMIT 50')]
    wins=sum((r['direction']=='UP')==(r['result']=='yes') for r in settled)
    streak=0;last=None
    for r in settled:
        won=(r['direction']=='UP')==(r['result']=='yes')
        if last is None:last=won
        if won!=last:break
        streak+=1
    return {'late':{'count':len(late_rows),'wins':late_wins,'losses':len(late_settled)-late_wins,'pending':len(late_rows)-len(late_settled),'accuracy':late_wins/len(late_settled) if late_settled else None},'attempts':attempts,'range':selection,'wins':wins,'losses':len(settled)-wins,'accuracy':wins/len(settled) if settled else None,'streak':{'kind':'WIN' if last else 'LOSS' if last is not None else 'NONE','count':streak},'pending':sum(r['state']=='LOCKED' and not r['result'] for r in rows),'missed':sum(r['state']=='MISSED' for r in rows),'awaiting_lock':sum(r['state']=='PENDING' for r in rows),'sample_size':len(settled),'rows':rows[offset:offset+limit],'total_rows':len(rows),'offset':offset,'page_size':limit,'has_next':len(rows)>offset+limit,'coverage':'Only discovered eligible markets; historical discoveries without an on-time observation are MISSED, never reconstructed.'}

def register_market(db,m,seen):
    from scanner import timestamp
    op,cl=timestamp(m['open_time']),timestamp(m['close_time'])
    if not m['ticker'].startswith('KXBTC15M-') or not 899<=cl-op<=901:return False
    result=m.get('result') if m.get('status') in ('finalized','settled') and m.get('result') in ('yes','no') else None
    with db:
        db.execute('INSERT INTO intel_markets VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(ticker) DO UPDATE SET strike=excluded.strike,result=COALESCE(excluded.result,intel_markets.result),status=excluded.status,payload=excluded.payload,seen=excluded.seen,settled_at=COALESCE(intel_markets.settled_at,excluded.settled_at)',(m['ticker'],op,cl,m.get('floor_strike'),result,m.get('status'),dumps(m),seen,timestamp(m['settlement_ts']) if result and m.get('settlement_ts') else seen if result else None))
        db.execute('INSERT OR IGNORE INTO intel_locks(ticker,scheduled,deadline,state,reason) VALUES(?,?,?,?,?)',(m['ticker'],op+60,op+65,'MISSED' if seen>op+65 else 'PENDING','Discovered after locking deadline' if seen>op+65 else 'Waiting for +60s lock'))
        db.execute('INSERT OR IGNORE INTO intel_reversals(ticker,target,state,reason) VALUES(?,?,?,?)',(m['ticker'],op+600,'MISSED' if seen>op+603 else 'PENDING','10-minute observation unavailable' if seen>op+603 else 'Waiting for 10-minute sample'))
        if result:
            db.execute('UPDATE intel_locks SET result=? WHERE ticker=?',(result,m['ticker']))
            db.execute('UPDATE intel_late_locks SET result=? WHERE ticker=?',(result,m['ticker']))
            db.execute('UPDATE intel_engines SET result=? WHERE ticker=?',(result,m['ticker']))
            db.execute('UPDATE intel_shadow SET result=? WHERE ticker=?',(result,m['ticker']))
    return True

def lock_forecast(db,m,p,now,features,regime,entries=None,multiplier=1):
    row=db.execute('SELECT * FROM intel_locks WHERE ticker=?',(m['ticker'],)).fetchone()
    if not row or row['state']!='PENDING' or now<row['scheduled']:return None
    try:probability=float(p['p_up']) if p else None
    except (TypeError,ValueError,KeyError):probability=None
    valid=(now<=row['deadline'] and p and probability is not None and math.isfinite(probability) and 0<=probability<=1 and p.get('observed_at',0)>=row['scheduled'] and 0<=now-p.get('btc_timestamp',0)<=2 and m.get('floor_strike') is not None)
    with db:
        if not valid:
            if now>row['deadline']:db.execute("UPDATE intel_locks SET state='MISSED',reason='No valid on-time live forecast' WHERE ticker=? AND state='PENDING'",(m['ticker'],))
            return None
        direction='UP' if probability>=.5 else 'DOWN'
        db.execute("UPDATE intel_locks SET state='LOCKED',direction=?,p_up=?,observed=?,features=?,model=?,reason=?,regime=?,entry_up=?,entry_down=?,fee_multiplier=?,strike=?,btc_price=? WHERE ticker=? AND state='PENDING'",(direction,probability,now,dumps(features),p['model'],'Locked at +60 seconds; probability uncalibrated',regime,(entries or {}).get('UP'),(entries or {}).get('DOWN'),multiplier,m.get('floor_strike'),p.get('btc_price'),m['ticker']))
    return dict(db.execute('SELECT * FROM intel_locks WHERE ticker=?',(m['ticker'],)).fetchone())
