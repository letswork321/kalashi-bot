"""Observed microstructure context, not calibrated trading probabilities."""
import math
import statistics


def pressure(ticks,now,window):
    rows=sorted((r for r in ticks if now-window<=r['ts']<=now),key=lambda r:r['id'])
    continuous=bool(rows) and now-rows[-1]['ts']<=3 and rows[0]['ts']<=now-window+3 and all(b['id']==a['id']+1 and b.get('continuous') for a,b in zip(rows,rows[1:]))
    known=[r for r in rows if r.get('side') in ('buy','sell')]
    # Coinbase Exchange match.side is maker/resting side: sell maker => buy aggressor.
    buy=sum(r['size'] for r in known if r['side']=='sell');sell=sum(r['size'] for r in known if r['side']=='buy');total=buy+sell
    good=continuous and len(known)==len(rows) and total>0
    return {'status':'LIVE' if good else 'INSUFFICIENT CONTINUOUS TRADES','window':window,'buy':buy,'sell':sell,'buy_share':buy/total if good else None,'sell_share':sell/total if good else None,'cvd':buy-sell if good else None,'volume':total,'trades':len(rows),'meaning':'Observed aggressive BTC volume, not people; maker side inverted'}


def analyze(s,ticks,previous=None):
    now=s['now'];fresh=s.get('spot_status')=='LIVE' and 0<=now-s.get('quote_ts',0)<=3
    p=pressure(ticks,now,15);long=pressure(ticks,now,60)
    if not fresh:
        for item in (p,long):item.update(status='STALE',buy_share=None,sell_share=None,cvd=None)
    rows=sorted((r for r in ticks if now-65<=r['ts']<=now),key=lambda r:(r['ts'],r['id']))
    changes=[math.log(b['price']/a['price']) for a,b in zip(rows,rows[1:]) if b['id']==a['id']+1]
    sigma=statistics.pstdev(changes) if len(changes)>=30 else None
    recent=[r for r in rows if r['ts']>=now-5]
    move=math.log(recent[-1]['price']/recent[0]['price']) if len(recent)>=2 else 0
    intensity=abs(move)/(sigma*math.sqrt(max(1,len(recent)-1))) if sigma and sigma>0 else None
    side=('UP' if move>0 else 'DOWN' if move<0 else None) if fresh else None
    b=s.get('book');bookgood=bool(b and s.get('book_event_verified') and s.get('fee_valid') and 0<=now-s.get('book_event_ts',0)<=1)
    yes=b.yes[0] if b and b.yes else (None,0);no=b.no[0] if b and b.no else (None,0)
    depth=sum(q for _,q in b.yes[:5]+b.no[:5]) if b else None
    prior_depth=previous.get('depth') if previous and previous.get('ticker')==s['market']['ticker'] else None
    depth_change=(depth/prior_depth-1) if bookgood and prior_depth else None
    micro=(yes[0]*no[1]+(1-no[0])*yes[1])/(yes[1]+no[1]) if bookgood and yes[1]+no[1] else None
    evidence=[]
    if fresh and p['buy_share'] is not None:
        if p['buy_share']>=.7:evidence.append('Aggressive buying dominates the last 15 seconds');side='UP'
        elif p['buy_share']<=.3:evidence.append('Aggressive selling dominates the last 15 seconds');side='DOWN'
    if intensity is not None and intensity>=2:evidence.append('Five-second move exceeds recent trade-return noise')
    if depth_change is not None and depth_change<=-.3:evidence.append('Observed Kalshi top-five depth fell at least 30%')
    score=min(100,(35 if evidence and fresh else 0)+(30 if intensity is not None and intensity>=2 else 0)+(20 if bookgood and b.spread<=.03 else 0)+(15 if depth_change is not None and abs(depth_change)>=.3 else 0)) if fresh and p['status']=='LIVE' else 0
    ask=(1-no[0] if side=='UP' else 1-yes[0]) if bookgood and side else None
    mult=1/ask if ask and ask>0 else None
    locked=s.get('locked_direction');outlook='WAIT'
    if fresh and p['status']=='LIVE':
        if locked and side and side!=locked and len(evidence)>=2:outlook=side+' REVERSAL BUILDING'
        elif locked and side and side!=locked:outlook=locked+' WEAKENING'
        elif locked:outlook=locked+' HOLDING'
    strength='ALERT' if score>=85 and bookgood and len(evidence)>=2 else 'BUILDING' if score>=50 else 'QUIET'
    large=[]
    if len(rows)>=30:
        sizes=[r['size'] for r in rows];med=statistics.median(sizes);mad=statistics.median(abs(x-med) for x in sizes)
        large=[{'ts':r['ts'],'size_btc':r['size'],'aggressor':'BUY' if r.get('side')=='sell' else 'SELL'} for r in rows[-100:] if r.get('side') in ('buy','sell') and r['size']>max(med*10,med+8*mad)]
    return {'observed':now,'status':'LIVE' if fresh else 'STALE','ticker':s['market']['ticker'],'depth':depth,'pressure':p,'pressure_long':long,'outlook':{'state':outlook,'side':side,'reason':'; '.join(evidence) or 'Waiting for continuous, agreeing evidence','invalidates':'Pressure returns to neutral or source becomes stale','remaining':s['market']['closed']-now},'flip':{'state':strength,'side':side,'score':score,'score_definition':'Heuristic signal strength; NOT probability','trend':score-(previous.get('flip',{}).get('score',score) if previous else score),'ask':ask,'gross_settlement_multiplier':mult,'cashout_multiplier':None,'book_verified':bookgood,'spread':b.spread if b else None,'evidence':evidence,'remaining':s['market']['closed']-now},'extreme':{'state':'ALERT' if fresh and p['status']=='LIVE' and intensity is not None and intensity>=4 else 'BUILDING' if fresh and intensity is not None and intensity>=2 else 'QUIET','side':side,'intensity_z':intensity if fresh else None,'definition':'5s return / recent per-trade volatility × sqrt(trade count); experimental anomaly, not liquidation proof','telegram':False,'volume_multiple':p['volume']/(long['volume']/4) if long['status']=='LIVE' and long['volume']>0 else None,'depth_change':depth_change},'whale':{'large_trades':large[-5:],'classification':'Unusually large observed prints, not identified whales','liquidity_change':depth_change,'microprice_yes':micro,'kalshi_imbalance':b.imbalance if bookgood else None,'liquidations':{'status':'UNAVAILABLE','reason':'No licensed/verified futures liquidation feed configured; Coinbase spot prints are not liquidations'},'open_interest':None,'funding':None},'cusum':cusum(changes),'regime':'HIGH VOLATILITY' if intensity is not None and intensity>=4 else 'DIRECTIONAL PRESSURE' if p['buy_share'] is not None and abs(p['buy_share']-.5)>=.2 else 'CHOPPY / UNCONFIRMED'}


def cusum(changes):
    if len(changes)<30:return {'state':'INSUFFICIENT DATA'}
    sd=statistics.pstdev(changes[:-10]);up=down=0
    if not sd:return {'state':'LOW VOLATILITY'}
    for x in changes[-10:]:up=max(0,up+x/sd-.5);down=min(0,down+x/sd+.5)
    return {'state':'UP SHIFT' if up>=5 else 'DOWN SHIFT' if down<=-5 else 'NO SHIFT','up':up,'down':down,'threshold':5,'status':'UNVALIDATED CUSUM context'}
