"""Background coordinator; SQLite connections belong to their own threads."""
from .recovery import resilient
from sqlite_runtime import health_write,rollback
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
import logging
import threading
import time
from . import VERSION
from .storage import migrate,connect,register_market,lock_forecast,tracker_summary,dumps,loads,ET
from .collector import Collector
from .engines import breakout_engine,reversal_engine,confluence_engine,observe_reversal,reversal_evidence,regime_detector
from .economics import flip_radar,scalp_radar,fair_value,Simulator,executable
from .models import features,shadow,retrain,evaluation
from .research import Backfill,report
from .streams import OptionalStream
from .notifications import Notifications
from . import callouts

class IntelligenceWorker:
    def __init__(self,path,telegram=None):
        self.path=Path(path);self.telegram=telegram;self.stop=threading.Event();self.thread=None;self.maintenance=None;self.stream=OptionalStream();self.error=None;self.scheduler=None;self.dispatcher=None;self.latest_snapshot=None;self.observer=None;self.v3=None;self.raw_snapshot=None
    def start(self):
        self.thread=threading.Thread(target=self.run,name='intelligence-collector',daemon=True);self.thread.start()
    def close(self):
        self.stop.set();self.stream.close()
        if self.scheduler:self.scheduler.close()
        if self.v3:self.v3.close()
        if self.thread:self.thread.join(timeout=3)
    @resilient
    def dispatch_alerts(self):
        db=migrate(self.path);notify=Notifications(db,self.telegram)
        try:
            while not self.stop.is_set():
                try:
                    notify.withdraw({'now':time.time(),'market':{'ticker':''}},[],expired_only=True)
                    notify.flush(time.time(),self.latest_snapshot)
                except Exception:
                    with health_write(db) as health:health.execute('INSERT OR REPLACE INTO intel_health VALUES(?,?,?)',('alert_dispatcher',time.time(),dumps({'ok':False,'reason':'Delivery unavailable; credentials redacted'})))
                self.stop.wait(.2)
        finally:db.close()
    @resilient
    def observe_execution(self):
        """Fast, network-free observer; research HTTP cannot hide delivery-time quotes."""
        from .economics import evaluate_flips
        from scanner import Book
        db=migrate(self.path);notify=Notifications(db,self.telegram);sim=Simulator(db);last_book=None;book_id=None
        try:
            while not self.stop.is_set():
                now=time.time();s=self.latest_snapshot
                with db:
                    db.execute("UPDATE intel_alert_evidence SET evaluation='MISSED_POST_DELIVERY_OBSERVATION' WHERE evaluation='AWAITING_LIVE_OBSERVATION' AND sent+3<?",(now,))
                    db.execute("UPDATE intel_sim SET state='CANCELLED',reason='Entry observation deadline missed' WHERE state='PENDING_ENTRY' AND entry_due+3<?",(now,))
                    db.execute("UPDATE intel_sim SET state='MISSED_EXIT',reason='Exit observation missed; no fabricated exit' WHERE state='OPEN' AND exit_due+3<?",(now,))
                    db.execute("UPDATE intel_flip_followups SET state='MISSED_ENTRY',reason='No delayed quote available' WHERE state='WAIT_ENTRY' AND entry_due+3<?",(now,))
                    db.execute("UPDATE intel_flip_followups SET state='MISSED_EXIT',reason='No exit quote available' WHERE state='OPEN' AND exit_due+3<?",(now,))
                try:
                    # When a slow collection cycle ages, use the independent clock's
                    # cached quotes/books plus a recently verified same-market fee.
                    if not s or now-s['now']>1:
                        fast,_,_=self.scheduler.snapshot(now)
                        if not fast or not s or fast['market']['ticker']!=s['market']['ticker'] or now-s['now']>60 or not s.get('fee_valid'):
                            self.stop.wait(.2);continue
                        fast.update(fee_valid=True,fee_multiplier=s['fee_multiplier']);s=fast
                        ws=self.stream.snapshot()
                        if ws and ws['ticker']==s['market']['ticker'] and 0<=now-ws['received']<=1 and ws['latency']<=1 and ws.get('event_ts') is not None and 0<=now-ws['event_ts']<=1:
                            s.update(book=Book.parse({'yes_dollars':ws['yes'],'no_dollars':ws['no']}),book_ts=ws['event_ts'],book_latency=ws['latency'],book_source='websocket',ws_sequence_valid=True,book_history=ws['history'])
                        key=(s['market']['ticker'],s['book_ts'],s['book_source'])
                        if key!=last_book:
                            b=s['book']
                            with db:book_id=db.execute('INSERT INTO intel_books(ticker,ts,event_ts,source,yes,no,spread,imbalance,latency,fee_multiplier) VALUES(?,?,?,?,?,?,?,?,?,?)',(s['market']['ticker'],s['book_ts'],s['book_ts'],s['book_source'],dumps(b.yes),dumps(b.no),b.spread,b.imbalance,s['book_latency'],s['fee_multiplier'])).lastrowid
                            last_book=key
                        s['book_id']=book_id
                    s={**s,'now':now}
                    notify.evaluate_delivered(s);sim.update(s);evaluate_flips(db,s)
                    with db:
                        db.execute("UPDATE intel_sim SET state='CANCELLED',reason='Entry observation deadline missed' WHERE state='PENDING_ENTRY' AND entry_due+3<?",(now,))
                        db.execute("UPDATE intel_sim SET state='MISSED_EXIT',reason='Exit observation missed; no fabricated exit' WHERE state='OPEN' AND exit_due+3<?",(now,))
                except Exception as exc:
                    with health_write(db) as health:health.execute('INSERT OR REPLACE INTO intel_health VALUES(?,?,?)',('execution_observer',now,dumps({'ok':False,'reason':type(exc).__name__})))
                self.stop.wait(.2)
        finally:db.close()
    @resilient
    def background_research(self):
        from scanner import HTTP
        db=migrate(self.path)
        try:
            last=0;first=True
            while not self.stop.is_set():
                now=time.time()
                if first:
                    job=db.execute('SELECT ended FROM intel_jobs WHERE kind=\'public_backfill\' AND status=\'COMPLETE\' ORDER BY id DESC LIMIT 1').fetchone()
                    if not job or now-job['ended']>86400:Backfill(db,HTTP()).run(7,10,now)
                    anchor=int(now//86400)*86400
                    attempted=db.execute("SELECT 1 FROM intel_jobs WHERE kind='trade_vwap_backfill' AND start_ts=? AND status IN ('COMPLETE','PARTIAL')",(anchor,)).fetchone()
                    if not attempted:Backfill(db,HTTP()).trade_session(32,now)
                    first=False
                if now-last>=1800:
                    n=db.execute("SELECT count(*) FROM intel_locks WHERE state='LOCKED' AND result IN ('yes','no')").fetchone()[0]
                    last_model=db.execute('SELECT report FROM intel_models ORDER BY created DESC LIMIT 1').fetchone()
                    prior=loads(last_model['report']).get('dataset_total',loads(last_model['report']).get('training_markets',0)) if last_model else 0
                    if n>=100 and n-prior>=10:retrain(db,now)
                    if n>=100:
                        from .boosted_models import retrain_comparison
                        retrain_comparison(db,now)
                    last=now
                self.stop.wait(15)
        except Exception as exc:
            with health_write(db) as health:health.execute('INSERT OR REPLACE INTO intel_health VALUES(?,?,?)',('research_worker',time.time(),dumps({'ok':False,'reason':type(exc).__name__})))
            raise
        finally:db.close()
    def reconcile(self,db,collector,sim,notify,now):
        rows=db.execute("SELECT ticker FROM intel_markets WHERE closed<? AND result IS NULL ORDER BY closed DESC LIMIT 50",(now,)).fetchall()
        for row in rows:
            if self.stop.is_set():break
            try:
                m=collector.k.market(row['ticker']);old=db.execute('SELECT result FROM intel_markets WHERE ticker=?',(row['ticker'],)).fetchone()
                register_market(db,m,now);sim.settle(m,now)
                if m.get('result') in ('yes','no') and m.get('status') in ('finalized','settled') and not old['result']:
                    locked=db.execute('SELECT direction,p_up,state FROM intel_locks WHERE ticker=?',(row['ticker'],)).fetchone()
                    message=f"FINAL {row['ticker']}: {m['result'].upper()}\nLocked forecast: {locked['direction'] if locked else 'MISSED'}\nOfficial Kalshi result; no real trades executed."
                    notify.enqueue('settlement',row['ticker'],'final:'+row['ticker'],message,now,now+3600)
            except Exception:pass
    def run(self):
        db=None
        try:
            db=migrate(self.path);callouts.ensure(db);collector=Collector(db,self.stream);sim=Simulator(db);notify=Notifications(db,self.telegram);self.stream.start()
            from .scheduler import ForecastScheduler
            self.scheduler=ForecastScheduler(self.path,self.telegram);self.scheduler.start()
            self.dispatcher=threading.Thread(target=self.dispatch_alerts,daemon=True,name='telegram-dispatcher');self.dispatcher.start()
            self.observer=threading.Thread(target=self.observe_execution,daemon=True,name='execution-quote-observer');self.observer.start()
            from .v3_runtime import V3Runtime
            self.v3=V3Runtime(self);collector.spot_stream=self.v3.spot;self.scheduler.spot_stream=self.v3.spot;self.v3.start()
            self.maintenance=threading.Thread(target=self.background_research,daemon=True,name='research-model-worker');self.maintenance.start()
            last_settle=last_retention=0;daily=None;radar_last={}
            with ThreadPoolExecutor(max_workers=3,thread_name_prefix='strategy') as pool:
                while not self.stop.is_set():
                    begin=time.time()
                    try:
                        if begin-last_settle>=30:self.reconcile(db,collector,sim,notify,begin);last_settle=begin
                        # Expire missed deadlines even if an entire feed is unavailable.
                        with db:
                            db.execute("UPDATE intel_locks SET state='MISSED',reason='Lock deadline passed without valid live observation' WHERE state='PENDING' AND deadline<?",(begin,))
                            db.execute("UPDATE intel_reversals SET state='MISSED',reason='10-minute quote observation missed' WHERE state='PENDING' AND target+3<?",(begin,))
                            db.execute("UPDATE intel_reversals SET outcome='MISSED' WHERE state='OBSERVED' AND band IS NOT NULL AND outcome IS NULL AND outcome_target+3<?",(begin,))
                        s=collector.snapshot();s['now']=time.time()
                        if self.stop.is_set():break
                        callouts.observe(db,s['now'],s.get('quote_ts'),s.get('price'))
                        regime=regime_detector(s);s['regime']=regime
                        active_callout=callouts.build(s)
                        observe_reversal(db,s)
                        r=db.execute('SELECT * FROM intel_reversals WHERE ticker=?',(s['market']['ticker'],)).fetchone();s['reversal']=dict(r) if r else None
                        s['reversal_evidence']=reversal_evidence(db,s['reversal'].get('band') if s['reversal'] else None)
                        # Independent workers; no engine sees/suppresses another engine.
                        futures=[pool.submit(fn,s) for fn in (breakout_engine,reversal_engine,confluence_engine)]
                        engines=[f.result(timeout=3) for f in futures]
                        candidate=shadow(db,s)
                        from .economics import scalp_evidence
                        s['scalp_evidence']=scalp_evidence(db,s['now'])
                        flips=flip_radar(s);scalps=scalp_radar(s);fv=fair_value(s,candidate)
                        from .economics import compare_flips
                        flips=compare_flips(db,s,flips)
                        for engine in engines:
                            bar=engine.get('readings',{}).get('trigger_close',int(s['now']//900)*900)
                            with db:db.execute('INSERT OR IGNORE INTO intel_engines(engine,ticker,bar,observed,signal,direction,quality,payload,regime) VALUES(?,?,?,?,?,?,?,?,?)',(engine['engine'],s['market']['ticker'],bar,s['now'],engine['signal'],engine.get('direction') if engine['signal'] in ('LONG BREAKOUT — CONFIRMED','REVERSAL RISK / FADE OPPORTUNITY','CONFLUENCE BUY','CONFLUENCE SELL') else None,engine['quality'],dumps(engine),regime['regime']))
                            if s.get('fee_valid') and engine.get('direction') and engine['quality']=='LIVE' and engine['signal'] not in ('UNCONFIRMED BREAKOUT WATCH',):
                                sim.propose(f"engine:{engine['engine']}:{s['market']['ticker']}:{bar}",'directional',engine['engine'],s,engine['direction'],None)
                        for kind,radar,states in [('flip',flips,('POTENTIAL OPPORTUNITY',)),('scalp',scalps,('OPPORTUNITY','WATCH'))]:
                            for rr in radar['rows']:
                                radar_key=(kind,s['market']['ticker'],rr.get('side'),rr.get('window'))
                                previous=radar_last.get(radar_key)
                                if not previous or previous[0]!=rr['status'] or s['now']-previous[1]>=30:
                                    with db:
                                        rid=db.execute('INSERT INTO intel_radars(kind,ticker,observed,side,status,payload) VALUES(?,?,?,?,?,?)',(kind,s['market']['ticker'],s['now'],rr.get('side'),rr['status'],dumps(rr))).lastrowid
                                        if kind=='flip' and rr.get('observed_entry_ask') is not None:
                                            db.execute('INSERT INTO intel_flip_followups(radar_id,ticker,side,signal_ts,entry_due,target,signal) VALUES(?,?,?,?,?,?,?)',(rid,s['market']['ticker'],rr['side'],s['now'],s['now']+2,rr['possible_exit_target'],rr['status']))
                                    radar_last[radar_key]=(rr['status'],s['now'])
                                if rr['status'] in states and (kind!='scalp' or rr.get('research_candidate')):sim.propose(f"{kind}:{s['market']['ticker']}:{rr['side']}:{int(s['now']//60)}:{rr.get('window',60)}",kind,kind,s,rr['side'],rr.get('window',60))
                        s['v3_active']=bool(self.v3)
                        self.raw_snapshot=s
                        if not self.v3:self.latest_snapshot=s
                        notify.signals(s,engines,flips,scalps);notify.directional(s,fv,candidate)
                        nxt=s.get('next_market')
                        outlook={'status':'PRELIMINARY — NOT LOCKED','ticker':nxt['ticker'] if nxt else None,'strike':nxt.get('strike') if nxt else None,'direction':'UP' if (s.get('baseline') or {}).get('features',{}).get('ema9',0)>(s.get('baseline') or {}).get('features',{}).get('ema21',0) else 'DOWN' if s.get('baseline') else None,'probability':None,'reason':'Trend-only outlook; official next strike '+('available but not yet locked' if nxt and nxt.get('strike') else 'not yet available')+'. Never counted as a locked forecast.'}
                        book=s.get('book')
                        payload={'version':VERSION,'timestamp':s['now'],'mode':'LIVE' if 0<=s['now']-s['quote_ts']<=3 else 'STALE','market':s['market'],'btc':{'price':s['price'],'timestamp':s['quote_ts'],'source':'Coinbase, not CF Benchmarks'},'book':{'yes_bid':book.yes[0][0],'yes_ask':1-book.no[0][0],'no_bid':book.no[0][0],'no_ask':1-book.yes[0][0],'spread':book.spread,'yes_bid_size':book.yes[0][1],'no_bid_size':book.no[0][1],'top5_depth':sum(q for _,q in book.yes[:5]+book.no[:5]),'source':s['book_source'],'timestamp':s['book_ts'],'latency':s['book_latency']} if book else None,'baseline':s.get('baseline'),'callout':active_callout,'engines':engines,'flip':flips,'scalp':scalps,'fair_value':fv,'regime':regime,'premarket':outlook,'candidate':candidate,'telegram':notify.status(),'websocket':{'enabled':self.stream.enabled,'status':self.stream.state},'vwap':s.get('vwap'),'data_quality':{'fees':'VERIFIED' if s.get('fee_valid') else 'UNKNOWN — ECONOMICS DISABLED','trade_weighted_vwap':'VERIFIED' if s.get('vwap') else 'WARMING UP — COMPLETE UTC-DAY TRADE COVERAGE REQUIRED','rest_scalps':'FASTER MARKET DATA REQUIRED' if s['book_source']=='REST' else 'Sequence/cadence gates applied'}}
                        with db:db.execute('INSERT INTO intel_snapshots(ts,ticker,payload) VALUES(?,?,?)',(s['now'],s['market']['ticker'],dumps(payload)))
                        today=datetime.fromtimestamp(s['now'],ET).date().isoformat()
                        if daily is not None and today!=daily:
                            from .storage import window_start
                            performance=tracker_summary(db,'today',window_start('today',s['now'])-1)
                            notify.enqueue('daily','daily',today,f"Locked prediction daily report {today}\n{performance['wins']} wins / {performance['losses']} losses; {performance['missed']} missed; {performance['pending']} pending. Forecast accuracy is separate from paper P&L.",s['now'],s['now']+3600)
                        daily=today
                        if begin-last_retention>=3600:collector.retention(begin);last_retention=begin
                        self.error=None
                        collector.health('intelligence_worker',True,'Collector and independent engines running; availability gates apply',time.time())
                    except Exception as exc:
                        self.error=type(exc).__name__+': '+str(exc)[:200]
                        with health_write(db) as health:health.execute('INSERT OR REPLACE INTO intel_health VALUES(?,?,?)',('intelligence_worker',time.time(),dumps({'ok':False,'reason':self.error})))
                    self.stop.wait(max(.05,1-(time.time()-begin)))
        except Exception as exc:
            self.error=type(exc).__name__+': '+str(exc)[:200]
            logging.getLogger(__name__).error('Intelligence worker unavailable: %s',self.error)
        finally:
            if self.v3:self.v3.close()
            if self.scheduler:self.scheduler.close()
            self.stream.close()
            if db:db.close()

def dashboard_snapshot(path,selection='today',days='7',now=None,page=0):
    now=time.time() if now is None else now;db=connect(path,True)
    try:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='intel_schema'").fetchone():return {'status':'WARMING UP','reason':'Upgrade worker has not migrated/collected data yet'}
        latest=db.execute('SELECT payload,ts FROM intel_snapshots ORDER BY id DESC LIMIT 1').fetchone()
        live=loads(latest['payload']) if latest else None
        if live and now-latest['ts']>5:
            live['mode']='STALE';live['data_age']=now-latest['ts']
        health=[{'name':r['name'],'timestamp':r['ts'],**loads(r['payload'])} for r in db.execute('SELECT * FROM intel_health')]
        from .storage import window_start
        from .notifications import performance
        from .alert_settings import settings
        return {'status':'LIVE' if live and live['mode']=='LIVE' else 'WARMING UP / STALE','now':now,'live':live,'alert_settings':settings(db),'alert_performance':performance(db,window_start(selection,now)),'tracker':tracker_summary(db,selection,now,offset=page*100,limit=100),'callouts':callouts.summary(db),'simulator':Simulator(db).summary(window_start(selection,now)),'research':report(db,days,now),'models':evaluation(db),'reversal_evidence':reversal_evidence(db),'health':health,'engine_performance':[dict(r) for r in db.execute("SELECT engine,count(*) n,sum(CASE WHEN (direction='UP' AND result='yes') OR (direction='DOWN' AND result='no') THEN 1 ELSE 0 END) wins FROM intel_engines WHERE result IN ('yes','no') AND direction IS NOT NULL GROUP BY engine")],'flip_followups':[dict(r) for r in db.execute('SELECT * FROM intel_flip_followups ORDER BY radar_id DESC LIMIT 100')],'radar_history':[dict(r) for r in db.execute('SELECT kind,ticker,observed,side,status FROM intel_radars ORDER BY id DESC LIMIT 100')]}
    finally:db.close()
