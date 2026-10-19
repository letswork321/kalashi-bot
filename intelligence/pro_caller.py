"""Independent, causal spot-pattern modules. Labels are not probability estimates."""
import math
import statistics
from .indicators import ema,rsi,bollinger,macd,InsufficientData


def complete(rows,period,now,minimum=26):
    out=sorted([r for r in rows if r['ts']+period<=now],key=lambda r:r['ts'])
    if len(out)<minimum or now-out[-1]['ts']-period>period+30:raise InsufficientData('Completed '+str(period)+'s candles warming up or stale')
    if any(b['ts']-a['ts']!=period for a,b in zip(out[-minimum:],out[-minimum+1:])):raise InsufficientData('Candle gap')
    for r in out:
        if not all(math.isfinite(float(r[k])) and float(r[k])>0 for k in ('low','high','open','close')) or r['low']>min(r['open'],r['close']) or r['high']<max(r['open'],r['close']):raise InsufficientData('Malformed OHLC')
    return out


def patterns(s):
    modules=[]
    def add(name,direction,signal,reason,readings):modules.append({'module':name,'direction':direction,'signal':signal,'reason':reason,'readings':readings,'timestamp':s['now'],'quality':'HEURISTIC CONTEXT — NOT CALIBRATED'})
    try:
        one=complete(s.get('candles1',[]),60,s['now'],63);five=complete(s.get('candles5',[]),300,s['now'],63)
        c=[r['close'] for r in one];c5=[r['close'] for r in five]
        fast,slow,long=ema(c,9)[-1],ema(c,21)[-1],ema(c,50)[-1]
        e5a,e5b=ema(c5,9)[-1],ema(c5,21)[-1]
        trend='UP' if fast>slow>long and e5a>e5b else 'DOWN' if fast<slow<long and e5a<e5b else None
        ranges=[max(r['high']-r['low'],abs(r['high']-one[i-1]['close']),abs(r['low']-one[i-1]['close'])) for i,r in enumerate(one) if i>0][-14:]
        atr=statistics.mean(ranges);strength=abs(fast-slow)/atr if atr else 0
        support=min(r['low'] for r in one[-26:-1]);resistance=max(r['high'] for r in one[-26:-1]);last=one[-1]
        add('trend_following',trend,'ALIGNED TREND' if trend else 'MIXED TRENDS','1-minute EMA9/21/50 and 5-minute EMA9/21 '+('agree.' if trend else 'do not agree.'),{'ema9':fast,'ema21':slow,'ema50':long,'ema5m9':e5a,'ema5m21':e5b,'atr14':atr,'strength_label':'STRONG' if strength>=1 else 'MODERATE' if strength>=.3 else 'WEAK','strength_definition':'EMA9/21 separation divided by observed ATR14; heuristic, not win probability'})
        direction='UP' if last['close']>resistance else 'DOWN' if last['close']<support else None
        add('spot_breakout',direction,'CONFIRMED '+('BREAKOUT' if direction=='UP' else 'BREAKDOWN') if direction else 'INSIDE RECENT RANGE','Last completed 1-minute close '+('cleared resistance.' if direction=='UP' else 'broke support.' if direction else 'remains inside the previous25 completed-candle range.'),{'support':support,'resistance':resistance,'close':last['close'],'confirmed_candle':last['ts']})
        band=bollinger(c,20,2);rr=rsi(c,14)
        mean_dir='DOWN' if c[-1]>=band['upper'] and rr>=70 else 'UP' if c[-1]<=band['lower'] and rr<=30 else None
        add('mean_reversion',mean_dir,'STRETCHED — REVERSAL WATCH' if mean_dir else 'NO EXTREME','Bollinger20/2 and RSI14 extremes are context only.',{'rsi14':rr,**band})
        failed='DOWN' if last['high']>resistance and last['close']<resistance else 'UP' if last['low']<support and last['close']>support else None
        add('failed_breakout',failed,'FAILED BREAK / REJECTION' if failed else 'NO FAILED BREAK','A wick beyond a prior level followed by a close back inside can signal rejection.',{'support':support,'resistance':resistance,'high':last['high'],'low':last['low'],'close':last['close']})
        momentum=math.log(s['price']/c[-4]);volume=last['volume']/statistics.mean(r['volume'] for r in one[-21:-1]) if sum(r['volume'] for r in one[-21:-1]) else None
        mm='UP' if momentum>.0003 else 'DOWN' if momentum<-.0003 else None
        add('momentum',mm,'MOMENTUM '+mm if mm else 'LITTLE MOMENTUM','BTC change from three completed minutes ago; elevated volume is supporting context, not a profit forecast.',{'log_return_3m':momentum,'volume_ratio':volume,'macd':macd(c)})
    except (InsufficientData,ValueError,KeyError,TypeError) as exc:
        for name in ('trend_following','spot_breakout','mean_reversion','failed_breakout','momentum'):add(name,None,'INSUFFICIENT DATA',str(exc),{})
    ticks=[r for r in s.get('trades',[]) if s['now']-20<=r['ts']<=s['now']]
    valid=len(ticks)>=10 and ticks[-1]['ts']>=s['now']-1 and all(b['id']==a['id']+1 for a,b in zip(ticks,ticks[1:])) and all(r.get('side') in ('buy','sell') for r in ticks)
    if valid:
        total=sum(r['size'] for r in ticks);imb=sum(r['size']*(1 if r['side']=='sell' else -1) for r in ticks)/total  # Coinbase side is the maker side.
        add('order_flow','UP' if imb>.2 else 'DOWN' if imb<-.2 else None,'AGGRESSOR BUY PRESSURE' if imb>.2 else 'AGGRESSOR SELL PRESSURE' if imb<-.2 else 'BALANCED FLOW','Coinbase maker side is inverted to estimate the aggressor; actual matched volume only.',{'aggressor_imbalance':imb,'btc_volume_20s':total,'prints':len(ticks)})
    else:add('order_flow',None,'INSUFFICIENT LIVE TICKS','Consecutive, fresh, sided Coinbase trades required.',{})
    book=s.get('book');fresh=book is not None and 0<=s['now']-s.get('book_ts',0)<=2
    add('liquidity',None,'TIGHT / DEEP' if fresh and book.spread<=.02 and sum(q for _,q in book.yes[:5]+book.no[:5])>=20 else 'THIN / WIDE' if fresh else 'BOOK UNAVAILABLE','Actual Kalshi depth and spread; no order placement.',{'spread':book.spread,'top5_depth':sum(q for _,q in book.yes[:5]+book.no[:5]),'imbalance':book.imbalance} if fresh else {})
    return modules


def caller(s,exit_model=None):
    modules=patterns(s);by={m['module']:m for m in modules};trend=by['trend_following'];breakout=by['spot_breakout'];mom=by['momentum']
    direction=breakout['direction'] or trend['direction'] or mom['direction'];fresh=s.get('spot_status')=='LIVE' and 0<=s['now']-s.get('quote_ts',0)<=3
    label='BTC '+direction+' pressure — WATCH' if fresh and direction else 'WAIT — data warming up' if not fresh else 'WAIT — mixed conditions'
    reasons=[m['reason'] for m in (breakout,trend,mom) if m['direction']==direction][:2]
    decision='WAIT';entry_reason='Spot patterns are context. No validated early-exit contract edge.'
    model=(exit_model or {}).get(direction or '',{})
    current_ask=(1-s['book'].no[0][0] if direction=='UP' else 1-s['book'].yes[0][0]) if s.get('book') and direction else None
    model_current=current_ask is not None and abs(current_ask-model.get('entry_ask',-1))<=.005
    if model_current and fresh and model.get('validated') and s.get('fee_valid') and s.get('book') and 0<=s['now']-s.get('book_ts',0)<=1 and s.get('book_event_verified'):
        if model.get('expected_net_lower',-1)>=.01 and s['book'].spread<=.03 and s['market']['closed']-s['now']>model.get('horizon',60)+30:decision='ENTER';entry_reason='Supported forward early-exit estimate after costs and executable depth; still uncertain and manual.'
        elif model.get('expected_net_upper',1)<0:decision='AVOID';entry_reason='Validated comparable observations indicate negative after-cost early-exit value.'
    if not fresh:direction=None;reasons=['Coinbase stream is stale, disconnected or resyncing. REST history remains available.']
    return {'version':'btc-caller-v3','timestamp':s['now'],'title':label,'direction':direction,'guidance':decision,'reason':' '.join(reasons) or 'Trend agreement and a confirmed move have not developed.','entry':entry_reason,'confidence':'Forward evidence available; uncertainty remains' if model.get('validated') else 'Heuristic context — probability and contract target NOT VALIDATED','contract_forecast':model if model.get('validated') else None,'modules':modules,'support':breakout['readings'].get('support'),'resistance':breakout['readings'].get('resistance'),'source':'Coinbase BTC-USD — not BRTI','data_age':s['now']-s.get('quote_ts',0)}
