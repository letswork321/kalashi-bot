"""Realistic source verification; fresh transport alone never proves continuity."""
from datetime import datetime,timezone
import json,sqlite3,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch
from intelligence.live_feed import TradeTape,CoinbaseStream
from intelligence.storage import migrate,dumps
from intelligence.chart_data import payload

NOW=1800000060

def match(i,event,kind='match'):
 return {'type':kind,'product_id':'BTC-USD','trade_id':i,'time':datetime.fromtimestamp(event,timezone.utc).isoformat(),'price':'100','size':'1','side':'sell'}

class SourceVerificationTests(unittest.TestCase):
 def test_fresh_consecutive_01_to_04_second_quotes_do_not_flicker(self):
  tape=TradeTape();tape.apply(match(1,NOW),NOW)
  for i in range(2,102):
   event=NOW+i*.1;tape.apply(match(i,event),event+.01)
   for age in (.1,.2,.4):self.assertEqual(tape.snapshot(event+age)['status'],'LIVE')
   tape.apply(match(i,event),event+.05)
  self.assertEqual(tape.gaps,0);self.assertEqual(tape.duplicates,100)
 def test_reordered_actual_trades_recover_without_fake_gap(self):
  tape=TradeTape();tape.apply(match(1,NOW),NOW);tape.apply(match(3,NOW+.2),NOW+.22)
  self.assertEqual(tape.snapshot(NOW+.23)['status'],'RESYNCING')
  tape.apply(match(2,NOW+.1),NOW+.24)
  self.assertEqual([r['id'] for r in tape.rows],[1,2,3]);self.assertEqual(tape.snapshot(NOW+.3)['status'],'LIVE');self.assertEqual(tape.gaps,0)
 def test_real_missing_id_is_not_marked_live_or_repaired_with_synthetic_data(self):
  tape=TradeTape();tape.apply(match(1,NOW),NOW);tape.apply(match(2,NOW+.1),NOW+.1);tape.apply(match(4,NOW+.2),NOW+.2)
  self.assertEqual(tape.snapshot(NOW+.3)['status'],'RESYNCING');self.assertNotEqual(tape.snapshot(NOW+.5)['status'],'LIVE');self.assertEqual(tape.gaps,1);self.assertEqual(tape.last_gap['expected'],3);self.assertNotIn(3,[r['id'] for r in tape.rows])
  tape.apply(match(5,NOW+.6),NOW+.6);self.assertEqual(tape.snapshot(NOW+.7)['status'],'LIVE');self.assertEqual(tape.gaps,1)
 def test_quiet_interval_with_proven_consecutive_id_is_not_missing_trade(self):
  tape=TradeTape();tape.apply(match(1,NOW),NOW);self.assertEqual(tape.snapshot(NOW+4)['status'],'STALE');tape.apply(match(2,NOW+4.1),NOW+4.1);self.assertEqual(tape.snapshot(NOW+4.3)['status'],'LIVE');self.assertEqual(tape.gaps,0)
 def test_reconnect_discards_old_epoch_verification(self):
  tape=TradeTape();tape.apply(match(1,NOW),NOW);tape.apply(match(2,NOW+.1),NOW+.1);tape.reset();d=tape.snapshot(NOW+.2);self.assertEqual(d['status'],'RESYNCING');self.assertIsNone(d['price'])
  tape.apply(match(5,NOW+.3),NOW+.3);self.assertNotEqual(tape.snapshot(NOW+.4)['status'],'LIVE');tape.apply(match(6,NOW+.5),NOW+.5);self.assertEqual(tape.snapshot(NOW+.6)['status'],'LIVE')
 def test_delayed_subscription_snapshot_cannot_override_live_sequence(self):
  tape=TradeTape();tape.apply(match(1,NOW),NOW);tape.apply(match(2,NOW+.1),NOW+.1);tape.apply(match(999,NOW+.2,'last_match'),NOW+.2);self.assertEqual(tape.last_id,2);self.assertEqual(tape.gaps,0)
 def test_future_clock_skew_and_timezone_rejection(self):
  tape=TradeTape();tape.apply(match(1,NOW+.4),NOW);tape.apply(match(2,NOW+.5),NOW+.1);self.assertEqual(tape.snapshot(NOW+.2)['status'],'CLOCK SKEW')
  msg=match(3,NOW+.6);msg['time']='2027-01-15T00:00:00';self.assertIsNone(tape.apply(msg,NOW+.6));self.assertEqual(tape.rejected,1)
 def test_stalled_heartbeat_only_socket_reconnects(self):
  stream=CoinbaseStream();sock=Mock();sock.recv.return_value=json.dumps({'type':'heartbeat','product_id':'BTC-USD','last_trade_id':100,'time':datetime.fromtimestamp(NOW,timezone.utc).isoformat()})
  def pause(_):stream.stop.set();return True
  with patch('websocket.create_connection',return_value=sock),patch('intelligence.live_feed.time.time',return_value=NOW),patch('intelligence.live_feed.time.monotonic',side_effect=[0,11]),patch.object(stream.stop,'wait',side_effect=pause):stream.run()
  self.assertEqual(stream.tape.reconnects,1);self.assertEqual(stream.tape.error['type'],'TimeoutError');self.assertEqual(stream.snapshot(NOW)['status'],'UNAVAILABLE');sock.close.assert_called()
 def test_pending_reorder_buffer_is_bounded(self):
  tape=TradeTape();tape.apply(match(1,NOW),NOW)
  for i in range(3,400):tape.apply(match(i,NOW+.01),NOW+.01)
  self.assertLess(len(tape.pending),tape.MAX_PENDING);self.assertGreater(tape.gaps,0)

class ChartVerificationTests(unittest.TestCase):
 def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.db=migrate(Path(self.tmp.name)/'history.sqlite3')
 def tearDown(self):self.db.close();self.tmp.cleanup()
 def state(self,status,stored=NOW,event=NOW-.1):
  with self.db:self.db.execute("INSERT OR REPLACE INTO v3_state VALUES('spot',?,?)",(stored,dumps({'status':status,'event_ts':event,'price':100})))
 def test_fresh_resync_not_misrepresented_as_stale_or_live(self):
  self.state('RESYNCING');self.assertEqual(payload(self.db,'1m',NOW)['status'],'RESYNCING')
 def test_fresh_event_cannot_hide_observer_delay(self):
  self.state('LIVE',stored=NOW-5);self.assertEqual(payload(self.db,'1m',NOW)['status'],'OBSERVER DELAY')
 def test_verified_fresh_quotes_live_and_actual_age_stale(self):
  for age in (.1,.4):self.state('LIVE',event=NOW-age);self.assertEqual(payload(self.db,'1m',NOW)['status'],'LIVE')
  self.state('LIVE',event=NOW-4);self.assertEqual(payload(self.db,'1m',NOW)['status'],'STALE')
