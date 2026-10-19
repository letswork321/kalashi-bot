"""Synthetic/unit fixtures verify correctness, never live profitability."""
import base64
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock,patch
import dashboard
from scanner import Book,Store,Config,Telegram,timestamp
from intelligence.storage import migrate,register_market,tracker_summary,dumps
from intelligence.scheduler import ForecastScheduler
from intelligence.notifications import Notifications,performance
from intelligence.alert_settings import settings,save
from intelligence.economics import scalp_radar,compare_flips,flip_radar,evaluate_flips,Simulator,fast_scalp_data
from intel_helpers import market,snapshot
import inplace_update

class Base(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'live.sqlite3';self.db=migrate(self.path)
        self.telegram=Mock(enabled=True);self.n=Notifications(self.db,self.telegram)
    def tearDown(self):self.db.close();self.tmp.cleanup()
    def fast(self,now=1800000060):
        s=snapshot(now);s.update(book_source='websocket',book_latency=.05,ws_sequence_valid=True,tick_metrics={'velocity':.001,'acceleration':.001,'age':0,'trades':100,'volume_btc':4})
        s['book']=Book.parse({'yes_dollars':[['.49','100']],'no_dollars':[['.50','100']]})
        s['book_history']=[{'ticker':s['market']['ticker'],'side':side,'ts':now-20+i*.5,'bid':.4+i*.002,'ask':.41+i*.002,'spread':.01} for i in range(41) for side in ('UP','DOWN')]
        return s
    def scalp_queue(self,s):
        save(self.db,{'scalp':True});r=scalp_radar(s);self.n.signals(s,[],{'rows':[]},r);return r

class SchedulerTests(Base):
    def fixture(self,now=1800000060):
        w=ForecastScheduler(self.path,self.telegram);m=market();end=int(now//60)*60
        w.cache={'metadata':{'received':now,'current':m,'markets':[m]},'quote':{'price':101,'timestamp':now,'received':now},'book':{'ticker':m['ticker'],'book':snapshot(now)['book'],'received':now,'latency':.1},'candles':[[end-(120-i)*60,99,102,100,100+i*.001,10] for i in range(120)]}
        return w,m
    def test_clock_locks_once_with_no_network_or_research_calls(self):
        w,m=self.fixture()
        with patch('scanner.HTTP.get',side_effect=AssertionError('Clock must not wait on HTTP')):
            w.tick(self.db,1800000060,self.n);w.tick(self.db,1800000060.2,self.n)
        r=self.db.execute('SELECT * FROM intel_locks').fetchone();self.assertEqual(r['state'],'LOCKED');self.assertEqual(r['strike'],100);self.assertEqual(r['btc_price'],101)
        self.assertEqual(self.db.execute('SELECT count(*) FROM intel_lock_attempts').fetchone()[0],1)
        self.assertEqual(self.db.execute("SELECT count(*) FROM intel_alerts WHERE category='locked'").fetchone()[0],1)
    def test_slow_or_stale_input_records_precise_rejection_then_late(self):
        w,m=self.fixture();w.cache['book']['latency']=4
        w.tick(self.db,1800000060,self.n)
        r=self.db.execute('SELECT * FROM intel_lock_attempts').fetchone();self.assertEqual(r['reason'],'ORDERBOOK_STALE_OR_UNAVAILABLE')
        w,m=self.fixture(1800000070);w.tick(self.db,1800000070,self.n)
        self.assertEqual(self.db.execute('SELECT state FROM intel_locks').fetchone()[0],'MISSED')
        late=self.db.execute('SELECT * FROM intel_late_locks').fetchone();self.assertEqual(late['observed'],1800000070)
        with self.assertRaises(sqlite3.IntegrityError):self.db.execute("UPDATE intel_late_locks SET direction='DOWN'")
        self.db.rollback()
        m.update(status='finalized',result='yes');register_market(self.db,m,1800001000)
        summary=tracker_summary(self.db,'all',1800001100);self.assertEqual(summary['sample_size'],0);self.assertEqual(summary['late']['wins'],1)
    def test_no_late_guess_after_120_seconds(self):
        w,m=self.fixture(1800000121);w.tick(self.db,1800000121,self.n)
        self.assertEqual(self.db.execute('SELECT count(*) FROM intel_late_locks').fetchone()[0],0)
    def test_market_rollover_rejects_old_book(self):
        w,m=self.fixture(1800000960);m=market(1800000900,'KXBTC15M-NEXT');w.cache['metadata'].update(current=m,markets=[m])
        w.tick(self.db,1800000960,self.n);self.assertEqual(self.db.execute('SELECT reason FROM intel_lock_attempts').fetchone()[0],'ORDERBOOK_STALE_OR_UNAVAILABLE')
    def test_old_92_missed_records_remain_byte_for_byte(self):
        for i in range(92):register_market(self.db,market(1800000000-(i+1)*900,'KXBTC15M-OLD'+str(i)),1800000000)
        before=[tuple(r) for r in self.db.execute("SELECT * FROM intel_locks WHERE ticker LIKE 'KXBTC15M-OLD%' ORDER BY ticker")]
        w,m=self.fixture();w.tick(self.db,1800000060,self.n)
        after=[tuple(r) for r in self.db.execute("SELECT * FROM intel_locks WHERE ticker LIKE 'KXBTC15M-OLD%' ORDER BY ticker")]
        self.assertEqual(before,after);self.assertEqual(len(after),92)
    def test_cached_pre_target_observation_never_backdated(self):
        w,m=self.fixture();w.cache['quote']['timestamp']=1800000057
        w.tick(self.db,1800000060,self.n);self.assertEqual(self.db.execute('SELECT state FROM intel_locks').fetchone()[0],'PENDING')
    def test_locked_alert_is_explicit_forecast_not_entry(self):
        w,m=self.fixture();w.tick(self.db,1800000060,self.n)
        text=self.db.execute('SELECT message FROM intel_alerts').fetchone()[0]
        self.assertIn('LOCKED',text);self.assertIn('UNCALIBRATED',text);self.assertIn('not an entry',text)
    def test_preliminary_unknown_strike_is_optional_and_one_time(self):
        save(self.db,{'preliminary':True});w,m=self.fixture();future=market(1800000120,'KXBTC15M-FUTURE');future['floor_strike']=None;w.cache['metadata']['markets'].append(future)
        self.n.preliminary(w.cache,1800000060);self.n.preliminary(w.cache,1800000061)
        rows=self.db.execute("SELECT message FROM intel_alerts WHERE category='preliminary'").fetchall();self.assertEqual(len(rows),1);self.assertIn('UNKNOWN',rows[0][0]);self.assertIn('NOT LOCKED',rows[0][0])

class SettingsAndAlertTests(Base):
    def test_switches_persist_and_disabled_pending_cancel(self):
        save(self.db,{'scalp':True,'directional':False,'locked':False})
        self.assertIn('scalp',Notifications(self.db,self.telegram).enabled);self.assertFalse(settings(self.db)['directional'])
        self.n.enqueue('scalp','M','s','test',100,200);save(self.db,{'scalp':False});self.n.flush(101)
        self.telegram.send.assert_not_called();self.assertEqual(self.db.execute('SELECT state FROM intel_alerts').fetchone()[0],'disabled')
    def test_rest_and_mock_never_produce_scalp_alerts(self):
        s=snapshot();self.scalp_queue(s);s['mode']='mock';self.scalp_queue(s);self.assertEqual(self.db.execute('SELECT count(*) FROM intel_alerts').fetchone()[0],0)
    def test_fast_feed_unvalidated_sends_watch_only_separate_horizons(self):
        s=self.fast();self.scalp_queue(s);rows=self.db.execute('SELECT message FROM intel_alerts').fetchall()
        self.assertEqual(len(rows),3)
        for r in rows:self.assertIn('SCALP WATCH',r[0]);self.assertIn('NOT AN ENTRY',r[0]);self.assertIn('after both fees',r[0])
        self.n.signals(s,[],{'rows':[]},scalp_radar(s));self.assertEqual(self.db.execute('SELECT count(*) FROM intel_alerts').fetchone()[0],3)
    def test_late_delivery_ack_is_not_backdated_into_entry(self):
        s=self.fast();self.scalp_queue(s)
        with patch('intelligence.notifications.time.time',side_effect=[s['now'],s['now']+4,s['now']+4,s['now']+4]):self.n.flush(s['now'],s)
        r=self.db.execute('SELECT * FROM intel_alert_evidence WHERE sent IS NOT NULL').fetchone();self.assertEqual(r['evaluation'],'DELIVERED_LATE_NO_ENTRY')
        self.n.evaluate_delivered(s);self.assertEqual(self.db.execute('SELECT count(*) FROM intel_sim').fetchone()[0],0)
    def test_stale_queued_scalp_is_not_delivered(self):
        s=self.fast();self.scalp_queue(s)
        with patch('intelligence.notifications.time.time',return_value=s['now']+2):self.n.flush(s['now']+2,s)
        self.telegram.send.assert_not_called()
    def test_delivery_followed_by_delayed_entry_and_observed_exit(self):
        s=self.fast();self.scalp_queue(s)
        with patch('intelligence.notifications.time.time',return_value=s['now']):self.n.flush(s['now'],s)
        s=self.fast(s['now']+.5);self.n.evaluate_delivered(s)
        r=self.db.execute('SELECT * FROM intel_sim ORDER BY id LIMIT 1').fetchone();self.assertGreater(r['entry_due'],r['signal_ts'])
        s=self.fast(s['now']+2);Simulator(self.db).update(s)
        s=self.fast(s['now']+20);Simulator(self.db).update(s)
        report=performance(self.db);g=next(g for g in report['groups'] if g['category']=='scalp' and g['window']==20)
        self.assertEqual(g['closed'],1);self.assertLess(g['net_pnl'],0);self.assertEqual(g['watch_closed'],1)
    def test_heuristic_only_never_generates_new_directional_entry(self):
        s=snapshot();self.n.directional(s,{'rows':[{'side':'UP','estimated_edge':.9}]},{'validated':False})
        self.assertEqual(self.db.execute('SELECT count(*) FROM intel_alerts').fetchone()[0],0)
    def test_qualified_calibrated_entry_does_not_require_strong_label(self):
        s=snapshot();s['book']=Book.parse({'yes_dollars':[['.49','100']],'no_dollars':[['.50','100']]})
        r={'side':'UP','observed_entry_ask':.5,'executable_entry':.502,'taker_fee':.0175,'estimated_probability':.65,'estimated_edge':.1305}
        self.n.directional(s,{'rows':[r]},{'validated':True,'version':'test-only','sample_size':200,'probability':.65})
        row=self.db.execute('SELECT * FROM intel_alerts').fetchone();self.assertIn('POTENTIAL UP ENTRY',row['message']);self.assertIn('after-cost edge',row['message'])
    def test_withdrawal_sent_once_only_after_delivery(self):
        self.db.execute("INSERT INTO intel_alerts(key,category,ticker,created,expires,state,sent) VALUES('e','directional','M',100,110,'sent',101)")
        self.db.execute("INSERT INTO intel_entry_state VALUES('M','UP','e',100,110,1,NULL)");self.db.commit()
        self.n.withdraw({'now':111,'market':{'ticker':'M'}},[]);self.n.withdraw({'now':112,'market':{'ticker':'M'}},[])
        self.assertEqual(self.db.execute("SELECT count(*) FROM intel_alerts WHERE category='withdrawal'").fetchone()[0],1)
    def test_reversal_invalidates_pending_scalp(self):
        s=self.fast();self.scalp_queue(s);s['tick_metrics']['acceleration']=-1
        with patch('intelligence.notifications.time.time',return_value=s['now']):self.n.flush(s['now'],s)
        self.telegram.send.assert_not_called()
    def test_cross_market_and_future_ticks_cannot_pass_fast_gate(self):
        s=self.fast();s['book_history']=[{**r,'ticker':'OTHER'} for r in s['book_history']];self.assertFalse(fast_scalp_data(s))
        s=self.fast();s['quote_ts']+=10;self.assertFalse(fast_scalp_data(s))

class FlipFollowupTests(Base):
    def seed(self,s):
        r=flip_radar(s)['rows'][0]
        self.db.execute("INSERT INTO intel_flip_followups(radar_id,ticker,side,signal_ts,entry_due,target,signal) VALUES(1,?,?,?,?,?,'POTENTIAL OPPORTUNITY')",(s['market']['ticker'],'UP',s['now'],s['now']+2,r['possible_exit_target']));self.db.commit()
    def test_every_signal_study_uses_delayed_ask_then_real_bid(self):
        s=snapshot();self.seed(s);evaluate_flips(self.db,s);self.assertEqual(self.db.execute('SELECT state FROM intel_flip_followups').fetchone()[0],'WAIT_ENTRY')
        s['now']+=2;s['book_ts']=s['now'];evaluate_flips(self.db,s)
        r=self.db.execute('SELECT * FROM intel_flip_followups').fetchone();self.assertEqual(r['state'],'OPEN')
        s['now']+=60;s['book_ts']=s['now'];evaluate_flips(self.db,s)
        r=self.db.execute('SELECT * FROM intel_flip_followups').fetchone();self.assertAlmostEqual(r['pnl'],r['exit']-r['entry']-r['entry_fee']-r['exit_fee'])
    def test_missing_future_exit_never_becomes_success(self):
        s=snapshot();self.seed(s);s['now']+=2;s['book_ts']=s['now'];evaluate_flips(self.db,s)
        s['now']+=70;s['book_ts']=s['now'];evaluate_flips(self.db,s)
        r=self.db.execute('SELECT * FROM intel_flip_followups').fetchone();self.assertEqual(r['state'],'MISSED_EXIT');self.assertIsNone(r['pnl'])
    def test_unvalidated_scenario_is_watch_not_demonstrated_ev(self):
        s=snapshot();r=compare_flips(self.db,s,flip_radar(s));self.assertEqual(r['assessment'],'WATCH')
        self.assertTrue(all(not x['historical']['validated'] for x in r['rows']))

class SettingsAPITests(Base):
    def setUp(self):
        super().setUp();self.env=patch.dict(os.environ,{'DASHBOARD_PASSWORD':'unit-test-password'});self.env.start();self.dbpatch=patch.object(dashboard,'DB',self.path);self.dbpatch.start()
        self.client=dashboard.app.test_client();self.auth={'Authorization':'Basic '+base64.b64encode(b'viewer:unit-test-password').decode()}
    def tearDown(self):self.dbpatch.stop();self.env.stop();super().tearDown()
    def test_auth_csrf_origin_and_boolean_validation(self):
        self.assertEqual(self.client.get('/api/alert-settings').status_code,401)
        self.assertEqual(self.client.post('/api/alert-settings',json={'scalp':True},headers=self.auth).status_code,403)
        data=self.client.get('/api/alert-settings',headers=self.auth).json;headers={**self.auth,'X-Alert-CSRF':data['csrf']}
        self.assertEqual(self.client.post('/api/alert-settings',json={'scalp':True},headers={**headers,'Origin':'https://evil.example'}).status_code,403)
        self.assertEqual(self.client.post('/api/alert-settings',json={'scalp':'true'},headers=headers).status_code,400)
        self.assertEqual(self.client.post('/api/alert-settings',json={'scalp':True,'locked':False},headers=headers).status_code,200)
        self.assertTrue(settings(self.db)['scalp']);self.assertFalse(settings(self.db)['locked'])
        self.assertNotIn('TELEGRAM_BOT_TOKEN',json.dumps(data))

class InPlaceUpdaterTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.base=Path(self.tmp.name).resolve();self.source=self.base/'new';self.target=self.base/'installed'
        self.source.mkdir();self.target.mkdir();(self.target/'data').mkdir();(self.target/'.venv').mkdir()
        (self.target/'.venv'/'keep').write_bytes(b'private-venv');(self.target/'data'/'credentials.dpapi').write_bytes(b'encrypted-secret-unchanged')
        (self.target/'data'/'research.csv').write_bytes(b'actual research history')
        (self.target/'scanner.py').write_text('old code');(self.source/'scanner.py').write_text('new code');(self.source/'extra.py').write_text('new helper')
        db=sqlite3.connect(self.target/'data'/'live.sqlite3');db.execute('CREATE TABLE history(value TEXT)');db.execute("INSERT INTO history VALUES('keep original')");db.commit();db.close()
        self.manifest={'scanner.py':hashlib.sha256((self.source/'scanner.py').read_bytes()).hexdigest(),'extra.py':hashlib.sha256((self.source/'extra.py').read_bytes()).hexdigest()}
        (self.source/'update-files.json').write_text(json.dumps(self.manifest))
    def tearDown(self):self.tmp.cleanup()
    def test_inplace_preserves_database_credentials_research_and_venv(self):
        original=(self.target/'data'/'live.sqlite3').read_bytes();recovery=inplace_update.update(self.target,self.source)
        self.assertEqual((self.target/'data'/'live.sqlite3').read_bytes(),original)
        self.assertEqual((self.target/'scanner.py').read_text(),'new code');self.assertEqual((self.target/'.venv'/'keep').read_bytes(),b'private-venv')
        self.assertEqual((self.target/'data'/'credentials.dpapi').read_bytes(),b'encrypted-secret-unchanged');self.assertEqual((recovery/'data'/'research.csv').read_bytes(),b'actual research history')
    def test_rollback_retains_new_history_backup_and_restores_matching_old_data(self):
        recovery=inplace_update.update(self.target,self.source)
        db=sqlite3.connect(self.target/'data'/'live.sqlite3');db.execute("INSERT INTO history VALUES('new history')");db.commit();db.close()
        previous=inplace_update.rollback(recovery)
        db=sqlite3.connect(self.target/'data'/'live.sqlite3');self.assertEqual(db.execute('SELECT count(*) FROM history').fetchone()[0],1);db.close()
        db=sqlite3.connect(previous/'live.sqlite3');self.assertEqual(db.execute('SELECT count(*) FROM history').fetchone()[0],2);db.close()
        self.assertEqual((self.target/'scanner.py').read_text(),'old code');self.assertFalse((self.target/'extra.py').exists())
    def test_corrupt_source_and_unsafe_manifest_refused_without_writes(self):
        (self.source/'scanner.py').write_text('corrupted')
        with self.assertRaises(ValueError):inplace_update.update(self.target,self.source)
        self.assertEqual((self.target/'scanner.py').read_text(),'old code')
        (self.source/'update-files.json').write_text(json.dumps({'../escape':'bad'}))
        with self.assertRaises(ValueError):inplace_update.update(self.target,self.source)
    def test_running_local_scanner_refused(self):
        guard=inplace_update.lock_old(self.target/'data'/'live.sqlite3')
        try:
            with self.assertRaisesRegex(ValueError,'still running'):inplace_update.update(self.target,self.source)
        finally:guard.close()
        self.assertEqual((self.target/'scanner.py').read_text(),'old code')
    def test_backup_failure_prevents_all_code_changes(self):
        with patch('inplace_update.online_copy',side_effect=sqlite3.DatabaseError('broken database')):
            with self.assertRaises(sqlite3.DatabaseError):inplace_update.update(self.target,self.source)
        self.assertEqual((self.target/'scanner.py').read_text(),'old code')
    def test_partial_copy_failure_restores_changed_code(self):
        original=__import__('shutil').copy2
        def copy(src,dest,*args,**kwargs):
            if Path(src)==self.source/'extra.py':raise OSError('simulated disk error')
            return original(src,dest,*args,**kwargs)
        with patch('inplace_update.shutil.copy2',side_effect=copy):
            with self.assertRaises(OSError):inplace_update.update(self.target,self.source)
        self.assertEqual((self.target/'scanner.py').read_text(),'old code');self.assertFalse((self.target/'extra.py').exists())
    def test_no_data_or_secret_files_allowed_in_update_manifest(self):
        (self.source/'update-files.json').write_text(json.dumps({'data/live.sqlite3':'bad'}))
        with self.assertRaises(ValueError):inplace_update.update(self.target,self.source)

class ObserverLiquidityTests(Base):
    def test_repeated_poll_does_not_reuse_one_contract_depth(self):
        s=snapshot();s['book']=Book.parse({'yes_dollars':[['.48','1']],'no_dollars':[['.49','1']]});sim=Simulator(self.db)
        sim.propose('a','scalp','scalp',s,'UP',20);sim.propose('b','scalp','scalp',s,'UP',40)
        s['now']+=2;s['book_ts']=s['now'];sim.update(s);s['now']+=.2;sim.update(s)
        self.assertEqual(self.db.execute("SELECT count(*) FROM intel_sim WHERE state='OPEN'").fetchone()[0],1)
    def test_missing_entry_data_never_creates_pnl_or_direction_win(self):
        s=snapshot();save(self.db,{'flip':True})
        self.n.enqueue('flip',s['market']['ticker'],'x','test',s['now'],s['now']+10,{'side':'UP','window':60})
        with self.db:
            self.db.execute("UPDATE intel_alerts SET state='sent',sent=?",(s['now'],))
            self.db.execute("UPDATE intel_alert_evidence SET sent=?,evaluation='AWAITING_LIVE_OBSERVATION'",(s['now'],))
        s['now']+=5;self.n.evaluate_delivered(s)
        p=performance(self.db);self.assertEqual(p['rows'][0]['evaluation'],'MISSED_POST_DELIVERY_OBSERVATION');self.assertIsNone(p['rows'][0]['pnl'])
    def test_official_alert_direction_result_separate_from_after_cost_pnl(self):
        s=snapshot();m=s['market']['raw'];register_market(self.db,m,s['now'])
        self.n.enqueue('locked',m['ticker'],'k','forecast',s['now'],s['now']+30,{'side':'UP','p_up':.6})
        self.n.flush(s['now']);m.update(status='finalized',result='yes');register_market(self.db,m,s['now']+900)
        p=performance(self.db);row=p['rows'][0];self.assertTrue(row['directional_correct']);self.assertIsNone(row['pnl'])
        g=next(g for g in p['groups'] if g['category']=='locked');self.assertEqual(g['directional_wins'],1);self.assertEqual(g['closed'],0)

class IndependentObserverTests(Base):
    def test_cached_fast_inputs_fill_despite_slow_collector_cycle(self):
        from intelligence.service import IntelligenceWorker
        s=snapshot();now=s['now'];old=snapshot(now-2);old.update(fee_valid=True,fee_multiplier=1)
        Simulator(self.db).propose('delayed','directional','test',old,'UP',None)
        worker=IntelligenceWorker(self.path,None);worker.latest_snapshot=old;worker.scheduler=Mock();worker.scheduler.snapshot.return_value=(s,None,{})
        worker.stop=Mock();worker.stop.is_set.side_effect=[False,True];worker.stream=Mock();worker.stream.snapshot.return_value=None
        with patch('intelligence.service.time.time',return_value=now):worker.observe_execution()
        self.assertEqual(self.db.execute("SELECT state FROM intel_sim WHERE key='delayed'").fetchone()[0],'OPEN')
    def test_alert_evidence_cannot_be_rewritten_after_later_quotes(self):
        self.n.enqueue('locked','M','locked:M','forecast',100,130,{'side':'UP','p_up':.6})
        with self.assertRaises(sqlite3.IntegrityError):self.db.execute("UPDATE intel_alert_evidence SET snapshot='{}'")
        self.db.rollback()

class UnifiedOutcomeTests(Base):
    def test_original_and_new_outcomes_use_one_dispatcher_and_unique_key(self):
        store=Store(self.path)
        try:
            with store.db:store.db.execute("INSERT INTO outcome_alerts(ticker,created,message) VALUES('M',100,'Official result test')")
            with patch.dict(os.environ,{'TELEGRAM_BOT_TOKEN':'unit-fake-token','TELEGRAM_CHAT_ID':'unit-fake-chat'}):telegram=Telegram()
            telegram.send=Mock();telegram.flush(store,100)
            self.assertEqual(store.db.execute('SELECT status FROM outcome_alerts').fetchone()[0],'forwarded');telegram.send.assert_not_called()
            n=Notifications(store.db,telegram);n.enqueue('settlement','M','final:M','Duplicate outcome',100,200);n.flush(100);telegram.flush(store,101);n.flush(101)
            self.assertEqual(telegram.send.call_count,1)
        finally:store.db.close()
