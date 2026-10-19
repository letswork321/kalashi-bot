"""Deterministic logistic gradient-boosted stumps, chronological SHADOW comparison.
No sklearn/Node runtime, no automatic model replacement, no shuffled labels.
"""
import hashlib
import math
import statistics
from .models import dataset,fit,predict,sigmoid,metrics
from .storage import dumps


def fit_boost(xs,ys,rounds=20,rate=.25):
    if not xs or len(xs)!=len(ys) or any(len(r)!=len(xs[0]) or any(not math.isfinite(v) for v in r) for r in xs) or any(y not in (0,1) for y in ys):raise ValueError('Finite equal-sized training rows and binary labels required')
    n=len(xs);base=math.log((sum(ys)+1)/(n-sum(ys)+1));scores=[base]*n;trees=[]
    thresholds={j:sorted({sorted(r[j] for r in xs)[int(q*(n-1))] for q in (.2,.4,.6,.8)}) for j in range(len(xs[0]))}
    for _ in range(rounds):
        residual=[y-sigmoid(f) for y,f in zip(ys,scores)];best=None
        for j,values in thresholds.items():
            for threshold in values:
                left=[v for r,v in zip(xs,residual) if r[j]<=threshold];right=[v for r,v in zip(xs,residual) if r[j]>threshold]
                if min(len(left),len(right))<5:continue
                a,b=statistics.mean(left),statistics.mean(right);loss=sum((v-a)**2 for v in left)+sum((v-b)**2 for v in right)
                item=(loss,j,threshold,a,b)
                if best is None or item<best:best=item
        if best is None:break
        _,j,t,a,b=best;tree={'feature':j,'threshold':t,'left':rate*a,'right':rate*b};trees.append(tree)
        scores=[f+(tree['left'] if r[j]<=t else tree['right']) for r,f in zip(xs,scores)]
    return {'base':base,'trees':trees,'rate':rate,'rounds':rounds}

def boost_predict(model,x):return sigmoid(model['base']+sum(t['left'] if x[t['feature']]<=t['threshold'] else t['right'] for t in model['trees']))

def evaluate(rows):
    if len(rows)<100:return {'status':'INSUFFICIENT DATA','required':100,'available':len(rows),'model':'Gradient-boosted stumps — SHADOW'}
    forecasts=[];folds=[]
    for start in range(80,len(rows)-19,20):
        train,val,test=rows[:start-20],rows[start-20:start],rows[start:start+20]
        train=[r for r in train if (r.get('settled_at') or r['closed'])<val[0]['scheduled']]
        if len(train)<40 or max(r.get('settled_at') or r['closed'] for r in val)>=test[0]['scheduled']:continue
        candidates=[]
        for rounds in (10,30):
            model=fit_boost([r['x'] for r in train],[r['y'] for r in train],rounds)
            ps=[boost_predict(model,r['x']) for r in val]
            calibrator=fit([[math.log(max(.001,p)/max(.001,1-p))] for p in ps],[r['y'] for r in val],epochs=200)
            def calibrated(r):
                p=boost_predict(model,r['x']);return predict(calibrator,[math.log(max(.001,p)/max(.001,1-p))])
            candidates.append((metrics([calibrated(r) for r in val],[r['y'] for r in val])['brier'],rounds,model,calibrator))
        _,rounds,model,cal=min(candidates,key=lambda x:(x[0],x[1]))
        for r in test:
            p=boost_predict(model,r['x']);p=predict(cal,[math.log(max(.001,p)/max(.001,1-p))]);forecasts.append({'ticker':r['ticker'],'scheduled':r['scheduled'],'p':p,'y':r['y'],'baseline':r['p_up'],'market_p':r['market_p']})
        folds.append({'train_end':max(r['closed'] for r in train),'validation_end':max(r['closed'] for r in val),'test_start':test[0]['scheduled'],'test_end':test[-1]['closed'],'test_tickers':[r['ticker'] for r in test],'rounds_chosen_on_validation':rounds,'artifact':model,'calibrator':cal})
    ys=[r['y'] for r in forecasts]
    return {'status':'SHADOW — NEVER PROMOTED' if forecasts else 'INSUFFICIENT TIME-SEPARATED DATA','model':'Logistic gradient-boosted decision stumps v1','available':len(rows),'candidate':metrics([r['p'] for r in forecasts],ys),'baseline':metrics([r['baseline'] for r in forecasts],ys),'market_implied':metrics([r['market_p'] for r in forecasts],ys),'folds':folds,'forecasts':forecasts,'scope':'Same immutable locked-market dataset; train-only split thresholds, validation-only rounds/calibration, disjoint chronological test blocks. Logistic comparison remains in existing evaluation center.'}

def retrain_comparison(db,now):
    rows=dataset(db)[-240:];identity=hashlib.sha256(dumps([(r['ticker'],r['observed'],r['result']) for r in rows]).encode()).hexdigest()[:16];version='boost-stumps-v1:'+identity
    if db.execute('SELECT 1 FROM v3_model_comparisons WHERE version=?',(version,)).fetchone():return
    report=evaluate(rows)
    with db:db.execute('INSERT INTO v3_model_comparisons VALUES(?,?,?)',(version,now,dumps(report)))
