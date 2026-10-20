"""Regime-conditioned OOS research and conservative monitoring, never automatic promotion."""
import statistics
from .models import metrics

STRATEGIES=('momentum_continuation','mean_reversion','neutral_strike_volatility','adaptive_fixed')

def monitoring(rows):
    out=[]
    # Never pool versions/checkpoints as though all four forecasts were independent markets.
    for checkpoint in (60,180,300,600):
        for version in sorted({r['payload']['version'] for r in rows if r['checkpoint']==checkpoint}):
            group=[r for r in rows if r['checkpoint']==checkpoint and r['payload']['version']==version]
            item={'checkpoint':checkpoint,'version':version,'n':len(group),'automatic_update':False}
            if len(group)<150:item.update(status='WARMING UP',required=150);out.append(item);continue
            reference=group[-150:-50];recent=group[-50:]
            before=metrics([r['p'] for r in reference],[r['y'] for r in reference]);after=metrics([r['p'] for r in recent],[r['y'] for r in recent])
            shifts={}
            for f in ('distance','sigma','momentum','reversal_frequency20','efficiency20'):
                a=[r['f'][f] for r in reference if r['f'].get(f) is not None];b=[r['f'][f] for r in recent if r['f'].get(f) is not None]
                if len(a)>=30 and len(b)>=30:
                    sd=statistics.pstdev(a);shifts[f]=(statistics.mean(b)-statistics.mean(a))/sd if sd>0 else None
            warnings=[]
            if after['brier']>before['brier']+.05:warnings.append('Recent Brier score worsened by >0.05')
            if after['ece']>.10:warnings.append('Recent estimated calibration error >0.10; uncalibrated probabilities need review')
            if any(v is not None and abs(v)>2 for v in shifts.values()):warnings.append('Feature mean shifted >2 reference standard deviations')
            item.update(status='REVIEW' if warnings else 'NO MONITORING THRESHOLD BREACH',reference_n=100,recent_n=50,reference=before,recent=after,feature_mean_shifts=shifts,warnings=warnings,action='Research review only; never switch models after a few losses')
            out.append(item)
    return out

def regime_comparison(rows):
    comparisons=[]
    for c in (60,180,300,600):
        cohort=[r for r in rows if r['checkpoint']==c and r['payload'].get('strategy_estimates')]
        # Only a previous settled period selects a strategy; test outcomes are untouched.
        if len(cohort)<100:
            comparisons.append({'checkpoint':c,'status':'INSUFFICIENT UNSEEN SETTLED ROUNDS','n':len(cohort),'required':100});continue
        split=int(len(cohort)*.6);test=cohort[split:];training=[r for r in cohort[:split] if r['settled_at'] is not None and r['settled_at']<test[0]['scheduled']]
        for regime in sorted({r['regime'] for r in cohort}):
            a=[r for r in training if r['regime']==regime];b=[r for r in test if r['regime']==regime]
            reports={name:metrics([r['payload']['strategy_estimates'][name] for r in b],[r['y'] for r in b]) for name in STRATEGIES}
            chosen=min(STRATEGIES,key=lambda name:metrics([r['payload']['strategy_estimates'][name] for r in a],[r['y'] for r in a])['brier']) if len(a)>=30 else None
            comparisons.append({'checkpoint':c,'regime':regime,'training_n':len(a),'test_n':len(b),'selected_on_prior_labels':chosen,'test_metrics':reports,'status':'EXPLORATORY HOLDOUT' if chosen and len(b)>=20 else 'INSUFFICIENT REGIME-SPECIFIC SAMPLE','promotion':False})
    return comparisons


def difficult_vs_trending(rows):
    result=[]
    for c in (60,180,300,600):
        for label in ('DIFFICULT','TRENDING','OTHER'):
            def condition(r):
                d=r['payload'].get('regime_details')
                return None if not d else 'DIFFICULT' if d['low_conviction'] else 'TRENDING' if 'TREND' in d['primary'] else 'OTHER'
            group=[r for r in rows if r['checkpoint']==c and condition(r)==label]
            losses=[r for r in group if (r['p']>=.5)!=bool(r['y'])]
            avg=lambda g,k:statistics.mean(r['f'][k] for r in g if r['f'].get(k) is not None) if any(r['f'].get(k) is not None for r in g) else None
            result.append({'checkpoint':c,'condition':label,**metrics([r['p'] for r in group],[r['y'] for r in group]),'mean_reversal_frequency':avg(group,'reversal_frequency20'),'loss_reversal_frequency':avg(losses,'reversal_frequency20'),'mean_volatility':avg(group,'sigma'),'loss_volatility':avg(losses,'sigma'),'interpretation':'Association in stored decision-time data; missing older regime features are excluded, never reconstructed.'})
    return result
