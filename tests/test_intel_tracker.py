import sqlite3
import tempfile
from pathlib import Path
from datetime import datetime,timezone
import unittest
from intelligence.storage import *
from intelligence.engines import observe_reversal,reversal_evidence
from intel_helpers import market,snapshot

class TrackerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'live.sqlite3';self.db=migrate(self.path)
    def tearDown(self):self.db.close();self.temp.cleanup()
    def lock(self,m,p=.6):
        op=__import__('scanner').timestamp(m['open_time']);register_market(self.db,m,op)
        s=snapshot(op+60);s['baseline'].update(p_up=p,observed_at=op+60,btc_timestamp=op+60)
        return lock_forecast(self.db,m,s['baseline'],op+60,{'market_p':.5},'RANGING')
    def test_exactly_one_immutable_lock(self):
        m=market();r=self.lock(m);self.assertEqual(r['direction'],'UP')
        self.assertIsNone(lock_forecast(self.db,m,{'p_up':.1},1800000061,{},'DOWN'))
        with self.assertRaises(sqlite3.IntegrityError):self.db.execute("UPDATE intel_locks SET direction='DOWN' WHERE ticker=?",(m['ticker'],))
    def test_early_and_late_observation(self):
        m=market();register_market(self.db,m,1800000000)
        p={'p_up':.6,'observed_at':1800000059,'btc_timestamp':1800000059,'model':'baseline'}
        self.assertIsNone(lock_forecast(self.db,m,p,1800000059,{},'RANGE'))
        self.assertIsNone(lock_forecast(self.db,m,p,1800000066,{},'RANGE'))
        self.assertEqual(self.db.execute('SELECT state FROM intel_locks').fetchone()[0],'MISSED')
    def test_stale_quote_not_locked(self):
        m=market();register_market(self.db,m,1800000000)
        p={'p_up':.6,'observed_at':1800000060,'btc_timestamp':1800000050,'model':'baseline'}
        self.assertIsNone(lock_forecast(self.db,m,p,1800000060,{},'RANGE'))
    def test_offline_historical_discovery_is_missed(self):
        register_market(self.db,market(),1800000700)
        self.assertEqual(self.db.execute('SELECT state FROM intel_locks').fetchone()[0],'MISSED')
    def test_no_result_until_official_finalization(self):
        m=market();self.lock(m);m.update(status='closed',result='yes');register_market(self.db,m,1800001000)
        self.assertIsNone(self.db.execute('SELECT result FROM intel_locks').fetchone()[0])
        m['status']='finalized';register_market(self.db,m,1800001001)
        self.assertEqual(tracker_summary(self.db,'all',1800001100)['wins'],1)
    def test_counts_pending_missed_and_streak(self):
        for i,(p,outcome) in enumerate([(.6,'yes'),(.6,'no'),(.4,'no'),(.6,None)]):
            m=market(1800000000+i*900,'KXBTC15M-'+str(i));self.lock(m,p)
            if outcome:m.update(status='finalized',result=outcome);register_market(self.db,m,1800005000)
        register_market(self.db,market(1800003600,'KXBTC15M-MISSED'),1800005000)
        r=tracker_summary(self.db,'all',1800006000)
        self.assertEqual((r['wins'],r['losses'],r['pending'],r['missed']),(2,1,1,1));self.assertEqual(r['streak'],{'kind':'WIN','count':1})
    def test_utc_storage_eastern_day_and_dst(self):
        ts=datetime(2026,11,1,6,30,tzinfo=timezone.utc).timestamp()
        local=datetime.fromtimestamp(ts,ET);self.assertEqual(local.hour,1);self.assertEqual(local.fold,1)
        midnight=window_start('today',ts);self.assertEqual(datetime.fromtimestamp(midnight,timezone.utc).hour,4)
        self.assertEqual(datetime.fromtimestamp(ts,ET).strftime('%A'),'Sunday')
        self.assertGreater(window_start('7',ts),window_start('30',ts))
    def test_reversal_exact_10_minute_sample_once(self):
        m=market();register_market(self.db,m,1800000000)
        s=snapshot(1800000600);s['price']=105
        observe_reversal(self.db,s)
        r=self.db.execute('SELECT * FROM intel_reversals').fetchone();self.assertEqual(r['state'],'OBSERVED');self.assertEqual(r['band'],'UPPER')
        s['price']=90;s['now']+=1;s['quote_ts']+=1;observe_reversal(self.db,s)
        self.assertEqual(self.db.execute('SELECT price FROM intel_reversals').fetchone()[0],105)
    def test_reversal_missed_or_old_quote_not_reconstructed(self):
        register_market(self.db,market(),1800000000)
        s=snapshot(1800000600);s['quote_ts']=1800000599;observe_reversal(self.db,s)
        self.assertEqual(self.db.execute('SELECT state FROM intel_reversals').fetchone()[0],'PENDING')
        s['now']=1800000604;s['quote_ts']=s['now'];observe_reversal(self.db,s)
        self.assertEqual(self.db.execute('SELECT state FROM intel_reversals').fetchone()[0],'MISSED')
    def test_reversal_measurable_outcome_and_sparse_evidence(self):
        register_market(self.db,market(),1800000000)
        s=snapshot(1800000600);s['price']=105;observe_reversal(self.db,s)
        s['now']=s['quote_ts']=1800000840;s['price']=104;observe_reversal(self.db,s)
        self.assertEqual(self.db.execute('SELECT outcome FROM intel_reversals').fetchone()[0],'REVERTED')
        self.assertFalse(reversal_evidence(self.db)['validated'])
    def test_backup_precedes_additive_migration_and_keeps_legacy(self):
        p=Path(self.temp.name)/'legacy.sqlite3';legacy=sqlite3.connect(p);legacy.execute('CREATE TABLE predictions(id INTEGER PRIMARY KEY,payload TEXT)');legacy.execute("INSERT INTO predictions VALUES(1,'original')");legacy.commit();legacy.close()
        db=migrate(p)
        row=db.execute('SELECT backup FROM intel_schema').fetchone();self.assertTrue(Path(row[0]).exists());self.assertEqual(db.execute('SELECT payload FROM predictions').fetchone()[0],'original')
        backup=sqlite3.connect(row[0]);self.assertIsNone(backup.execute("SELECT name FROM sqlite_master WHERE name='intel_locks'").fetchone());backup.close();db.close()
    def test_migration_repeat_does_not_create_another_backup(self):
        second=migrate(self.path);second.close();self.assertEqual(self.db.execute('SELECT count(*) FROM intel_schema').fetchone()[0],1)

class ModeIsolationTests(unittest.TestCase):
    def test_intelligence_refuses_mock_database(self):
        from scanner import Store
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'mock.sqlite3';store=Store(path,'mock');store.db.close()
            with self.assertRaisesRegex(ValueError,'mock database'):migrate(path)

class InvalidForecastTests(unittest.TestCase):
    def test_invalid_probability_never_locks_a_guess(self):
        with tempfile.TemporaryDirectory() as directory:
            db=migrate(Path(directory)/'test.sqlite3');m=market();register_market(db,m,1800000000)
            for value in (float('nan'),float('inf'),-1,2,'bad'):
                p={'p_up':value,'observed_at':1800000060,'btc_timestamp':1800000060,'model':'x'}
                self.assertIsNone(lock_forecast(db,m,p,1800000060,{},'RANGE'))
            self.assertEqual(db.execute('SELECT state FROM intel_locks').fetchone()[0],'PENDING');db.close()
