from pathlib import Path
import tempfile
import unittest
from scanner import Book,fee
from intelligence.storage import migrate
from intelligence.economics import *
from intel_helpers import snapshot

class EconomicsTests(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.db=migrate(Path(self.tmp.name)/'test.sqlite3');self.sim=Simulator(self.db)
    def tearDown(self):self.db.close();self.tmp.cleanup()
    def test_bid_ask_depth_and_slippage(self):
        book=Book.parse({'yes_dollars':[['.55','1'],['.50','1']],'no_dollars':[['.44','1'],['.43','1']]})
        self.assertAlmostEqual(executable(book,'UP','buy',2),.567)
        self.assertAlmostEqual(executable(book,'UP','sell',2),.523)
        with self.assertRaises(ValueError):executable(book,'UP','buy',3)
    def test_56_cent_contract_not_automatic_opportunity(self):
        s=snapshot();s['book']=Book.parse({'yes_dollars':[['.55','20']],'no_dollars':[['.44','20']]});s['book_history']=[]
        r=flip_radar(s)['rows'][0]
        self.assertLess(r['immediate_net'],0);self.assertNotEqual(r['status'],'POTENTIAL OPPORTUNITY')
    def test_stale_radar_is_stale(self):
        s=snapshot();s['book_ts']-=5
        self.assertTrue(all(r['status']=='STALE' for r in flip_radar(s)['rows']))
    def test_rest_scalps_require_faster_feed(self):
        self.assertTrue(all(r['status']=='FASTER MARKET DATA REQUIRED' for r in scalp_radar(snapshot())['rows']))
    def test_fair_value_requires_validated_candidate(self):
        r=fair_value(snapshot(),{'validated':False,'probability':.99});self.assertEqual(r['status'],'INSUFFICIENT DATA');self.assertEqual(r['rows'],[])
    def test_fair_value_cost_not_probability_alone(self):
        s=snapshot();s['book']=Book.parse({'yes_dollars':[['.94','10']],'no_dollars':[['.04','10']]})
        r=fair_value(s,{'validated':True,'probability':.9,'sample_size':200})
        self.assertEqual(r['rows'][0]['status'],'OVERPRICED')
    def test_simulation_does_not_fill_at_signal_time(self):
        s=snapshot();self.sim.propose('test','flip','flip',s,'UP',40);self.sim.update(s)
        self.assertEqual(self.db.execute('SELECT state FROM intel_sim').fetchone()[0],'PENDING_ENTRY')
    def fill(self):
        s=snapshot();self.sim.propose('test','flip','flip',s,'UP',40)
        s['now']+=2;s['book_ts']=s['now'];self.sim.update(s)
        return s
    def test_delayed_entry_and_bid_exit_with_both_fees(self):
        s=self.fill();p=self.db.execute('SELECT * FROM intel_sim').fetchone();self.assertEqual(p['state'],'OPEN')
        s['now']+=40;s['book_ts']=s['now'];s['book']=Book.parse({'yes_dollars':[['.60','100']],'no_dollars':[['.38','100']]});self.sim.update(s)
        p=self.db.execute('SELECT * FROM intel_sim').fetchone();self.assertEqual(p['state'],'CLOSED');self.assertAlmostEqual(p['exit'],.598);self.assertAlmostEqual(p['pnl'],p['exit']-p['entry']-p['entry_fee']-p['exit_fee']);self.assertGreater(p['exit_fee'],0)
    def test_midpoint_rise_without_bid_does_not_make_profit(self):
        s=self.fill();s['now']+=40;s['book_ts']=s['now']
        s['book']=Book.parse({'yes_dollars':[['.48','100']],'no_dollars':[['.30','100']]});self.sim.update(s)
        self.assertLess(self.db.execute('SELECT pnl FROM intel_sim').fetchone()[0],0)
    def test_missed_entry_cannot_be_replayed_later(self):
        s=snapshot();self.sim.propose('test','flip','flip',s,'UP',40);s['now']+=10;s['book_ts']=s['now'];self.sim.update(s)
        self.assertEqual(self.db.execute('SELECT state FROM intel_sim').fetchone()[0],'CANCELLED')
    def test_missed_exit_not_fabricated(self):
        s=self.fill();s['now']+=50;s['book_ts']=s['now'];self.sim.update(s)
        p=self.db.execute('SELECT * FROM intel_sim').fetchone();self.assertEqual(p['state'],'MISSED_EXIT');self.assertIsNone(p['pnl'])
    def test_mock_never_opens_live_simulation(self):
        s=snapshot();s['mode']='mock';self.sim.propose('x','flip','x',s,'UP',40)
        self.assertEqual(self.db.execute('SELECT count(*) FROM intel_sim').fetchone()[0],0)
    def test_settlement_directional_vs_flip_separate(self):
        s=snapshot();self.sim.propose('d','directional','d',s,'DOWN',None);s['now']+=2;s['book_ts']=s['now'];self.sim.update(s)
        self.sim.settle({'ticker':s['market']['ticker'],'result':'no','status':'finalized'},s['now']+900)
        result=self.sim.summary();self.assertEqual(result['directional']['closed'],1);self.assertGreater(result['directional']['net_pnl'],0);self.assertEqual(result['flip']['closed'],0)

class ScalpCadenceTests(unittest.TestCase):
    def test_optional_feed_must_have_real_cadence_before_opportunity(self):
        s=snapshot();s['book']=Book.parse({'yes_dollars':[['.49','100']],'no_dollars':[['.50','100']]});s.update(book_source='websocket',ws_sequence_valid=True,tick_metrics={'velocity':.001,'acceleration':.001,'age':0})
        now=s['now'];ticker=s['market']['ticker']
        s['book_history']=[{'ticker':ticker,'side':side,'ts':now-20+i*.5,'bid':.4+i*.002} for i in range(41) for side in ('UP','DOWN')]
        result=scalp_radar(s)
        self.assertTrue(any(r['status']=='WATCH' for r in result['rows']))
        self.assertFalse(any(r['status']=='OPPORTUNITY' for r in result['rows']))
        s['scalp_evidence']={'UP:'+str(h):{'validated':True} for h in (20,40,60)}
        self.assertTrue(any(r['status']=='OPPORTUNITY' for r in scalp_radar(s)['rows']))
        s['ws_sequence_valid']=False
        self.assertTrue(all(r['status']=='FASTER MARKET DATA REQUIRED' for r in scalp_radar(s)['rows']))
    def test_clustered_updates_with_long_gap_are_not_fast_coverage(self):
        s=snapshot();s.update(book_source='websocket',ws_sequence_valid=True,tick_metrics={'velocity':.001})
        s['book_history']=[{'ticker':s['market']['ticker'],'side':'UP','ts':s['now']-19+i*.01,'bid':.5} for i in range(30)]+[{'ticker':s['market']['ticker'],'side':'UP','ts':s['now'],'bid':.6}]
        self.assertTrue(all(r['status']=='FASTER MARKET DATA REQUIRED' for r in scalp_radar(s)['rows']))

class CostQualityTests(unittest.TestCase):
    def test_unverified_fees_disable_economics_not_independent_engines(self):
        s=snapshot();s['fee_valid']=False
        self.assertTrue(all(r['status']=='STALE' for r in flip_radar(s)['rows']))
        self.assertEqual(fair_value(s,{'validated':True,'probability':.9,'sample_size':200})['status'],'INSUFFICIENT DATA')
    def test_stale_inputs_never_become_valid_fair_value(self):
        s=snapshot();s['quote_ts']-=10
        self.assertEqual(fair_value(s,{'validated':True,'probability':.9,'sample_size':200})['status'],'INSUFFICIENT DATA')

class SharedLiquidityTests(unittest.TestCase):
    def test_same_observation_depth_is_not_reused_by_competing_entries(self):
        with tempfile.TemporaryDirectory() as directory:
            db=migrate(Path(directory)/'test.sqlite3');sim=Simulator(db);s=snapshot()
            s['book']=Book.parse({'yes_dollars':[['.48','1']],'no_dollars':[['.49','1']]})
            sim.propose('one','scalp','scalp20',s,'UP',20);sim.propose('two','scalp','scalp40',s,'UP',40)
            s['now']+=2;s['book_ts']=s['now'];sim.update(s)
            self.assertEqual(db.execute("SELECT count(*) FROM intel_sim WHERE state='OPEN'").fetchone()[0],1)
            self.assertEqual(db.execute("SELECT count(*) FROM intel_sim WHERE state='PENDING_ENTRY'").fetchone()[0],1);db.close()

class ConditionalTargetCostTests(unittest.TestCase):
    def test_raw_bid_target_still_deducts_exit_slippage(self):
        s=snapshot();r=flip_radar(s)['rows'][0]
        expected=r['possible_exit_target']-.002-r['entry']-r['entry_fee']-fee(r['possible_exit_target']-.002,1,.07,1)
        self.assertAlmostEqual(r['conditional_net'],expected)
        self.assertAlmostEqual(r['observed_exit_bid']-.002,r['executable_exit'])

class RetentionAuditTests(unittest.TestCase):
    def test_retention_keeps_books_used_for_paper_fills(self):
        from intelligence.collector import Collector
        from intelligence.storage import dumps
        with tempfile.TemporaryDirectory() as directory:
            db=migrate(Path(directory)/'test.sqlite3');s=snapshot();sim=Simulator(db)
            for identity in (1,2):db.execute('INSERT INTO intel_books(id,ticker,ts,event_ts,source,yes,no,spread,imbalance,latency,fee_multiplier) VALUES(?,?,?,?,?,?,?,?,?,?,?)',(identity,s['market']['ticker'],s['now']-30*86400,s['now']-30*86400,'REST',dumps(s['book'].yes),dumps(s['book'].no),.03,0,.1,1))
            db.commit();sim.propose('one','flip','flip',s,'UP',40);s['now']+=2;s['book_ts']=s['now'];s['book_id']=1;sim.update(s)
            Collector(db).retention(s['now'])
            self.assertIsNotNone(db.execute('SELECT id FROM intel_books WHERE id=1').fetchone());self.assertIsNone(db.execute('SELECT id FROM intel_books WHERE id=2').fetchone());db.close()
