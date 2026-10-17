import base64
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import dashboard
from intelligence.storage import migrate

class IntelligenceDashboardTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'data.sqlite3';db=migrate(self.path);db.close()
        self.env=patch.dict(os.environ,{'DASHBOARD_PASSWORD':'unit-test-password'});self.env.start();self.dbpatch=patch.object(dashboard,'DB',self.path);self.dbpatch.start();dashboard._intel_cache.clear()
        self.client=dashboard.app.test_client();self.auth={'Authorization':'Basic '+base64.b64encode(b'viewer:unit-test-password').decode()}
    def tearDown(self):self.dbpatch.stop();self.env.stop();self.tmp.cleanup()
    def test_intelligence_requires_existing_auth(self):self.assertEqual(self.client.get('/api/intelligence').status_code,401)
    def test_all_ranges_work_without_history(self):
        for value in ('today','7','30','all'):
            r=self.client.get('/api/intelligence?range='+value,headers=self.auth);self.assertEqual(r.status_code,200);self.assertEqual(r.json['tracker']['sample_size'],0)
    def test_bad_ranges_rejected(self):self.assertEqual(self.client.get('/api/intelligence?days=1000',headers=self.auth).status_code,400)
    def test_all_panels_and_same_site_script_exist(self):
        r=self.client.get('/',headers=self.auth)
        for text in [b'15-Minute Prediction Tracker',b'Three Independent Strategy Engines',b'Flip Radar',b'Scalp Radar',b'Fair Value',b'Market Regime',b'Historical Research',b'Model Evaluation Center',b'Advanced Paper Trade Simulator']:
            self.assertIn(text,r.data)
        script=self.client.get('/static/intelligence.js',headers=self.auth);self.assertEqual(script.status_code,200);script.close()
    def test_no_write_api_added(self):self.assertEqual(self.client.post('/api/intelligence',headers=self.auth).status_code,405)
