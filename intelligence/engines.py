"""Three independent pure engines. Each consumes the same immutable market snapshot."""
import math
import statistics
from .indicators import completed,ema,rsi,macd,bollinger,tick_metrics,InsufficientData

NAMES=('breakout','reversal','confluence')

def result(engine,s,signal,reason,quality='LIVE',direction=None,readings=None):
    return {'engine':engine,'signal':signal,'direction':direction,'reason':reason,'quality':quality,'timestamp':s['now'],'ticker':s.get('market',{}).get('ticker'),'readings':readings or {},'probability':None}

def require_live(s):
    if s.get('mode')=='mock':raise InsufficientData('MOCK TEST ONLY')
    if not s.get('price') or not 0<=s['now']-s.get('quote_ts',0)<=3:raise InsufficientData('Fresh BTC quote unavailable')

def breakout_engine(snapshot):
    s=snapshot
    try:
        require_live(s)
        rows=completed(s['candles15'],s['now'],minimum=26)
        if rows[-1]['ts']+900 != int(s['now']//900)*900:raise InsufficientData('Latest 15-minute candle stale')
        last=rows[-1];e=ema([r['close'] for r in rows],20)[-1]
        v=s.get('vwap_at_close');current=s.get('vwap')
        if not v or v['asof']!=last['ts']+900 or not current:raise InsufficientData('Complete trade-weighted, time-aligned VWAP warming up')
        high=max(r['high'] for r in rows[-26:-1])
        readings={'ema20':e,'vwap_at_close':v['value'],'current_vwap':current['value'],'previous_25_high':high,'completed_low':last['low'],'completed_close':last['close'],'trigger_close':last['ts']+900,'volume':last['volume'],'price':s['price']}
        if last['low']>e and last['low']>v['value'] and last['close']>high and s['price']>=current['value']:
            market=s.get('market',{})
            if market.get('opened',0)<last['ts']+900:return result('breakout',s,'NEXT MARKET INFORMATION','Confirmed candle cannot be applied retroactively to its closing market',readings=readings)
            return result('breakout',s,'LONG BREAKOUT — CONFIRMED','Completed candle entirely above EMA20 and its time-aligned VWAP; close exceeds previous 25 highs; current price holds VWAP',direction='UP',readings=readings)
        watch_high=max(r['high'] for r in rows[-25:])
        if s['price']>watch_high and s['price']>current['value']:
            return result('breakout',s,'UNCONFIRMED BREAKOUT WATCH','Developing candle has not closed; not a confirmed prediction',direction='UP',readings=readings)
        return result('breakout',s,'NO BREAKOUT','Completed-candle confirmation conditions not met',readings=readings)
    except (InsufficientData,KeyError,ValueError,TypeError) as e:return result('breakout',s,'WARMING UP',str(e),'INSUFFICIENT DATA')

def reversal_engine(snapshot):
    s=snapshot;r=s.get('reversal')
    if not r:return result('reversal',s,'WAITING FOR 10:00','A single observation is scheduled from the actual market opening time','WARMING UP')
    if r['state']=='MISSED':return result('reversal',s,'MISSED',r.get('reason','10-minute observation missed'),'MISSED')
    if r['state']=='PENDING':return result('reversal',s,'WAITING FOR 10:00','Will only sample an on-time fresh quote; never reconstruct from later candles','WARMING UP',readings={'target':r['target']})
    if not r.get('band'):return result('reversal',s,'NO BAND EXCURSION','On-time observation stayed between opening-time Bollinger Bands',readings=r)
    evidence=s.get('reversal_evidence') or {}
    out=result('reversal',s,'REVERSAL RISK / FADE OPPORTUNITY','10-minute quote crossed '+r['band']+' band. A reversal is not guaranteed.',direction=r['direction'],readings={**r,'deviation':r['price']-(r['upper'] if r['band']=='UPPER' else r['lower']),'evidence':evidence})
    out['probability_status']='PROBABILITY NOT VALIDATED'
    if evidence.get('validated'):
        out['probability']=evidence['probability'];out['probability_status']='OUT-OF-SAMPLE OBSERVED FREQUENCY (not a guarantee)'
    out['observed_at']=r['observed']
    out['timestamp']=r['observed']
    return out

def confluence_engine(snapshot):
    s=snapshot
    try:
        require_live(s)
        rows=completed(s['candles15'],s['now'],minimum=64)
        if rows[-1]['ts']+900 != int(s['now']//900)*900:raise InsufficientData('15-minute candles stale')
        closes=[r['close'] for r in rows]
        fast,slow=ema(closes,27),ema(closes,63)
        rs=rsi(closes);m=macd(closes);t=tick_metrics(s['trades'],s['now'])
        v=s.get('vwap')
        if not v or v['sd']<=0:raise InsufficientData('Verified trade VWAP and weighted deviation unavailable')
        avg=statistics.mean(r['volume'] for r in rows[-21:-1])
        ratio=rows[-1]['volume']/avg if avg>0 else 0
        z=(s['price']-v['value'])/v['sd']
        sign=lambda x:1 if x>0 else -1 if x<0 else 0
        votes={
            'EMA27/63':sign(fast[-1]-slow[-1]),
            'RSI14':1 if rs<=30 else -1 if rs>=70 else 0,
            'Volume surge':sign(rows[-1]['close']-rows[-1]['open']) if ratio>=1.5 else 0,
            'MACD shift':1 if m['histogram']>0 and m['histogram']>m['previous_histogram'] else -1 if m['histogram']<0 and m['histogram']<m['previous_histogram'] else 0,
            'Acceleration':1 if t['acceleration']>=.00005 else -1 if t['acceleration']<=-.00005 else 0,
            'Tick velocity':1 if t['velocity']>=.0001 else -1 if t['velocity']<=-.0001 else 0,
            'VWAP deviation':1 if z>=1 else -1 if z<=-1 else 0}
        score=sum(votes.values())
        signal='CONFLUENCE BUY' if score>=6 else 'CONFLUENCE SELL' if score<=-6 else 'NO MAJOR CONFLUENCE'
        out=result('confluence',s,signal,'Six of seven signed votes are required; no other engine changes these votes',direction='UP' if score>=6 else 'DOWN' if score<=-6 else None,readings={'ema27':fast[-1],'ema63':slow[-1],'rsi14':rs,'volume_ratio':ratio,'macd':m,'ticks':t,'vwap_z':z})
        out.update(votes=votes,score=score);return out
    except (InsufficientData,KeyError,ValueError,TypeError) as e:
        out=result('confluence',s,'INSUFFICIENT DATA',str(e),'INSUFFICIENT DATA');out.update(votes={},score=None);return out

def observe_reversal(db,s):
    ticker=s['market']['ticker'];r=db.execute('SELECT * FROM intel_reversals WHERE ticker=?',(ticker,)).fetchone()
    if not r:return
    now=s['now'];target=r['target']
    if r['state']=='PENDING' and now>=target:
        if now>target+3:
            with db:db.execute("UPDATE intel_reversals SET state='MISSED',reason='Fresh 10-minute observation missed (3s deadline)' WHERE ticker=?",(ticker,))
        elif target<=s.get('quote_ts',0)<=target+2 and 0<=now-s['quote_ts']<=2:
            try:
                rows=completed(s['candles15'],s['market']['opened'],minimum=20)
                b=bollinger([c['close'] for c in rows])
                if b['sd']<=0:raise InsufficientData('Zero-width Bollinger bands')
                band='UPPER' if s['price']>=b['upper'] else 'LOWER' if s['price']<=b['lower'] else None
                direction='DOWN' if band=='UPPER' else 'UP' if band else None
                with db:db.execute("UPDATE intel_reversals SET state='OBSERVED',observed=?,price=?,band=?,lower=?,upper=?,mean=?,direction=?,outcome_target=?,reason=? WHERE ticker=? AND state='PENDING'",(s['quote_ts'],s['price'],band,b['lower'],b['upper'],b['mean'],direction,target+240,'Frozen bands from candles completed before market open',ticker))
            except InsufficientData:pass
    r=db.execute('SELECT * FROM intel_reversals WHERE ticker=?',(ticker,)).fetchone()
    if r['state']=='OBSERVED' and r['band'] and not r['outcome'] and now>=r['outcome_target']:
        target=r['outcome_target']
        if now>target+3:
            with db:db.execute("UPDATE intel_reversals SET outcome='MISSED' WHERE ticker=?",(ticker,))
        elif target<=s.get('quote_ts',0)<=target+2 and now-s['quote_ts']<=2:
            signed=(s['price']/r['price']-1)*(1 if r['direction']=='UP' else -1)
            with db:db.execute('UPDATE intel_reversals SET outcome_price=?,outcome=? WHERE ticker=?',(s['price'],'REVERTED' if signed>=.0002 else 'NOT_REVERTED',ticker))

def reversal_evidence(db,band=None):
    rows=db.execute("SELECT observed,outcome FROM intel_reversals WHERE outcome IN ('REVERTED','NOT_REVERTED') AND (? IS NULL OR band=?) ORDER BY observed",(band,band)).fetchall()
    n=len(rows);test=rows[int(n*.7):]
    base={'sample_size':n,'test_size':len(test),'definition':'At +14 minutes, at least 0.02% spot movement toward the opening-time band mean relative to +10-minute quote; quotes <=2s after each target; late outcomes excluded.','validated':False}
    if n>=100 and len(test)>=30:
        p=sum(r['outcome']=='REVERTED' for r in test)/len(test);z=1.96;den=1+z*z/len(test)
        center=(p+z*z/(2*len(test)))/den;half=z*math.sqrt(p*(1-p)/len(test)+z*z/(4*len(test)**2))/den
        base.update(validated=True,probability=p,wilson95=[center-half,center+half],train_end=rows[int(n*.7)-1]['observed'],test_start=test[0]['observed'])
    return base

def regime_detector(s):
    try:
        rows=completed(s['candles15'],s['now'],minimum=64);cl=[r['close'] for r in rows]
        e20=ema(cl,20)[-1];e60=ema(cl,60)[-1]
        ret=[math.log(b/a) for a,b in zip(cl,cl[1:])];vol=statistics.stdev(ret[-20:])
        past=[statistics.stdev(ret[i-20:i]) for i in range(20,len(ret)+1)]
        low,high=sorted(past)[int((len(past)-1)*.2)],sorted(past)[int((len(past)-1)*.8)]
        strength=abs(e20/e60-1)/max(vol,1e-7)
        trend='Strong upward trend' if e20>e60 and strength>=1 else 'Strong downward trend' if e20<e60 and strength>=1 else 'Sideways/ranging'
        b=s.get('book');depth=sum(q for _,q in (b.yes[:5]+b.no[:5])) if b else 0
        return {'regime':trend,'volatility':'High volatility' if vol>high else 'Low volatility' if vol<low else 'Normal volatility','liquidity':'Thin liquidity' if depth<100 or not b or b.spread>.08 else 'High liquidity' if depth>=1000 else 'Normal liquidity','classification_strength':min(.99,strength/3),'confidence_label':'Heuristic classification strength, not a calibrated probability','readings':{'ema20':e20,'ema60':e60,'volatility15m':vol,'rolling_vol_p20':low,'rolling_vol_p80':high,'top5_depth':depth},'quality':'LIVE','timestamp':s['now']}
    except (InsufficientData,KeyError,ValueError):return {'regime':'WARMING UP','quality':'INSUFFICIENT DATA','timestamp':s['now']}
