import contextlib
import io
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock, patch
import requests
import scanner as s

class Fixture:
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = s.Store(Path(self.temp.name)/'test.sqlite3')
        self.config = s.Config()
        self.now = int(time.time()//60)*60+10
        self.market,self.book,self.feed = s.mock_inputs(self.now)
        self.market['ticker']='KXBTC15M-TEST'

    def tearDown(self):
        self.store.db.close()
        self.temp.cleanup()

    def prediction(self):
        return s.analyze(self.market,self.book,self.feed,self.now,self.config,1)

class ScannerTests(Fixture, unittest.TestCase):
    def test_dollars_best_bid_and_complement_depth(self):
        b=s.Book.parse({'yes_dollars':[['0.20','2'],['0.60','4']], 'no_dollars':[['0.30','2'],['0.35','1']]})
        self.assertEqual(b.yes[0][0],.60)
        self.assertAlmostEqual(b.spread,.05)
        self.assertAlmostEqual(b.entry('UP',2,0),.675)
        with self.assertRaises(s.DataError): b.entry('UP',5,0)
        with self.assertRaises(s.DataError): s.Book.parse({'yes_dollars':[['60','2']], 'no_dollars':[['0.2','2']]})

    def test_guard_stale_missing_strike_and_late(self):
        self.feed.time=self.now-21
        with self.assertRaises(s.DataError): self.prediction()
        self.feed.time=self.now
        self.market['floor_strike']=None
        with self.assertRaises(s.DataError): self.prediction()
        self.market['floor_strike']=80500
        self.market['close_time']=s.datetime.fromtimestamp(self.now+60,s.timezone.utc).isoformat()
        p=self.prediction()
        self.assertEqual(p['signal'],'NO TRADE')

    def test_indicator_gaps_and_rsi(self):
        f=s.indicators(self.feed,self.now)
        self.assertGreater(f['ema9'],f['ema21'])
        self.assertEqual(f['rsi14'],100)
        self.feed.candles.pop(-10)
        with self.assertRaises(s.DataError): s.indicators(self.feed,self.now)

    def test_probability_and_fee(self):
        p=self.prediction()
        self.assertFalse(p['calibrated'])
        self.assertAlmostEqual(p['p_up']+p['p_down'],1)
        self.assertGreaterEqual(p['p_up'],.05)
        self.assertEqual(s.fee(.5,1,.07,1),.0175)
        self.assertEqual(s.fee(.5,100,.07,1),1.75)

    def test_official_settlement_idempotent_and_paper_fees(self):
        p=self.prediction()
        self.assertEqual(p['signal'],'UP')
        self.store.record(p,self.config)
        self.store.record(p,self.config)
        self.assertEqual(self.store.report()['paper_open'],1)
        m=dict(self.market,result='yes',status='closed')
        self.assertFalse(self.store.settle(m,self.now+900))
        m['status']='finalized'
        self.assertTrue(self.store.settle(m,self.now+901))
        self.store.settle(m,self.now+902)
        report=self.store.report()
        self.assertEqual(report['settled_forecasts'],2)
        self.assertEqual(report['settled_distinct_markets'],1)
        self.assertEqual(report['paper_settled'],1)
        self.assertAlmostEqual(report['paper_net_pnl'],1-p['candidate']['entry']-p['candidate']['fee'])
        self.assertEqual(report['first_forecast_per_market_accuracy'],1)

    def test_down_loss_and_pending_not_counted(self):
        p=self.prediction()
        p['signal']='DOWN'
        self.store.record(p,self.config)
        self.assertIsNone(self.store.report()['paper_win_rate'])
        self.store.settle(dict(self.market,status='finalized',result='yes'),self.now+901)
        self.assertLess(self.store.report()['paper_net_pnl'],0)
        self.assertEqual(self.store.report()['actionable_signal_accuracy'],0)

    def test_mock_cannot_mix_database_modes(self):
        with self.assertRaises(s.DataError): s.Store(Path(self.temp.name)/'test.sqlite3','mock')

    def test_no_live_fallback_on_network_failure(self):
        e=s.Engine(self.store,self.config)
        e.last_settle=self.now
        e.kalshi.current=Mock(return_value=self.market)
        e.kalshi.fees=Mock(return_value=1)
        e.kalshi.book=Mock(return_value=self.book)
        e.btc.snapshot=Mock(side_effect=s.DataError('Blocked live feed'))
        with contextlib.redirect_stdout(io.StringIO()): p=e.cycle()
        self.assertEqual(p['signal'],'NO TRADE')
        self.assertIsNone(p['p_up'])
        self.assertEqual(self.store.report()['paper_open'],0)

    def test_alert_dedup_retry_and_redaction(self):
        p=self.prediction()
        p['strength']='STRONG'
        self.store.record(p,self.config,True)
        self.store.record(p,self.config,True)
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM alerts').fetchone()[0],1)
        with patch.dict(s.os.environ,{'TELEGRAM_BOT_TOKEN':'SECRET123','TELEGRAM_CHAT_ID':'123'}): t=s.Telegram()
        t.session.post=Mock(side_effect=requests.ConnectionError('https://api.telegram.org/botSECRET123'))
        with self.assertRaises(s.DataError) as ctx: t.send('test')
        self.assertNotIn('SECRET123',str(ctx.exception))
        with contextlib.redirect_stdout(io.StringIO()): t.flush(self.store,self.now)
        r=self.store.db.execute('SELECT * FROM alerts').fetchone()
        self.assertEqual(r['status'],'pending')
        self.assertEqual(r['attempts'],1)
        t.session.post=Mock(return_value=Mock(ok=True,status_code=200,json=lambda:{'ok':True}))
        t.flush(self.store,self.now+20)
        self.assertEqual(self.store.db.execute('SELECT status FROM alerts').fetchone()[0],'sent')

    def test_market_discovery_uses_time_window(self):
        h=Mock()
        future=dict(self.market,ticker='KXBTC15M-FUTURE',open_time=s.datetime.fromtimestamp(self.now+60,s.timezone.utc).isoformat())
        h.get.side_effect=[{'markets':[future,self.market],'cursor':''},{'market':self.market}]
        self.assertEqual(s.Kalshi(h).current(self.now)['ticker'],self.market['ticker'])


class NotificationTests(Fixture, unittest.TestCase):
    def test_first_weak_quiet_then_strong_once(self):
        p=self.prediction();p['strength']='WEAK'
        self.store.record(p,self.config,True)
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM alerts').fetchone()[0],0)
        p['strength']='STRONG';self.store.record(p,self.config,True)
        p['observed_at']+=20;self.store.record(p,self.config,True)
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM alerts').fetchone()[0],1)

    def test_outcome_dedup_and_delivery(self):
        p=self.prediction();self.store.record(p,self.config,True)
        m=dict(self.market,status='finalized',result='no')
        self.store.settle(m,self.now+901,alerts=True)
        self.store.settle(m,self.now+902,alerts=True)
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM outcome_alerts').fetchone()[0],1)
        with patch.dict(s.os.environ,{'TELEGRAM_BOT_TOKEN':'test','TELEGRAM_CHAT_ID':'123'}): t=s.Telegram()
        t.send=Mock(return_value=True)
        t.flush(self.store,self.now+1000,signals=False)
        t.send.assert_called_once()
        self.assertIn('LOSS',t.send.call_args[0][0])
        t.flush(self.store,self.now+1001,signals=False)
        t.send.assert_called_once()

    def test_reversal_during_cooldown_cancels_old_message(self):
        p=self.prediction();p['strength']='STRONG'
        self.store.record(p,self.config,True)
        p['observed_at']+=5;p['signal']='DOWN';p['candidate']['probability']=.8
        self.store.record(p,self.config,True)
        self.assertEqual(self.store.db.execute('SELECT status FROM alerts').fetchone()[0],'superseded')
        p['observed_at']+=60
        self.store.record(p,self.config,True)
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM alerts WHERE status='pending'").fetchone()[0],1)


class ApiContractTests(unittest.TestCase):
    def test_scheduled_event_fee_override(self):
        h=Mock()
        h.get.side_effect=[{'series':{'fee_type':'quadratic','fee_multiplier':1}},
                          {'cursor':'','event_fee_changes':[
                              {'event_ticker':'E','fee_type_override':'quadratic','fee_multiplier_override':2,'scheduled_ts':'2020-01-01T00:00:00Z'},
                              {'event_ticker':'E','fee_type_override':'flat','fee_multiplier_override':99,'scheduled_ts':'2099-01-01T00:00:00Z'}]}]
        self.assertEqual(s.Kalshi(h).fees({'event_ticker':'E'},time.time()),2)

    def test_rolling_candle_request(self):
        h=Mock();now=time.time()
        h.get.side_effect=[{'price':'80000','time':s.datetime.fromtimestamp(now,s.timezone.utc).isoformat()},[[int(now)-60,79990,80010,80000,80000,1]]]
        feed=s.Coinbase(h).snapshot(now)
        self.assertEqual(feed.price,80000)
        params=h.get.call_args[0][2]
        self.assertEqual(params['granularity'],60)
        self.assertIn('start',params);self.assertIn('end',params)

    def test_nonfinite_inputs_rejected(self):
        for value in ['NaN','Infinity','-Infinity',None]:
            with self.assertRaises(s.DataError): s.number(value)

if __name__=='__main__': unittest.main()

class ProcessLockTests(unittest.TestCase):
    def test_windows_lock_branch(self):
        fake=Mock()
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'ledger.sqlite3'
            with patch.object(s.os,'name','nt'), patch.dict(s.sys.modules,{'msvcrt':fake}):
                handle=s.acquire_lock(path)
                fake.locking.assert_called_once_with(handle.fileno(),fake.LK_NBLCK,1)
                handle.close()
            self.assertEqual(Path(str(path)+'.lock').read_bytes(),b'0')

    def test_unix_duplicate_process_lock(self):
        if s.os.name=='nt':self.skipTest('Unix-specific subprocess contract')
        import subprocess,sys
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'ledger.sqlite3'
            handle=s.acquire_lock(path)
            try:
                code='import scanner; scanner.acquire_lock('+repr(str(path))+')'
                result=subprocess.run([sys.executable,'-c',code],capture_output=True,text=True)
                self.assertNotEqual(result.returncode,0)
                self.assertIn('already running',result.stderr)
            finally:handle.close()
