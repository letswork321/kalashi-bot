"""Independent, causal BTC-only paper forecaster. All weights are EXPERIMENTAL.
Kalshi odds/book/favorite and the operational baseline are deliberately absent.
Final-minute average variance assumes a Brownian reference process, not a claim
that a spot proxy exactly follows the licensed benchmark.
"""
import math
import statistics
from .indicators import completed,ema,rsi,macd,bollinger,InsufficientData
from .v4_analysis import pressure

VERSION='btc-independent-v5-1-experimental'

def clip(x,lo,hi):return max(lo,min(hi,x))

def frame(candles,now,period):
    rows=completed(candles,now,period,20);c=[r['close'] for r in rows];last=rows[-1];span=last['high']-last['low']
    out={'last_closed':last['ts']+period,'ema9_gap':c[-1]/ema(c,9)[-1]-1,'ema20_gap':c[-1]/ema(c,20)[-1]-1,'rsi14':rsi(c),
         'momentum':math.log(c[-1]/c[-6]),'volume_ratio':last['volume']/statistics.mean(r['volume'] for r in rows[-21:-1]) if len(rows)>20 and sum(r['volume'] for r in rows[-21:-1])>0 else None,
         'body':(last['close']-last['open'])/span if span else 0,'upper_wick':(last['high']-max(last['open'],last['close']))/span if span else 0,'lower_wick':(min(last['open'],last['close'])-last['low'])/span if span else 0,
         'support':min(r['low'] for r in rows[-20:-1]),'resistance':max(r['high'] for r in rows[-20:-1]),'bands':bollinger(c)}
    out['structure']='HIGHER HIGHS / LOWS' if last['high']>rows[-2]['high'] and last['low']>rows[-2]['low'] else 'LOWER HIGHS / LOWS' if last['high']<rows[-2]['high'] and last['low']<rows[-2]['low'] else 'RANGING'
    out['failed_breakout']=last['high']>out['resistance'] and last['close']<out['resistance']
    out['failed_breakdown']=last['low']<out['support'] and last['close']>out['support']
    if len(c)>=50:out['ema50_gap']=c[-1]/ema(c,50)[-1]-1
    try:out['macd']=macd(c)
    except InsufficientData:out['macd']=None
    return out

def forecast(*,now,opened,closed,strike,price,quote_ts,candles1,candles5=(),candles15=(),ticks=(),source='Coinbase spot PROXY',brti=None):
    # Keyword-only allowlist prevents accidental injection of contract odds.
    if not all(math.isfinite(float(v)) for v in (now,opened,closed,strike,price,quote_ts)) or not 899<=closed-opened<=901 or not opened<=now<closed or strike<=0 or price<=0:raise ValueError('INVALID_ESSENTIAL_INPUT')
    if not 0<=now-quote_ts<=3:raise ValueError('STALE_ESSENTIAL_QUOTE')
    rows=completed(candles1,now,60,61)
    if now-(rows[-1]['ts']+60)>120:raise ValueError('STALE_COMPLETED_CANDLES')
    closes=[r['close'] for r in rows];returns=[math.log(b/a) for a,b in zip(closes,closes[1:])]
    sigma=statistics.pstdev(returns[-60:])
    if sigma<=0:raise ValueError('UNUSABLE_REALIZED_VOLATILITY')
    reference=price;event=quote_ts;official=False
    if brti and brti.get('status')=='LIVE' and brti.get('price') and brti.get('event_ts') is not None and 0<=now-brti['event_ts']<=3:
        reference=float(brti['price']);event=brti['event_ts']
        if not math.isfinite(reference) or reference<=0:raise ValueError('INVALID_BENCHMARK_VALUE')
        official=True;source='CF Benchmarks BRTI via Kalshi'
    frames={'1m':frame(rows,now,60)};missing=[]
    for name,data,period in [('5m',candles5,300),('15m',candles15,900)]:
        try:
            f=frame(data,now,period)
            if now-f['last_closed']>period*2:raise InsufficientData('Stale timeframe')
            frames[name]=f
        except (InsufficientData,ValueError,KeyError):missing.append(name)
    flow15=pressure(ticks,now,15);flow60=pressure(ticks,now,60)
    a=frames['1m'];momentum=sum(returns[-5:])/5;acceleration=sum(returns[-2:])/2-sum(returns[-5:-2])/3
    trend=statistics.mean(clip(f['ema20_gap']/sigma,-1,1) for f in frames.values())
    flow=(flow60['buy_share']-.5)*2 if flow60['buy_share'] is not None else 0
    # Transparent fixed experimental drift, bounded to avoid confident indicator stacking.
    parts={'momentum':.25*clip(momentum/sigma,-1,1),'multi_timeframe_trend':.15*trend,'verified_aggression':.10*flow,
           'volume_confirmation':.05*clip(momentum/sigma,-1,1)*clip((a['volume_ratio'] or 1)-1,-1,1),
           'macd_momentum':.05*clip((a['macd']['histogram'] if a['macd'] else 0)/(price*sigma),-1,1),
           'rsi_exhaustion':-.05 if a['rsi14']>70 and a['upper_wick']>.4 else .05 if a['rsi14']<30 and a['lower_wick']>.4 else 0,
           'failed_level_test':-.10 if a['failed_breakout'] else .10 if a['failed_breakdown'] else 0}
    drift=sigma*clip(sum(parts.values()),-.35,.35)
    minutes=(closed-now)/60
    # For the average over the final 60 seconds, Var(mean) = sigma^2*(T-2/3)
    # when T>=1 minute. These checkpoints are all earlier than that window.
    variance_minutes=max(1/60,minutes-2/3) if minutes>=1 else max(1/60,minutes/3)
    sd=sigma*math.sqrt(variance_minutes)
    z=math.log(reference/strike)/sd
    drift_horizon=min(minutes,3) # short-lived evidence, not a 14-minute constant drift
    adjusted=z+drift*drift_horizon/sd
    p=clip(.5*(1+math.erf(adjusted/math.sqrt(2))),.01,.99)
    direction='UP' if p>=.5 else 'DOWN';bull=[];bear=[]
    (bull if reference>=strike else bear).append(f'Reference is ${abs(reference-strike):,.2f} '+('above' if reference>=strike else 'below')+' the official strike')
    for key,value in parts.items():
        if value:(bull if value>0 else bear).append(key.replace('_',' ')+(' supports rising BTC' if value>0 else 'supports falling BTC'))
    if a['upper_wick']>=.5:bear.append('Long upper wick: rejection risk')
    if a['lower_wick']>=.5:bull.append('Long lower wick: rebound risk')
    horizon=[t for t in ticks if now-60<=t['ts']<=now]
    vwap=None
    if flow60['status']=='LIVE' and horizon:
        vol=sum(t['size'] for t in horizon)
        if vol:vwap=sum(t['price']*t['size'] for t in horizon)/vol
    return {'version':VERSION,'direction':direction,'p_up':p,'calibrated':False,'conviction':'LOW' if max(p,1-p)<.65 or missing or flow60['buy_share'] is None else 'MODEL STRONG / UNVALIDATED',
            'source':source,'official_reference':official,'reference':reference,'reference_ts':event,'quote_age':now-event,'strike':strike,'remaining':closed-now,
            'bullish':bull or ['No strong bullish evidence'],'bearish':bear or ['No strong bearish evidence'],'frames':frames,'pressure15':flow15,'pressure60':flow60,
            'features':{'distance':reference/strike-1,'sigma':sigma,'momentum':momentum,'acceleration':acceleration,'trend':trend,'flow':flow,'failed_breakout':int(a['failed_breakout']),'failed_breakdown':int(a['failed_breakdown']),'rsi':a['rsi14'],'volume_ratio':a['volume_ratio'],'vwap60':vwap,'z':z,'drift':drift,'remaining':closed-now,'quote_age':now-event,'drift_parts':parts},
            'missing_optional':missing,'regime':'UP TREND' if trend>.3 else 'DOWN TREND' if trend<-.3 else 'RANGING / MIXED','guidance':'WAIT',
            'risk':'Experimental, uncalibrated BTC model; '+('benchmark path averaging remains approximate' if official else 'Coinbase is a proxy, not the settlement index'),
            'model_basis':'BTC-only strike/volatility plus bounded experimental momentum, multi-frame trend, verified flow and failed-level-test drift; no contract odds'}
