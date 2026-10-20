"""V4 deterministic safety checks; fixtures do not establish trading profitability."""
import base64,json,math,os,sqlite3,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch
import dashboard
from intelligence.storage import migrate,register_market,dumps
from intelligence.v4_analysis import pressure,analyze,cusum
from intelligence.v4_positions import create,quote,realized
from intelligence.v4_paths import quotes,observe,summary
from intelligence.v4_research import export,investigate
from intelligence.v4_sources import calendar_events,Liquidations,save_calendar,macro_context
from intelligence.v4_models import lock_shadow,comparison,retrain
from intelligence.v4_runtime import Runtime,snapshot as state
from intelligence.early_exit import set_target,target_bid
from intelligence.notifications import Notifications
from intelligence.alert_settings import save
from intelligence.live_feed import TradeTape
from intelligence.scheduler import ForecastScheduler
from intelligence.chart_data import markers
from intel_helpers import snapshot,market
from scanner import Book,fee

NOW=1800000060

def s(now=NOW):
 v=snapshot(now);v.update(spot_status='LIVE',book_event_verified=True,book_event_ts=now,book_ts=now,quote_ts=now,fee_valid=True)
 v['book']=Book.parse({'yes_dollars':[['.19','100']],'no_dollars':[['.79','100']]});return v

def ticks(now=NOW,n=650):
 return [{'id':i,'ts':now-65+i*.1,'received':now-65+i*.1+.01,'price':100+i*.0001,'size':1,'side':'sell','continuous':True} for i in range(n+1)]

class DB(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'db.sqlite3';self.db=migrate(self.path);register_market(self.db,market(),NOW)
 def tearDown(self):self.db.close();self.tmp.cleanup()

class FlowTests(unittest.TestCase):
 def test_maker_side_is_inverted_and_weighted(self):
  t=ticks();t[-1].update(side='buy',size=1000);p=pressure(t,NOW,15);self.assertEqual(p['status'],'LIVE');self.assertGreater(p['sell_share'],.8);self.assertAlmostEqual(p['buy_share']+p['sell_share'],1)
 def test_missing_id_disables_pressure(self):
  t=ticks();t.pop(-20);self.assertIsNone(pressure(t,NOW,15)['buy_share'])
 def test_stale_pressure_no_recommendation(self):self.assertIsNone(pressure(ticks(),NOW+10,15)['buy_share'])
 def test_multiplier_tracks_selected_side(self):
  a=analyze(s(),ticks());self.assertEqual(a['flip']['side'],'UP');self.assertAlmostEqual(a['flip']['gross_settlement_multiplier'],1/.21)
  t=ticks();[r.update(side='buy',price=200-r['id']*.0001) for r in t];a=analyze(s(),t);self.assertEqual(a['flip']['side'],'DOWN');self.assertAlmostEqual(a['flip']['gross_settlement_multiplier'],1/.81)
 def test_reversal_requires_opposing_evidence_and_never_mutates_lock(self):
  v=s();v['locked_direction']='DOWN';a=analyze(v,ticks());self.assertIn(a['outlook']['state'],('DOWN WEAKENING','UP REVERSAL BUILDING'));self.assertEqual(v['locked_direction'],'DOWN')
 def test_stale_extreme_is_not_alert(self):
  v=s();v['spot_status']='STALE';a=analyze(v,ticks());self.assertEqual(a['extreme']['state'],'QUIET');self.assertFalse(a['extreme']['telegram']);self.assertEqual(a['outlook']['state'],'WAIT')
 def test_no_fake_whale_or_liquidations(self):
  a=analyze(s(),[]);self.assertEqual(a['whale']['large_trades'],[]);self.assertEqual(a['whale']['liquidations']['status'],'UNAVAILABLE')
 def test_cusum_has_defined_threshold(self):self.assertEqual(cusum([(-1)**i*.001 for i in range(60)])['threshold'],5)

class PositionTests(DB):
 def create(self,**kw):return create(self.db,{'ticker':market()['ticker'],'side':'UP','entry_cents':20,**kw},NOW)
 def test_cents_optional_size_fee_and_multiple(self):
  ids=[self.create(),self.create(side='DOWN')];self.assertNotEqual(*ids)
  r=self.db.execute('SELECT * FROM v3_watch_positions WHERE id=?',(ids[0],)).fetchone();self.assertEqual(r['entry'],.2);self.assertEqual(r['quantity'],1);self.assertGreater(r['entry_fee'],0)
  self.assertIn('ESTIMATED',self.db.execute('SELECT fee_basis FROM v4_position_details LIMIT 1').fetchone()[0])
 def test_99_goal_and_impossible_target(self):
  set_target(self.db,.99,NOW);self.create(entry_cents=80,target_roi=.99)
  self.assertIsNone(quote(self.db,s())[0]['target_bid']);self.assertEqual(quote(self.db,s())[0]['target_status'],'IMPOSSIBLE')
 def test_invalid_inputs_rejected(self):
  for values in ({'entry_cents':math.nan},{'entry_cents':100},{'quantity':0},{'entry_fee':-1},{'ticker':'KXBTC15M-NO'},{'target_roi':1}):
   with self.assertRaises(ValueError):self.create(**values)
 def test_actual_bid_roi_both_fees_and_slippage(self):
  self.create(entry_fee=.02);r=quote(self.db,s())[0];bid=.19-.002;cost=.22;expected=bid-fee(bid,1,.07,1)-cost;self.assertAlmostEqual(r['net'],expected);self.assertAlmostEqual(r['roi'],expected/cost)
 def test_missing_quote_never_goal_hit(self):
  self.create();v=s();v['book_event_verified']=False;r=quote(self.db,v)[0];self.assertEqual(r['status'],'UNAVAILABLE');self.assertNotIn('goal_hit',r)
 def test_realized_result_separate_user_confirmed(self):
  identifier=self.create(entry_fee=.01);net=realized(self.db,{'id':identifier,'exit_cents':40,'exit_fee':.01},NOW+20);self.assertAlmostEqual(net,.18)
  r=self.db.execute('SELECT * FROM v4_position_details').fetchone();self.assertIn('USER_CONFIRMED',r['realized_basis'])
 def test_max_verified_roi_persists(self):
  self.create();first=quote(self.db,s())[0];v=s(NOW+1);v['book']=Book.parse({'yes_dollars':[['.1','100']],'no_dollars':[['.89','100']]});second=quote(self.db,v)[0];self.assertEqual(second['max_roi'],first['roi'])

class ProfitPathTests(DB):
 def test_no_rest_hypothesis(self):
  v=s();v['book_event_verified']=False;observe(self.db,v);self.assertEqual(summary(self.db)['counts'],[])
 def test_both_sides_delayed_entry_and_frozen_basis(self):
  observe(self.db,s());self.assertEqual(self.db.execute('SELECT count(*) FROM v4_profit_paths').fetchone()[0],2)
  self.assertIsNone(self.db.execute('SELECT entry FROM v4_profit_paths LIMIT 1').fetchone()[0]);observe(self.db,s(NOW+2));self.assertEqual(self.db.execute('SELECT state FROM v4_profit_paths LIMIT 1').fetchone()[0],'OPEN')
  with self.assertRaises(sqlite3.IntegrityError):self.db.execute('UPDATE v4_profit_paths SET goal=.1')
  self.db.rollback()
 def test_verified_path_goal_is_not_realized_trade(self):
  observe(self.db,s());observe(self.db,s(NOW+2));v=s(NOW+3);v['book']=Book.parse({'yes_dollars':[['.50','100']],'no_dollars':[['.49','100']]});observe(self.db,v)
  r=self.db.execute("SELECT * FROM v4_profit_paths WHERE side='UP'").fetchone();self.assertEqual(r['state'],'GOAL HIT');self.assertEqual(r['barrier'],'TARGET_FIRST');self.assertEqual(self.db.execute('SELECT count(*) FROM v4_position_details').fetchone()[0],0)
 def test_gap_before_price_jump_not_win(self):
  observe(self.db,s());observe(self.db,s(NOW+2));v=s(NOW+8);v['book']=Book.parse({'yes_dollars':[['.5','100']],'no_dollars':[['.49','100']]});observe(self.db,v);self.assertEqual(self.db.execute("SELECT state FROM v4_profit_paths WHERE side='UP' LIMIT 1").fetchone()[0],'UNVERIFIED')
 def test_stop_first_not_future_win(self):
  observe(self.db,s());observe(self.db,s(NOW+2));v=s(NOW+3);v['book']=Book.parse({'yes_dollars':[['.05','100']],'no_dollars':[['.94','100']]});observe(self.db,v);self.assertEqual(self.db.execute("SELECT barrier FROM v4_profit_paths WHERE side='UP' LIMIT 1").fetchone()[0],'STOP_FIRST')
 def test_insufficient_depth_and_costs_both_sides(self):
  for r in quotes(s(),quantity=1000):self.assertEqual(r['status'],'INSUFFICIENT EXECUTABLE DEPTH')
  for r in quotes(s()):self.assertLess(r['roi'],0)

class ResearchTests(DB):
 def test_export_readonly_bounded_and_sanitized(self):
  self.db.execute("CREATE TABLE secret(token TEXT)");self.db.execute("INSERT INTO secret VALUES('do-not-export-token')");self.db.commit();before=self.path.read_bytes();p=Path(self.tmp.name)/'export.json';export(self.path,p,1);text=p.read_text();self.assertNotIn('do-not-export-token',text);self.assertNotIn('credentials',json.loads(text)['tables']);self.assertEqual(before,self.path.read_bytes());self.assertTrue(all(len(rows)<=1 for rows in json.loads(text)['tables'].values()))
 def test_export_never_overwrites_db_or_existing_file(self):
  with self.assertRaises(ValueError):export(self.path,self.path)
 def test_endpoint_scoring_separate_from_gapped_v3(self):
  runtime=Runtime(Mock());runtime.started=NOW-1
  self.db.execute("INSERT INTO v4_call_endpoints(key,issued,ack,due,side,target) VALUES('e',?,?,?,'UP',101)",(NOW,NOW+1,NOW+181));self.db.commit();runtime.endpoints(self.db,[{'ts':NOW+181,'received':NOW+181.1,'price':102}],NOW+181.2)
  self.assertEqual(self.db.execute('SELECT state FROM v4_call_endpoints').fetchone()[0],'HIT');self.assertEqual(self.db.execute('SELECT count(*) FROM intel_callouts').fetchone()[0],0)
 def test_endpoint_missing_observation_unverified(self):
  runtime=Runtime(Mock());self.db.execute("INSERT INTO v4_call_endpoints(key,issued,ack,due,side,target) VALUES('e',0,1,181,'UP',101)");self.db.commit();runtime.endpoints(self.db,[],184);self.assertEqual(self.db.execute('SELECT state FROM v4_call_endpoints').fetchone()[0],'UNVERIFIED')
 def test_live_scheduler_uses_stream_without_http(self):
  worker=ForecastScheduler(self.path);worker.spot_stream=Mock();worker.spot_stream.snapshot.return_value={'status':'LIVE','price':100,'event_ts':NOW};http=Mock();worker.quote(http);http.get.assert_not_called();self.assertEqual(worker.cache['quote']['timestamp'],NOW)
 def test_stale_stream_still_uses_real_rest(self):
  worker=ForecastScheduler(self.path);worker.spot_stream=Mock();worker.spot_stream.snapshot.return_value={'status':'STALE'};http=Mock();http.get.return_value={'price':'100','time':'2026-01-01T00:00:00Z'};worker.quote(http);http.get.assert_called_once()
 def test_state_masks_stale_economics(self):
  self.db.execute("INSERT INTO v3_state VALUES('v4',?,?)",(NOW,dumps({'cashout':{'guidance':'ENTER'},'positions':[{'status':'LIVE','goal_hit':True,'roi':.8}]})));self.db.commit();d=state(self.db,NOW+5);self.assertEqual(d['cashout']['guidance'],'WAIT');self.assertFalse(d['positions'][0]['goal_hit'])
 def test_challenger_cannot_modify_original_and_empty_training_honest(self):
  self.assertEqual(retrain(self.db,NOW)['candidate']['n'],0);self.assertEqual(comparison(self.db)['same_forward_markets'],0)

class SourceTests(unittest.TestCase):
 def test_calendar_dst_and_no_fake_surprise(self):
  events=calendar_events('BEGIN:VEVENT\nUID:test\nDTSTART;TZID=America/New_York:20261101T083000\nSUMMARY:Employment\nEND:VEVENT',NOW);self.assertEqual(len(events),1);self.assertIsNone(events[0]['surprise']);self.assertEqual(events[0]['scheduled'],__import__('datetime').datetime(2026,11,1,13,30,tzinfo=__import__('datetime').timezone.utc).timestamp())
 def test_untrusted_calendar_rejected(self):
  with self.assertRaises(ValueError):calendar_events('',NOW,'https://rumors.invalid/calendar')
 def test_partial_liquidations_not_marketwide(self):
  feed=Liquidations();feed.apply({'e':'forceOrder','o':{'s':'BTCUSDT','T':NOW*1000,'S':'SELL','z':'2','ap':'100'}},NOW);d=feed.snapshot(NOW);self.assertEqual(len(d['observed']),1);self.assertIn('1000ms',d['coverage']);self.assertIn('partial',d['observed'][0]['meaning'])
 def test_stale_future_or_other_symbol_liquidations_rejected(self):
  feed=Liquidations()
  for symbol,ts in [('ETHUSDT',NOW),('BTCUSDT',NOW+10),('BTCUSDT',NOW-10)]:feed.apply({'e':'forceOrder','o':{'s':symbol,'T':ts*1000,'S':'BUY','z':'2','ap':'100'}},NOW)
  self.assertEqual(feed.snapshot(NOW)['observed'],[])
 def test_heartbeat_recorded_without_inventing_trade(self):
  tape=TradeTape();tape.apply({'type':'heartbeat','product_id':'BTC-USD','last_trade_id':2,'time':'2026-01-01T00:00:00Z'},NOW);self.assertEqual(tape.heartbeat['last_id'],2);self.assertEqual(len(tape.rows),0)

class APIAndAlerts(DB):
 def setUp(self):
  super().setUp();self.env=patch.dict(os.environ,{'DASHBOARD_PASSWORD':'test-pass-v4-secure'});self.env.start();self.patch=patch.object(dashboard,'DB',self.path);self.patch.start();self.client=dashboard.app.test_client();self.auth={'Authorization':'Basic '+base64.b64encode(b'viewer:test-pass-v4-secure').decode()}
 def tearDown(self):self.patch.stop();self.env.stop();super().tearDown()
 def test_auth_and_csrf_required(self):
  self.assertEqual(self.client.get('/api/v4/state').status_code,401);self.assertEqual(self.client.post('/api/v4/positions',headers=self.auth,json={}).status_code,403)
 def test_cents_api_no_account_operations(self):
  token=self.client.get('/api/v3/settings',headers=self.auth).json['csrf'];self.db.execute('UPDATE intel_markets SET opened=0,closed=?',(9999999999,));self.db.commit()
  r=self.client.post('/api/v4/positions',headers={**self.auth,'X-Alert-CSRF':token},json={'ticker':market()['ticker'],'side':'UP','entry_cents':20});self.assertEqual(r.status_code,200);self.assertEqual(self.db.execute('SELECT entry FROM v3_watch_positions').fetchone()[0],.2)
 def test_extreme_never_sends_and_round_budget(self):
  notify=Notifications(self.db,Mock(enabled=True));save(self.db,{'live_change':True,'flip':True,'exit':True})
  self.assertFalse(notify.enqueue('extreme','M','x','must not send',NOW,NOW+5))
  for i in range(3):self.assertTrue(notify.enqueue('live_change','M',str(i),'Watch',NOW+i*301,NOW+i*301+5,scope=str(i)))
  self.assertFalse(notify.enqueue('flip','M','four','watch',NOW+905,NOW+910));self.assertTrue(notify.enqueue('exit','M','urgent','risk',NOW+905,NOW+910))
 def test_markers_short_text_and_precise_times(self):
  self.db.execute("INSERT INTO intel_callouts(key,ticker,observed,direction,btc_price,quote_ts,horizon,due,minimum_move,reason,sent) VALUES('mark','M',?,'UP',100,?,180,?,.0005,'Reason',?)",(NOW+.7,NOW,NOW+180,NOW+1));self.db.commit();r=markers(self.db,60,NOW-100)[0];self.assertEqual(r['event_ts'],NOW+.7);self.assertEqual(r['text'],'UP WATCH');self.assertLess(r['time'],r['event_ts'])

class AdvancedProofTests(DB):
 def test_real_shadow_fit_and_chronological_evaluation(self):
  from intelligence.v4_models import retrain
  for i in range(100):
   op=NOW-60+i*900;ticker='KXBTC15M-V4TRAIN-'+str(i);m=market(op,ticker);register_market(self.db,m,op)
   from intelligence.storage import lock_forecast
   lock_forecast(self.db,m,{'p_up':.55,'observed_at':op+60,'btc_timestamp':op+60,'model':'baseline'},op+60,{},'RANGE')
   self.db.execute('UPDATE intel_locks SET result=? WHERE ticker=?',('yes' if i%2 else 'no',ticker));self.db.execute('UPDATE intel_markets SET settled_at=? WHERE ticker=?',(op+901,ticker))
   f={'z':math.sin(i),'sigma':.001,'momentum':.001,'acceleration':.001,'market_p':.5,'imbalance':.1,'pressure':.7,'distance':.001,'remaining':840}
   self.db.execute('INSERT INTO v4_challengers VALUES(?,?,?,?,?,?,?)',(ticker,op+60,'fixture-v4',.6,dumps(f),'SHADOW','Test fixture'))
  self.db.commit();r=retrain(self.db,NOW+100*900);self.assertEqual(r['candidate']['n'],20);self.assertTrue(r['shadow_only']);self.assertLess(r['folds'][0]['validation_end'],r['folds'][0]['test_start']);self.assertEqual(self.db.execute('SELECT count(*) FROM intel_models').fetchone()[0],0)
 def test_first_passage_uses_independent_markets_and_purged_holdout(self):
  from intelligence.v4_paths import path_forecast
  for i in range(200):
   issued=NOW-(201-i)*900
   self.db.execute("INSERT INTO v4_profit_paths(ticker,side,issued,entry_due,closed,ask,quantity,entry_fee,multiplier,goal,stop,version,provenance,state,entry,filled,last_event,max_roi,barrier,last_bid) VALUES(?,'UP',?,?,?,?,1,.01,1,.65,-.25,'fixture','test','GOAL HIT',.212,?,?,1,'TARGET_FIRST',.5)",('KXBTC15M-FP-'+str(i),issued,issued+2,issued+840,.21,issued+2,issued+20))
  self.db.commit();r=path_forecast(self.db,s(),'UP',.65);self.assertEqual(r['n'],200);self.assertTrue(r['validated']);self.assertLess(r['train_end'],r['test_start']);self.assertIn('SHADOW',r['production'])
 def test_late_shadow_not_backfilled_and_baseline_immutable(self):
  from intelligence.storage import lock_forecast
  m=market();lock_forecast(self.db,m,{'p_up':.6,'observed_at':NOW,'btc_timestamp':NOW,'model':'baseline'},NOW,{},'RANGE');before=tuple(self.db.execute('SELECT * FROM intel_locks').fetchone());lock_shadow(self.db,s(NOW+2));self.assertEqual(self.db.execute('SELECT count(*) FROM v4_challengers').fetchone()[0],0);self.assertEqual(tuple(self.db.execute('SELECT * FROM intel_locks').fetchone()),before)
 def test_release_source_and_publication_guards(self):
  from intelligence.v4_sources import save_release
  e={'id':'release','source':'https://www.bls.gov/report','scheduled':NOW,'published':NOW,'title':'Official fixture','consensus':2,'actual':3};save_release(self.db,e,NOW);self.assertEqual(self.db.execute('SELECT surprise FROM v4_macro').fetchone()[0],1)
  with self.assertRaises(ValueError):save_release(self.db,{**e,'published':NOW+1},NOW)
 def test_export_retains_numeric_book_depth_not_secrets(self):
  v=s();self.db.execute("INSERT INTO intel_books(ticker,ts,event_ts,source,yes,no) VALUES('M',?,?,'websocket',?,?)",(NOW,NOW,dumps(v['book'].yes),dumps(v['book'].no)));self.db.execute("INSERT INTO v4_health(observed,source,state,payload) VALUES(?,'Coinbase','STALE',?)",(NOW,dumps({'age':4,'token':'never-export-secret'})));self.db.commit();p=Path(self.tmp.name)/'depth.json';export(self.path,p);text=p.read_text();self.assertNotIn('never-export-secret',text);self.assertEqual(json.loads(text)['tables']['intel_books'][0]['yes'][0][0],.19)
 def test_book_age_rechecked_on_every_http_state(self):
  self.db.execute("INSERT INTO v3_state VALUES('v4',?,?)",(NOW,dumps({'cashout':{'guidance':'ENTER'},'positions':[],'book_event_ts':NOW-1.1})));self.db.commit();self.assertEqual(state(self.db,NOW)['cashout']['guidance'],'WAIT')
 def test_warnings_are_immutable(self):
  self.db.execute("INSERT INTO v4_events(ticker,observed,kind,state,payload) VALUES('M',?,'outlook','UP REVERSAL BUILDING','{}')",(NOW,));self.db.commit()
  with self.assertRaises(sqlite3.IntegrityError):self.db.execute("UPDATE v4_events SET observed=observed-10")
  self.db.rollback()
 def test_research_audit_missing_history_never_claims_profit(self):
  from intelligence.v4_research import historical_cashout
  self.assertEqual(historical_cashout(self.db,'M','DOWN',NOW,NOW+840)['status'],'UNVERIFIED')

class CoordinatorTests(DB):
 def test_end_to_end_step_keeps_extreme_off_telegram(self):
  runtime=Runtime(Mock());notify=Mock();v=s();runtime.step(self.db,v,ticks(),{'status':'LIVE','age':0},notify)
  self.assertEqual(self.db.execute("SELECT count(*) FROM v3_state WHERE name='v4'").fetchone()[0],1)
  for call in notify.enqueue.call_args_list:self.assertNotEqual(call.args[0],'extreme')
  payload=json.loads(self.db.execute("SELECT payload FROM v3_state WHERE name='v4'").fetchone()[0]);self.assertEqual(payload['cashout']['guidance'],'WAIT')
 def test_manual_cashout_alert_uses_supplied_basis(self):
  create(self.db,{'ticker':market()['ticker'],'side':'UP','entry_cents':10,'entry_fee':0,'target_roi':.65},NOW)
  runtime=Runtime(Mock());notify=Mock();runtime.step(self.db,s(),ticks(),{'status':'LIVE'},notify)
  cash=[c for c in notify.enqueue.call_args_list if c.args[0]=='cashout'];self.assertEqual(len(cash),1);self.assertIn('Supplied entry',cash[0].args[3]);self.assertIn('not a sale',cash[0].args[3])
 def test_stdlib_export_accepts_null_features(self):
  p=Path(self.tmp.name)/'null.json';export(self.path,p);self.assertTrue(p.exists())
