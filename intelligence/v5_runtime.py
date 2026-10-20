"""Independent forecast clock and durable checkpoint-only Telegram outbox."""
import math
import threading
import time
from time import monotonic as decision_time
from scanner import timestamp
from .storage import migrate,loads,dumps
from .v5_engine import forecast
from .v5_storage import ensure,schedule,settings,CHECKPOINTS
from .recovery import resilient
from sqlite_runtime import health_write


def candle_dict(rows):
    return [dict(ts=r[0],low=r[1],high=r[2],open=r[3],close=r[4],volume=r[5]) for r in rows if len(r)==6]


def message(db,ticker,c,pred,now):
    first=db.execute('SELECT state,payload FROM v5_checkpoints WHERE ticker=? AND checkpoint=60',(ticker,)).fetchone()
    original=loads(first['payload'])['direction'] if first and first['state']=='FORECAST' else first['state'] if first else 'PENDING'
    previous=db.execute("SELECT payload FROM v5_checkpoints WHERE ticker=? AND checkpoint<? AND state='FORECAST' ORDER BY checkpoint DESC LIMIT 1",(ticker,c)).fetchone()
    prior=loads(previous['payload']) if previous else None
    changed=bool(prior and prior['direction']!=pred['direction'])
    delta='DIRECTION CHANGED: '+prior['direction']+' → '+pred['direction'] if changed else 'Direction unchanged' if prior else 'Original checkpoint'
    if prior:
        delta+=f"; reference moved ${pred['reference']-prior['reference']:+,.2f}; momentum changed {pred['features']['momentum']-prior['features']['momentum']:+.5f}"
    regime=pred.get('regime_details',{});old_regime=(prior or {}).get('regime')
    regime_note='Regime: '+pred['regime']+(' (was '+old_regime+')' if old_regime and old_regime!=pred['regime'] else '')
    regime_note+='; BTC liquidity: '+regime.get('liquidity',{}).get('state','UNAVAILABLE')
    regime_note+='; reversal risk: '+('; '.join(regime.get('warnings',[])) or 'no strong completed-candle warning')
    position=db.execute("SELECT side,entry,quantity FROM v3_watch_positions WHERE ticker=? AND state='WATCHING'",(ticker,)).fetchall()
    note=''
    if position:note='\nManual position: '+', '.join(f"{p['side']} ×{p['quantity']:g}; "+('forecast now opposes your side — recheck reversal risk' if pred['direction']!=p['side'] else 'forecast still favors your side') for p in position)+'. Current sellable bid/costs must be checked; no sale performed.'
    live_position=db.execute("SELECT ts,payload FROM v3_state WHERE name='v4'").fetchone()
    if live_position and 0<=now-live_position['ts']<=2:
        data=loads(live_position['payload'])
        if data.get('book_event_ts') is not None and 0<=now-data['book_event_ts']<=1:
            quotes=[p for p in data.get('positions',[]) if p.get('ticker')==ticker and p.get('status')=='LIVE']
            if quotes:note+='\nLatest verified cash-out estimates: '+ '; '.join(f"{p['side']} sellable bid ${p['bid']:.3f}, net ${p['net']:.2f}, ROI {p['roi']:.0%}; target {p['target_roi']:.0%}" for p in quotes)+'. Fees/slippage estimated, not a sale.'
    return (f"BTC Pro V5 · +{c//60}m · {ticker}\nOriginal: {original} | Latest: {pred['direction']} · {pred['conviction']}\n"
            f"UP estimate {pred['p_up']:.0%} — UNCALIBRATED / experimental\n{delta}\n"
            f"{regime_note}\nBull: {pred['bullish'][0]}\nBear: {pred['bearish'][0]}\n"
            f"Strike ${pred['strike']:,.2f}; {pred['source']} ${pred['reference']:,.2f}\n"
            f"{pred['remaining']:.0f}s remaining; data age {pred['quote_age']:.2f}s\n"
            f"WAIT — forecast is not an entry recommendation. {pred['risk']}\n{pred['version']}{note}\nManual only. Changed opinions are scored only at official settlement.")

class Runtime:
    def __init__(self,scheduler):self.scheduler=scheduler;self.stop=threading.Event();self.threads=[];self.last_error={};self.last_attempt={};self.scheduled=set();self.health_at=0
    def start(self):
        for fn,name in [(self.run,'v5-forecast-clock'),(self.deliver,'v5-telegram'),(self.research,'v5-model-research'),(self.observe,'v5-live-regime')]:
            t=threading.Thread(target=fn,name=name,daemon=True);t.start();self.threads.append(t)
    def close(self):
        self.stop.set()
        for t in self.threads:t.join(timeout=3)
    @resilient
    def research(self):
        from .v5_evaluation import train
        db=migrate(self.scheduler.path)
        try:
            ensure(db)
            while not self.stop.is_set():
                try:train(db,time.time())
                except Exception as exc:
                    with health_write(db) as health:health.execute("INSERT OR REPLACE INTO v5_health VALUES('research',?,?)",(time.time(),dumps({'ok':False,'error':type(exc).__name__})))
                self.stop.wait(1800)
        finally:db.close()
    @resilient
    def observe(self):
        # Descriptive live context only: never creates/replaces a scheduled forecast.
        db=migrate(self.scheduler.path)
        try:
            ensure(db)
            while not self.stop.is_set():
                now=time.time()
                try:
                    m,kwargs=self.inputs(now);pred=forecast(**kwargs)
                    data={'ok':True,'ticker':m['ticker'],'reference_ts':pred['reference_ts'],'source':pred['source'],'regime':pred['regime_details'],'risk':pred['risk']}
                except (ValueError,KeyError,TypeError):data={'ok':False,'reason':'Fresh essential inputs unavailable; no live regime fabricated'}
                with health_write(db) as health:health.execute("INSERT OR REPLACE INTO v5_health VALUES('live_context',?,?)",(now,dumps(data)))
                self.stop.wait(2)
        finally:db.close()
    def inputs(self,now):
        with self.scheduler.lock:c=dict(self.scheduler.cache)
        meta=c.get('metadata') or {};m=meta.get('current');q=c.get('quote') or {}
        if not m:raise ValueError('CURRENT_MARKET_UNAVAILABLE')
        if not 0<=now-meta['received']<=30:raise ValueError('OFFICIAL_METADATA_STALE')
        if m.get('floor_strike') is None:raise ValueError('OFFICIAL_STRIKE_UNAVAILABLE')
        live=self.scheduler.spot_stream.snapshot() if self.scheduler.spot_stream else None
        if live and live['status']=='LIVE':q={'price':live['price'],'timestamp':live['event_ts'],'source':'Coinbase verified WebSocket PROXY'}
        if not q:raise ValueError('ESSENTIAL_QUOTE_UNAVAILABLE')
        brti=self.scheduler.brti_stream.snapshot() if getattr(self.scheduler,'brti_stream',None) else None
        extra=c.get('v5candles') or {}
        return m,dict(now=now,opened=timestamp(m['open_time']),closed=timestamp(m['close_time']),strike=float(m['floor_strike']),price=q['price'],quote_ts=q['timestamp'],candles1=candle_dict(c.get('candles') or []),candles5=candle_dict(extra.get(300,[])),candles15=candle_dict(extra.get(900,[])),ticks=live.get('rows',[]) if live and live['status']=='LIVE' else [],source=q.get('source','Coinbase REST spot PROXY'),brti=brti,btc_liquidity=c.get('btcliquidity'))
    def tick(self,db,now):
        with self.scheduler.lock:meta=dict(self.scheduler.cache.get('metadata') or {})
        # Register all known official markets, including ones discovered after a deadline.
        for m in meta.get('markets',[]):
            if m['ticker'] not in self.scheduled:
                schedule(db,{'ticker':m['ticker'],'opened':timestamp(m['open_time'])});self.scheduled.add(m['ticker'])
        if len(self.scheduled)>512:self.scheduled={m['ticker'] for m in meta.get('markets',[])}
        due=db.execute("SELECT * FROM v5_checkpoints WHERE state='PENDING' AND scheduled<=? ORDER BY scheduled LIMIT 128",(now,)).fetchall()
        for r in due:
            key=(r['ticker'],r['checkpoint'])
            if now>r['deadline']:
                state='NO CALL' if key in self.last_error else 'MISSED'
                reason=self.last_error.get(key,'Technical deadline passed without a committed timely forecast; never backfilled')
                with db:db.execute("UPDATE v5_checkpoints SET state=?,reason=? WHERE ticker=? AND checkpoint=? AND state='PENDING'",(state,reason,*key))
                self.last_error.pop(key,None);self.last_attempt.pop(key,None);continue
            start=decision_time()
            try:
                m,kwargs=self.inputs(now)
                if m['ticker']!=r['ticker']:raise ValueError('MARKET_ROLLOVER_NOT_VERIFIED')
                pred=forecast(**kwargs)
            except (ValueError,KeyError,TypeError,OverflowError) as exc:
                self.last_error[key]=str(exc)[:200];continue
            with db:
                actual=now+decision_time()-start
                if actual>r['deadline'] or not 0<=actual-pred['reference_ts']<=3:
                    # Reservation delays cannot backdate predictions or reuse stale evidence.
                    self.last_error.pop(key,None);continue
                # Odds are attached AFTER forecasting, only as a separately labeled comparison.
                favorite=None
                with self.scheduler.lock:b=self.scheduler.cache.get('book') or {}
                if b.get('ticker')==r['ticker'] and 0<=actual-b.get('received',0)<=2:
                    book=b['book']
                    if book.yes and book.no:
                        implied=(book.yes[0][0]+1-book.no[0][0])/2
                        favorite={'p_up':implied,'direction':'UP' if implied>=.5 else 'DOWN','disagrees':(implied>=.5)!=(pred['direction']=='UP'),'observed':b['received']}
                pred['market_comparison']=favorite
                pred['observed']=actual
                # Atomic original forecast and durable alert: no committed forecast without its outbox row.
                cur=db.execute("UPDATE v5_checkpoints SET state='FORECAST',observed=?,payload=?,reason=? WHERE ticker=? AND checkpoint=? AND state='PENDING'",(actual,dumps(pred),'Fresh causal BTC inputs; fixed +5s technical deadline',*key))
                if cur.rowcount:
                    text=message(db,r['ticker'],r['checkpoint'],pred,actual)
                    db.execute('INSERT OR IGNORE INTO v5_outbox(key,ticker,checkpoint,created,expires,message) VALUES(?,?,?,?,?,?)',(f"v5:{r['ticker']}:{r['checkpoint']}",r['ticker'],r['checkpoint'],actual,min(actual+20,kwargs['closed']),text))
            self.last_error.pop(key,None)
        # Cap temporary diagnostics; persistent decisions stay in SQLite forever.
        if len(self.last_error)>256:self.last_error={k:self.last_error[k] for k in list(self.last_error)[-256:]}
        if now-self.health_at>=1:
            with health_write(db) as health:health.execute("INSERT OR REPLACE INTO v5_health VALUES('clock',?,?)",(time.time(),dumps({'ok':True,'pending_due':len(due),'last_input_errors':list(self.last_error.values())[-4:]})))
            self.health_at=now
    @resilient
    def run(self):
        db=migrate(self.scheduler.path)
        try:
            ensure(db)
            while not self.stop.is_set():
                try:self.tick(db,time.time())
                except Exception as exc:
                    with health_write(db) as health:health.execute("INSERT OR REPLACE INTO v5_health VALUES('clock',?,?)",(time.time(),dumps({'ok':False,'error':type(exc).__name__})))
                self.stop.wait(.2)
        finally:db.close()
    def flush(self,db,now):
        opts=settings(db);telegram=self.scheduler.telegram
        with db:
            db.execute("UPDATE v5_outbox SET state='delivery_unknown' WHERE state='sending'")
            db.execute("UPDATE v5_outbox SET state='expired' WHERE state='pending' AND expires<=?",(now,))
        if not telegram or not telegram.enabled:return
        for r in db.execute("SELECT * FROM v5_outbox WHERE state='pending' AND expires>? ORDER BY created LIMIT 8",(now,)).fetchall():
            with db:
                if not opts.get(str(r['checkpoint']) if r['checkpoint'] else r['key'].split(':')[0],False):
                    db.execute("UPDATE v5_outbox SET state='disabled' WHERE key=?",(r['key'],));continue
                if time.time()>=r['expires']:continue
                claim=db.execute("UPDATE v5_outbox SET state='sending',attempts=attempts+1 WHERE key=? AND state='pending'",(r['key'],))
                if not claim.rowcount:continue
            # No automatic retry of an ambiguous HTTP result: avoid duplicate phone notifications.
            if time.time()>=r['expires']:
                with db:db.execute("UPDATE v5_outbox SET state='expired' WHERE key=?",(r['key'],))
                continue
            try:telegram.send(r['message'])
            except Exception:
                with db:db.execute("UPDATE v5_outbox SET state='delivery_unknown' WHERE key=?",(r['key'],))
                continue
            sent=time.time()
            with db:db.execute("UPDATE v5_outbox SET state=?,sent=? WHERE key=?",('sent' if sent<r['expires'] else 'sent_late',sent,r['key']))
    def outcomes(self,db,now):
        for m in db.execute("SELECT DISTINCT m.ticker,m.result FROM intel_markets m JOIN v5_checkpoints v USING(ticker) WHERE m.result IN ('yes','no') AND v.state='FORECAST' ORDER BY m.closed DESC LIMIT 128"):
            rows=db.execute("SELECT checkpoint,payload FROM v5_checkpoints WHERE ticker=? AND state='FORECAST' ORDER BY checkpoint",(m['ticker'],)).fetchall()
            result='UP' if m['result']=='yes' else 'DOWN'
            text='BTC Pro V5 · OFFICIAL SETTLEMENT '+result+'\n'+m['ticker']+'\n'+' | '.join(f"+{r['checkpoint']//60}m {loads(r['payload'])['direction']}: "+('WIN' if loads(r['payload'])['direction']==result else 'LOSS') for r in rows)+'\nPaper forecasts, not realized trading profits. Manual only.'
            with db:db.execute('INSERT OR IGNORE INTO v5_outbox(key,ticker,created,expires,message) VALUES(?,?,?,?,?)',('settlement:'+m['ticker'],m['ticker'],now,now+300,text))
    def daily(self,db,now):
        from datetime import datetime,timedelta
        from .storage import ET
        local=datetime.fromtimestamp(now,ET)
        if local.hour!=0 or local.minute<5:return
        start=local.replace(hour=0,minute=0,second=0,microsecond=0)
        previous=start-timedelta(days=1);lo=previous.timestamp();hi=start.timestamp()
        rows=db.execute("SELECT v.checkpoint,v.payload,m.result FROM v5_checkpoints v JOIN intel_markets m USING(ticker) WHERE v.state='FORECAST' AND v.scheduled>=? AND v.scheduled<? AND m.result IN ('yes','no')",(lo,hi)).fetchall()
        if not rows:return
        lines=[]
        for c in CHECKPOINTS:
            g=[r for r in rows if r['checkpoint']==c];wins=sum((loads(r['payload'])['direction']=='UP')==(r['result']=='yes') for r in g)
            lines.append(f"+{c//60}m {wins}–{len(g)-wins} (n={len(g)})")
        with db:db.execute('INSERT OR IGNORE INTO v5_outbox(key,ticker,created,expires,message) VALUES(?,?,?,?,?)',('daily:'+previous.date().isoformat(),'DAILY',now,hi+3600,'BTC Pro V5 · '+previous.date().isoformat()+' ET\n'+' | '.join(lines)+'\nOfficial settled paper forecasts, not trading profit.'))
    @resilient
    def deliver(self):
        db=migrate(self.scheduler.path)
        try:
            ensure(db);last=0
            while not self.stop.is_set():
                try:
                    now=time.time()
                    if now-last>=15:self.outcomes(db,now);self.daily(db,now);last=now
                    from .v5_paper import observe
                    observe(db,self.scheduler,now)
                    self.flush(db,now)
                    with health_write(db) as health:health.execute("INSERT OR REPLACE INTO v5_health VALUES('telegram',?,?)",(time.time(),dumps({'ok':bool(self.scheduler.telegram and self.scheduler.telegram.enabled),'delivery':'HTTP acceptance only; ambiguous requests are not blindly resent'})))
                except Exception as exc:
                    with health_write(db) as health:health.execute("INSERT OR REPLACE INTO v5_health VALUES('telegram',?,?)",(time.time(),dumps({'ok':False,'error':type(exc).__name__})))
                self.stop.wait(.25)
        finally:db.close()
