"""Timestamped public data collection with explicit trade-sequence coverage."""
import math
import os
import statistics
import time
from datetime import datetime,timezone
from scanner import HTTP,Kalshi,Book,Feed,Config,analyze,timestamp,KALSHI,COINBASE,DataError
from .storage import register_market,dumps,loads
from .indicators import tick_metrics,InsufficientData,covered

class Collector:
    def __init__(self,db,stream=None):
        self.db=db;self.http=HTTP();self.k=Kalshi(self.http);self.stream=stream
        self.times={};self.market=None;self.multiplier=None;self.fee_valid=False;self.errors={};self.next_market=None;self.previous_bid={}
    def due(self,name,seconds,now):return now-self.times.get(name,0)>=seconds
    def health(self,name,ok,reason,now):
        with self.db:self.db.execute('INSERT OR REPLACE INTO intel_health VALUES(?,?,?)',(name,now,dumps({'ok':ok,'reason':reason})))
    def discovery(self,now):
        data=self.http.get(KALSHI,'/markets',{'series_ticker':'KXBTC15M','limit':200,'min_close_ts':int(now-3600),'max_close_ts':int(now+3600)})
        for m in data.get('markets',[]):register_market(self.db,m,now)
        rows=self.db.execute('SELECT * FROM intel_markets WHERE opened<=? AND closed>? AND status IN (\'active\',\'open\') ORDER BY closed LIMIT 1',(now,now)).fetchall()
        self.market=loads(rows[0]['payload']) if rows else None
        nxt=self.db.execute('SELECT * FROM intel_markets WHERE opened>? ORDER BY opened LIMIT 1',(now,)).fetchone()
        self.next_market=dict(nxt) if nxt else None
        self.times['discovery']=now
    def candles(self,period,now):
        iso=lambda t:datetime.fromtimestamp(t,timezone.utc).isoformat()
        rows=self.http.get(COINBASE,'/products/BTC-USD/candles',{'granularity':period,'start':iso(now-period*280),'end':iso(now)})
        with self.db:
            for r in rows:
                if len(r)!=6:continue
                ts,lo,hi,op,cl,vol=r
                if ts%period or ts+period>now:continue
                self.db.execute('INSERT OR IGNORE INTO intel_candles VALUES(?,?,?,?,?,?,?,?,?)',('coinbase',period,ts,lo,hi,op,cl,vol,now))
        self.times['candles'+str(period)]=now
    def trades(self,now):
        # Paginate backward until overlapping the already recorded sequence.
        old=self.db.execute('SELECT max(id) FROM intel_btc_trades').fetchone()[0]
        received=[];after=None
        for _ in range(8):
            params={'limit':1000}
            if after:params['after']=after
            elif old is not None:params['before']=str(old-1)
            data=self.http.get(COINBASE,'/products/BTC-USD/trades',params)
            if not data:break
            received.extend(data);oldest=min(int(r['trade_id']) for r in data)
            if (old is not None and oldest<=old) or (old is None and len(received)>=1000):break
            after=str(oldest)
        rows={int(r['trade_id']):{'id':int(r['trade_id']),'ts':timestamp(r['time']),'price':float(r['price']),'size':float(r['size'])} for r in received}
        ordered=sorted(rows.values(),key=lambda r:r['id'])
        if not ordered:return
        if any(r['price']<=0 or r['size']<=0 or not math.isfinite(r['price']+r['size']) for r in ordered):raise ValueError('Invalid trade price/volume')
        continuous=all(b['id']==a['id']+1 for a,b in zip(ordered,ordered[1:])) and (old is None or ordered[0]['id']<=old+1)
        with self.db:
            self.db.executemany('INSERT OR IGNORE INTO intel_btc_trades VALUES(?,?,?,?,?)',[(r['id'],r['ts'],r['price'],r['size'],now) for r in ordered])
            if continuous:
                lo=min(r['ts'] for r in ordered);hi=max(r['ts'] for r in ordered)
                overlaps=self.db.execute("SELECT start,end FROM intel_coverage WHERE source='coinbase_trades' AND end>=? AND start<=?",(lo,hi)).fetchall()
                if overlaps:
                    lo=min(lo,min(r['start'] for r in overlaps));hi=max(hi,max(r['end'] for r in overlaps))
                    self.db.execute("DELETE FROM intel_coverage WHERE source='coinbase_trades' AND end>=? AND start<=?",(lo,hi))
                self.db.execute('INSERT OR IGNORE INTO intel_coverage VALUES(?,?,?)',(lo,hi,'coinbase_trades'))
        self.health('coinbase_trade_sequence',continuous,'Complete returned IDs; VWAP only on fully covered time intervals' if continuous else 'Sequence gap; interval not certified',now)
        self.times['trades']=now
    def vwap(self,asof):
        anchor=math.floor((asof-1e-6)/86400)*86400
        intervals=[(r[0],r[1]) for r in self.db.execute("SELECT start,end FROM intel_coverage WHERE source='coinbase_trades' AND end>=? AND start<=?",(anchor,asof))]
        if not covered(intervals,anchor,asof):return None
        r=self.db.execute('SELECT sum(size) v,sum(price*size) pv,sum(price*price*size) p2 FROM intel_btc_trades WHERE ts>=? AND ts<?',(anchor,asof)).fetchone()
        if not r['v']:return None
        mean=r['pv']/r['v'];sd=math.sqrt(max(0,r['p2']/r['v']-mean*mean))
        return {'value':mean,'sd':sd,'volume':r['v'],'anchor':anchor,'asof':asof,'source':'actual Coinbase trades, UTC daily anchor, complete sequence coverage'}
    def snapshot(self):
        now=time.time()
        urgent=self.market and any(-3<=now-timestamp(self.market['open_time'])-offset<=6 for offset in (60,600,840))
        if self.due('discovery',15,now) or not self.market or timestamp(self.market['close_time'])<=now:self.discovery(now)
        m=self.market
        if not urgent:
            for period,interval in [(900,60),(300,30),(60,15)]:
                if self.due('candles'+str(period),interval,now):
                    try:self.candles(period,now)
                    except Exception as exc:self.health('candles'+str(period),False,type(exc).__name__,now)
            if self.due('trades',3,now):
                try:self.trades(now)
                except Exception as exc:self.health('coinbase_trades',False,type(exc).__name__,now)
        if not m:raise ValueError('No active market metadata; collector continues next poll')
        opened,closed=timestamp(m['open_time']),timestamp(m['close_time'])
        if self.due('fees',60 if self.fee_valid else 5,now) or self.times.get('fee_ticker')!=m['ticker']:
            try:
                self.multiplier=self.k.fees(m,now);self.fee_valid=True
                self.health('fees',True,'Official effective fee multiplier verified',now)
            except Exception as exc:
                self.multiplier=None;self.fee_valid=False;self.health('fees',False,str(exc),now)
            self.times['fees']=now;self.times['fee_ticker']=m['ticker']
        book=None;book_ts=0;source='REST';latency=99;seq=False
        if self.stream:
            self.stream.set_market(m['ticker']);ws=self.stream.snapshot()
            if ws and ws['ticker']==m['ticker'] and now-ws['received']<=1 and ws['latency']<=1:
                try:
                    book=Book.parse({'yes_dollars':ws['yes'],'no_dollars':ws['no']});book_ts=ws['received'];latency=ws['latency'];source='websocket';seq=True
                except (ValueError,DataError):pass
        if not book:
            t=time.time()
            try:book=self.k.book(m['ticker']);book_ts=time.time();latency=book_ts-t
            except Exception as exc:self.health('orderbook',False,str(exc),time.time())
        # Sample ticker last, immediately before scheduled observation decisions.
        tick=self.http.get(COINBASE,'/products/BTC-USD/ticker')
        quote_ts=timestamp(tick['time']);price=float(tick['price']);now=time.time()
        if not math.isfinite(price) or price<=0:raise ValueError('Invalid live BTC quote')
        candles=[dict(r) for r in self.db.execute("SELECT ts,low,high,open,close,volume FROM intel_candles WHERE source='coinbase' AND period=900 AND ts+900<=? ORDER BY ts DESC LIMIT 280",(now,))][::-1]
        trades=[dict(r) for r in self.db.execute('SELECT id,ts,price,size FROM intel_btc_trades WHERE ts>=? AND ts<=? ORDER BY ts,id',(now-120,now))]
        one=[list(r) for r in self.db.execute("SELECT ts,low,high,open,close,volume FROM intel_candles WHERE period=60 AND ts+60<=? ORDER BY ts DESC LIMIT 180",(now,))][::-1]
        five=[dict(r) for r in self.db.execute("SELECT ts,low,high,open,close,volume FROM intel_candles WHERE source='coinbase' AND period=300 AND ts+300<=? ORDER BY ts DESC LIMIT 180",(now,))][::-1]
        one_named=[dict(zip(('ts','low','high','open','close','volume'),r)) for r in one]
        baseline=None
        if book and now-book_ts<=3 and self.fee_valid:
            try:baseline=analyze(m,book,Feed(price,quote_ts,one),now,Config(),self.multiplier)
            except Exception as exc:self.health('baseline',False,str(exc),now)
        book_id=None
        if book:
            with self.db:
                book_id=self.db.execute('INSERT INTO intel_books(ticker,ts,event_ts,source,yes,no,spread,imbalance,latency,fee_multiplier) VALUES(?,?,?,?,?,?,?,?,?,?)',(m['ticker'],book_ts,book_ts,source,dumps(book.yes),dumps(book.no),book.spread,book.imbalance,latency,self.multiplier)).lastrowid
        history=[]
        for r in self.db.execute('SELECT * FROM intel_books WHERE ticker=? AND ts>=? ORDER BY ts',(m['ticker'],now-120)):
            y,n=loads(r['yes']),loads(r['no'])
            if y and n:
                history.extend([{'ticker':m['ticker'],'ts':r['ts'],'side':'UP','bid':y[0][0]},{'ticker':m['ticker'],'ts':r['ts'],'side':'DOWN','bid':n[0][0]}])
        if source=='websocket' and ws:
            history=ws['history']
        latest_trade=self.db.execute('SELECT max(ts) FROM intel_btc_trades').fetchone()[0]
        v=self.vwap(latest_trade) if latest_trade and now-latest_trade<=3 else None
        close=candles[-1]['ts']+900 if candles else 0
        out={'now':now,'market':{'ticker':m['ticker'],'opened':opened,'closed':closed,'strike':m.get('floor_strike'),'raw':m},'price':price,'quote_ts':quote_ts,'candles15':candles,'candles1':one_named,'candles5':five,'trades':trades,'vwap':v,'vwap_at_close':self.vwap(close) if close else None,'book':book,'book_id':book_id,'book_ts':book_ts,'book_latency':latency,'book_source':source,'ws_sequence_valid':seq,'book_history':history,'fee_multiplier':self.multiplier,'fee_valid':self.fee_valid,'baseline':baseline,'next_market':self.next_market,'mode':'live'}
        try:out['tick_metrics']=tick_metrics(trades,now)
        except InsufficientData:out['tick_metrics']=None
        if self.due('kalshi_trades',15,now) and not urgent:
            try:
                d=self.http.get(KALSHI,'/markets/trades',{'ticker':m['ticker'],'limit':100})
                with self.db:
                    for r in d.get('trades',[]):self.db.execute('INSERT OR IGNORE INTO intel_kalshi_trades VALUES(?,?,?,?,?,?,?)',(r['trade_id'],r['ticker'],timestamp(r['created_time']),float(r['yes_price_dollars']),float(r['count_fp']),dumps(r),now))
                self.times['kalshi_trades']=now
            except Exception as exc:self.health('kalshi_trades',False,type(exc).__name__,now)
        old=self.previous_bid.get(m['ticker']);mid=book.yes[0][0] if book else None
        delta=(mid-old[1]) if mid is not None and old and 0<now-old[0]<=5 else None
        velocity=delta/(now-old[0]) if delta is not None else None
        if mid is not None:self.previous_bid[m['ticker']]=(now,mid)
        tm=out.get('tick_metrics');vol=(baseline or {}).get('features',{}).get('volatility_1m')
        with self.db:self.db.execute('''INSERT INTO intel_hourly VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(hour_utc) DO UPDATE SET n=n+1,spread_sum=spread_sum+excluded.spread_sum,spread_n=spread_n+excluded.spread_n,depth_sum=depth_sum+excluded.depth_sum,depth_n=depth_n+excluded.depth_n,velocity_sum=velocity_sum+excluded.velocity_sum,tick_n=tick_n+excluded.tick_n,volatility_sum=volatility_sum+excluded.volatility_sum,vol_n=vol_n+excluded.vol_n,flip_moves=flip_moves+excluded.flip_moves,kalshi_velocity_sum=kalshi_velocity_sum+excluded.kalshi_velocity_sum,kalshi_velocity_n=kalshi_velocity_n+excluded.kalshi_velocity_n''',(int(now//3600)*3600,1,book.spread if book else 0,int(book is not None),sum(q for _,q in book.yes[:5]+book.no[:5]) if book else 0,int(book is not None),tm['velocity'] if tm else 0,int(tm is not None),vol or 0,int(vol is not None),int(delta is not None and abs(delta)>=.03),velocity or 0,int(velocity is not None)))
        self.health('collector',True,'Actual public inputs; incomplete coverage remains unavailable',now)
        return out
    def retention(self,now):
        # Hourly aggregates and locked/model/paper history are permanent. Raw
        # observations are bounded; preserve every book referenced by paper fills.
        days=lambda name,default:max(1,min(90,int(os.environ.get(name,str(default)))))
        tick_days=days('INTELLIGENCE_TICK_DAYS',2);book_days=days('INTELLIGENCE_BOOK_DAYS',7);snapshot_days=days('INTELLIGENCE_SNAPSHOT_DAYS',2)
        with self.db:
            self.db.execute('DELETE FROM intel_btc_trades WHERE id IN (SELECT id FROM intel_btc_trades WHERE ts<? LIMIT 10000)',(now-tick_days*86400,))
            oldest=self.db.execute('SELECT min(ts) FROM intel_btc_trades').fetchone()[0]
            if oldest is not None:
                self.db.execute('DELETE FROM intel_coverage WHERE end<?',(oldest,))
                self.db.execute('UPDATE intel_coverage SET start=? WHERE start<? AND end>=?',(oldest,oldest,oldest))
            self.db.execute('DELETE FROM intel_books WHERE ts<? AND id NOT IN (SELECT entry_book FROM intel_sim WHERE entry_book IS NOT NULL UNION SELECT exit_book FROM intel_sim WHERE exit_book IS NOT NULL)',(now-book_days*86400,))
            self.db.execute('DELETE FROM intel_snapshots WHERE ts<?',(now-snapshot_days*86400,))
            self.db.execute('DELETE FROM intel_radars WHERE observed<?',(now-30*86400,))
