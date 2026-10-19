"""Additive V3 tables. No existing history is rewritten or seeded."""
SCHEMA='''
CREATE TABLE IF NOT EXISTS v3_state(name TEXT PRIMARY KEY,ts REAL NOT NULL,payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS v3_candle_provenance(period INTEGER NOT NULL,ts REAL NOT NULL,origin TEXT NOT NULL,first_event REAL,last_event REAL,PRIMARY KEY(period,ts));
CREATE TABLE IF NOT EXISTS v3_ticks(source TEXT NOT NULL,id TEXT NOT NULL,event REAL NOT NULL,received REAL NOT NULL,price REAL NOT NULL,size REAL NOT NULL,continuous INTEGER NOT NULL,PRIMARY KEY(source,id));
CREATE INDEX IF NOT EXISTS v3_tick_time ON v3_ticks(source,event);
CREATE TABLE IF NOT EXISTS v3_call_paths(key TEXT PRIMARY KEY,last_event REAL,last_id INTEGER,gaps INTEGER NOT NULL DEFAULT 0,hit_ts REAL,hit_price REAL,state TEXT NOT NULL DEFAULT 'PENDING');
CREATE TABLE IF NOT EXISTS v3_contract_samples(id INTEGER PRIMARY KEY,ticker TEXT NOT NULL,side TEXT NOT NULL,observed REAL NOT NULL,entry_ask REAL NOT NULL,entry_fee REAL NOT NULL,multiplier REAL NOT NULL,horizon INTEGER NOT NULL,due REAL NOT NULL,spread REAL NOT NULL,imbalance REAL,btc_velocity REAL,regime TEXT,state TEXT NOT NULL DEFAULT 'PENDING',bid REAL,exit_fee REAL,outcome_ts REAL,net REAL,UNIQUE(ticker,side,observed,horizon));
CREATE INDEX IF NOT EXISTS v3_samples_comparable ON v3_contract_samples(side,horizon,entry_ask,observed);
CREATE INDEX IF NOT EXISTS v3_sample_due ON v3_contract_samples(state,due);
CREATE TABLE IF NOT EXISTS v3_watch_positions(id INTEGER PRIMARY KEY,ticker TEXT NOT NULL,side TEXT NOT NULL,entry REAL NOT NULL,quantity REAL NOT NULL,entry_fee REAL NOT NULL,created REAL NOT NULL,state TEXT NOT NULL DEFAULT 'WATCHING',target_roi REAL NOT NULL,notified TEXT NOT NULL DEFAULT '[]',last_bid REAL,last_ts REAL,last_net REAL,last_roi REAL,basis TEXT NOT NULL DEFAULT 'USER_SUPPLIED — NOT ACCOUNT DATA');
CREATE TABLE IF NOT EXISTS v3_paper_rules(sim_id INTEGER PRIMARY KEY,target_roi REAL NOT NULL,stop_roi REAL NOT NULL DEFAULT -0.25,created REAL NOT NULL,exit_decision REAL,exit_reason TEXT);
CREATE TABLE IF NOT EXISTS v3_settings(name TEXT PRIMARY KEY,value TEXT NOT NULL,updated REAL NOT NULL);
CREATE TABLE IF NOT EXISTS v3_model_comparisons(version TEXT PRIMARY KEY,created REAL NOT NULL,payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS v3_module_events(id INTEGER PRIMARY KEY,ticker TEXT NOT NULL,module TEXT NOT NULL,observed REAL NOT NULL,direction TEXT,signal TEXT,features TEXT NOT NULL,regime TEXT,result TEXT,UNIQUE(ticker,module,observed));
CREATE INDEX IF NOT EXISTS v3_modules_time ON v3_module_events(module,observed);
'''
