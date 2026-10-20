"""Deterministic correctness/safety tests, never evidence of live profitability."""
import copy,math,os,sqlite3,tempfile,time,unittest
from pathlib import Path
from unittest.mock import Mock,patch
from datetime import datetime,timezone
from intelligence.v5_engine import forecast,VERSION
from intelligence.v5_storage import ensure,schedule,summary,metrics
from intelligence.v5_runtime import Runtime
from intelligence.v5_evaluation import report,threshold_study,train
from intelligence.v5_dashboard import snapshot
from intelligence.scheduler import ForecastScheduler
from intelligence.storage import migrate,register_market,dumps,loads
from intel_helpers import market
from scanner import Book

OPEN=1800000000

def candles(now,period=60,n=100):
 end=int(now//period)*period
 return [dict(ts=end-(n-i)*period,open=100+math.sin(i*.7)*.08,close=100+math.sin(i*.7)*.08+.01,low=99.8+math.sin(i*.7)*.08,high=100.2+math.sin(i*.7)*.08,volume=10+i%5) for i in range(n)]

def args(now=OPEN+60):
 return dict(now=now,opened=OPEN,closed=OPEN+900,strike=100,price=100.01,quote_ts=now-.1,candles1=candles(now),candles5=candles(now,300),candles15=candles(now,900))

def raw(rows):return [[r[k] for k in ('ts','low','high','open','close','volume')] for r in rows]

class EngineTests(unittest.TestCase):
 def test_new_version_and_no_odds_inputs(self):
  p=forecast(**args());self.assertEqual(p['version'],VERSION);self.assertFalse(p['calibrated']);self.assertIn(p['direction'],('UP','DOWN'))
  with self.assertRaises(TypeError):forecast(**args(),market_p=.9)
 def test_missing_optional_keeps_low_conviction_call(self):
  a=args();a.update(candles5=[],candles15=[]);p=forecast(**a);self.assertEqual(p['conviction'],'LOW');self.assertIsNotNone(p['p_up'])
 def test_stale_future_and_invalid_quotes_rejected(self):
  for key,value in [('quote_ts',OPEN+55),('quote_ts',OPEN+61),('price',float('nan')),('strike',0)]:
   a=args();a[key]=value
   with self.assertRaises(ValueError):forecast(**a)
 def test_future_candle_cannot_change_prediction(self):
  a=args();before=forecast(**a);a['candles1'].append(dict(ts=OPEN+60,open=100,close=200,high=200,low=100,volume=99999));self.assertEqual(before,forecast(**a))
 def test_missing_candle_or_stale_candles_rejected(self):
  a=args();a['candles1'].pop(-5)
  with self.assertRaises(ValueError):forecast(**a)
  a=args();a['candles1']=candles(OPEN-180)
  with self.assertRaises(ValueError):forecast(**a)
 def test_benchmark_verified_or_explicit_proxy(self):
  a=args();self.assertFalse(forecast(**a)['official_reference']);a['brti']={'status':'LIVE','event_ts':a['now']-.1,'price':100.02};p=forecast(**a);self.assertTrue(p['official_reference']);self.assertEqual(p['reference'],100.02)
  a['brti']['event_ts']-=10;self.assertFalse(forecast(**a)['official_reference'])
 def test_strike_distance_changes_independent_probability(self):
  a=args();a['price']=100.2;up=forecast(**a)['p_up'];a['price']=99.8;self.assertGreater(up,forecast(**a)['p_up'])
 def test_timeframe_indicators_and_levels_recorded(self):
  p=forecast(**args())
  for f in p['frames'].values():self.assertIn('rsi14',f);self.assertIn('macd',f);self.assertIn('support',f);self.assertIn('failed_breakout',f)
 def test_flow_continuity_required_and_influences_forecast(self):
  a=args();a['ticks']=[{'id':i,'ts':a['now']-60+i/10,'received':a['now']-60+i/10,'price':100,'size':1,'side':'sell','continuous':True} for i in range(601)];p=forecast(**a)
  for r in a['ticks']:r['side']='buy'
  q=forecast(**a);self.assertGreater(p['p_up'],q['p_up']);self.assertAlmostEqual(p['pressure60']['buy_share'],1)
  a['ticks'].pop(-15);self.assertIsNone(forecast(**a)['pressure60']['buy_share'])
 def test_flat_unusable_volatility_not_fake_probability(self):
  a=args()
  for r in a['candles1']:r.update(open=100,close=100)
  with self.assertRaises(ValueError):forecast(**a)

class DatabaseTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'live.sqlite3';self.db=migrate(self.path);ensure(self.db);self.m=market();register_market(self.db,self.m,OPEN);self.scheduler=ForecastScheduler(self.path,Mock(enabled=True));self.worker=Runtime(self.scheduler);self.cache(OPEN+60)
 def tearDown(self):self.db.close();self.tmp.cleanup()
 def cache(self,now):
  self.scheduler.cache.update(metadata={'received':now,'current':self.m,'markets':[self.m]},quote={'price':100.01,'timestamp':now-.1},candles=raw(candles(now)),v5candles={300:raw(candles(now,300)),900:raw(candles(now,900))})
 def tick(self,now):
  self.cache(now)
  with patch('intelligence.v5_runtime.time.time',return_value=now):self.worker.tick(self.db,now)
 def test_all_four_checkpoints_scheduled_from_official_open(self):
  self.tick(OPEN+59);rows=self.db.execute('SELECT * FROM v5_checkpoints ORDER BY checkpoint').fetchall();self.assertEqual([r['scheduled'] for r in rows],[OPEN+c for c in (60,180,300,600)]);self.assertTrue(all(r['state']=='PENDING' for r in rows))
 def test_all_four_immutable_forecasts_and_outboxes(self):
  for c in (60,180,300,600):self.tick(OPEN+c)
  self.assertEqual(self.db.execute("SELECT count(*) FROM v5_checkpoints WHERE state='FORECAST'").fetchone()[0],4);self.assertEqual(self.db.execute('SELECT count(*) FROM v5_outbox').fetchone()[0],4)
  self.assertEqual([r[0] for r in self.db.execute('SELECT checkpoint FROM v5_outbox ORDER BY checkpoint')],[60,180,300,600])
  with self.assertRaises(sqlite3.IntegrityError):
   with self.db:self.db.execute("UPDATE v5_checkpoints SET payload='{}' WHERE checkpoint=60")
  with self.assertRaises(sqlite3.IntegrityError):self.db.execute('DELETE FROM v5_checkpoints WHERE checkpoint=60')
 def test_forecast_needs_no_kalshi_book_or_baseline(self):
  self.tick(OPEN+60);p=loads(self.db.execute('SELECT payload FROM v5_checkpoints WHERE checkpoint=60').fetchone()[0]);self.assertIsNone(p['market_comparison']);self.assertIsNotNone(p['p_up'])
 def test_odds_only_change_post_forecast_comparison(self):
  self.scheduler.cache['book']={'ticker':self.m['ticker'],'received':OPEN+60,'book':Book.parse({'yes_dollars':[['.05','5']],'no_dollars':[['.94','5']]})};self.tick(OPEN+60);p=loads(self.db.execute('SELECT payload FROM v5_checkpoints WHERE checkpoint=60').fetchone()[0]);self.assertAlmostEqual(p['p_up'],forecast(**args())['p_up']);self.assertEqual(p['market_comparison']['direction'],'DOWN')
 def test_duplicate_ticks_and_restart_never_duplicate(self):
  self.tick(OPEN+60);self.tick(OPEN+61);self.worker=Runtime(self.scheduler);self.tick(OPEN+62);self.assertEqual(self.db.execute('SELECT count(*) FROM v5_outbox').fetchone()[0],1)
 def test_late_restart_records_missed_not_reconstructed(self):
  self.tick(OPEN+70);self.assertEqual(self.db.execute('SELECT state FROM v5_checkpoints WHERE checkpoint=60').fetchone()[0],'MISSED')
 def test_genuine_data_failure_separate_no_call(self):
  self.scheduler.cache['quote']['timestamp']=OPEN
  self.worker.tick(self.db,OPEN+60);self.worker.tick(self.db,OPEN+66)
  self.assertEqual(self.db.execute('SELECT state FROM v5_checkpoints WHERE checkpoint=60').fetchone()[0],'NO CALL')
 def test_database_reservation_delay_never_backdates(self):
  with patch('intelligence.v5_runtime.decision_time',side_effect=[100,106]):self.worker.tick(self.db,OPEN+60)
  self.assertEqual(self.db.execute('SELECT state FROM v5_checkpoints WHERE checkpoint=60').fetchone()[0],'PENDING');self.tick(OPEN+66);self.assertEqual(self.db.execute('SELECT state FROM v5_checkpoints WHERE checkpoint=60').fetchone()[0],'MISSED')
 def test_changed_opinion_preserves_original_and_explains_change(self):
  self.tick(OPEN+60);original=self.db.execute('SELECT payload FROM v5_checkpoints WHERE checkpoint=60').fetchone()[0];self.cache(OPEN+180);self.scheduler.cache['quote']['price']=99.5;self.worker.tick(self.db,OPEN+180)
  text=self.db.execute('SELECT message FROM v5_outbox WHERE checkpoint=180').fetchone()[0];self.assertIn('DIRECTION CHANGED',text);self.assertIn('momentum changed',text);self.assertEqual(self.db.execute('SELECT payload FROM v5_checkpoints WHERE checkpoint=60').fetchone()[0],original)
 def test_official_settlement_scores_each_checkpoint(self):
  for c in (60,180,300,600):self.tick(OPEN+c)
  m={**self.m,'status':'settled','result':'yes'};register_market(self.db,m,OPEN+901)
  scores=summary(self.db,OPEN+902)
  self.assertTrue(all(s['n']==1 for s in scores));self.assertTrue(all(s['wins']+s['losses']==1 for s in scores));self.worker.outcomes(self.db,OPEN+902);self.worker.outcomes(self.db,OPEN+903);self.assertEqual(self.db.execute("SELECT count(*) FROM v5_outbox WHERE checkpoint IS NULL").fetchone()[0],1)
 def test_nonfinal_market_does_not_score(self):
  self.tick(OPEN+60);register_market(self.db,{**self.m,'result':'yes'},OPEN+901);self.assertEqual(summary(self.db,OPEN+902)[0]['n'],0)
 def test_telegram_sends_four_once_not_v4_rate_capped(self):
  for c in (60,180,300,600):
   self.tick(OPEN+c)
   with patch('intelligence.v5_runtime.time.time',return_value=OPEN+c+1):self.worker.flush(self.db,OPEN+c+1);self.worker.flush(self.db,OPEN+c+1)
  self.assertEqual(self.scheduler.telegram.send.call_count,4)
 def test_telegram_disabled_checkpoint_and_expiry(self):
  self.db.execute("INSERT INTO v5_settings VALUES('60','false')");self.tick(OPEN+60)
  with patch('intelligence.v5_runtime.time.time',return_value=OPEN+61):self.worker.flush(self.db,OPEN+61)
  self.assertFalse(self.scheduler.telegram.send.called);self.tick(OPEN+180);self.worker.flush(self.db,OPEN+210);self.assertFalse(self.scheduler.telegram.send.called)
 def test_ambiguous_telegram_error_not_retried(self):
  self.tick(OPEN+60);self.scheduler.telegram.send.side_effect=TimeoutError()
  with patch('intelligence.v5_runtime.time.time',return_value=OPEN+61):self.worker.flush(self.db,OPEN+61);self.worker.flush(self.db,OPEN+61)
  self.assertEqual(self.scheduler.telegram.send.call_count,1);self.assertEqual(self.db.execute('SELECT state FROM v5_outbox').fetchone()[0],'delivery_unknown')
 def test_baseline_history_untouched_by_v5_schema_and_calls(self):
  before=[tuple(r) for r in self.db.execute('SELECT * FROM intel_locks')];ensure(self.db);self.tick(OPEN+60);self.assertEqual(before,[tuple(r) for r in self.db.execute('SELECT * FROM intel_locks')])
 def test_report_does_not_invent_performance(self):
  self.assertEqual(report(self.db)['baseline']['n'],0);self.assertEqual(train(self.db,OPEN+1000)['status'],'INSUFFICIENT TIME-SEPARATED FORWARD DATA')
 def test_pinned_original_and_separate_score(self):
  self.tick(OPEN+60);s=snapshot(self.db,OPEN+61);self.assertEqual(s['original']['state'],'FORECAST');self.assertEqual(s['historical']['wins'],0)
 def test_flask_auth_csrf_and_no_settings_secret_leak(self):
  import dashboard
  with patch.object(dashboard,'DB',self.path),patch.dict(os.environ,{'DASHBOARD_PASSWORD':'a-valid-secret','BTC_PRO_V5':'true'}):
   client=dashboard.app.test_client();self.assertEqual(client.get('/api/v5/state').status_code,401)
   auth={'Authorization':'Basic '+__import__('base64').b64encode(b'viewer:a-valid-secret').decode()};self.assertEqual(client.get('/api/v5/state',headers=auth).status_code,200)
   self.assertEqual(client.post('/api/v5/settings',headers=auth,json={'60':False}).status_code,403)
   d=client.get('/api/v5/settings',headers=auth).json;self.assertNotIn('TELEGRAM_BOT_TOKEN',str(d));self.assertEqual(client.post('/api/v5/settings',headers={**auth,'X-Alert-CSRF':d['csrf']},json={'60':False}).status_code,200)
   page=client.get('/',headers=auth).text;self.assertIn('v5-original',page);self.assertIn('v4-scoreboard',page);self.assertIn('pro-chart',page)

class EvaluationTests(unittest.TestCase):
 def test_insufficient_threshold_data_no_hindsight_claim(self):self.assertEqual(threshold_study([])['status'],'INSUFFICIENT TIME-SEPARATED DATA')
 def test_threshold_chosen_before_holdout(self):
  rows=[{'scheduled':i*900,'settled_at':i*900+850,'p':.7 if i%2 else .55,'y':i%2} for i in range(100)]
  r=threshold_study(rows);alter=copy.deepcopy(rows)
  for row in alter[60:]:row['y']=1-row['y']
  q=threshold_study(alter);self.assertEqual(r['chosen_threshold'],q['chosen_threshold']);self.assertEqual(r['test_n'],40);self.assertFalse(r['production_changed'])
 def test_et_today_dst_window(self):
  from intelligence.storage import window_start,ET
  now=datetime(2026,11,1,18,tzinfo=timezone.utc).timestamp();start=window_start('today',now);self.assertEqual(datetime.fromtimestamp(start,ET).hour,0);self.assertEqual(datetime.fromtimestamp(start,ET).day,1)
 def test_metrics_separate_probability_quality(self):
  r=metrics([(.8,1),(.2,0)]);self.assertEqual(r['accuracy'],1);self.assertAlmostEqual(r['brier'],.04);self.assertEqual(r['n'],2)

class InstallTests(unittest.TestCase):
 def test_v5_import_is_separate_preserves_all_history_and_credentials(self):
  from windows_v5 import initialize
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);old=root/'v4';new=root/'v5';old.mkdir();new.mkdir();(old/'scanner.py').write_text('# old');db=migrate(old/'data/live.sqlite3');register_market(db,market(),OPEN);db.close();(old/'data/credentials.dpapi').write_bytes(b'opaque encrypted fixture')
   result=initialize(old,new);a=sqlite3.connect(old/'data/live.sqlite3');b=sqlite3.connect(new/'data/live.sqlite3')
   try:self.assertEqual(a.execute('select * from intel_locks').fetchall(),b.execute('select * from intel_locks').fetchall());self.assertEqual(a.execute("select count(*) from sqlite_master where name='v5_checkpoints'").fetchone()[0],0);self.assertEqual(b.execute('pragma integrity_check').fetchone()[0],'ok')
   finally:a.close();b.close()
   self.assertEqual((new/'data/credentials.dpapi').read_bytes(),b'opaque encrypted fixture');self.assertTrue((new/'data/v5-isolated.txt').exists());self.assertTrue(Path(result['backup']).is_dir())
 def test_v5_start_uses_nuget_and_no_py_launcher(self):
  s=(Path(__file__).resolve().parents[1]/'start-v5.cmd').read_text();self.assertIn('python.3.12.10',s);self.assertIn('windows_v5.py',s);self.assertNotIn('py -',s)

class PaperTests(unittest.TestCase):
 setUp=DatabaseTests.setUp
 tearDown=DatabaseTests.tearDown
 cache=DatabaseTests.cache
 tick=DatabaseTests.tick
 def test_paper_entry_delay_fee_and_official_settlement(self):
  from intelligence.v5_paper import observe,summary as paper_summary
  self.tick(OPEN+60);self.scheduler.owner=Mock(latest_snapshot={'now':OPEN+62,'market':{'ticker':self.m['ticker']},'fee_valid':True,'fee_multiplier':1})
  self.scheduler.cache['book']={'ticker':self.m['ticker'],'received':OPEN+62,'book':Book.parse({'yes_dollars':[['.49','5']],'no_dollars':[['.50','5']]})}
  observe(self.db,self.scheduler,OPEN+60.5);self.assertEqual(self.db.execute('SELECT state FROM v5_paper').fetchone()[0],'WAIT_ENTRY')
  observe(self.db,self.scheduler,OPEN+62);r=self.db.execute('SELECT * FROM v5_paper').fetchone();self.assertEqual(r['state'],'OPEN');self.assertAlmostEqual(r['entry'],.502);self.assertGreater(r['entry_fee'],0)
  register_market(self.db,{**self.m,'status':'settled','result':'yes'},OPEN+901);observe(self.db,self.scheduler,OPEN+902);r=self.db.execute('SELECT * FROM v5_paper').fetchone();self.assertAlmostEqual(r['pnl'],1-.502-r['entry_fee']);self.assertEqual(paper_summary(self.db)['cohorts'][0]['state'],'SETTLED')
 def test_insufficient_depth_and_stale_fee_never_fill(self):
  from intelligence.v5_paper import observe
  self.tick(OPEN+60);self.scheduler.owner=Mock(latest_snapshot={'now':OPEN+62,'market':{'ticker':self.m['ticker']},'fee_valid':True,'fee_multiplier':1});self.scheduler.cache['book']={'ticker':self.m['ticker'],'received':OPEN+62,'book':Book.parse({'yes_dollars':[['.49','.5']],'no_dollars':[['.50','.5']]})}
  observe(self.db,self.scheduler,OPEN+62);self.assertEqual(self.db.execute('SELECT state FROM v5_paper').fetchone()[0],'WAIT_ENTRY');observe(self.db,self.scheduler,OPEN+65);self.assertEqual(self.db.execute('SELECT state FROM v5_paper').fetchone()[0],'MISSED_ENTRY')
 def test_exact_pairing_excludes_later_baseline(self):
  from intelligence.v5_evaluation import paired
  rows=[{'checkpoint':60,'baseline':.7,'baseline_observed':61,'observed':60,'p':.4,'y':0},{'checkpoint':60,'baseline':.8,'baseline_observed':70,'observed':60,'p':.3,'y':0}]
  p=paired(rows,'baseline');self.assertEqual(p['n'],1);self.assertEqual(p['v5_only_wins'],1)
 def test_real_chronological_retraining_and_ablation_no_label_leak(self):
  # 100 independent fixture markets, labels genuinely known before subsequent decisions.
  for i in range(100):
   op=OPEN+i*900;ticker='KXBTC15M-FOLD-'+str(i);m=market(op,ticker);register_market(self.db,m,op);p=forecast(**args());p['features']['distance']=(i%3-1)*.001;p['p_up']=.4 if i%2 else .6
   schedule(self.db,{'ticker':ticker,'opened':op})
   self.db.execute("UPDATE v5_checkpoints SET state='FORECAST',observed=?,payload=? WHERE ticker=? AND checkpoint=60",(op+60,dumps(p),ticker));register_market(self.db,{**m,'status':'settled','result':'yes' if i%2 else 'no'},op+901)
  result=train(self.db,OPEN+100*900+10);self.assertTrue(result['folds']);self.assertTrue(result['artifacts']);self.assertFalse(result['automatic_promotion'])
  for f in result['folds']:self.assertLess(f['train_label_max'],f['validation_start']);self.assertLess(f['validation_label_max'],f['test_start']);self.assertEqual(f['candidate']['n'],f['without_flow']['n'])
 def test_daily_summary_deduplicated_and_et_day_boundary(self):
  self.tick(OPEN+60);register_market(self.db,{**self.m,'status':'settled','result':'yes'},OPEN+901)
  from intelligence.storage import ET
  day=datetime.fromtimestamp(OPEN+60,ET);nextday=(day.replace(hour=0,minute=5,second=0,microsecond=0)+__import__('datetime').timedelta(days=1)).timestamp()
  self.worker.daily(self.db,nextday);self.worker.daily(self.db,nextday+1);self.assertEqual(self.db.execute("SELECT count(*) FROM v5_outbox WHERE key LIKE 'daily:%'").fetchone()[0],1)
