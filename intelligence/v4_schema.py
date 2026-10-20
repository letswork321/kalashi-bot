"""Additive V4 audit tables; no historical scoring definitions are rewritten."""
SCHEMA='''
CREATE TABLE IF NOT EXISTS v4_events(id INTEGER PRIMARY KEY,ticker TEXT,observed REAL NOT NULL,kind TEXT NOT NULL,side TEXT,state TEXT NOT NULL,payload TEXT NOT NULL,result TEXT);
CREATE INDEX IF NOT EXISTS v4_event_time ON v4_events(ticker,kind,observed);
CREATE TABLE IF NOT EXISTS v4_profit_paths(id INTEGER PRIMARY KEY,ticker TEXT NOT NULL,side TEXT NOT NULL,issued REAL NOT NULL,entry_due REAL NOT NULL,closed REAL NOT NULL,ask REAL NOT NULL,quantity REAL NOT NULL,entry_fee REAL NOT NULL,multiplier REAL NOT NULL,goal REAL NOT NULL,stop REAL NOT NULL,version TEXT NOT NULL,provenance TEXT NOT NULL,state TEXT NOT NULL DEFAULT 'WAIT_ENTRY',entry REAL,filled REAL,last_event REAL,max_roi REAL,hit REAL,barrier TEXT,coverage TEXT NOT NULL DEFAULT 'UNVERIFIED',last_bid REAL);
CREATE INDEX IF NOT EXISTS v4_path_open ON v4_profit_paths(ticker,state);
CREATE TRIGGER IF NOT EXISTS v4_frozen_profit BEFORE UPDATE OF ticker,side,issued,entry_due,closed,ask,quantity,entry_fee,multiplier,goal,stop,version,provenance ON v4_profit_paths BEGIN SELECT RAISE(ABORT,'Original profit hypothesis is immutable'); END;
CREATE TABLE IF NOT EXISTS v4_position_details(watch_id INTEGER PRIMARY KEY,fee_basis TEXT NOT NULL,max_roi REAL,realized_ts REAL,exit_price REAL,exit_fee REAL,realized_net REAL,realized_basis TEXT);
CREATE TABLE IF NOT EXISTS v4_macro(id TEXT PRIMARY KEY,scheduled REAL NOT NULL,published REAL,consensus REAL,actual REAL,surprise REAL,source TEXT NOT NULL,received REAL NOT NULL,title TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS v4_mistakes(ticker TEXT PRIMARY KEY,created REAL NOT NULL,payload TEXT NOT NULL);
CREATE TRIGGER IF NOT EXISTS v4_frozen_mistake BEFORE UPDATE ON v4_mistakes BEGIN SELECT RAISE(ABORT,'Research summary is immutable'); END;
CREATE TABLE IF NOT EXISTS v4_challengers(ticker TEXT PRIMARY KEY,observed REAL NOT NULL,version TEXT NOT NULL,p_up REAL,features TEXT NOT NULL,state TEXT NOT NULL,reason TEXT NOT NULL);
CREATE TRIGGER IF NOT EXISTS v4_frozen_challenger BEFORE UPDATE ON v4_challengers BEGIN SELECT RAISE(ABORT,'Shadow forecast is immutable'); END;
CREATE TABLE IF NOT EXISTS v4_health(id INTEGER PRIMARY KEY,observed REAL NOT NULL,source TEXT NOT NULL,state TEXT NOT NULL,payload TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS v4_health_time ON v4_health(observed);
'''
SCHEMA+='''
CREATE TABLE IF NOT EXISTS v4_call_endpoints(key TEXT PRIMARY KEY,issued REAL NOT NULL,ack REAL NOT NULL,due REAL NOT NULL,side TEXT NOT NULL,target REAL NOT NULL,state TEXT NOT NULL DEFAULT 'PENDING',observed REAL,price REAL);
CREATE TRIGGER IF NOT EXISTS v4_endpoint_frozen BEFORE UPDATE OF key,issued,ack,due,side,target ON v4_call_endpoints BEGIN SELECT RAISE(ABORT,'Endpoint definition immutable'); END;
'''
SCHEMA+='''
CREATE TRIGGER IF NOT EXISTS v4_event_frozen BEFORE UPDATE OF ticker,observed,kind,side,state,payload ON v4_events BEGIN SELECT RAISE(ABORT,'Issued warning immutable'); END;
'''
SCHEMA+='''
CREATE INDEX IF NOT EXISTS v4_path_state ON v4_profit_paths(state);
CREATE INDEX IF NOT EXISTS v4_warning_result ON v4_events(kind,state,result);
CREATE INDEX IF NOT EXISTS v4_lock_diagnostics ON intel_lock_attempts(reason,ticker);
'''
