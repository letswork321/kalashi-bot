"""One-contract delayed-entry settlement paper cohorts; never sends an order."""
from scanner import fee
from .economics import executable
from .storage import loads

def observe(db,scheduler,now):
    with scheduler.lock:book=dict(scheduler.cache.get('book') or {})
    owner=getattr(scheduler,'owner',None);snapshot=getattr(owner,'latest_snapshot',None) or {}
    for r in db.execute("SELECT ticker,checkpoint,observed,payload FROM v5_checkpoints WHERE state='FORECAST' ORDER BY scheduled DESC LIMIT 128"):
        with db:db.execute('INSERT OR IGNORE INTO v5_paper(ticker,checkpoint,side,issued,entry_due,reason) VALUES(?,?,?,?,?,?)',(r['ticker'],r['checkpoint'],loads(r['payload'])['direction'],r['observed'],r['observed']+1,'Fixed one-second execution delay; full one-contract depth required, then official settlement'))
    for r in db.execute("SELECT * FROM v5_paper WHERE state='WAIT_ENTRY'").fetchall():
        if now<r['entry_due']:continue
        key=(r['ticker'],r['checkpoint'])
        if now>r['entry_due']+3:
            with db:db.execute("UPDATE v5_paper SET state='MISSED_ENTRY',reason='No timely verified book and fee observation; no fill fabricated' WHERE ticker=? AND checkpoint=?",key)
            continue
        if book.get('ticker')!=r['ticker'] or not r['entry_due']<=book.get('received',0)<=now or now-book['received']>2:continue
        if not snapshot.get('fee_valid') or snapshot.get('market',{}).get('ticker')!=r['ticker'] or not 0<=now-snapshot.get('now',0)<=30:continue
        try:
            entry=executable(book['book'],r['side'],'buy',quantity=1,slippage=.002);mult=snapshot['fee_multiplier'];f=fee(entry,1,.07,mult)
        except (ValueError,KeyError,TypeError):continue
        with db:db.execute("UPDATE v5_paper SET state='OPEN',entry=?,entry_fee=?,observed=?,book_ts=?,multiplier=? WHERE ticker=? AND checkpoint=? AND state='WAIT_ENTRY'",(entry,f,now,book['received'],mult,*key))
    for r in db.execute("SELECT p.*,m.result FROM v5_paper p JOIN intel_markets m USING(ticker) WHERE p.state='OPEN' AND m.result IN ('yes','no')").fetchall():
        won=(r['side']=='UP')==(r['result']=='yes');net=int(won)-r['entry']-r['entry_fee']
        with db:db.execute("UPDATE v5_paper SET state='SETTLED',pnl=? WHERE ticker=? AND checkpoint=?",(net,r['ticker'],r['checkpoint']))

def summary(db):
    rows=[dict(r) for r in db.execute('SELECT * FROM v5_paper ORDER BY issued DESC LIMIT 2000')];equity=0;peak=0;drawdown=0
    for r in reversed(rows):
        if r['pnl'] is not None:equity+=r['pnl'];peak=max(peak,equity);drawdown=max(drawdown,peak-equity)
    return {'cohorts':[dict(r) for r in db.execute('SELECT checkpoint,state,count(*) n,sum(pnl) net FROM v5_paper GROUP BY checkpoint,state')],'net':db.execute("SELECT COALESCE(sum(pnl),0) FROM v5_paper WHERE state='SETTLED'").fetchone()[0],'max_drawdown_dollars':drawdown,'drawdown_scope':'most recent 2000 paper records ordered by entry; settlement-time equity can differ','basis':'One-contract directional paper strategies, fixed 1s delay, observed executable ask/depth, $0.002 slippage, verified standard taker fees, official settlement; no passive-fill assumption. Not realized money. Early-exit/flip/scalp paper remain separate existing tools.','recent':rows[:40]}
