"""Read-only chart payloads: real completed candles, observed partial live bar, no forward fill."""
import math
import time
from .storage import loads
from .indicators import ema,rsi,bollinger,covered

PERIODS={'1m':60,'5m':300,'15m':900,'15s':15}

def indicators(rows):
    values=[r['close'] for r in rows];out={}
    for period in (9,21,50):out['ema'+str(period)]=[{'time':r['time'],'value':v} for r,v in zip(rows[period-1:],ema(values,period))] if len(values)>=period else []
    out['rsi14']=[{'time':rows[i]['time'],'value':rsi(values[:i+1],14)} for i in range(14,len(rows))]
    out['bb_upper']=[];out['bb_lower']=[]
    for i in range(19,len(rows)):
        b=bollinger(values[:i+1]);out['bb_upper'].append({'time':rows[i]['time'],'value':b['upper']});out['bb_lower'].append({'time':rows[i]['time'],'value':b['lower']})
    out['macd']=[];out['macd_signal']=[]
    if len(values)>=34:
        a=ema(values,12);b=ema(values,26);line=[x-y for x,y in zip(a[-len(b):],b)]
        out['macd']=[{'time':r['time'],'value':v} for r,v in zip(rows[25:],line)]
        out['macd_signal']=[{'time':r['time'],'value':v} for r,v in zip(rows[33:],ema(line,9))]
    if len(rows)>=20:
        y=values[-20:];mean=sum(y)/20;slope=sum((i-9.5)*(v-mean) for i,v in enumerate(y))/sum((i-9.5)**2 for i in range(20))
        out['trend_line']=[{'time':rows[-20]['time'],'value':mean-9.5*slope},{'time':rows[-1]['time'],'value':mean+9.5*slope}]
        out['levels']={'support':min(r['low'] for r in rows[-21:-1]),'resistance':max(r['high'] for r in rows[-21:-1])}
    return out

def history(db,period,now):
    if period==15:return [],{}
    provenance={r['ts']:r['origin'] for r in db.execute('SELECT ts,origin FROM v3_candle_provenance WHERE period=?',(period,))}
    rows=[{'time':r['ts'],'open':r['open'],'high':r['high'],'low':r['low'],'close':r['close'],'volume':r['volume'],'source':provenance.get(r['ts'],'Coinbase REST completed candles')} for r in db.execute("SELECT * FROM intel_candles WHERE source='coinbase' AND period=? AND ts+?<=? ORDER BY ts DESC LIMIT 280",(period,period,now))][::-1]
    rows=[r for r in rows if r['time']%period==0 and all(isinstance(r[k],(int,float)) and math.isfinite(r[k]) for k in ('open','high','low','close','volume')) and r['low']>0 and r['low']<=min(r['open'],r['close']) and r['high']>=max(r['open'],r['close'])]
    tail=0
    for i in range(1,len(rows)):
        if rows[i]['time']-rows[i-1]['time']!=period:tail=i
    lines=indicators(rows[tail:]);lines['vwap']=[]
    # Draw only actual UTC-session volume-weighted values with full certified coverage.
    anchor=int(now//86400)*86400
    coverage=[tuple(r) for r in db.execute("SELECT start,end FROM intel_coverage WHERE source='coinbase_trades' AND end>=?",(anchor,))]
    if rows and covered(coverage,anchor,rows[-1]['time']+period):
        grouped=db.execute('SELECT CAST(ts/? AS INTEGER)*? bucket,sum(price*size) pv,sum(size) v FROM intel_btc_trades WHERE ts>=? AND ts<? GROUP BY bucket ORDER BY bucket',(period,period,anchor,rows[-1]['time']+period)).fetchall()
        pv=vol=0;wanted={r['time'] for r in rows}
        for r in grouped:
            pv+=r['pv'];vol+=r['v']
            if r['bucket'] in wanted and vol>0:lines['vwap'].append({'time':r['bucket'],'value':pv/vol})
    return rows,lines

def live_bar(db,period,now,start=None):
    start=int(now//period)*period if start is None else start
    rows=db.execute('SELECT id,event,received,price,size,continuous FROM v3_ticks WHERE source=? AND event>=? AND event<=? ORDER BY event,CAST(id AS INTEGER)',('Coinbase WebSocket',start,min(now,start+period-1e-6))).fetchall()
    if not rows:return None
    first,last=rows[0],rows[-1]
    partial=first['event']>start+1 or any(not r['continuous'] for r in rows) or any(b['event']-a['event']>3 or int(b['id'])!=int(a['id'])+1 for a,b in zip(rows,rows[1:]))
    return {'time':start,'open':first['price'],'high':max(r['price'] for r in rows),'low':min(r['price'] for r in rows),'close':last['price'],'volume':sum(r['size'] for r in rows),'event_ts':last['event'],'source':'Coinbase WebSocket observed intraperiod trades','partial':partial,'first_event':first['event']}

def payload(db,timeframe,now,history_cache=None):
    period=PERIODS[timeframe]
    candles,lines=history_cache if history_cache is not None else history(db,period,now)
    row=db.execute("SELECT payload,ts FROM v3_state WHERE name='spot'").fetchone();spot=loads(row['payload']) if row else {}
    event=spot.get('event_ts');age=now-event if event is not None else None
    live=bool(spot.get('status')=='LIVE' and age is not None and 0<=age<=3 and row and 0<=now-row['ts']<=2)
    observer_age=now-row['ts'] if row else None
    source_status=spot.get('status','UNAVAILABLE')
    status='LIVE' if live else source_status if source_status in ('RESYNCING','CLOCK SKEW','CONNECTING','UNAVAILABLE','DISABLED') else 'OBSERVER DELAY' if source_status=='LIVE' and observer_age is not None and observer_age>2 else 'STALE' if event else 'REST HISTORY / STREAM UNAVAILABLE'
    developing=live_bar(db,period,now)
    # An existing partial candle remains visible on disconnection, with a red stale mask.
    bars=list(candles)
    previous=int(now//period)*period-period
    if not bars or bars[-1]['time']<previous:
        observed_previous=live_bar(db,period,now,previous)
        if observed_previous:bars.append(observed_previous)
    if developing and (not bars or developing['time']>bars[-1]['time']):bars.append(developing)
    if period==15:
        from .live_feed import candle_rows
        ticks=[{'id':int(r['id']),'ts':r['event'],'price':r['price'],'size':r['size'],'epoch':0 if r['continuous'] else int(r['id'])} for r in db.execute("SELECT * FROM v3_ticks WHERE source='Coinbase WebSocket' AND event>=? ORDER BY event,CAST(id AS INTEGER)",(now-900,))]
        short=candle_rows(ticks,15,now);bars=[r for r in short if not r['partial']]
        if len(bars)<10 or any(b['time']-a['time']!=15 for a,b in zip(bars[-10:],bars[-9:])):return {'status':'UNAVAILABLE','reason':'15s requires >=10 fully observed consecutive tick-built bars; REST cannot manufacture them','candles':[],'indicators':{},'period':period,'source':'Coinbase BTC-USD'}
        lines=indicators(bars)
    marks=markers(db,period,bars[0]['time'] if bars else now)
    return {'status':status,'verification_reason':spot.get('verification_reason'),'observer_age':observer_age,'server_time':now,'event_ts':event,'age':age,'source':'Coinbase BTC-USD — NOT official BRTI','timeframe':timeframe,'period':period,'candles':bars,'indicators':lines,'markers':marks,'developing_partial':bool(developing and developing['partial']),'history_revision':candles[-1]['time'] if candles else None,'trade_id':spot.get('last_id'),'gaps':spot.get('gaps',0),'note':'No synthetic bars. Partial last bar shows observed prints only; earlier extremes may be unknown. Missing historical bars are not filled.'}


def markers(db,period,start):
    rows=db.execute('SELECT observed,direction,metric,version,reason FROM intel_callouts WHERE sent IS NOT NULL AND observed>=? ORDER BY observed DESC LIMIT 100',(start,)).fetchall()
    return [{'time':int(r['observed']//period)*period,'position':'belowBar' if r['direction']=='UP' else 'aboveBar','shape':'arrowUp' if r['direction']=='UP' else 'arrowDown','color':'#5ee7b0' if r['direction']=='UP' else '#ff7d91','text':r['direction']+' WATCH','event_ts':r['observed'],'model':r['version'],'metric':r['metric'],'reason':r['reason']} for r in reversed(rows)]
