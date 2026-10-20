"""Real lock/recovery tests use isolated databases, never production histories."""
import os,sqlite3,tempfile,threading,time,unittest
from pathlib import Path
from unittest.mock import Mock,patch
from sqlite_runtime import open_database,busy,health_write
from intelligence.storage import migrate,register_market,lock_forecast
from intelligence.notifications import Notifications
from intelligence.alert_settings import save
from intelligence.recovery import resilient
from intel_helpers import market
import windows_runner

class StorageRecoveryTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'history.sqlite3';self.db=open_database(self.path);self.db.execute('CREATE TABLE records(value INTEGER)')
 def tearDown(self):self.db.close();self.tmp.cleanup()
 def holder(self,duration):
  ready=threading.Event()
  def hold():
   db=sqlite3.connect(self.path);db.execute('BEGIN IMMEDIATE');ready.set();time.sleep(duration);db.rollback();db.close()
  t=threading.Thread(target=hold);t.start();self.assertTrue(ready.wait(2));return t
 def test_external_writer_release_is_retried_without_reset(self):
  t=self.holder(.3);start=time.monotonic()
  try:
   with self.db:self.db.execute('INSERT INTO records VALUES(7)')
  finally:t.join()
  self.assertGreater(time.monotonic()-start,.2);self.assertEqual(self.db.execute('SELECT value FROM records').fetchone()[0],7);self.assertFalse(self.db.in_transaction)
 def test_exhaustion_is_bounded_and_next_cycle_recovers(self):
  t=self.holder(.5);start=time.monotonic()
  try:
   with patch('sqlite_runtime.RETRY_SECONDS',.1):
    with self.assertRaises(sqlite3.OperationalError):
     with self.db:self.db.execute('INSERT INTO records VALUES(1)')
   self.assertLess(time.monotonic()-start,.45)
  finally:t.join()
  with self.db:self.db.execute('INSERT INTO records VALUES(2)')
  self.assertEqual([r[0] for r in self.db.execute('SELECT value FROM records')],[2])
 def test_nested_scope_rollback_and_atomic_outer_transaction(self):
  with self.db:
   self.db.execute('INSERT INTO records VALUES(1)')
   try:
    with self.db:self.db.execute('INSERT INTO records VALUES(2)');raise ValueError('fixture')
   except ValueError:pass
   self.db.execute('INSERT INTO records VALUES(3)')
  self.assertEqual([r[0] for r in self.db.execute('SELECT value FROM records')],[1,3])
  with self.assertRaises(ValueError):
   with self.db:self.db.execute('INSERT INTO records VALUES(4)');raise ValueError('fixture')
  self.assertEqual(self.db.execute('SELECT count(*) FROM records').fetchone()[0],2)
 def test_bare_writes_do_not_hold_transactions_during_io(self):
  self.db.execute('INSERT INTO records VALUES(1)');self.assertFalse(self.db.in_transaction)
  other=open_database(self.path)
  try:
   with other:other.execute('INSERT INTO records VALUES(2)')
  finally:other.close()
 def test_reader_remains_available_during_writer(self):
  reader=open_database(self.path,True)
  try:
   with self.db:
    self.db.execute('INSERT INTO records VALUES(1)');self.assertEqual(reader.execute('SELECT count(*) FROM records').fetchone()[0],0)
   self.assertEqual(reader.execute('SELECT count(*) FROM records').fetchone()[0],1)
   with self.assertRaises(sqlite3.OperationalError):reader.execute('DELETE FROM records')
  finally:reader.close()
 def test_multiple_application_writers_preserve_all_rows(self):
  errors=[]
  def work():
   db=open_database(self.path)
   try:
    for i in range(30):
     with db:db.execute('INSERT INTO records VALUES(?)',(i,))
   except Exception as exc:errors.append(exc)
   finally:db.close()
  threads=[threading.Thread(target=work) for _ in range(6)]
  for t in threads:t.start()
  for t in threads:t.join(5)
  self.assertFalse(any(t.is_alive() for t in threads));self.assertEqual(errors,[]);self.assertEqual(self.db.execute('SELECT count(*) FROM records').fetchone()[0],180);self.assertEqual(self.db.execute('PRAGMA integrity_check').fetchone()[0],'ok')
 def test_non_lock_errors_are_not_retried_or_suppressed(self):
  self.assertFalse(busy(sqlite3.OperationalError('disk I/O error')))
  with self.assertRaises(sqlite3.OperationalError):
   with self.db:self.db.execute('INSERT INTO nonexistent VALUES(1)')
  self.assertFalse(self.db.in_transaction)
 def test_failed_health_report_cannot_kill_worker(self):
  t=self.holder(.3)
  try:
   with patch('sqlite_runtime.RETRY_SECONDS',.05):
    with health_write(self.db) as health:health.execute('INSERT INTO records VALUES(99)')
  finally:t.join()
  self.assertEqual(self.db.execute('SELECT count(*) FROM records').fetchone()[0],0)

class DecisionAndRecoveryTests(unittest.TestCase):
 def test_lock_wait_rechecks_deadline_and_never_backdates_prediction(self):
  with tempfile.TemporaryDirectory() as td:
   db=migrate(Path(td)/'db.sqlite3');m=market();now=1800000064;register_market(db,m,now-4)
   try:
    with patch('intelligence.storage.decision_time',side_effect=[10,12]):r=lock_forecast(db,m,{'p_up':.6,'observed_at':now,'btc_timestamp':now,'model':'baseline'},now,{},'RANGE')
    self.assertIsNone(r);row=db.execute('SELECT * FROM intel_locks').fetchone();self.assertEqual(row['state'],'MISSED');self.assertIsNone(row['direction'])
   finally:db.close()
 def test_worker_initialization_failure_retries_without_busy_health_write(self):
  class Worker:
   def __init__(self):self.stop=threading.Event();self.calls=0
   @resilient
   def run(self):
    self.calls+=1
    if self.calls==1:raise sqlite3.OperationalError('database is locked')
    self.stop.set()
  w=Worker()
  with patch.object(w.stop,'wait',return_value=False):w.run()
  self.assertEqual(w.calls,2)
 def test_windows_scanner_crash_does_not_terminate_dashboard(self):
  scanner=Mock();scanner.poll.return_value=1;web=Mock();web.poll.return_value=None;fresh=Mock();fresh.poll.return_value=None;children={'scanner':scanner,'dashboard':web};times=iter([0,0,0,2])
  with patch.object(windows_runner.subprocess,'Popen',return_value=fresh) as spawn:
   with self.assertRaises(KeyboardInterrupt):windows_runner.supervise(children,clock=lambda:next(times),pause=Mock(side_effect=[None,KeyboardInterrupt]))
  self.assertIs(children['scanner'],fresh);web.terminate.assert_not_called();self.assertEqual(spawn.call_args.args[0][1],'scanner.py')
 def test_windows_dashboard_crash_does_not_terminate_scanner(self):
  scanner=Mock();scanner.poll.return_value=None;web=Mock();web.poll.return_value=1;fresh=Mock();fresh.poll.return_value=None;children={'scanner':scanner,'dashboard':web};times=iter([0,0,0,2])
  with patch.object(windows_runner.subprocess,'Popen',return_value=fresh):
   with self.assertRaises(KeyboardInterrupt):windows_runner.supervise(children,clock=lambda:next(times),pause=Mock(side_effect=[None,KeyboardInterrupt]))
  self.assertIs(children['dashboard'],fresh);scanner.terminate.assert_not_called()
 def test_ack_persistence_failure_does_not_replay_accepted_alert(self):
  with tempfile.TemporaryDirectory() as td:
   db=migrate(Path(td)/'db.sqlite3');telegram=Mock(enabled=True);n=Notifications(db,telegram);save(db,{'locked':True});n.enqueue('locked','M','lock:M','forecast',100,1000)
   original=db.execute
   def execute(sql,*args,**kwargs):
    if "state='sent'" in sql:raise sqlite3.OperationalError('database is locked')
    return original(sql,*args,**kwargs)
   try:
    with patch.object(db,'execute',side_effect=execute):
     with self.assertRaises(sqlite3.OperationalError):n.flush(101)
    n.flush(102);self.assertEqual(telegram.send.call_count,1);self.assertEqual(db.execute('SELECT state FROM intel_alerts').fetchone()[0],'sending')
   finally:db.close()
