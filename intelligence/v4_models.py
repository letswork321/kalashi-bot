"""Same-market immutable Gaussian challenger; actual chronological boosted comparison."""
import math,statistics
from .storage import dumps,loads

VERSION='strike-vol-gaussian-shadow-v4-1'


def lock_shadow(db,s,ticks=()):
    now=s['now'];ticker=s['market']['ticker']
    lock=db.execute("SELECT * FROM intel_locks WHERE ticker=? AND state='LOCKED'",(ticker,)).fetchone()
    if not lock or now-lock['observed']>1 or now<lock['observed']:return
    rows=s.get('candles1',[]);close=[r['close'] for r in sorted(rows,key=lambda r:r['ts']) if r['ts']+60<=now]
    returns=[math.log(b/a) for a,b in zip(close,close[1:]) if a>0 and b>0]
    sigma=statistics.pstdev(returns[-60:]) if len(returns)>=60 else None
    z=None;p=None;reason='INSUFFICIENT DATA';f={}
    if sigma and sigma>0 and s['price']>0 and s['market']['strike']>0:
        z=math.log(s['price']/s['market']['strike'])/(sigma*math.sqrt(max(1,(s['market']['closed']-now)/60)))
        p=max(.001,min(.999,.5*(1+math.erf(z/math.sqrt(2)))));reason='UNVALIDATED zero-drift spot approximation; not BRTI averaging or calibrated settlement model'
        from .v4_analysis import pressure
        flow=pressure(ticks,now,15);features=(s.get('baseline') or {}).get('features',{})
        f={'z':z,'sigma':sigma,'momentum':sum(returns[-5:]),'acceleration':sum(returns[-2:])-sum(returns[-4:-2]),'market_p':(s['book'].yes[0][0]+1-s['book'].no[0][0])/2,'imbalance':s['book'].imbalance,'pressure':flow['buy_share'],'rsi':features.get('rsi14'),'distance':s['price']/s['market']['strike']-1,'remaining':s['market']['closed']-now}
        from .indicators import ema,rsi
        f.update(ema9_gap=(close[-1]-ema(close,9)[-1])/close[-1],ema21_gap=(close[-1]-ema(close,21)[-1])/close[-1],ema50_gap=(close[-1]-ema(close,50)[-1])/close[-1],rsi=rsi(close,14)/100,macd=(ema(close,12)[-1]-ema(close,26)[-1])/close[-1],cvd=flow['cvd'])
        live=[r for r in ticks if int(now//60)*60<=r['ts']<=now]
        if live:
            prices=[r['price'] for r in live];span=max(prices)-min(prices)
            f.update(body=(prices[-1]-prices[0])/prices[0],upper_wick=(max(prices)-max(prices[0],prices[-1]))/span if span else 0,lower_wick=(min(prices[0],prices[-1])-min(prices))/span if span else 0)

    with db:db.execute('INSERT OR IGNORE INTO v4_challengers VALUES(?,?,?,?,?,?,?)',(ticker,now,VERSION,p,dumps(f),'SHADOW' if p is not None else 'ABSTAIN',reason))


def comparison(db):
    rows=db.execute("SELECT v.*,l.p_up baseline,l.direction,l.result,m.settled_at,m.closed FROM v4_challengers v JOIN intel_locks l USING(ticker) JOIN intel_markets m USING(ticker) ORDER BY v.observed").fetchall()
    out=[]
    for label in ('V3 baseline','V4 Gaussian SHADOW'):
        data=[r for r in rows if r['result'] in ('yes','no') and r['p_up'] is not None]
        preds=[(r['baseline'] if label=='V3 baseline' else r['p_up'],int(r['result']=='yes')) for r in data]
        out.append({'model':label,'n':len(preds),'abstentions':sum(r['p_up'] is None for r in rows) if label!='V3 baseline' else 0,'wins':sum((p>=.5)==bool(y) for p,y in preds),'brier':statistics.mean((p-y)**2 for p,y in preds) if preds else None,'log_loss':statistics.mean(-y*math.log(max(.001,p))-(1-y)*math.log(max(.001,1-p)) for p,y in preds) if preds else None,'calibration':[{'bin':i,'n':len(g),'mean_p':statistics.mean(p for p,y in g) if g else None,'observed':statistics.mean(y for p,y in g) if g else None} for i in range(5) for g in [[(p,y) for p,y in preds if min(4,int(p*5))==i]]],'production':'UNCHANGED V3 BASELINE' if label=='V3 baseline' else 'SHADOW ONLY'})
    return {'same_forward_markets':len(rows),'models':out,'status':'No demonstrated improvement until sufficient chronological/forward evidence','promotion':'Never automatic'}


def retrain(db,now):
    from .boosted_models import evaluate
    rows=[]
    for r in db.execute("SELECT v.*,l.p_up baseline,l.result,m.closed,m.settled_at FROM v4_challengers v JOIN intel_locks l USING(ticker) JOIN intel_markets m USING(ticker) WHERE v.state='SHADOW' AND l.result IN ('yes','no') AND m.settled_at IS NOT NULL ORDER BY v.observed"):
        f=loads(r['features']);keys=('z','sigma','momentum','acceleration','market_p','imbalance','pressure','distance','remaining','ema9_gap','ema21_gap','ema50_gap','rsi','macd','cvd','body','upper_wick','lower_wick');x=[float(f.get(k) or 0) for k in keys]+[int(f.get(k) is None) for k in keys]
        rows.append({'ticker':r['ticker'],'scheduled':r['observed'],'closed':r['closed'],'settled_at':r['settled_at'],'x':x,'y':int(r['result']=='yes'),'p_up':r['baseline'],'market_p':f['market_p']})
    report=evaluate(rows)
    from .models import metrics
    report.setdefault('candidate',metrics([],[]));report.update(shadow_only=True,feature_version='v4-microstructure-1',real_forward_rows=len(rows))
    version='v4-boosted-'+str(int(now))
    with db:db.execute('INSERT OR IGNORE INTO v3_model_comparisons VALUES(?,?,?)',(version,now,dumps(report)))
    return report
