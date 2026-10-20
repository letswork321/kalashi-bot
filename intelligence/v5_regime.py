"""Causal descriptive regimes. Thresholds are fixed research hypotheses, not fitted wins."""
import math
import statistics

def efficiency(values):
    changes=[b-a for a,b in zip(values,values[1:])];den=sum(abs(x) for x in changes)
    return abs(values[-1]-values[0])/den if den else 0

def classify(rows,now,liquidity=None):
    rows=[r for r in rows if r['ts']+60<=now][-61:];prices=[math.log(r['close']) for r in rows]
    returns=[b-a for a,b in zip(prices,prices[1:])];recent=returns[-20:];nonzero=[r for r in recent if r!=0]
    flip_count=sum(a*b<0 for a,b in zip(nonzero,nonzero[1:]));flip_rate=flip_count/max(1,len(nonzero)-1)
    er=efficiency(prices[-21:]);short_er=efficiency(prices[-6:]);old_er=efficiency(prices[-26:-5])
    previous_sd=statistics.pstdev(returns[-50:-10]);recent_sd=statistics.pstdev(returns[-10:]);vol_ratio=recent_sd/previous_sd if previous_sd else None
    base_volume=statistics.mean(r['volume'] for r in rows[-25:-5]);current_volume=statistics.mean(r['volume'] for r in rows[-5:]);volume_ratio=current_volume/base_volume if base_volume else None
    prior_volume=statistics.mean(r['volume'] for r in rows[-10:-5]);volume_change=current_volume/prior_volume if prior_volume else None
    high_vol=bool(vol_ratio is not None and vol_ratio>=1.5 or previous_sd==0 and recent_sd>0)
    reversal_heavy=flip_rate>=.6;choppy=er<=.25 and flip_rate>=.45;ranging=er<=.35
    net=sum(recent);trend=er>=.55;direction='UP' if net>0 else 'DOWN' if net<0 else 'FLAT'
    transitioning=(short_er>=.65 and old_er<=.3) or (short_er<=.3 and old_er>=.65) or (sum(returns[-5:])*sum(returns[-20:-5])<0 and abs(sum(returns[-5:]))>max(recent_sd,1e-12)*2)
    failed_continuation=returns[-1]*sum(returns[-5:-1])<0 and abs(returns[-1])>=abs(sum(returns[-5:-1]))*.5
    sudden=returns[-1]*sum(returns[-5:-1])<0 and abs(returns[-1])>=max(previous_sd,1e-12)*2
    last=rows[-1];span=last['high']-last['low'];upper=(last['high']-max(last['open'],last['close']))/span if span else 0;lower=(min(last['open'],last['close'])-last['low'])/span if span else 0
    resistance=max(r['high'] for r in rows[-21:-1]);support=min(r['low'] for r in rows[-21:-1])
    false_up=last['high']>resistance and last['close']<resistance;false_down=last['low']<support and last['close']>support
    divergence=volume_change is not None and volume_change<.7 and abs(sum(returns[-5:]))>recent_sd
    flags=[]
    for name,yes in [('CHOPPY',choppy),('REVERSAL HEAVY',reversal_heavy),('HIGH VOLATILITY',high_vol),('LOW VOLUME',volume_ratio is not None and volume_ratio<=.6),('TRANSITIONING',transitioning),('RANGING',ranging)]:
        if yes:flags.append(name)
    primary='TRANSITIONING' if transitioning else 'REVERSAL HEAVY' if reversal_heavy else 'CHOPPY' if choppy else direction+' TREND' if trend else 'RANGING' if ranging else 'MIXED'
    warnings=[]
    for text,yes in [('False breakout / upper-level rejection',false_up),('False breakdown / support rejection',false_down),('Momentum continuation failed on the latest completed candle',failed_continuation),('Sudden completed-candle reversal',sudden),('Large upper wick / exhaustion risk',upper>=.5),('Large lower wick / rebound risk',lower>=.5),('Price movement has declining volume support',divergence)]:
        if yes:warnings.append(text)
    l=liquidity or {};liq_good=l.get('status')=='OBSERVED REST SNAPSHOT' and 0<=now-l.get('received',0)<=3 and l.get('latency',99)<=2
    liquidity_state='UNAVAILABLE'
    if liq_good:
        ratio=l.get('depth_ratio');liquidity_state='THIN RELATIVE DEPTH' if ratio is not None and ratio<.5 else 'HIGH RELATIVE DEPTH' if ratio is not None and ratio>1.5 else 'OBSERVED / BASELINE WARMING UP' if ratio is None else 'NORMAL RELATIVE DEPTH'
    risky=choppy or reversal_heavy or transitioning or high_vol or 'LOW VOLUME' in flags or liquidity_state=='THIN RELATIVE DEPTH'
    return {'version':'causal-regime-v5-1','primary':primary,'flags':flags,'classification_quality':'DESCRIPTIVE / UNVALIDATED; adequate price sample, liquidity '+('observed' if liq_good else 'unavailable'),
            'efficiency20':er,'efficiency5':short_er,'reversal_count20':flip_count,'reversal_frequency20':flip_rate,'volatility_ratio':vol_ratio,'volatility_recent':recent_sd,'volume_ratio':volume_ratio,
            'failed_continuation':failed_continuation,'false_breakout':false_up,'false_breakdown':false_down,'sudden_reversal':sudden,'volume_price_divergence':divergence,'warnings':warnings,'low_conviction':risky,
            'liquidity':{'state':liquidity_state,'source':'Coinbase BTC-USD public L2 REST','received':l.get('received') if liq_good else None,'spread_bps':l.get('spread_bps') if liq_good else None,'imbalance':l.get('imbalance') if liq_good else None,'depth_ratio':l.get('depth_ratio') if liq_good else None,'cancellations':'NOT OBSERVABLE from unsequenced snapshots'},
            'adaptation_status':'FIXED EXPERIMENTAL routing; regime-specific improvement requires unseen settled rounds'}
