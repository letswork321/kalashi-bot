"""Fast V3 observer. Socket threads collect; this owner persists observed events.
Research, slow REST discovery and Telegram POSTs cannot block socket reception.
"""
from datetime import datetime,timezone
from pathlib import Path
import threading
import time
from scanner import HTTP,Book,COINBASE,Feed,Config,analyze,DataError
from .storage import migrate,dumps,loads
from .live_feed import CoinbaseStream,candle_rows
from .streams import BRTIStream
from .early_exit import BidResearch,watches,settings
from .pro_caller import caller
from . import callouts,path_scoring
from .notifications import Notifications
from .indicators import tick_metrics,InsufficientData

class V3Runtime:
    def __init__(self,owner):
        self.owner=owner;self.stop=threading.Event();self.thread=None;self.history_thread=None;self.spot=CoinbaseStream();self.brti=BRTIStream();self.history={};self.lock=threading.Lock();self.last_history={};self.last_tick=None;self.last_modules={};self.forecasts={};self.forecast_time=0
    def start(self):
        self.spot.start();self.brti.start()
        self.history_thread=threading.Thread(target=self.collect_history,daemon=True,name='v3-history-input');self.history_thread.start()
        self.thread=threading.Thread(target=self.run,daemon=True,name='v3-live-observer');self.thread.start()
    def collect_history(self):
        from .scheduler import ShortHTTP
        http=ShortHTTP()
        while not self.stop.is_set():
            now=time.time();iso=lambda t:datetime.fromtimestamp(t,timezone.utc).isoformat()
            for period in (60,300,900):
                if self.stop.is_set():break
                try:
                    rows=http.get(COINBASE,'/products/BTC-USD/candles',{'granularity':period,'start':iso(now-period*280),'end':iso(now)})
                    clean=[]
                    for r in rows:
                        if len(r)==6 and r[0]%period==0 and r[0]+period<=now:clean.append(r)
                    with self.lock:self.history[period]=(now,clean)
                except Exception:pass
            self.stop.wait(25)
    def snapshot(self,db,now,spot):
        base=getattr(self.owner,'raw_snapshot',None) or self.owner.latest_snapshot
        fast=None
        if self.owner.scheduler:fast,_,_=self.owner.scheduler.snapshot(now)
        if fast:
            same=base and fast['market']['ticker']==base['market']['ticker'] and 0<=now-base['now']<=60
            s={**(base if same else {}),**fast,'fee_valid':bool(same and base.get('fee_valid')),'fee_multiplier':base.get('fee_multiplier') if same else None}
        elif base:s={**base,'now':now}
        else:return None
        if s['market']['closed']<=now:return None
        s.update(now=now,spot_status=spot['status'],spot_source=spot['source'])
        if spot['status']=='LIVE':s.update(price=spot['price'],quote_ts=spot['event_ts'],trades=spot['rows'])
        else:s['spot_status']='REST_FALLBACK' if 0<=now-s.get('quote_ts',0)<=3 else 'STALE'
        for period,name in ((60,'candles1'),(300,'candles5'),(900,'candles15')):
            s[name]=[dict(r) for r in db.execute("SELECT ts,low,high,open,close,volume FROM intel_candles WHERE source='coinbase' AND period=? AND ts+?<=? ORDER BY ts DESC LIMIT 280",(period,period,now))][::-1]
        ws=self.owner.stream.snapshot();s['book_event_verified']=False;s['book_event_ts']=None
        if ws and ws['ticker']==s['market']['ticker'] and 0<=now-ws['received']<=1 and ws.get('event_ts') is not None and 0<=now-ws['event_ts']<=1 and ws['latency']<=1:
            try:s.update(book=Book.parse({'yes_dollars':ws['yes'],'no_dollars':ws['no']}),book_ts=ws['event_ts'],book_event_ts=ws['event_ts'],book_event_verified=True,book_source='websocket',book_latency=ws['latency'],ws_sequence_valid=True,book_history=ws['history'])
            except ValueError:pass
        if not s.get('book_event_verified'):
            s.update(book_source='REST',ws_sequence_valid=False)
        try:s['tick_metrics']=tick_metrics(s.get('trades',[]),now)
        except (InsufficientData,KeyError):s['tick_metrics']=None
        # Recalculate the preserved baseline with current inputs; never reuse an old probability as new.
        s['baseline']=None
        if s.get('fee_valid') and s.get('book') and now-s.get('book_ts',0)<=2:
            try:s['baseline']=analyze(s['market']['raw'],s['book'],Feed(s['price'],s['quote_ts'],[[r[k] for k in ('ts','low','high','open','close','volume')] for r in s['candles1']]),now,Config(),s['fee_multiplier'])
            except (ValueError,DataError):pass
        return s
    def run(self):
        db=migrate(self.owner.path);notify=Notifications(db,self.owner.telegram);bid=BidResearch(db);last_retention=0;last_book=None
        try:
            while not self.stop.is_set() and not self.owner.stop.is_set():
                now=time.time()
                try:
                    with self.lock:history=dict(self.history)
                    for period,(received,rows) in history.items():
                        if self.last_history.get(period)==received:continue
                        self.last_history[period]=received
                        with db:
                            db.executemany("INSERT OR REPLACE INTO intel_candles(source,period,ts,low,high,open,close,volume,received) VALUES('coinbase',?,?,?,?,?,?,?,?)",[(period,*r,received) for r in rows])
                            db.executemany("INSERT OR REPLACE INTO v3_candle_provenance VALUES(?,?,'Coinbase REST completed candle',NULL,NULL)",[(period,r[0]) for r in rows])
                    spot=self.spot.snapshot(now);new=[r for r in spot['rows'] if self.last_tick is None or r['id']>self.last_tick]
                    if new:
                        with db:db.executemany('INSERT OR IGNORE INTO v3_ticks VALUES(?,?,?,?,?,?,?)',[(r['source'],str(r['id']),r['ts'],r['received'],r['price'],r['size'],int(r['continuous'])) for r in new])
                        with db:db.executemany('INSERT OR IGNORE INTO intel_btc_trades VALUES(?,?,?,?,?)',[(r['id'],r['ts'],r['price'],r['size'],r['received']) for r in new])
                        certify_trades(db,new,spot['rows'])
                        self.last_tick=new[-1]['id']
                        for period in (60,300,900):
                            for bar in candle_rows(spot['rows'],period,now):
                                if bar['time']+period>now or bar['partial'] or bar['event_ts']<bar['time']+period-3:continue
                                with db:
                                    changed=db.execute("INSERT OR IGNORE INTO intel_candles VALUES('coinbase',?,?,?,?,?,?,?,?)",(period,bar['time'],bar['low'],bar['high'],bar['open'],bar['close'],bar['volume'],now)).rowcount
                                    if changed:db.execute("INSERT OR REPLACE INTO v3_candle_provenance VALUES(?,?,'Coinbase continuous WebSocket trades',?,?)",(period,bar['time'],bar['first_event'],bar['event_ts']))
                    spot_summary={k:v for k,v in spot.items() if k!='rows'}
                    with db:db.execute('INSERT OR REPLACE INTO v3_state VALUES(?,?,?)',('spot',now,dumps(spot_summary)))
                    path_scoring.observe(db,new,now);callouts.observe(db,now,spot['event_ts'] if spot['status']=='LIVE' else None,spot['price'] if spot['status']=='LIVE' else None)
                    s=self.snapshot(db,now,spot)
                    if s:
                        self.owner.latest_snapshot=s
                        if s.get('book'):
                            key=(s['market']['ticker'],s.get('book_ts'),s.get('book_source'))
                            if last_book!=key:
                                b=s['book']
                                with db:s['book_id']=db.execute('INSERT INTO intel_books(ticker,ts,event_ts,source,yes,no,spread,imbalance,latency,fee_multiplier) VALUES(?,?,?,?,?,?,?,?,?,?)',(s['market']['ticker'],s.get('book_ts',0),s.get('book_event_ts'),s['book_source'],dumps(b.yes),dumps(b.no),b.spread,b.imbalance,s.get('book_latency',99),s.get('fee_multiplier'))).lastrowid
                                self.book_id=s['book_id'];last_book=key
                            else:s['book_id']=self.book_id
                        from .engines import observe_reversal
                        observe_reversal(db,s)
                        bid.observe(s)
                        if now-self.forecast_time>=30:self.forecasts=bid.forecast(s);self.forecast_time=now
                        s['v3_active']=True;s['early_exit_forecasts']=self.forecasts
                        output=caller(s,self.forecasts)
                        notify.caller_entry(s,output)
                        notify.withdraw(s,[output['direction']] if output['guidance']=='ENTER' else [])
                        s['caller_direction']=output['direction']
                        if output['guidance']=='ENTER' and output['direction']:
                            from .economics import Simulator
                            pid=Simulator(db).propose(f"v3-early:{s['market']['ticker']}:{output['direction']}:{int(now//60)}",'directional','v3_early_exit',s,output['direction'],None)
                            if pid:
                                with db:db.execute('INSERT OR IGNORE INTO v3_paper_rules(sim_id,target_roi,created) VALUES(?,?,?)',(pid,settings(db)['target_roi'],now))
                        # Live spot WATCHs only. No stale REST quote masquerades as a streaming call.
                        c=callouts.build(s) if spot['status']=='LIVE' else None
                        if c:
                            c.update(source='Coinbase WebSocket',remaining=s['market']['closed']-now)
                            notify.callout(s,c)
                        watch=watches(db,s,notify)
                        for module in output['modules']:
                            key=(s['market']['ticker'],module['module']);signature=(module['signal'],int(now//60))
                            if self.last_modules.get(key)!=signature:
                                with db:db.execute('INSERT OR IGNORE INTO v3_module_events(ticker,module,observed,direction,signal,features,regime) VALUES(?,?,?,?,?,?,?)',(s['market']['ticker'],module['module'],now,module['direction'],module['signal'],dumps(module['readings']),(s.get('regime') or {}).get('regime','UNKNOWN')))
                                self.last_modules[key]=signature
                        b=s.get('book');age=now-s.get('book_ts',0)
                        if spot['status']!='LIVE':spot_summary={**spot_summary,'price':s.get('price'),'event_ts':s.get('quote_ts'),'age':now-s.get('quote_ts',0),'status':s['spot_status']}
                        payload={'timestamp':now,'caller':output,'spot':spot_summary,'brti':self.brti.snapshot(now),'market':s['market'],'book':{'status':'VERIFIED STREAM' if s.get('book_event_verified') else 'REST — EVENT TIME UNVERIFIED','yes_bid':b.yes[0][0],'yes_ask':1-b.no[0][0],'no_bid':b.no[0][0],'no_ask':1-b.yes[0][0],'spread':b.spread,'age':age,'event_ts':s.get('book_event_ts'),'receipt_ts':s.get('book_ts'),'top5_depth':sum(q for _,q in b.yes[:5]+b.no[:5])} if b else None,'fees':'VERIFIED' if s.get('fee_valid') else 'UNAVAILABLE','exit_forecasts':self.forecasts,'watch_positions':watch,'settings':settings(db),'kalshi_socket':self.owner.stream.state,'decision_source':'V3 verified fast observer; no orders'}
                        with db:db.execute('INSERT OR REPLACE INTO v3_state VALUES(?,?,?)',('dashboard',now,dumps(payload)))
                    if now-last_retention>=3600:
                        with db:
                            db.execute('DELETE FROM v3_ticks WHERE event<?',(now-172800,))
                            db.execute('DELETE FROM v3_contract_samples WHERE observed<?',(now-90*86400,))
                        last_retention=now
                except Exception as exc:
                    with db:db.execute('INSERT OR REPLACE INTO intel_health VALUES(?,?,?)',('v3_observer',now,dumps({'ok':False,'reason':type(exc).__name__+': '+str(exc)[:160]})))
                self.stop.wait(.2)
        finally:db.close()
    def close(self):
        self.stop.set();self.spot.close();self.brti.close()
        if self.thread:self.thread.join(timeout=2)


def certify_trades(db,new,observed):
    """Certify only truly consecutive observed trade-ID intervals; never bridge a gap."""
    if not new:return
    first=new[0]['id'];previous=next((r for r in reversed(observed) if r['id']<first),None)
    groups=[];lo=previous['ts'] if previous and first==previous['id']+1 and new[0]['continuous'] else new[0]['ts'];last=previous
    for r in new:
        if last and (not r['continuous'] or r['id']!=last['id']+1 or r['ts']<last['ts']):
            if last['ts']>lo:groups.append((lo,last['ts']))
            lo=r['ts']
        last=r
    if last and last['ts']>lo:groups.append((lo,last['ts']))
    with db:
        for lo,hi in groups:
            overlap=db.execute("SELECT start,end FROM intel_coverage WHERE source='coinbase_trades' AND end>=? AND start<=?",(lo,hi)).fetchall()
            if overlap:
                lo=min(lo,min(r['start'] for r in overlap));hi=max(hi,max(r['end'] for r in overlap))
                db.execute("DELETE FROM intel_coverage WHERE source='coinbase_trades' AND end>=? AND start<=?",(lo,hi))
            db.execute("INSERT OR IGNORE INTO intel_coverage VALUES(?,?,'coinbase_trades')",(lo,hi))
