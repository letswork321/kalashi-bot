"""Regime behavior and unseen-evaluation boundaries, not profitability evidence."""
import copy,math,unittest
from unittest.mock import Mock
from test_v5 import args,candles,OPEN
import test_v5 as fixtures
from intelligence.v5_engine import forecast
from intelligence.v5_regime import classify
from intelligence.v5_adaptive_research import monitoring,regime_comparison,difficult_vs_trending
from intelligence.storage import loads


def path(kind,now=OPEN+60):
 rows=candles(now,n=100);p=100
 for i,r in enumerate(rows):
  move=(.001 if i%2 else -.001) if kind=='chop' else .0003*(1+.1*math.sin(i))
  if kind=='highvol' and i>=90:move=(.004 if i%2 else -.004)
  close=p*math.exp(move);r.update(open=p,close=close,high=max(p,close)*1.00005,low=min(p,close)*.99995,volume=100 if not(kind=='lowvolume' and i>=95) else 10);p=close
 return rows

class RegimeTests(unittest.TestCase):
 def test_clean_trend_efficiency_and_direction(self):
  r=classify(path('trend'),OPEN+60);self.assertEqual(r['primary'],'UP TREND');self.assertGreater(r['efficiency20'],.9)
 def test_chop_reversal_heavy_measured_not_no_call(self):
  a=args();a['candles1']=path('chop');r=forecast(**a);self.assertIn('CHOPPY',r['regime_details']['flags']);self.assertIn('REVERSAL HEAVY',r['regime_details']['flags']);self.assertEqual(r['conviction'],'LOW');self.assertIn(r['direction'],('UP','DOWN'));self.assertGreater(r['features']['reversal_frequency20'],.9)
 def test_relative_high_volatility_and_low_volume(self):
  self.assertIn('HIGH VOLATILITY',classify(path('highvol'),OPEN+60)['flags']);self.assertIn('LOW VOLUME',classify(path('lowvolume'),OPEN+60)['flags'])
 def test_future_candle_cannot_change_regime(self):
  rows=path('trend');a=classify(rows,OPEN+60);rows.append(dict(ts=OPEN+60,open=100,close=1,low=1,high=100,volume=1e9));self.assertEqual(a,classify(rows,OPEN+60))
 def test_transition_detected_from_prior_and_current_efficiency(self):
  rows=path('chop');p=rows[-6]['close']
  for r in rows[-5:]:r.update(open=p,close=p*1.001,high=p*1.0011,low=p*.9999);p=r['close']
  self.assertIn('TRANSITIONING',classify(rows,OPEN+60)['flags'])
 def test_fresh_btc_liquidity_and_stale_rejection(self):
  l={'status':'OBSERVED REST SNAPSHOT','received':OPEN+60,'latency':.1,'depth_ratio':.4,'imbalance':.8,'spread_bps':1}
  r=classify(path('trend'),OPEN+60,l);self.assertEqual(r['liquidity']['state'],'THIN RELATIVE DEPTH');self.assertTrue(r['low_conviction'])
  l['received']-=4;self.assertEqual(classify(path('trend'),OPEN+60,l)['liquidity']['state'],'UNAVAILABLE')
 def test_model_contains_both_hypotheses_and_regime_routing(self):
  a=args();a['candles1']=path('chop');c=forecast(**a);a['candles1']=path('trend');t=forecast(**a)
  self.assertLess(c['regime_details']['continuation_weight'],t['regime_details']['continuation_weight']);self.assertIn('mean_reversion',c['strategy_estimates']);self.assertNotEqual(c['strategy_estimates']['mean_reversion'],c['strategy_estimates']['momentum_continuation'])
 def test_btc_depth_influences_forecast_without_contract_inputs(self):
  a=args();p=forecast(**a);a['btc_liquidity']={'status':'OBSERVED REST SNAPSHOT','received':OPEN+60,'latency':.1,'depth_ratio':1,'imbalance':1,'spread_bps':1};q=forecast(**a);self.assertGreater(q['p_up'],p['p_up'])
 def test_volume_price_divergence_and_failed_continuation(self):
  rows=path('trend')
  for r in rows[-5:]:r['volume']=10
  self.assertTrue(classify(rows,OPEN+60)['volume_price_divergence'])
  last=rows[-1];last.update(close=last['open']*.995,low=last['open']*.994);r=classify(rows,OPEN+60);self.assertTrue(r['failed_continuation']);self.assertTrue(r['sudden_reversal'])
 def test_false_breakout_warning_uses_completed_highs(self):
  rows=path('chop');r=rows[-1];r['high']=max(x['high'] for x in rows[:-1])*1.01
  self.assertTrue(classify(rows,OPEN+60)['false_breakout'])


def observed(n=160):
 out=[]
 for i in range(n):
  p={'version':'test-v5','regime_details':{'low_conviction':True,'primary':'REVERSAL HEAVY'},'strategy_estimates':{'momentum_continuation':.7,'mean_reversion':.3,'neutral_strike_volatility':.5,'adaptive_fixed':.4}}
  out.append({'checkpoint':60,'scheduled':i*900,'settled_at':i*900+850,'p':.4,'y':0 if i<100 else 1,'regime':'REVERSAL HEAVY','f':{'sigma':.001,'momentum':.001,'distance':.001,'reversal_frequency20':.8,'efficiency20':.1},'payload':p})
 return out

class AdaptiveResearchTests(unittest.TestCase):
 def test_insufficient_data_never_claims_improvement(self):
  r=regime_comparison(observed(40));self.assertEqual(r[0]['status'],'INSUFFICIENT UNSEEN SETTLED ROUNDS');self.assertEqual(monitoring(observed(40))[0]['status'],'WARMING UP')
 def test_strategy_selection_does_not_see_test_labels(self):
  rows=observed(100);a=regime_comparison(rows);changed=copy.deepcopy(rows)
  for r in changed[60:]:r['y']=1-r['y']
  b=regime_comparison(changed);self.assertEqual(a[0]['selected_on_prior_labels'],b[0]['selected_on_prior_labels']);self.assertEqual(a[0]['test_n'],40);self.assertFalse(a[0]['promotion'])
 def test_late_official_labels_excluded_from_strategy_selection(self):
  rows=observed(100)
  for r in rows[:60]:r['settled_at']=rows[-1]['scheduled']+1000
  r=regime_comparison(rows)[0];self.assertEqual(r['training_n'],0);self.assertIsNone(r['selected_on_prior_labels'])
 def test_calibration_drift_warns_without_model_change(self):
  rows=observed();r=monitoring(rows)[0];self.assertEqual(r['reference_n'],100);self.assertEqual(r['recent_n'],50);self.assertEqual(r['status'],'REVIEW');self.assertFalse(r['automatic_update'])
 def test_distinct_versions_and_checkpoints_not_pooled(self):
  rows=observed(160)
  for r in rows[80:]:r['payload']={**r['payload'],'version':'new-version'}
  r=monitoring(rows);self.assertTrue(all(x['status']=='WARMING UP' for x in r));self.assertEqual(len(r),2)
 def test_difficult_loss_context_excludes_unrecorded_old_regimes(self):
  rows=observed(40);rows[-1]['payload'].pop('regime_details');r=difficult_vs_trending(rows)[0];self.assertEqual(r['n'],39);self.assertAlmostEqual(r['mean_reversal_frequency'],.8)

class TelegramRegimeTests(unittest.TestCase):
 setUp=fixtures.DatabaseTests.setUp
 tearDown=fixtures.DatabaseTests.tearDown
 cache=fixtures.DatabaseTests.cache
 tick=fixtures.DatabaseTests.tick
 def test_checkpoint_alert_has_regime_and_reversal_risk(self):
  self.tick(OPEN+60);message=self.db.execute('SELECT message FROM v5_outbox').fetchone()[0];self.assertIn('Regime:',message);self.assertIn('reversal risk:',message);self.assertIn('UNCALIBRATED',message)
 def test_btc_liquidity_adapter_does_not_consume_kalshi_odds(self):
  http=Mock();http.get.return_value={'bids':[['100','2','1']],'asks':[['100.01','3','1']],'sequence':42}
  with __import__('unittest').mock.patch.dict(__import__('os').environ,{'BTC_PRO_V5':'true'}):self.scheduler.btcliquidity(http)
  self.assertEqual(http.get.call_args.args[1],'/products/BTC-USD/book');self.assertEqual(self.scheduler.cache['btcliquidity']['status'],'OBSERVED REST SNAPSHOT');self.assertIsNone(self.scheduler.cache['btcliquidity']['depth_ratio'])

class LiveContextTests(unittest.TestCase):
 setUp=fixtures.DatabaseTests.setUp
 tearDown=fixtures.DatabaseTests.tearDown
 cache=fixtures.DatabaseTests.cache
 def test_continuous_context_cannot_create_checkpoint_or_alert(self):
  from unittest.mock import patch
  stop=Mock();stop.is_set.side_effect=[False,True];self.worker.stop=stop
  with patch('intelligence.v5_runtime.time.time',return_value=OPEN+60):self.worker.observe()
  self.assertEqual(self.db.execute('SELECT count(*) FROM v5_checkpoints').fetchone()[0],0);self.assertEqual(self.db.execute('SELECT count(*) FROM v5_outbox').fetchone()[0],0)
  row=self.db.execute("SELECT payload FROM v5_health WHERE name='live_context'").fetchone();self.assertTrue(loads(row['payload'])['ok'])
 def test_context_freshness_checks_original_event_not_only_write_time(self):
  from intelligence.v5_dashboard import snapshot
  from intelligence.storage import dumps
  self.db.execute("INSERT INTO v5_health VALUES('live_context',?,?)",(OPEN+60,dumps({'ok':True,'reference_ts':OPEN+50,'regime':{'primary':'UP TREND'}})))
  self.assertFalse(snapshot(self.db,OPEN+60)['live_context']['fresh'])
