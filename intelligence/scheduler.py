"""Dedicated forecast clock and independent short-timeout input workers.
No research, fee lookup, settlement request, Telegram POST or network wait runs on the clock.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
import math
import threading
import time
import requests
from scanner import HTTP,Kalshi,Book,Feed,forecast_components,indicators,timestamp,MODEL,KALSHI,COINBASE,DataError
from .storage import migrate,register_market,lock_forecast,dumps,loads
from .models import features,shadow
from .notifications import Notifications

class ShortHTTP(HTTP):
    def get(self,base,path,params=None):
        try:
            response=self.session.get(base+path,params=params,timeout=(1.5,2))
            response.raise_for_status();data=response.json()
            if not isinstance(data,(dict,list)):raise ValueError('Unexpected JSON')
            return data
        except (requests.RequestException,ValueError):
            raise DataError('Forecast input unavailable: '+base+path+' (short timeout; no inline retries)') from None

class ForecastScheduler:
    def __init__(self,path,telegram=None):
        self.path=path;self.telegram=telegram;self.stop=threading.Event();self.lock=threading.Lock();self.cache={};self.threads=[];self.spot_stream=None
    def put(self,name,value):
        with self.lock:self.cache[name]=value
    def start(self):
        for name,fn in [('metadata',self.metadata),('candles',self.candles),('quote',self.quote),('book',self.book)]:
            thread=threading.Thread(target=self.feed,args=(name,fn),daemon=True,name='forecast-'+name);thread.start();self.threads.append(thread)
        t=threading.Thread(target=self.run,daemon=True,name='forecast-clock');t.start();self.threads.append(t)
    def feed(self,name,fn):
        http=ShortHTTP()
        while not self.stop.is_set():
            try:fn(http);self.put(name+'_error',None)
            except Exception as exc:self.put(name+'_error',type(exc).__name__+': '+str(exc)[:180])
            now=time.time();elapsed=now%900
            urgent=45<=elapsed<=125
            self.stop.wait((.3 if urgent else 2) if name in ('quote','book') else 5 if name=='metadata' else 20)
    def metadata(self,http):
        now=time.time()
        data=http.get(KALSHI,'/markets',{'series_ticker':'KXBTC15M','limit':100,'min_close_ts':int(now),'max_close_ts':int(now+1800)})
        markets=[m for m in data.get('markets',[]) if m.get('ticker','').startswith('KXBTC15M-') and 899<=timestamp(m['close_time'])-timestamp(m['open_time'])<=901]
        current=next((m for m in sorted(markets,key=lambda m:timestamp(m['close_time'])) if timestamp(m['open_time'])<=now<timestamp(m['close_time']) and m.get('status') in ('active','open')),None)
        if current:
            # Current /market detail is authoritative for the now-established official strike.
            current=Kalshi(http).market(current['ticker'])
            markets=[m for m in markets if m['ticker']!=current['ticker']]+[current]
        self.put('metadata',{'received':time.time(),'markets':markets,'current':current})
    def candles(self,http):
        now=time.time();iso=lambda t:datetime.fromtimestamp(t,timezone.utc).isoformat()
        self.put('candles',http.get(COINBASE,'/products/BTC-USD/candles',{'granularity':60,'start':iso(now-180*60),'end':iso(now)}))
    def quote(self,http):
        live=self.spot_stream.snapshot() if self.spot_stream else None
        if live and live['status']=='LIVE':
            self.put('quote',{'price':live['price'],'timestamp':live['event_ts'],'received':time.time(),'source':'Coinbase WebSocket'});return
        tick=http.get(COINBASE,'/products/BTC-USD/ticker')
        price=float(tick['price'])
        if not math.isfinite(price) or price<=0:raise ValueError('Invalid BTC quote')
        self.put('quote',{'price':price,'timestamp':timestamp(tick['time']),'received':time.time()})
    def book(self,http):
        with self.lock:meta=self.cache.get('metadata',{})
        m=meta.get('current')
        if not m:return
        start=time.time();book=Kalshi(http).book(m['ticker']);now=time.time()
        self.put('book',{'ticker':m['ticker'],'book':book,'received':now,'latency':now-start})
    def snapshot(self,now):
        with self.lock:c=dict(self.cache)
        meta=c.get('metadata') or {};m=meta.get('current')
        if not m or not timestamp(m['open_time'])<=now<timestamp(m['close_time']):return None,'CURRENT_MARKET_UNAVAILABLE',c
        if now-meta['received']>30:return None,'MARKET_METADATA_STALE',c
        if m.get('floor_strike') is None:return None,'OFFICIAL_STRIKE_UNAVAILABLE',c
        q=c.get('quote') or {};b=c.get('book') or {}
        if not q or not 0<=now-q['timestamp']<=2:return None,'BTC_QUOTE_STALE_OR_UNAVAILABLE',c
        if b.get('ticker')!=m['ticker'] or not 0<=now-b.get('received',0)<=2 or b.get('latency',99)>2:return None,'ORDERBOOK_STALE_OR_UNAVAILABLE',c
        if not c.get('candles'):return None,'ONE_MINUTE_CANDLES_UNAVAILABLE',c
        try:
            f,p,strike,remaining=forecast_components(m,b['book'],Feed(q['price'],q['timestamp'],c['candles']),now)
            forecast={'p_up':p,'model':MODEL,'calibrated':False,'features':f,'observed_at':now,'btc_timestamp':q['timestamp'],'btc_price':q['price'],'official_strike':strike,'reason':'Strike distance, realized volatility, momentum, RSI and book consensus; uncalibrated baseline'}
            return {'now':now,'mode':'live','baseline':forecast,'price':q['price'],'quote_ts':q['timestamp'],'book':b['book'],'book_ts':b['received'],'book_latency':b['latency'],'book_source':'REST','market':{'ticker':m['ticker'],'opened':timestamp(m['open_time']),'closed':timestamp(m['close_time']),'strike':strike,'raw':m},'tick_metrics':None},None,c
        except Exception as exc:return None,'BASELINE_INPUT_INVALID: '+str(exc)[:140],c
    def tick(self,db,now,notify):
        s,reason,c=self.snapshot(now);meta=c.get('metadata') or {}
        # Metadata can be refreshed independently even while the quote/book fails.
        for m in meta.get('markets',[]):register_market(db,m,now)
        m=meta.get('current')
        if not m or not timestamp(m['open_time'])+60<=now<=timestamp(m['open_time'])+120:
            known=db.execute('SELECT payload FROM intel_markets WHERE opened+60<=? AND opened+120>=? ORDER BY opened DESC LIMIT 1',(now,now)).fetchone()
            m=loads(known['payload']) if known else None
        if m and s and s['market']['ticker']!=m['ticker']:s=None;reason='MARKET_ROLLOVER_PENDING_METADATA'
        if m and timestamp(m['open_time'])+60<=now<=timestamp(m['open_time'])+120:
            row=db.execute('SELECT * FROM intel_locks WHERE ticker=?',(m['ticker'],)).fetchone()
            late=db.execute('SELECT 1 FROM intel_late_locks WHERE ticker=?',(m['ticker'],)).fetchone()
            if row and row['state']!='LOCKED' and not late:
                result=None
                if s:
                    f=features(s) or {};p=s['baseline']
                    if now<=row['deadline']:
                        result=lock_forecast(db,m,p,now,f,'UNKNOWN',None,None)
                    else:
                        with db:
                            if row['state']=='PENDING':db.execute("UPDATE intel_locks SET state='MISSED',reason='On-time deadline missed; separate LATE observation allowed only through +120s' WHERE ticker=?",(m['ticker'],))
                            db.execute('INSERT OR IGNORE INTO intel_late_locks(ticker,scheduled,deadline,direction,p_up,observed,features,model,reason,regime,strike,btc_price) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                                       (m['ticker'],row['scheduled'],row['deadline'],'UP' if p['p_up']>=.5 else 'DOWN',p['p_up'],now,dumps(f),p['model'],'Observed after +65s deadline; separate late cohort, never backdated','UNKNOWN',m['floor_strike'],s['price']))
                        result=dict(db.execute('SELECT * FROM intel_late_locks WHERE ticker=?',(m['ticker'],)).fetchone())
                    if result:
                        from .v4_models import lock_shadow
                        ss={**s,'candles1':[{'ts':r[0],'close':r[4]} for r in c.get('candles',[])]}
                        lock_shadow(db,ss,(self.spot_stream.snapshot(now).get('rows',[]) if self.spot_stream else []))
                        notify.locked(s,result)
                        if result['state']=='LOCKED':
                            candidate=shadow(db,s)
                            if candidate.get('probability') is not None:
                                with db:db.execute('INSERT OR IGNORE INTO intel_shadow VALUES(?,?,?,?,NULL)',(m['ticker'],candidate['version'],now,candidate['probability']))
                with db:db.execute('INSERT INTO intel_lock_attempts(ticker,observed,reason,outcome) VALUES(?,?,?,?)',(m['ticker'],now,'Forecast recorded from fresh independent inputs' if result else reason or 'Forecast rejected by immutable tracker checks',result['state'] if result else 'REJECTED'))
        # Finalize deadlines even during quote failure; old MISSED decisions stay immutable.
        with db:db.execute("UPDATE intel_locks SET state='MISSED',reason='Independent scheduler: no valid observation before +65s; see attempt log' WHERE state='PENDING' AND deadline<?",(now,))
        notify.preliminary(c,now)
        with db:db.execute('INSERT OR REPLACE INTO intel_health VALUES(?,?,?)',('forecast_scheduler',now,dumps({'ok':s is not None,'reason':reason or 'Independent clock active; fresh inputs available','inputs':{k:v for k,v in c.items() if k.endswith('_error') and v}})))
    def run(self):
        db=migrate(self.path);notify=Notifications(db,self.telegram)
        try:
            while not self.stop.is_set():
                now=time.time()
                try:self.tick(db,now,notify)
                except Exception as exc:
                    with db:db.execute('INSERT OR REPLACE INTO intel_health VALUES(?,?,?)',('forecast_scheduler',now,dumps({'ok':False,'reason':type(exc).__name__+': '+str(exc)[:180]})))
                self.stop.wait(.2 if 58<=now%900<=121 else 1)
        finally:db.close()
    def close(self):
        self.stop.set()
        for t in self.threads:t.join(timeout=.2)
