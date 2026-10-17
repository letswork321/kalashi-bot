"""Deterministic causal indicators; candle timestamps are UTC opening seconds."""
import math
import statistics

class InsufficientData(ValueError):pass

def completed(candles,asof,period=900,minimum=1):
    rows=sorted((dict(c) for c in candles if c['ts']+period<=asof),key=lambda c:c['ts'])
    if len(rows)<minimum:raise InsufficientData(f'Need {minimum} completed {period}s candles')
    for a,b in zip(rows,rows[1:]):
        if b['ts']-a['ts']!=period:raise InsufficientData('Nonconsecutive candle coverage')
    for r in rows:
        if r['ts']%period or not all(math.isfinite(float(r[k])) for k in ('open','close','low','high','volume')) or r['low']<=0 or r['volume']<0 or r['low']>min(r['open'],r['close']) or r['high']<max(r['open'],r['close']):raise InsufficientData('Invalid OHLCV candle')
    return rows

def ema(values,period):
    if len(values)<period:raise InsufficientData(f'EMA{period} warming up')
    out=[sum(values[:period])/period]
    for x in values[period:]:out.append(out[-1]+2/(period+1)*(x-out[-1]))
    return out

def rsi(values,period=14):
    if len(values)<period+1:raise InsufficientData('RSI warming up')
    changes=[b-a for a,b in zip(values,values[1:])]
    g=sum(max(x,0) for x in changes[:period])/period;l=sum(max(-x,0) for x in changes[:period])/period
    for d in changes[period:]:g=(g*(period-1)+max(d,0))/period;l=(l*(period-1)+max(-d,0))/period
    return 50 if g==l==0 else 100 if l==0 else 100-100/(1+g/l)

def bollinger(values,period=20,k=2):
    if len(values)<period:raise InsufficientData('Bollinger Bands warming up')
    mean=statistics.mean(values[-period:]);sd=statistics.pstdev(values[-period:])
    return {'mean':mean,'upper':mean+k*sd,'lower':mean-k*sd,'sd':sd}

def macd(values):
    fast=ema(values,12);slow=ema(values,26)
    line=[a-b for a,b in zip(fast[-len(slow):],slow)]
    signal=ema(line,9)
    hist=[a-b for a,b in zip(line[-len(signal):],signal)]
    if len(hist)<2:raise InsufficientData('MACD histogram warming up')
    return {'macd':line[-1],'signal':signal[-1],'histogram':hist[-1],'previous_histogram':hist[-2]}

def covered(intervals,start,end):
    cursor=start
    for lo,hi in sorted(intervals):
        if hi<=cursor:continue
        if lo>cursor+1e-6:return False
        cursor=max(cursor,hi)
        if cursor>=end:return True
    return cursor>=end

def trade_vwap(trades,start,end,intervals):
    if not covered(intervals,start,end):raise InsufficientData('Complete trade coverage is required for time-aligned VWAP')
    rows=[r for r in trades if start<=r['ts']<end]
    if any(not math.isfinite(float(r['price'])) or not math.isfinite(float(r['size'])) or r['price']<=0 or r['size']<=0 for r in rows):raise InsufficientData('Invalid actual trade price/size')
    volume=sum(r['size'] for r in rows)
    if volume<=0:raise InsufficientData('No verified trade volume for VWAP')
    mean=sum(r['price']*r['size'] for r in rows)/volume
    variance=sum(r['size']*(r['price']-mean)**2 for r in rows)/volume
    return {'value':mean,'sd':math.sqrt(variance),'volume':volume,'anchor':start,'asof':end,'source':'actual Coinbase trades'}

def tick_metrics(trades,now):
    rows=sorted([r for r in trades if now-60<=r['ts']<=now],key=lambda r:(r['ts'],r.get('id',0)))
    if len(rows)<10 or rows[-1]['ts']<now-3 or rows[0]['ts']>now-50:raise InsufficientData('Need fresh consecutive trades spanning a minute')
    if any(b['id']-a['id']!=1 for a,b in zip(rows,rows[1:])):raise InsufficientData('Trade sequence gap')
    def price_before(t):
        eligible=[r['price'] for r in rows if r['ts']<=t]
        if not eligible:raise InsufficientData('Missing tick boundary')
        return eligible[-1]
    a=price_before(now-50);b=price_before(now-25);c=rows[-1]['price']
    first=math.log(b/a)/(25/60);second=math.log(c/b)/(25/60)
    return {'velocity':math.log(c/a)/(50/60),'acceleration':(second-first)/(25/60),'trades':len(rows),'age':now-rows[-1]['ts']}
