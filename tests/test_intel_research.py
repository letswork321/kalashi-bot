import tempfile
from pathlib import Path
import unittest
from unittest.mock import Mock,patch
from intelligence.storage import migrate,register_market
from intelligence.research import report,Backfill
from intel_helpers import market

class ResearchTests(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.db=migrate(Path(self.tmp.name)/'test.sqlite3')
    def tearDown(self):self.db.close();self.tmp.cleanup()
    def test_all_weekdays_hours_and_zero_samples_are_explicit(self):
        r=report(self.db,7,1800001000);self.assertEqual(len(r['hourly']),168);self.assertTrue(all(x['up_frequency'] is None for x in r['hourly']));self.assertIn('Unavailable',r['coverage']['historical_depth'])
    def test_official_outcomes_without_books_do_not_fabricate_depth(self):
        m=market();m.update(status='finalized',result='yes');register_market(self.db,m,1800001000)
        r=report(self.db,7,1800001100);self.assertEqual(r['coverage']['official_outcomes'],1);self.assertEqual(r['coverage']['live_book_observations'],0)
        self.assertTrue(all(x['mean_spread'] is None for x in r['hourly']))
    def test_backfill_failure_records_error_not_complete(self):
        http=Mock();http.get.side_effect=ValueError('unavailable')
        r=Backfill(self.db,http).run(7,1,1800001000);self.assertEqual(r['status'],'FAILED');self.assertEqual(self.db.execute('SELECT status FROM intel_jobs').fetchone()[0],'FAILED')
    def test_backfill_honors_capped_windows(self):
        http=Mock()
        def get(base,path,params=None):
            if path=='/markets':return {'markets':[],'cursor':''}
            if path=='/historical/cutoff':return {'market_settled_ts':'2000-01-01T00:00:00Z'}
            return []
        http.get.side_effect=get
        r=Backfill(self.db,http).run(90,1,1800001000);self.assertEqual(r['status'],'PARTIAL');self.assertIn('capped',r['message'])
    def test_unsupported_ranges_rejected(self):
        with self.assertRaises(ValueError):report(self.db,5)
        with self.assertRaises(ValueError):Backfill(self.db,Mock()).run(100)

class TradeBackfillTests(unittest.TestCase):
    def test_trade_volume_backfill_certifies_only_contiguous_real_rows(self):
        from datetime import datetime,timezone
        iso=lambda t:datetime.fromtimestamp(t,timezone.utc).isoformat()
        now=1800000100;anchor=int(now//86400)*86400
        with tempfile.TemporaryDirectory() as directory:
            db=migrate(Path(directory)/'test.sqlite3');http=Mock()
            http.get.return_value=[{'trade_id':2,'time':iso(anchor+10),'price':'100','size':'2'},{'trade_id':1,'time':iso(anchor-1),'price':'99','size':'1'}]
            r=Backfill(db,http).trade_session(1,now)
            self.assertEqual(r['status'],'COMPLETE');self.assertEqual(db.execute('SELECT count(*) FROM intel_btc_trades').fetchone()[0],2)
            self.assertEqual(db.execute('SELECT count(*) FROM intel_coverage').fetchone()[0],1);db.close()
    def test_trade_gap_never_certifies_vwap_coverage(self):
        with tempfile.TemporaryDirectory() as directory:
            db=migrate(Path(directory)/'test.sqlite3');http=Mock()
            http.get.return_value=[{'trade_id':3,'time':'2026-01-01T00:00:02Z','price':'100','size':'1'},{'trade_id':1,'time':'2026-01-01T00:00:00Z','price':'100','size':'1'}]
            r=Backfill(db,http).trade_session(1,1800000100)
            self.assertEqual(r['status'],'FAILED');self.assertEqual(db.execute('SELECT count(*) FROM intel_coverage').fetchone()[0],0);db.close()

class TradeCollectorCursorTests(unittest.TestCase):
    def test_live_collector_uses_recorded_id_to_avoid_cached_latest_page(self):
        from intelligence.collector import Collector
        from datetime import datetime,timezone
        now=1800000100;iso=lambda t:datetime.fromtimestamp(t,timezone.utc).isoformat()
        with tempfile.TemporaryDirectory() as directory:
            db=migrate(Path(directory)/'test.sqlite3')
            db.execute('INSERT INTO intel_btc_trades VALUES(?,?,?,?,?)',(2,now-1,100,1,now-1));db.commit()
            c=Collector(db);c.http=Mock();c.http.get.return_value=[{'trade_id':3,'time':iso(now),'price':'101','size':'1'},{'trade_id':2,'time':iso(now-1),'price':'100','size':'1'}]
            c.trades(now)
            self.assertEqual(c.http.get.call_args.args[2]['before'],'1')
            self.assertEqual(db.execute('SELECT max(id) FROM intel_btc_trades').fetchone()[0],3);db.close()

class PaperHourResearchTests(unittest.TestCase):
    def test_realized_paper_results_grouped_by_eastern_entry_hour(self):
        with tempfile.TemporaryDirectory() as directory:
            db=migrate(Path(directory)/'test.sqlite3');now=1800001000
            db.execute("INSERT INTO intel_sim(key,kind,strategy,ticker,side,quantity,signal_ts,entry_due,state,entry,entry_fee,pnl) VALUES('x','flip','flip','M','UP',1,?,?,'CLOSED',.5,.02,.1)",(now-10,now-8));db.commit()
            r=report(db,7,now);scored=[x for x in r['hourly'] if x['paper_closed']]
            self.assertEqual(len(scored),1);self.assertAlmostEqual(scored[0]['paper_net'],.1);self.assertEqual(scored[0]['paper_closed'],1);db.close()
