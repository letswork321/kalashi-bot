"""Auditable public-data backfill and ET hour/day research, never invented depth."""
from datetime import datetime,timezone
import math
import statistics
import time
from urllib.parse import quote
from .storage import register_market,dumps,loads,ET,window_start

class Backfill:
    def __init__(self,db,http):self.db,self.http=db,http
    def run(self,days=7,max_pages=10,now=None):
        from scanner import KALSHI,COINBASE
        now=time.time() if now is None else now
        if days not in (7,30,90) or not 1<=max_pages<=200:raise ValueError('Use 7/30/90 days and 1..200 pages')
        start=now-days*86400;count=0;partial=[]
        with self.db:job=self.db.execute('INSERT INTO intel_jobs(kind,started,start_ts,end_ts,status,rows) VALUES(?,?,?,?,?,0)',('public_backfill',now,start,now,'RUNNING')).lastrowid
        try:
            cursor='';finished=False
            for page in range(max_pages):
                data=self.http.get(KALSHI,'/markets',{'series_ticker':'KXBTC15M','status':'settled','limit':200,'min_close_ts':int(start),'max_close_ts':int(now),'cursor':cursor})
                markets=data.get('markets',[])
                for m in markets:
                    if register_market(self.db,m,now,track=False):count+=1
                cursor=data.get('cursor','')
                if not cursor:finished=True;break
            if not finished:partial.append('Kalshi pagination capped; rerun with larger --max-pages')
            # The live endpoint excludes archived markets. Query the documented
            # historical store separately; no unsupported close-time filters there.
            from scanner import timestamp
            cutoff=self.http.get(KALSHI,'/historical/cutoff')
            if timestamp(cutoff['market_settled_ts'])>start:
                cursor='';historical_done=False
                for page in range(max_pages):
                    data=self.http.get(KALSHI,'/historical/markets',{'series_ticker':'KXBTC15M','limit':200,'cursor':cursor})
                    markets=data.get('markets',[])
                    for m in markets:
                        if start<=timestamp(m['close_time'])<=now:
                            if register_market(self.db,m,now,track=False):count+=1
                    cursor=data.get('cursor','')
                    if not cursor:
                        historical_done=True;break
                if not historical_done:partial.append('Archived markets pagination capped; no assumption about archive sort order')
            # Each Coinbase request <=300 candles. Forward-only, UTC opening times.
            end=math.floor(now/900)*900;position=math.floor(start/900)*900;pages=0
            while position<end and pages<max_pages:
                stop=min(end,position+299*900)
                iso=lambda t:datetime.fromtimestamp(t,timezone.utc).isoformat()
                rows=self.http.get(COINBASE,'/products/BTC-USD/candles',{'granularity':900,'start':iso(position),'end':iso(stop)})
                with self.db:
                    for row in rows:
                        if len(row)!=6:continue
                        ts,low,high,op,close,vol=row
                        if position<=ts<stop and ts+900<=now:
                            self.db.execute('INSERT OR IGNORE INTO intel_candles VALUES(?,?,?,?,?,?,?,?,?)',('coinbase',900,ts,low,high,op,close,vol,now));count+=1
                position=stop;pages+=1
            if position<end:partial.append('Coinbase candle window capped; increase --max-pages')
            sampled=0
            for market in self.db.execute('SELECT ticker,opened,closed FROM intel_markets WHERE closed>=? AND closed<=? AND result IS NOT NULL ORDER BY closed DESC LIMIT ?',(start,now,min(max_pages,20))).fetchall():
                try:sampled+=self.kalshi_candles(market['ticker'],market['opened'],market['closed'])
                except Exception:partial.append('Some historical Kalshi minute candles unavailable; coverage table reports actual count')
            count+=sampled
            status='PARTIAL' if partial else 'COMPLETE'
            message='; '.join(partial) or 'Requested public outcome/candle windows fetched. Missing exchange intervals remain missing; no historic depth or simulated quotes generated.'
        except Exception as exc:
            # HTTP wrapper redacts credentials. No authenticated endpoints here.
            status='FAILED';message=type(exc).__name__+': '+str(exc)[:300]
        with self.db:self.db.execute('UPDATE intel_jobs SET ended=?,status=?,rows=?,message=? WHERE id=?',(time.time(),status,count,message,job))
        return {'status':status,'rows':count,'message':message,'job':job}
    def trade_session(self,max_pages=32,now=None):
        from scanner import COINBASE,timestamp
        import math
        now=time.time() if now is None else now;anchor=int(now//86400)*86400
        if not 1<=max_pages<=200:raise ValueError('Trade backfill page limit must be 1..200')
        with self.db:job=self.db.execute('INSERT INTO intel_jobs(kind,started,start_ts,end_ts,status,rows) VALUES(?,?,?,?,?,0)',('trade_vwap_backfill',now,anchor,now,'RUNNING')).lastrowid
        after=None;seen={};done=False;message=''
        try:
            for _ in range(max_pages):
                params={'limit':1000}
                if after:params['after']=after
                rows=self.http.get(COINBASE,'/products/BTC-USD/trades',params)
                if not rows:break
                minimum=min(int(r['trade_id']) for r in rows)
                if after is not None and minimum>=int(after):raise ValueError('Backward trade pagination did not advance')
                for r in rows:
                    identity=int(r['trade_id']);ts=timestamp(r['time']);price=float(r['price']);size=float(r['size'])
                    if not math.isfinite(price+size) or price<=0 or size<=0:raise ValueError('Invalid trade price or size')
                    seen[identity]=(identity,ts,price,size,now)
                if min(timestamp(r['time']) for r in rows)<=anchor:done=True;break
                after=str(minimum)
            ordered=sorted(seen.values())
            if not ordered or any(b[0]!=a[0]+1 for a,b in zip(ordered,ordered[1:])):raise ValueError('Historical trade sequence has a gap')
            lo=min(r[1] for r in ordered);hi=max(r[1] for r in ordered)
            with self.db:
                self.db.executemany('INSERT OR IGNORE INTO intel_btc_trades VALUES(?,?,?,?,?)',ordered)
                intervals=self.db.execute("SELECT start,end FROM intel_coverage WHERE source='coinbase_trades' AND end>=? AND start<=?",(lo,hi)).fetchall()
                if intervals:
                    lo=min(lo,min(r[0] for r in intervals));hi=max(hi,max(r[1] for r in intervals))
                    self.db.execute("DELETE FROM intel_coverage WHERE source='coinbase_trades' AND end>=? AND start<=?",(lo,hi))
                self.db.execute('INSERT OR IGNORE INTO intel_coverage VALUES(?,?,?)',(lo,hi,'coinbase_trades'))
            status='COMPLETE' if done else 'PARTIAL';message='Verified real contiguous trades; '+('UTC session anchor reached' if done else 'page cap reached before UTC anchor; VWAP stays gated. Run backfill-trades with more pages if desired')
        except Exception as exc:status='FAILED';message=type(exc).__name__+': '+str(exc)[:250]
        with self.db:self.db.execute('UPDATE intel_jobs SET ended=?,status=?,rows=?,message=? WHERE id=?',(time.time(),status,len(seen),message,job))
        return {'status':status,'rows':len(seen),'message':message}
    def kalshi_candles(self,ticker,start,end):
        from scanner import KALSHI
        try:
            data=self.http.get(KALSHI,'/series/KXBTC15M/markets/'+quote(ticker,safe='')+'/candlesticks',{'start_ts':int(start),'end_ts':int(end),'period_interval':1})
        except Exception:
            data=self.http.get(KALSHI,'/historical/markets/'+quote(ticker,safe='')+'/candlesticks',{'start_ts':int(start),'end_ts':int(end),'period_interval':1})
        rows=data.get('candlesticks',[])
        with self.db:
            for row in rows:self.db.execute('INSERT OR REPLACE INTO intel_kalshi_candles VALUES(?,?,?)',(ticker,row['end_period_ts'],dumps(row)))
        return len(rows)

def report(db,days=7,now=None):
    if str(days) not in ('7','30','90'):raise ValueError('Unsupported research range')
    now=time.time() if now is None else now;start=window_start(str(days),now)
    markets=db.execute('SELECT * FROM intel_markets WHERE closed>=? AND closed<=?',(start,now)).fetchall()
    candles=db.execute('SELECT * FROM intel_candles WHERE period=900 AND ts>=? AND ts+900<=? ORDER BY ts',(start,now)).fetchall()
    books=db.execute('SELECT * FROM intel_hourly WHERE hour_utc>=? ORDER BY hour_utc',(int(start//3600)*3600,)).fetchall()
    groups={}
    for day in range(7):
        for hour in range(24):groups[(day,hour)]={'weekday':['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday'][day],'hour_et':hour,'outcomes':[],'returns':[],'volumes':[],'spreads':[],'depths':[],'flips':0,'book_count':0,'sum_spread':0,'n_spread':0,'sum_depth':0,'n_depth':0,'sum_velocity':0,'n_ticks':0,'sum_volatility1m':0,'n_volatility1m':0,'sum_kalshi_velocity':0,'n_kalshi_velocity':0,'paper_n':0,'paper_pnl':0,'paper_cost':0}
    key=lambda ts:(datetime.fromtimestamp(ts,ET).weekday(),datetime.fromtimestamp(ts,ET).hour)
    for m in markets:
        if m['result'] in ('yes','no'):groups[key(m['opened'])]['outcomes'].append(int(m['result']=='yes'))
    for c in candles:
        if c['open']>0:
            g=groups[key(c['ts'])];g['returns'].append(math.log(c['close']/c['open']));g['volumes'].append(c['volume'])
    for b in books:
        g=groups[key(b['hour_utc'])];g['book_count']+=b['depth_n'];g['sum_spread']+=b['spread_sum'];g['n_spread']+=b['spread_n'];g['sum_depth']+=b['depth_sum'];g['n_depth']+=b['depth_n'];g['flips']+=b['flip_moves'];g['sum_velocity']+=b['velocity_sum'];g['n_ticks']+=b['tick_n'];g['sum_volatility1m']+=b['volatility_sum'];g['n_volatility1m']+=b['vol_n'];g['sum_kalshi_velocity']+=b['kalshi_velocity_sum'];g['n_kalshi_velocity']+=b['kalshi_velocity_n']
    for paper in db.execute("SELECT signal_ts,pnl,quantity,entry,entry_fee FROM intel_sim WHERE signal_ts>=? AND state='CLOSED'",(start,)):
        g=groups[key(paper['signal_ts'])];g['paper_n']+=1;g['paper_pnl']+=paper['pnl'];g['paper_cost']+=paper['quantity']*paper['entry']+paper['entry_fee']
    output=[]
    for g in groups.values():
        output.append({'weekday':g['weekday'],'hour_et':g['hour_et'],'market_n':len(g['outcomes']),'up_frequency':statistics.mean(g['outcomes']) if g['outcomes'] else None,'candle_n':len(g['returns']),'volatility15m':statistics.stdev(g['returns']) if len(g['returns'])>1 else None,'mean_absolute_return':statistics.mean(abs(r) for r in g['returns']) if g['returns'] else None,'mean_volume':statistics.mean(g['volumes']) if g['volumes'] else None,'book_n':g['book_count'],'mean_spread':g['sum_spread']/g['n_spread'] if g['n_spread'] else None,'mean_top5_depth':g['sum_depth']/g['n_depth'] if g['n_depth'] else None,'mean_btc_velocity':g['sum_velocity']/g['n_ticks'] if g['n_ticks'] else None,'btc_tick_windows':g['n_ticks'],'mean_realized_volatility1m':g['sum_volatility1m']/g['n_volatility1m'] if g['n_volatility1m'] else None,'mean_kalshi_bid_velocity':g['sum_kalshi_velocity']/g['n_kalshi_velocity'] if g['n_kalshi_velocity'] else None,'observed_3c_flips':g['flips'],'paper_closed':g['paper_n'],'paper_net':g['paper_pnl'] if g['paper_n'] else None,'paper_roi':g['paper_pnl']/g['paper_cost'] if g['paper_cost'] else None})
    strategy=[]
    for row in db.execute("SELECT engine,regime,count(*) n,sum(CASE WHEN (direction='UP' AND result='yes') OR (direction='DOWN' AND result='no') THEN 1 ELSE 0 END) wins FROM intel_engines WHERE observed>=? AND result IN ('yes','no') AND direction IS NOT NULL GROUP BY engine,regime",(start,)):
        strategy.append({**dict(row),'accuracy':row['wins']/row['n']})
    sim=[]
    for row in db.execute("SELECT strategy,kind,count(*) n,sum(pnl) pnl FROM intel_sim WHERE signal_ts>=? AND state='CLOSED' GROUP BY strategy,kind",(start,)):sim.append(dict(row))
    jobs=[dict(r) for r in db.execute('SELECT * FROM intel_jobs ORDER BY id DESC LIMIT 10')]
    daily={}
    for m in markets:
        day=datetime.fromtimestamp(m['opened'],ET).date().isoformat();daily.setdefault(day,{'date':day,'up':0,'down':0})
        if m['result'] in ('yes','no'):daily[day]['up' if m['result']=='yes' else 'down']+=1
    return {'days':int(days),'timezone':'America/New_York','storage_timezone':'UTC epoch seconds','hourly':output,'daily':sorted(daily.values(),key=lambda r:r['date']),'strategy_by_regime':strategy,'simulated_profitability':sim,'jobs':jobs,'coverage':{'actual_first_market':min((m['opened'] for m in markets),default=None),'actual_last_market':max((m['closed'] for m in markets),default=None),'official_outcomes':sum(m['result'] in ('yes','no') for m in markets),'coinbase_15m_candles':len(candles),'live_book_observations':sum(b['depth_n'] for b in books),'kalshi_minute_candles':db.execute('SELECT count(*) FROM intel_kalshi_candles WHERE ts>=?',(start,)).fetchone()[0],'historical_depth':'Unavailable from public historical candles; recorded live going forward only','scalping':'No retrospective scalp fills inferred from OHLC or trade prints','patterns':'Descriptive sample counts only; day/hour correlations are not validated predictive effects','strategy_unit':'Distinct engine/candle signals; correlated within markets, not independent trades'},'radar_conditions':[dict(r) for r in db.execute('SELECT kind,status,count(*) n FROM intel_radars WHERE observed>=? GROUP BY kind,status',(start,))],'reversal_frequency':{'observed':db.execute("SELECT count(*) FROM intel_reversals WHERE observed>=? AND band IS NOT NULL",(start,)).fetchone()[0]},'warning':'Sparse or zero samples are displayed honestly; no invented Friday/weekend effect.'}
