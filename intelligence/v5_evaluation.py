"""Auditable same-market comparisons and label-availability-safe walk-forward research."""
from datetime import datetime
from .storage import loads,dumps,ET,window_start
from .models import metrics,calibrated_fit,score

FEATURES=('distance','remaining','sigma','momentum','acceleration','trend','flow','failed_breakout','failed_breakdown','rsi','quote_age')

def records(db,selection='all',now=None):
    import time
    now=time.time() if now is None else now
    rows=[]
    for r in db.execute("SELECT v.*,m.result,m.settled_at,m.closed,l.p_up baseline,l.observed baseline_observed,w.p_up v4,w.observed v4_observed FROM v5_checkpoints v JOIN intel_markets m USING(ticker) LEFT JOIN intel_locks l ON l.ticker=v.ticker AND l.state='LOCKED' LEFT JOIN v4_challengers w ON w.ticker=v.ticker WHERE v.state='FORECAST' AND m.result IN ('yes','no') AND m.closed<=? AND v.scheduled>=? ORDER BY v.scheduled DESC LIMIT 10000",(now,window_start(selection,now))):
        p=loads(r['payload']);f=p['features'];market=p.get('market_comparison') or {}
        rows.append({**dict(r),'p':p['p_up'],'y':int(r['result']=='yes'),'f':f,'regime':p['regime'],'conviction':p['conviction'],'market_p':market.get('p_up'),'x':[float(f.get(k) or 0) for k in FEATURES],'payload':p})
    return list(reversed(rows))

def paired(rows,other):
    # Initial baseline/shadow comparison only: same ticker and decision timestamps within 1s.
    cohort=[r for r in rows if r['checkpoint']==60 and r.get(other) is not None and r.get(other+'_observed') is not None and abs(r[other+'_observed']-r['observed'])<=1]
    return {'n':len(cohort),'v5':metrics([r['p'] for r in cohort],[r['y'] for r in cohort]),other:metrics([r[other] for r in cohort],[r['y'] for r in cohort]),'v5_only_wins':sum((r['p']>=.5)==bool(r['y']) and (r[other]>=.5)!=bool(r['y']) for r in cohort),'other_only_wins':sum((r['p']>=.5)!=bool(r['y']) and (r[other]>=.5)==bool(r['y']) for r in cohort),'rule':'Same ticker, +1m forecasts within one second; unmatched observations excluded'}

def threshold_study(rows):
    rows=sorted(rows,key=lambda r:r['scheduled']);n=len(rows)
    if n<100:return {'status':'INSUFFICIENT TIME-SEPARATED DATA','n':n,'required':100,'production_changed':False}
    # Choose on earlier settled labels, evaluate once on untouched later 40%.
    cut=int(n*.6);test=rows[cut:];train=[r for r in rows[:cut] if r['settled_at'] is not None and r['settled_at']<test[0]['scheduled']]
    candidates=[]
    for t in (.5,.55,.6,.65,.7,.75):
        g=[r for r in train if max(r['p'],1-r['p'])>=t]
        if len(g)>=30:candidates.append((metrics([r['p'] for r in g],[r['y'] for r in g])['accuracy'], -t,t))
    if not candidates:return {'status':'INSUFFICIENT TRAINING COVERAGE','n':n,'production_changed':False}
    chosen=max(candidates)[2];kept=[r for r in test if max(r['p'],1-r['p'])>=chosen]
    return {'status':'EXPLORATORY HOLDOUT — not proof of improvement','chosen_threshold':chosen,'training_n':len(train),'test_n':len(test),'retained':len(kept),'test_coverage':len(kept)/len(test),'filtered':metrics([r['p'] for r in kept],[r['y'] for r in kept]),'unfiltered':metrics([r['p'] for r in test],[r['y'] for r in test]),'production_changed':False}

def report(db,selection='all',now=None):
    rows=records(db,selection,now);groups=[]
    for c in (60,180,300,600):
        cohort=[r for r in rows if r['checkpoint']==c]
        for field,fn in [('direction',lambda r:r['payload']['direction']),('regime',lambda r:r['regime']),('conviction',lambda r:r['conviction']),('hour_ET',lambda r:str(datetime.fromtimestamp(r['observed'],ET).hour)),('weekday_ET',lambda r:datetime.fromtimestamp(r['observed'],ET).strftime('%A')),('distance_bps',lambda r:'<5' if abs(r['f']['distance'])*10000<5 else '5–15' if abs(r['f']['distance'])*10000<15 else '15+'),('momentum',lambda r:'UP' if r['f']['momentum']>0 else 'DOWN'),('source',lambda r:r['payload']['source']),('volatility_1m',lambda r:'<0.05%' if r['f']['sigma']<.0005 else '0.05–0.15%' if r['f']['sigma']<.0015 else '0.15%+'),('quote_age_seconds',lambda r:'<1' if r['f']['quote_age']<1 else '1–2' if r['f']['quote_age']<=2 else '2–3')]:
            labels=sorted({fn(r) for r in cohort})
            for label in labels:
                g=[r for r in cohort if fn(r)==label];groups.append({'checkpoint':c,'dimension':field,'value':label,**metrics([r['p'] for r in g],[r['y'] for r in g])})
    return {'scope':selection,'research_limit':'most recent 10000 settled checkpoint records within range; lifetime scoreboard is not capped','baseline':paired(rows,'baseline'),'v4_shadow':paired(rows,'v4'),'market_favorite_by_checkpoint':[{ 'checkpoint':c,'v5':metrics([r['p'] for r in rows if r['checkpoint']==c and r['market_p'] is not None],[r['y'] for r in rows if r['checkpoint']==c and r['market_p'] is not None]),'market':metrics([r['market_p'] for r in rows if r['checkpoint']==c and r['market_p'] is not None],[r['y'] for r in rows if r['checkpoint']==c and r['market_p'] is not None])} for c in (60,180,300,600)],'loss_patterns':groups,'thresholds':{str(c):threshold_study([r for r in rows if r['checkpoint']==c]) for c in (60,180,300,600)},'interpretation':'Exploratory strata, not causal proof. Small samples and multiple comparisons can mislead. No accuracy target is guaranteed. Accuracy is separate from after-cost paper P&L.'}

def train(db,now):
    rows=records(db,now=now);folds=[];forecasts=[];artifacts={}
    for c in (60,180,300,600):
        cohort=[r for r in rows if r['checkpoint']==c and r['settled_at'] is not None]
        # Bounded recent data, no mixing checkpoints from the same market across folds.
        cohort=cohort[-500:]
        for i in range(80,len(cohort)-19,20):
            validation=cohort[i-20:i];test=cohort[i:i+20]
            training=[r for r in cohort[:i-20] if r['settled_at']<validation[0]['scheduled']]
            if len(training)<40 or max(r['settled_at'] for r in validation)>=test[0]['scheduled']:continue
            model=calibrated_fit(training,validation,1)
            ps=[score(model,r['x']) for r in test];ys=[r['y'] for r in test]
            # Actual no-flow ablation: fit and test on identical chronological cohorts.
            noflow=lambda rs:[{**r,'x':r['x'][:6]+r['x'][7:]} for r in rs]
            ablated=calibrated_fit(noflow(training),noflow(validation),1)
            ap=[score(ablated,r['x']) for r in noflow(test)]
            folds.append({'checkpoint':c,'train_n':len(training),'validation_n':len(validation),'test_n':len(test),'train_label_max':max(r['settled_at'] for r in training),'validation_start':validation[0]['scheduled'],'validation_label_max':max(r['settled_at'] for r in validation),'test_start':test[0]['scheduled'],'candidate':metrics(ps,ys),'fixed_v5':metrics([r['p'] for r in test],ys),'without_flow':metrics(ap,ys)})
            forecasts.extend({'ticker':r['ticker'],'checkpoint':c,'p':p,'y':r['y'],'scheduled':r['scheduled']} for r,p in zip(test,ps))
            artifacts[str(c)]=model
    out={'status':'SHADOW WALK-FORWARD EVALUATED' if folds else 'INSUFFICIENT TIME-SEPARATED FORWARD DATA','feature_names':FEATURES,'folds':folds,'candidate':metrics([r['p'] for r in forecasts],[r['y'] for r in forecasts]),'artifacts':artifacts,'automatic_promotion':False,'trained_at':now,'required_per_checkpoint':100}
    with db:db.execute('INSERT OR REPLACE INTO v5_evaluations VALUES(?,?)',(now,dumps(out)))
    return out
