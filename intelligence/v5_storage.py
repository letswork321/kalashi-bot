"""Additive, isolated V5 records. Official results are joined, never forecast rewrites."""
from .storage import dumps,loads
SCHEMA='''
CREATE TABLE IF NOT EXISTS v5_checkpoints(ticker TEXT NOT NULL,checkpoint INTEGER NOT NULL,scheduled REAL NOT NULL,deadline REAL NOT NULL,state TEXT NOT NULL DEFAULT 'PENDING',observed REAL,payload TEXT,reason TEXT,PRIMARY KEY(ticker,checkpoint));
CREATE INDEX IF NOT EXISTS v5_time ON v5_checkpoints(scheduled);
CREATE INDEX IF NOT EXISTS v5_due ON v5_checkpoints(state,scheduled);
CREATE TRIGGER IF NOT EXISTS v5_immutable BEFORE UPDATE ON v5_checkpoints WHEN OLD.state!='PENDING' BEGIN SELECT RAISE(ABORT,'V5 checkpoint immutable'); END;
CREATE TRIGGER IF NOT EXISTS v5_no_delete BEFORE DELETE ON v5_checkpoints BEGIN SELECT RAISE(ABORT,'V5 history cannot be deleted'); END;
CREATE TABLE IF NOT EXISTS v5_outbox(key TEXT PRIMARY KEY,ticker TEXT NOT NULL,checkpoint INTEGER,created REAL NOT NULL,expires REAL NOT NULL,message TEXT NOT NULL,state TEXT NOT NULL DEFAULT 'pending',sent REAL,attempts INTEGER NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS v5_delivery ON v5_outbox(state,expires);
CREATE TABLE IF NOT EXISTS v5_settings(name TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS v5_health(name TEXT PRIMARY KEY,observed REAL NOT NULL,payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS v5_evaluations(created REAL PRIMARY KEY,payload TEXT NOT NULL);
'''
CHECKPOINTS=(60,180,300,600)

def ensure(db):db.executescript(SCHEMA)

def settings(db):
    out={str(c):True for c in CHECKPOINTS};out.update(settlement=True,daily=False)
    for row in db.execute('SELECT name,value FROM v5_settings'):out[row['name']]=row['value']=='true'
    return out

def schedule(db,market):
    with db:
        for c in CHECKPOINTS:db.execute('INSERT OR IGNORE INTO v5_checkpoints(ticker,checkpoint,scheduled,deadline) VALUES(?,?,?,?)',(market['ticker'],c,market['opened']+c,market['opened']+c+5))

def metrics(pairs):
    import math
    n=len(pairs);wins=sum((p>=.5)==bool(y) for p,y in pairs)
    return {'n':n,'wins':wins,'losses':n-wins,'accuracy':wins/n if n else None,'brier':sum((p-y)**2 for p,y in pairs)/n if n else None,'log_loss':sum(-y*math.log(max(.000001,p))-(1-y)*math.log(max(.000001,1-p)) for p,y in pairs)/n if n else None}

def summary(db,now,selection='all'):
    from .storage import window_start
    since=window_start(selection,now)
    out=[]
    for c in CHECKPOINTS:
        r=db.execute("""SELECT
          count(*) total,
          sum(v.scheduled<=?) eligible,
          sum(v.state='FORECAST') forecast_count,
          sum(v.state='MISSED') missed,
          sum(v.state='NO CALL') no_call,
          sum(v.state='PENDING' OR (v.state='FORECAST' AND (m.result IS NULL OR m.result NOT IN ('yes','no')))) pending,
          sum(v.state='FORECAST' AND m.result IN ('yes','no')) n,
          sum(CASE WHEN v.state='FORECAST' AND m.result IN ('yes','no') THEN (json_extract(v.payload,'$.p_up')>=.5)=(m.result='yes') ELSE 0 END) wins,
          sum(CASE WHEN v.state='FORECAST' AND m.result IN ('yes','no') THEN (json_extract(v.payload,'$.p_up')-(m.result='yes'))*(json_extract(v.payload,'$.p_up')-(m.result='yes')) ELSE 0 END) squared
          FROM v5_checkpoints v LEFT JOIN intel_markets m USING(ticker)
          WHERE v.checkpoint=? AND v.scheduled>=?""",(now,c,since)).fetchone()
        result={k:int(r[k] or 0) for k in ('eligible','forecast_count','missed','no_call','pending','n','wins')}
        result.update(checkpoint=c,losses=result['n']-result['wins'],accuracy=result['wins']/result['n'] if result['n'] else None,brier=(r['squared'] or 0)/result['n'] if result['n'] else None,coverage=result['forecast_count']/result['eligible'] if result['eligible'] else None)
        out.append(result)
    return out
SCHEMA+='''
CREATE TABLE IF NOT EXISTS v5_paper(ticker TEXT NOT NULL,checkpoint INTEGER NOT NULL,side TEXT NOT NULL,issued REAL NOT NULL,entry_due REAL NOT NULL,state TEXT NOT NULL DEFAULT 'WAIT_ENTRY',entry REAL,entry_fee REAL,observed REAL,book_ts REAL,multiplier REAL,pnl REAL,reason TEXT,PRIMARY KEY(ticker,checkpoint));
CREATE INDEX IF NOT EXISTS v5_paper_open ON v5_paper(state);
'''
