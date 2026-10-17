"""Small deterministic logistic candidates, validation calibration, expanding OOS folds.
No automatic promotion; baseline remains the operational directional estimator.
"""
import hashlib
import math
import statistics
from datetime import datetime
from .storage import ET,dumps,loads

FEATURES=('distance','minutes','volatility','momentum','acceleration','ema_gap','rsi','volume_ratio','market_p','imbalance','tick_available')

def features(snapshot):
    b=snapshot.get('baseline') or {};f=b.get('features') or {};p=snapshot.get('price');strike=snapshot.get('market',{}).get('strike')
    if not p or not strike or not b.get('features') or b.get('p_up') is None:return None
    ticks=snapshot.get('tick_metrics') or {}
    return {'distance':math.log(p/strike),'minutes':max(0,snapshot['market']['closed']-snapshot['now'])/60,'volatility':f.get('volatility_1m',0),'momentum':f.get('momentum_3m',0),'acceleration':ticks.get('acceleration',0),'ema_gap':(f.get('ema9',p)-f.get('ema21',p))/p,'rsi':f.get('rsi14',50)/100,'volume_ratio':min(10,f.get('volume_ratio',0)),'market_p':snapshot['book'].implied if snapshot.get('book') else .5,'imbalance':snapshot['book'].imbalance if snapshot.get('book') else 0,'tick_available':int(bool(ticks))}

def sigmoid(x):
    x=max(-35,min(35,x));return 1/(1+math.exp(-x))

def fit(xs,ys,penalty=1,epochs=350):
    n=len(xs);d=len(xs[0])
    means=[statistics.mean(r[j] for r in xs) for j in range(d)]
    scales=[max(statistics.pstdev(r[j] for r in xs),1e-6) for j in range(d)]
    z=[[max(-10,min(10,(r[j]-means[j])/scales[j])) for j in range(d)] for r in xs]
    w=[0.0]*d;intercept=math.log((sum(ys)+1)/(n-sum(ys)+1))
    for _ in range(epochs):
        errors=[sigmoid(intercept+sum(a*b for a,b in zip(w,r)))-y for r,y in zip(z,ys)]
        intercept-=.08*sum(errors)/n
        w=[v-.08*(sum(e*r[j] for e,r in zip(errors,z))/n+penalty*v/n) for j,v in enumerate(w)]
    return {'means':means,'scales':scales,'weights':w,'intercept':intercept}

def predict(model,x):
    z=[max(-10,min(10,(v-m)/sd)) for v,m,sd in zip(x,model['means'],model['scales'])]
    return max(.01,min(.99,sigmoid(model['intercept']+sum(a*b for a,b in zip(model['weights'],z)))))

def score(candidate,x):
    p=predict(candidate['base'],x)
    return predict(candidate['calibrator'],[math.log(p/(1-p))])

def metrics(probabilities,ys):
    n=len(ys)
    if not n:return {'n':0,'accuracy':None,'brier':None,'log_loss':None,'ece':None,'calibration':[]}
    bins=[]
    for i in range(10):
        pairs=[(p,y) for p,y in zip(probabilities,ys) if i/10<=p<(i+1)/10 or (i==9 and p==1)]
        if pairs:bins.append({'lower':i/10,'upper':(i+1)/10,'n':len(pairs),'mean_probability':statistics.mean(p for p,y in pairs),'up_frequency':statistics.mean(y for p,y in pairs)})
    return {'n':n,'accuracy':sum((p>=.5)==bool(y) for p,y in zip(probabilities,ys))/n,'brier':statistics.mean((p-y)**2 for p,y in zip(probabilities,ys)),'log_loss':-statistics.mean(y*math.log(max(1e-12,p))+(1-y)*math.log(max(1e-12,1-p)) for p,y in zip(probabilities,ys)),'ece':sum(b['n']*abs(b['mean_probability']-b['up_frequency']) for b in bins)/n,'calibration':bins}

def dataset(db):
    rows=db.execute("SELECT l.*,m.opened,m.closed,m.settled_at FROM intel_locks l JOIN intel_markets m USING(ticker) WHERE state='LOCKED' AND l.result IN ('yes','no') AND features IS NOT NULL ORDER BY scheduled").fetchall()
    result=[]
    for row in rows:
        r=dict(row);f=loads(r['features'])
        if not all(k in f and isinstance(f[k],(int,float)) and math.isfinite(f[k]) for k in FEATURES):continue
        r.update(x=[f[k] for k in FEATURES],y=int(r['result']=='yes'),market_p=f['market_p']);result.append(r)
    return result

def calibrated_fit(train,val,penalty):
    base=fit([r['x'] for r in train],[r['y'] for r in train],penalty)
    ps=[predict(base,r['x']) for r in val]
    calibrator=fit([[math.log(p/(1-p))] for p in ps],[r['y'] for r in val],penalty=1)
    return {'base':base,'calibrator':calibrator}

def walk_forward(rows):
    if len(rows)<100:return {'status':'INSUFFICIENT DATA','required':100,'available':len(rows),'folds':[],'predictions':[]}
    predictions=[];folds=[];last=None
    for test_start in range(80,len(rows)-19,20):
        train=rows[:test_start-20];val=rows[test_start-20:test_start];test=rows[test_start:test_start+20]
        # Labels must be officially available before validation/test decisions.
        train=[r for r in train if (r.get('settled_at') or r['closed'])<val[0]['scheduled']]
        if not train or max(r.get('settled_at') or r['closed'] for r in val)>=test[0]['scheduled']:continue
        candidates=[]
        for penalty in (.1,1,10):
            model=calibrated_fit(train,val,penalty)
            validation=metrics([score(model,r['x']) for r in val],[r['y'] for r in val])
            candidates.append((validation['brier'],penalty,model))
        _,penalty,model=min(candidates,key=lambda t:t[0]);last=(penalty,model)
        fold={'train_n':len(train),'validation_n':len(val),'test_n':len(test),'train_end':max(r['closed'] for r in train),'validation_start':val[0]['scheduled'],'validation_end':val[-1]['closed'],'test_start':test[0]['scheduled'],'test_end':test[-1]['closed'],'penalty':penalty,'test_tickers':[r['ticker'] for r in test]}
        folds.append(fold)
        for r in test:predictions.append({'ticker':r['ticker'],'p':score(model,r['x']),'baseline':r['p_up'],'market_p':r['market_p'],'y':r['y'],'regime':r['regime'],'scheduled':r['scheduled'],'entry_up':r['entry_up'],'entry_down':r['entry_down'],'fee_multiplier':r['fee_multiplier']})
    ps=[r['p'] for r in predictions];ys=[r['y'] for r in predictions]
    report={'status':'SHADOW EVALUATED' if predictions else 'INSUFFICIENT TIME-SEPARATED DATA','folds':folds,'predictions':predictions,'candidate':metrics(ps,ys),'baseline':metrics([r['baseline'] for r in predictions],ys),'market_implied':metrics([r['market_p'] for r in predictions],ys),'last_penalty':last[0] if last else None}
    report['by_regime']=group_scores(predictions,'regime')
    for r in predictions:r['weekday']=datetime.fromtimestamp(r['scheduled'],ET).strftime('%A')
    report['by_weekday']=group_scores(predictions,'weekday')
    from scanner import fee
    for model_name,field in [('candidate','p'),('baseline','baseline')]:
        pnl=[]
        for r in predictions:
            p=r[field];up=p>=.5;entry=r['entry_up'] if up else r['entry_down'];prob=p if up else 1-p
            if entry is not None and prob>=.6:
                f=fee(entry,1,.07,r['fee_multiplier'] or 1)
                if prob-entry-f>=.05:pnl.append(int(up==bool(r['y']))-entry-f)
        report[model_name]['quote_return_proxy']={'positions':len(pnl),'net':sum(pnl),'note':'On-time entry quote held to settlement, not delayed executed simulator fills'}
    return report

def group_scores(rows,key):
    out={}
    for value in sorted({str(r.get(key) or 'UNKNOWN') for r in rows}):
        group=[r for r in rows if str(r.get(key) or 'UNKNOWN')==value]
        out[value]=metrics([r['p'] for r in group],[r['y'] for r in group])
    return out

def retrain(db,now):
    all_rows=[r for r in dataset(db) if r['closed']<=now and (r.get('settled_at') or r['closed'])<=now]
    rows=all_rows[-240:]
    report=walk_forward(rows)
    if report.get('last_penalty') is None:return report
    # Final shadow artifact uses the past only; the latest validation segment is
    # reserved for calibration. It never replaces the baseline automatically.
    train=rows[:-20];val=rows[-20:]
    train=[r for r in train if (r.get('settled_at') or r['closed'])<val[0]['scheduled']]
    artifact=calibrated_fit(train,val,report['last_penalty'])
    artifact.update(feature_names=FEATURES,training_tickers=[r['ticker'] for r in train],calibration_tickers=[r['ticker'] for r in val],train_end=max(r['closed'] for r in rows),created=now)
    version='logistic-shadow-'+hashlib.sha256(dumps({'rows':[r['ticker'] for r in rows],'model':artifact}).encode()).hexdigest()[:12]
    report['version']=version;report['training_markets']=len(rows);report['dataset_total']=len(all_rows);report['evaluation_window']='Most recent 240 settled locked markets maximum; expanding folds inside this bounded window';report['auto_promoted']=False
    oos=report['candidate'];base=report['baseline']
    report['validated_for_estimation']=len(rows)>=200 and oos['n']>=60 and oos['ece']<=.1 and oos['brier']<=base['brier'] and oos['log_loss']<=base['log_loss']
    with db:db.execute('INSERT OR IGNORE INTO intel_models VALUES(?,?,?,?,?)',(version,now,artifact['train_end'],dumps(artifact),dumps(report)))
    return report

def shadow(db,s):
    if not 0<=s['now']-s.get('quote_ts',0)<=3 or not s.get('baseline'):
        return {'validated':False,'status':'INSUFFICIENT DATA','reason':'Current verified feature vector unavailable'}
    row=db.execute('SELECT * FROM intel_models WHERE created<=? AND train_end<? ORDER BY created DESC LIMIT 1',(s['now'],s['market']['opened'])).fetchone()
    if not row:return {'validated':False,'sample_size':len(dataset(db)),'status':'INSUFFICIENT DATA','required':100}
    f=features(s)
    if not f:return {'validated':False,'status':'INSUFFICIENT DATA'}
    artifact=loads(row['artifact']);report=loads(row['report'])
    vector=[f[k] for k in artifact['feature_names']]
    max_z=max(abs((v-m)/sd) for v,m,sd in zip(vector,artifact['base']['means'],artifact['base']['scales']))
    return {'out_of_distribution':max_z>5,'validated':report['validated_for_estimation'] and max_z<=5,'sample_size':report['candidate']['n'],'probability':score(artifact,[f[k] for k in artifact['feature_names']]),'version':row['version'],'calibration':report['candidate'],'status':'SHADOW ONLY'}

def evaluation(db):
    row=db.execute('SELECT * FROM intel_models ORDER BY created DESC LIMIT 1').fetchone()
    history=[dict(r) for r in db.execute('SELECT version,created,train_end FROM intel_models ORDER BY created DESC LIMIT 20')]
    shadow_rows=db.execute("SELECT p_up,result FROM intel_shadow WHERE result IN ('yes','no')").fetchall()
    return {'latest':loads(row['report']) if row else {'status':'INSUFFICIENT DATA','available':len(dataset(db)),'required':100,'reason':'Needs on-time locked forecasts and official labels. Historical proxy prices cannot manufacture these features.'},'history':history,'live_shadow':metrics([r['p_up'] for r in shadow_rows],[int(r['result']=='yes') for r in shadow_rows]),'baseline_preserved':True,'auto_promotion':False}
