import copy
import math
import tempfile
from pathlib import Path
import unittest
from intelligence.models import *
from intelligence.storage import migrate,register_market,lock_forecast
from intel_helpers import market

class ModelTests(unittest.TestCase):
    def rows(self,n=120):
        result=[]
        for i in range(n):
            t=1800000000+i*900;y=int(math.sin(i/3)>0);x=[math.sin(i/3),5,.001,.002,0,0,.5,1,.5,0]
            result.append({'ticker':'M'+str(i),'x':x,'y':y,'p_up':.55,'market_p':.5,'scheduled':t+60,'closed':t+900,'settled_at':t+901,'regime':'TREND' if i%2 else 'RANGE','entry_up':.52,'entry_down':.52,'fee_multiplier':1})
        return result
    def test_metrics_accuracy_brier_logloss_and_calibration(self):
        r=metrics([.8,.2],[1,0]);self.assertEqual(r['accuracy'],1);self.assertAlmostEqual(r['brier'],.04);self.assertAlmostEqual(r['log_loss'],-math.log(.8));self.assertEqual(sum(b['n'] for b in r['calibration']),2)
    def test_no_data_metrics_not_fake_zero_accuracy(self):
        self.assertIsNone(metrics([],[])['accuracy'])
    def test_logistic_actually_fits_data(self):
        xs=[[-2],[-1],[-.5],[.5],[1],[2]];ys=[0,0,0,1,1,1]
        model=fit(xs,ys);self.assertLess(predict(model,[-1]),.5);self.assertGreater(predict(model,[1]),.5)
    def test_training_normalizer_uses_training_rows_only(self):
        model=fit([[1],[2],[3]],[0,1,1]);self.assertEqual(model['means'],[2]);predict(model,[10000]);self.assertEqual(model['means'],[2])
    def test_sparse_samples_do_not_train(self):
        self.assertEqual(walk_forward(self.rows(50))['status'],'INSUFFICIENT DATA')
    def test_walk_forward_periods_are_disjoint_and_auditable(self):
        report=walk_forward(self.rows())
        self.assertEqual(report['candidate']['n'],40)
        tickers=[]
        for f in report['folds']:
            self.assertLess(f['train_end'],f['validation_start']);self.assertLess(f['validation_end'],f['test_start']);tickers+=f['test_tickers']
        self.assertEqual(len(tickers),len(set(tickers)))
    def test_future_test_labels_cannot_change_prior_forecast(self):
        rows=self.rows(100);first=walk_forward(rows)
        changed=copy.deepcopy(rows)
        for r in changed[80:]:r['y']=1-r['y']
        later=walk_forward(changed)
        self.assertEqual([r['p'] for r in first['predictions']],[r['p'] for r in later['predictions']])
    def test_late_labels_excluded_from_oos_fold(self):
        rows=self.rows(100)
        for r in rows[60:80]:r['settled_at']=rows[-1]['closed']+10000
        self.assertEqual(walk_forward(rows)['predictions'],[])
    def test_shadow_never_trains_from_synthetic_candle_labels(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=migrate(Path(tmp)/'test.sqlite3')
            try:
                r=retrain(db,1800200000);self.assertEqual(r['available'],0);self.assertEqual(db.execute('SELECT count(*) FROM intel_models').fetchone()[0],0)
            finally:db.close()

class PersistedTrainingTests(unittest.TestCase):
    def test_retraining_produces_real_versioned_shadow_artifact(self):
        import json
        from datetime import datetime,timezone
        from intelligence.models import FEATURES,shadow
        from intel_helpers import snapshot
        with tempfile.TemporaryDirectory() as tmp:
            db=migrate(Path(tmp)/'training.sqlite3')
            try:
                for i in range(100):
                    op=1800000000+i*900;m=market(op,'KXBTC15M-TRAIN-'+str(i));register_market(db,m,op)
                    y=int(math.sin(i/3)>0);x={k:0.1 for k in FEATURES};x['distance']=math.sin(i/3);x['market_p']=.5
                    p={'p_up':.55,'observed_at':op+60,'btc_timestamp':op+60,'model':'baseline'}
                    lock_forecast(db,m,p,op+60,x,'RANGE',{'UP':.52,'DOWN':.52})
                    m.update(result='yes' if y else 'no',status='finalized',settlement_ts=datetime.fromtimestamp(op+901,timezone.utc).isoformat());register_market(db,m,op+901)
                report=retrain(db,1800000000+100*900+2)
                self.assertEqual(report['candidate']['n'],20);self.assertFalse(report['auto_promoted']);self.assertFalse(report['validated_for_estimation'])
                stored=db.execute('SELECT * FROM intel_models').fetchone();self.assertIsNotNone(stored)
                artifact=json.loads(stored['artifact']);self.assertTrue(artifact['training_tickers']);self.assertTrue(artifact['calibration_tickers'])
                s=snapshot(1800000000+101*900+60);s['market']['opened']=1800000000+101*900
                candidate=shadow(db,s);self.assertIsNotNone(candidate.get('probability'));self.assertFalse(candidate['validated'])
            finally:db.close()
