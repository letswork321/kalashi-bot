import tempfile
from pathlib import Path
import unittest
from unittest.mock import Mock,patch
from intelligence.storage import migrate
from intelligence.notifications import Notifications

class NotificationTests(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.db=migrate(Path(self.tmp.name)/'test.sqlite3');self.telegram=Mock(enabled=True)
    def tearDown(self):self.db.close();self.tmp.cleanup()
    def test_new_categories_are_off_by_default(self):
        with patch.dict('os.environ',{'INTELLIGENCE_ALERT_CATEGORIES':''}):n=Notifications(self.db,self.telegram)
        self.assertFalse(n.enqueue('breakout','M','key','test',100,200))
    def test_dedupe_cooldown_and_expiration(self):
        with patch.dict('os.environ',{'INTELLIGENCE_ALERT_CATEGORIES':'breakout'}):n=Notifications(self.db,self.telegram)
        n.enqueue('breakout','M','key','test',100,200);n.enqueue('breakout','M','key','test',101,200);n.enqueue('breakout','M','other','test',102,200)
        self.assertEqual(self.db.execute('SELECT count(*) FROM intel_alerts').fetchone()[0],1)
        n.flush(201);self.telegram.send.assert_not_called()
    def test_global_hourly_limit(self):
        with patch.dict('os.environ',{'INTELLIGENCE_ALERT_CATEGORIES':'breakout'}):n=Notifications(self.db,self.telegram)
        for i in range(10):n.enqueue('breakout',str(i),str(i),'test',100,10000)
        for _ in range(10):n.flush(101)
        self.assertEqual(self.telegram.send.call_count,6)
    def test_retry_preserves_unsent_state(self):
        with patch.dict('os.environ',{'INTELLIGENCE_ALERT_CATEGORIES':'breakout'}):n=Notifications(self.db,self.telegram)
        n.enqueue('breakout','M','key','test',100,200);self.telegram.send.side_effect=RuntimeError('network')
        n.flush(101);r=self.db.execute('SELECT * FROM intel_alerts').fetchone();self.assertEqual(r['state'],'pending');self.assertEqual(r['attempts'],1)
