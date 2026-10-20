"""V3 fixtures verify safety/correctness, not live trading profitability."""
import base64
from datetime import datetime,timezone
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock,patch
import dashboard
from intelligence.storage import migrate,connect,dumps,register_market
from intelligence.live_feed import TradeTape,candle_rows,CoinbaseStream
from intelligence.streams import BRTIStream,OptionalStream,SequencedBook
from intelligence.pro_caller import patterns,caller
from intelligence import callouts,path_scoring
from intelligence.early_exit import target_bid,add_watch,watches,set_target,BidResearch
from intelligence.economics import Simulator
from intelligence.chart_data import payload,history
from intelligence.v3_dashboard import snapshot as dashboard_snapshot
from intelligence.boosted_models import fit_boost,boost_predict,evaluate
from intel_helpers import snapshot,market
from scanner import Book,fee

NOW=1800000060

def iso(t):return datetime.fromtimestamp(t,timezone.utc).isoformat()
def message(identifier,event=NOW,price=100,size=1):return {'type':'match','product_id':'BTC-USD','trade_id':identifier,'time':iso(event),'price':str(price),'size':str(size),'side':'sell'}
def bars(period,n=90,now=NOW):
 end=int(now//period)*period
 return [{'ts':end-(n-i)*period,'open':100+i*.2-.1,'close':100+i*.2,'low':100+i*.2-.2,'high':100+i*.2+.1,'volume':10+i} for i in range(n)]

def pro_snapshot(now=NOW):
 s=snapshot(now);s.update(candles1=bars(60,now=now),candles5=bars(300,now=now),spot_status='LIVE',book_event_verified=True,book_event_ts=now,fee_valid=True)
 s['price']=s['candles1'][-1]['close']+.2
 return s

class Base(unittest.TestCase):
 def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'live.sqlite3';self.db=migrate(self.path)
 def tearDown(self):self.db.close();self.tmp.cleanup()
 def seed_candles(self,period=60):
  with self.db:self.db.executemany("INSERT OR REPLACE INTO intel_candles VALUES('coinbase',?,?,?,?,?,?,?,?)",[(period,*[r[k] for k in ('ts','low','high','open','close','volume')],NOW) for r in bars(period)])
 def stream_state(self,now=NOW,age=0,status='LIVE'):
  with self.db:self.db.execute("INSERT OR REPLACE INTO v3_state VALUES('spot',?,?)",(now,dumps({'status':status,'event_ts':now-age,'price':100,'gaps':0})))
 def call(self,key='v3',sent=None):
  c={'ticker':'KXBTC15M-TEST','direction':'UP','observed':NOW,'btc_price':100,'quote_ts':NOW,'horizon':180,'minimum_move':.0005,'reason':'Synthetic test only','source':'Coinbase WebSocket'}
  path_scoring.record(self.db,c,key)
  if sent is not None:callouts.acknowledged(self.db,key,sent)
  return c

class TapeTests(unittest.TestCase):
 def test_live_needs_contiguous_fresh_event_timestamps(self):
  t=TradeTape();t.apply(message(1),NOW);self.assertNotEqual(t.snapshot(NOW)['status'],'LIVE')
  t.apply(message(2,NOW+.1),NOW+.1);self.assertEqual(t.snapshot(NOW+.2)['status'],'LIVE');self.assertEqual(t.snapshot(NOW+4)['status'],'STALE')
 def test_out_of_order_duplicate_gap_and_clock_skew(self):
  t=TradeTape();t.apply(message(1),NOW);t.apply(message(2,NOW+.1),NOW+.1)
  self.assertIsNone(t.apply(message(2),NOW+.2));t.apply(message(5,NOW+.3),NOW+.3);self.assertEqual(t.gaps,0);self.assertEqual(t.snapshot(NOW+.3)['status'],'RESYNCING');self.assertNotEqual(t.snapshot(NOW+.6)['status'],'LIVE');self.assertEqual(t.gaps,1)
  self.assertIsNone(t.apply(message(6,NOW+20),NOW));self.assertEqual(t.rejected,1)
 def test_reconnect_requires_new_sequence(self):
  t=TradeTape();t.apply(message(1),NOW);t.apply(message(2,NOW+.1),NOW+.1);t.reset();self.assertNotEqual(t.snapshot(NOW+.1)['status'],'LIVE')
 def test_bad_and_nonfinite_values_rejected(self):
  t=TradeTape()
  for price in ('NaN','inf',-1,0):self.assertIsNone(t.apply(message(1,price=price),NOW))
 def test_actual_tick_ohlcv_and_partial_bar(self):
  ticks=[{'id':i,'ts':NOW+i*.1,'price':p,'size':2,'epoch':0} for i,p in enumerate((100,102,99,101))]
  r=candle_rows(ticks,60,NOW+1)[0];self.assertEqual((r['open'],r['high'],r['low'],r['close'],r['volume']),(100,102,99,101,8))
  ticks[0]['ts']+=4;r=candle_rows(ticks,60,NOW+5)[0];self.assertTrue(r['partial'])
 def test_no_synthetic_empty_bars(self):
  ticks=[{'id':1,'ts':NOW,'price':100,'size':1,'epoch':0},{'id':2,'ts':NOW+120,'price':101,'size':1,'epoch':0}]
  self.assertEqual(len(candle_rows(ticks,60,NOW+121)),2)
 def test_disabled_public_stream_never_connects(self):
  with patch.dict(os.environ,{'COINBASE_WS_ENABLED':'false'}):s=CoinbaseStream();s.start();self.assertIsNone(s.thread)

class BenchmarkTests(unittest.TestCase):
 def value(self,ts=NOW,seq=1):return {'type':'cfbenchmarks_value','sid':3,'seq':seq,'msg':{'index_id':'BRTI','data':json.dumps({'time':ts*1000,'value':'81000.12'}),'avg_60s_data':{'value':'81001','window_size':60}}}
 def test_source_time_averages_and_staleness(self):
  b=BRTIStream();b.apply_value(self.value(),NOW);self.assertEqual(b.snapshot(NOW)['price'],81000.12);self.assertEqual(b.snapshot(NOW+4)['status'],'STALE')
  self.assertEqual(b.snapshot(NOW)['average_60s']['window_size'],60)
 def test_sequence_gap_rejects_feed(self):
  b=BRTIStream();b.apply_value(self.value(),NOW)
  with self.assertRaises(ValueError):b.apply_value(self.value(NOW+1,3),NOW+1)
 def test_security_gate_prevents_reading_any_private_key(self):
  with patch.dict(os.environ,{'KALSHI_WS_ENABLED':'true','KALSHI_DATA_SECURITY_CONFIRMED':'false'}):
   s=OptionalStream()
   with patch.object(s,'headers',side_effect=AssertionError('No private key access')):s.start()
   self.assertIsNone(s.thread);self.assertIn('SECURITY',s.state)
 def test_sending_timestamp_preserved(self):
  s=SequencedBook();s.apply({'type':'orderbook_snapshot','sending_ts_ms':(NOW-.5)*1000,'sid':1,'seq':1,'msg':{'market_ticker':'M','yes_dollars_fp':[['.4','10']],'no_dollars_fp':[['.5','10']]}},NOW)
  self.assertEqual(s.snapshot()['event_ts'],NOW-.5);self.assertEqual(s.snapshot()['latency'],.5)

class CallerTests(unittest.TestCase):
 def test_independent_modules_and_no_heuristic_enter(self):
  s=pro_snapshot();out=caller(s);self.assertEqual(len(out['modules']),7);self.assertEqual(out['guidance'],'WAIT');self.assertIn('NOT VALIDATED',out['confidence'])
  self.assertEqual({m['module'] for m in out['modules']},{'trend_following','spot_breakout','mean_reversion','failed_breakout','momentum','order_flow','liquidity'})
 def test_stale_quote_or_unknown_rest_event_cannot_enter(self):
  s=pro_snapshot();s['spot_status']='REST_FALLBACK';self.assertEqual(caller(s,{'UP':{'validated':True,'expected_net_lower':.5}})['guidance'],'WAIT')
  s=pro_snapshot();s['book_event_verified']=False;self.assertEqual(caller(s,{'UP':{'validated':True,'expected_net_lower':.5}})['guidance'],'WAIT')
 def test_missing_candles_never_invent_trend(self):
  s=pro_snapshot();s['candles5']=[];out=patterns(s);self.assertEqual(out[0]['signal'],'INSUFFICIENT DATA')
 def test_completed_close_not_developing_wick_confirms_break(self):
  s=pro_snapshot();out=patterns(s);b=next(m for m in out if m['module']=='spot_breakout');self.assertEqual(b['direction'],'UP')
  live={**s['candles1'][-1],'ts':NOW,'close':10000,'high':10001};s['candles1'].append(live)
  self.assertEqual(next(m for m in patterns(s) if m['module']=='spot_breakout')['readings']['close'],s['candles1'][-2]['close'])
 def test_order_flow_uses_maker_side_inverse(self):
  s=pro_snapshot();s['trades']=[{'id':i,'ts':NOW-1+i*.05,'price':100,'size':1,'side':'sell'} for i in range(20)]
  self.assertEqual(next(m for m in patterns(s) if m['module']=='order_flow')['direction'],'UP')

class PathMetricTests(Base):
 def ticks(self,end,price=100.06):return [{'id':i,'ts':NOW+i,'received':NOW+i,'price':price if i==end else 100,'continuous':True} for i in range(1,end+1)]
 def test_acknowledged_path_hit_does_not_mix_endpoint_scores(self):
  self.call(sent=NOW+1);path_scoring.observe(self.db,self.ticks(5),NOW+5)
  self.assertEqual(path_scoring.summary(self.db)['hits'],1);self.assertEqual(callouts.summary(self.db)['hits'],0)
 def test_no_ack_no_score(self):
  self.call();path_scoring.observe(self.db,self.ticks(5),NOW+5);self.assertEqual(path_scoring.summary(self.db)['hits'],0)
 def test_gap_or_late_delivery_is_unscored(self):
  self.call(sent=NOW+1);path_scoring.observe(self.db,[{'id':6,'ts':NOW+6,'received':NOW+6,'price':110,'continuous':False}],NOW+6)
  self.assertEqual(path_scoring.summary(self.db)['missed'],1);self.assertEqual(path_scoring.summary(self.db)['hits'],0)
 def test_late_ack_not_win(self):
  self.call(sent=NOW+4);path_scoring.observe(self.db,self.ticks(5),NOW+5);self.assertEqual(path_scoring.summary(self.db)['missed'],1)
 def test_contiguous_non_hit_endpoint(self):
  self.call(sent=NOW+1);path_scoring.observe(self.db,self.ticks(180,100),NOW+182);self.assertEqual(path_scoring.summary(self.db)['not_hits'],1)
 def test_target_metric_and_original_timestamp_are_immutable(self):
  self.call()
  for field,value in [('target_price','120'),('metric',"'fake'"),('btc_price','110')]:
   with self.assertRaises(sqlite3.IntegrityError):self.db.execute('UPDATE intel_callouts SET '+field+'='+value)
   self.db.rollback()
 def test_backfilled_tick_not_accepted_as_live_observation(self):
  self.call(sent=NOW+1);rows=self.ticks(5)
  for t in rows:t['received']=NOW+50
  path_scoring.observe(self.db,rows,NOW+50);self.assertEqual(path_scoring.summary(self.db)['hits'],0)

class ChartTests(Base):
 def test_actual_history_for_each_timeframe(self):
  for timeframe,period in [('1m',60),('5m',300),('15m',900)]:
   self.seed_candles(period);p=payload(self.db,timeframe,NOW);self.assertEqual(len(p['candles']),90);self.assertNotEqual(p['status'],'LIVE');self.assertGreater(len(p['indicators']['ema50']),0)
 def test_event_age_not_http_receipt_controls_live_badge(self):
  self.seed_candles();self.stream_state(age=300);p=payload(self.db,'1m',NOW);self.assertEqual(p['status'],'STALE')
  self.stream_state(age=1);self.assertEqual(payload(self.db,'1m',NOW)['status'],'LIVE')
 def test_genuine_partial_developing_candle(self):
  self.seed_candles();self.stream_state()
  self.db.executemany('INSERT INTO v3_ticks VALUES(?,?,?,?,?,?,?)',[('Coinbase WebSocket',str(i),NOW+i*.1,NOW+i*.1,p,1,1) for i,p in enumerate((100,102,99,101))]);self.db.commit()
  p=payload(self.db,'1m',NOW+1);self.assertEqual(p['candles'][-1]['high'],102);self.assertEqual(p['candles'][-1]['volume'],4)
 def test_missing_15s_coverage_is_unavailable(self):self.assertEqual(payload(self.db,'15s',NOW)['status'],'UNAVAILABLE')
 def test_vwap_not_invented_from_candle_volume(self):
  self.seed_candles();self.assertEqual(history(self.db,60,NOW)[1]['vwap'],[])
 def test_no_recommendation_survives_stale_persisted_snapshot(self):
  with self.db:self.db.execute("INSERT INTO v3_state VALUES('dashboard',?,?)",(NOW-10,dumps({'caller':{'guidance':'ENTER'},'spot':{'event_ts':NOW-10,'status':'LIVE'},'market':{}})))
  self.assertEqual(dashboard_snapshot(self.db,NOW)['caller']['guidance'],'WAIT')

class ExitEconomicsTests(Base):
 def test_65_percent_goal_deducts_all_costs(self):
  entry=.4;ef=fee(entry,1,.07,1);bid=target_bid(entry,entry_fee=ef,roi=.65);exit=bid-.002;net=exit-entry-ef-fee(exit,1,.07,1)
  self.assertGreaterEqual(net/(entry+ef),.65-1e-7);self.assertGreater(bid,.66)
 def test_unreachable_target_has_no_fake_exit(self):self.assertIsNone(target_bid(.8,roi=.65))
 def test_manual_basis_validation_and_persistence(self):
  identifier=add_watch(self.db,{'ticker':'KXBTC15M-TEST','side':'UP','entry':.4,'quantity':1,'entry_fee':.02},NOW)
  self.assertGreater(identifier,0);self.assertEqual(self.db.execute('SELECT entry FROM v3_watch_positions').fetchone()[0],.4)
  with self.assertRaises(ValueError):add_watch(self.db,{'ticker':'X','side':'UP','entry':.4,'quantity':1,'entry_fee':.02},NOW)
 def test_rest_cannot_claim_executable_watch_roi(self):
  add_watch(self.db,{'ticker':'KXBTC15M-TEST','side':'UP','entry':.4,'quantity':1,'entry_fee':.02},NOW)
  s=pro_snapshot();s['book_event_verified']=False;self.assertEqual(watches(self.db,s)[0]['status'],'QUOTE UNAVAILABLE')
 def test_exit_goal_settings_not_probability(self):
  self.assertEqual(set_target(self.db,.9,NOW)['target_roi'],.9)
  with self.assertRaises(ValueError):set_target(self.db,9,NOW)
 def test_bid_research_never_backfills_missing_endpoint(self):
  s=pro_snapshot();research=BidResearch(self.db);research.observe(s);self.assertGreater(self.db.execute('SELECT count(*) FROM v3_contract_samples').fetchone()[0],0)
  s.update(now=NOW+25,book_event_ts=NOW+25,book_ts=NOW+25);research.observe(s)
  self.assertEqual(self.db.execute("SELECT count(*) FROM v3_contract_samples WHERE state='OBSERVED'").fetchone()[0],0)
 def test_bid_model_reports_insufficient_samples(self):self.assertFalse(BidResearch(self.db).forecast(pro_snapshot())['UP']['validated'])
 def test_paper_goal_exit_has_real_delay_and_bid_cost(self):
  s=pro_snapshot();s['book']=Book.parse({'yes_dollars':[['.39','100']],'no_dollars':[['.60','100']]});sim=Simulator(self.db)
  identifier=sim.propose('v3paper','directional','v3_early_exit',s,'UP',None)
  with self.db:self.db.execute('INSERT INTO v3_paper_rules(sim_id,target_roi,created) VALUES(?,?,?)',(identifier,.65,NOW))
  s.update(now=NOW+2,book_ts=NOW+2,book_id=2);sim.update(s)
  s.update(now=NOW+10,book_ts=NOW+10,book_id=3,book=Book.parse({'yes_dollars':[['.75','100']],'no_dollars':[['.24','100']]}));sim.update(s)
  r=self.db.execute('SELECT * FROM intel_sim').fetchone();self.assertEqual(r['state'],'OPEN');self.assertEqual(r['exit_due'],NOW+12)
  s.update(now=NOW+12,book_ts=NOW+12,book_id=4);sim.update(s)
  r=self.db.execute('SELECT * FROM intel_sim').fetchone();self.assertEqual(r['state'],'CLOSED');self.assertAlmostEqual(r['exit'],.748);self.assertGreater(r['exit_fee'],0)

class V3APITests(Base):
 def setUp(self):
  super().setUp();self.env=patch.dict(os.environ,{'DASHBOARD_PASSWORD':'v3-unit-test-password'});self.env.start();self.dbpatch=patch.object(dashboard,'DB',self.path);self.dbpatch.start();dashboard._v3_chart_cache.clear()
  self.client=dashboard.app.test_client();self.auth={'Authorization':'Basic '+base64.b64encode(b'viewer:v3-unit-test-password').decode()}
 def tearDown(self):self.dbpatch.stop();self.env.stop();super().tearDown()
 def test_api_auth_and_timeframe_validation(self):
  self.assertEqual(self.client.get('/api/v3/state').status_code,401);self.assertEqual(self.client.get('/api/v3/chart?timeframe=1h',headers=self.auth).status_code,400)
  self.seed_candles();self.assertEqual(self.client.get('/api/v3/chart',headers=self.auth).status_code,200)
 def test_watch_csrf_and_secure_settings(self):
  self.assertEqual(self.client.post('/api/v3/watch',headers=self.auth,json={}).status_code,403)
  d=self.client.get('/api/v3/settings',headers=self.auth).json;headers={**self.auth,'X-Alert-CSRF':d['csrf']}
  self.assertEqual(self.client.post('/api/v3/settings',headers=headers,json={'target_roi':.75}).status_code,200)
  self.assertEqual(self.client.post('/api/v3/watch',headers=headers,json={'ticker':'KXBTC15M-TEST','side':'UP','entry':.4,'quantity':1,'entry_fee':.02}).status_code,200)
  self.assertEqual(self.client.post('/api/v3/watch',headers={**headers,'Origin':'https://evil.example'},json={}).status_code,403)
 def test_compact_layout_contains_chart_and_collapsed_advanced(self):
  html=self.client.get('/',headers=self.auth).data.decode();self.assertIn('pro-chart',html);self.assertIn('TradingView',html);self.assertIn('<details id="advanced-root">',html);self.assertNotIn('<details id="advanced-root" open',html)
 def test_self_hosted_library_matches_recorded_digest(self):
  root=Path(__file__).resolve().parents[1]/'static'/'vendor';p=json.loads((root/'lightweight-charts-provenance.json').read_text());self.assertEqual(hashlib.sha256((root/'lightweight-charts-5.0.9.js').read_bytes()).hexdigest(),p['sha256'])

class BoostedTests(unittest.TestCase):
 def test_actual_gradient_boost_fit_learns_separable_inputs(self):
  x=[[float(i)] for i in range(60)];y=[int(i>=30) for i in range(60)];m=fit_boost(x,y,30);self.assertGreater(boost_predict(m,[55]),boost_predict(m,[5]));self.assertGreater(len(m['trees']),0)
 def test_no_data_is_not_fake_accuracy(self):self.assertEqual(evaluate([])['status'],'INSUFFICIENT DATA')

class AdditionalSafetyTests(Base):
 def test_history_backfill_does_not_create_new_missed_forecasts(self):
  m=market(NOW-900,'KXBTC15M-HISTORICAL');m.update(status='finalized',result='yes');register_market(self.db,m,NOW,track=False)
  self.assertEqual(self.db.execute('SELECT count(*) FROM intel_locks').fetchone()[0],0)
  self.assertEqual(self.db.execute('SELECT result FROM intel_markets').fetchone()[0],'yes')
 def test_existing_missed_and_locked_rows_survive_research_metadata_refresh(self):
  m=market(NOW-900,'KXBTC15M-EXISTING');register_market(self.db,m,NOW);before=dict(self.db.execute('SELECT * FROM intel_locks').fetchone());register_market(self.db,m,NOW+10,track=False)
  self.assertEqual(dict(self.db.execute('SELECT * FROM intel_locks').fetchone()),before)
 def test_model_has_no_measured_edge_when_fee_or_event_time_unknown(self):
  s=pro_snapshot();s['fee_valid']=False;s['fee_multiplier']=None
  self.assertFalse(BidResearch(self.db).forecast(s)['UP']['validated'])
 def test_gap_after_proven_hit_does_not_change_result_by_batching(self):
  self.call(sent=NOW+1)
  rows=[{'id':1,'ts':NOW+1,'received':NOW+1,'price':100.1,'continuous':True},{'id':8,'ts':NOW+8,'received':NOW+8,'price':90,'continuous':False}]
  path_scoring.observe(self.db,rows,NOW+8);self.assertEqual(path_scoring.summary(self.db)['hits'],1)
 def test_missing_end_of_window_is_unscored_not_a_loss(self):
  self.call(sent=NOW+1)
  rows=[{'id':i,'ts':NOW+i,'received':NOW+i,'price':100,'continuous':True} for i in range(1,179)]
  path_scoring.observe(self.db,rows,NOW+182);self.assertEqual(path_scoring.summary(self.db)['missed'],1);self.assertEqual(path_scoring.summary(self.db)['not_hits'],0)
 def test_consecutive_post_window_tick_can_certify_no_intermediate_trade(self):
  self.call(sent=NOW+1)
  rows=[{'id':i,'ts':NOW+i,'received':NOW+i,'price':100,'continuous':True} for i in range(1,180)]
  rows.append({'id':180,'ts':NOW+181,'received':NOW+181,'price':110,'continuous':True})
  path_scoring.observe(self.db,rows,NOW+182);self.assertEqual(path_scoring.summary(self.db)['not_hits'],1);self.assertEqual(path_scoring.summary(self.db)['hits'],0)
 def test_nonpositive_slippage_adjusted_quote_is_unavailable(self):
  s=pro_snapshot();s['book']=Book.parse({'yes_dollars':[['.001','100']],'no_dollars':[['.998','100']]})
  self.assertFalse(BidResearch(self.db).forecast(s)['UP']['validated'])
 def test_goal_does_not_use_gross_contract_price_increase(self):
  entry=.5;goal=.65;raw_goal=entry*(1+goal)
  self.assertGreater(target_bid(entry,roi=goal),raw_goal)
 def test_separate_model_comparison_does_not_overwrite_operational_model(self):
  from intelligence.boosted_models import retrain_comparison
  retrain_comparison(self.db,NOW);self.assertEqual(self.db.execute('SELECT count(*) FROM intel_models').fetchone()[0],0)
  self.assertEqual(self.db.execute('SELECT count(*) FROM v3_model_comparisons').fetchone()[0],1)
 def test_empty_rest_response_cannot_generate_synthetic_chart_bars(self):
  self.assertEqual(payload(self.db,'1m',NOW)['candles'],[])
 def test_stale_brti_never_overwrites_coinbase_price(self):
  row={'caller':{'guidance':'WAIT'},'spot':{'price':100,'event_ts':NOW,'status':'LIVE'},'brti':{'price':90,'event_ts':NOW-50,'status':'LIVE'},'market':{}}
  with self.db:self.db.execute("INSERT INTO v3_state VALUES('dashboard',?,?)",(NOW,dumps(row)))
  out=dashboard_snapshot(self.db,NOW);self.assertEqual(out['spot']['price'],100);self.assertEqual(out['brti']['status'],'STALE')
 def test_frontend_scripts_parse_when_node_is_available(self):
  import shutil,subprocess
  if not shutil.which('node'):self.skipTest('Node is cloud/CI verification only, not required on Windows laptop')
  root=Path(__file__).resolve().parents[1]
  for name in ('pro.js','intelligence.js','alerts.js'):
   result=subprocess.run(['node','--check',str(root/'static'/name)],capture_output=True,text=True);self.assertEqual(result.returncode,0,result.stderr)

class ChronologicalBoostTests(unittest.TestCase):
 def rows(self):
  return [{'ticker':'KXBTC15M-'+str(i),'scheduled':NOW+i*900,'closed':NOW+i*900+840,'settled_at':NOW+i*900+850,'x':[math.sin(i),i%3],'y':i%2,'p_up':.5,'market_p':.5} for i in range(100)]
 def test_real_boosted_shadow_walk_forward_uses_disjoint_later_test(self):
  report=evaluate(self.rows());self.assertEqual(report['candidate']['n'],20)
  fold=report['folds'][0];self.assertLess(fold['validation_end'],fold['test_start']);self.assertTrue(all(int(x.split('-')[-1])>=80 for x in fold['test_tickers']))
 def test_validation_labels_unavailable_at_test_time_prevent_evaluation(self):
  rows=self.rows();rows[79]['settled_at']=rows[80]['scheduled']+1;out=evaluate(rows);self.assertEqual(out['candidate']['n'],0);self.assertIsNone(out['candidate']['brier'])
 def test_model_rejects_nonfinite_training_input(self):
  with self.assertRaises(ValueError):fit_boost([[math.nan]],[1])

@unittest.skipUnless(os.name=='nt','Native Windows DPAPI check; no equivalent on Linux')
class NativeWindowsV3Tests(unittest.TestCase):
 def test_real_current_user_dpapi_round_trip_with_dummy_values(self):
  from intelligence.credentials import save,load
  with tempfile.TemporaryDirectory() as td:
   p=Path(td)/'dummy.dpapi';values={'TELEGRAM_BOT_TOKEN':'test-only-not-a-real-bot','TELEGRAM_CHAT_ID':'0','DASHBOARD_PASSWORD':'dummy-test-only-password'}
   save(p,values);self.assertNotIn(b'test-only-not-a-real-bot',p.read_bytes());self.assertEqual(load(p),values)
