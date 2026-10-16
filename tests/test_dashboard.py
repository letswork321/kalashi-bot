import base64
import contextlib
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
import dashboard
import scanner as s

class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.path=Path(self.temp.name)/'live.sqlite3'
        self.env=patch.dict(os.environ,{'DASHBOARD_PASSWORD':'test-password-only'})
        self.env.start()
        self.dbpatch=patch.object(dashboard,'DB',self.path)
        self.dbpatch.start()
        self.client=dashboard.app.test_client()
        self.auth={'Authorization':'Basic '+base64.b64encode(b'viewer:test-password-only').decode()}

    def tearDown(self):
        self.dbpatch.stop();self.env.stop();self.temp.cleanup()

    def test_auth_and_security_headers(self):
        self.assertEqual(self.client.get('/').status_code,401)
        self.assertEqual(self.client.get('/api/state').status_code,401)
        r=self.client.get('/',headers=self.auth)
        self.assertEqual(r.status_code,200)
        self.assertIn(b'Official price to beat',r.data)
        self.assertEqual(r.headers['Cache-Control'],'no-store')
        self.assertEqual(self.client.get('/healthz').status_code,200)
        with patch.dict(os.environ,{'DASHBOARD_PASSWORD':''}):
            self.assertEqual(self.client.get('/').status_code,503)

    def test_missing_database_and_live_to_stale(self):
        r=self.client.get('/api/state',headers=self.auth)
        self.assertEqual(r.json['state'],'WAITING')
        st=s.Store(self.path)
        now=time.time()
        p=s.analyze(*s.mock_inputs(now),now,s.Config(),1)
        st.record(p,s.Config())
        st.db.close()
        r=self.client.get('/api/state',headers=self.auth)
        self.assertEqual(r.json['state'],'LIVE')
        self.assertEqual(len(r.json['recent']),1)
        self.assertEqual(len(r.json['prices']),1)
        self.assertEqual(r.json['stats']['paper_open'],1)
        with patch.object(dashboard.time,'time',return_value=now+60):
            self.assertEqual(self.client.get('/api/state',headers=self.auth).json['state'],'STALE')

    def test_mock_clearly_labelled(self):
        st=s.Store(self.path,'mock')
        now=time.time()
        p=s.analyze(*s.mock_inputs(now),now,s.Config(),1)
        st.record(p,s.Config());st.db.close()
        self.assertEqual(self.client.get('/api/state',headers=self.auth).json['state'],'MOCK TEST ONLY')

if __name__=='__main__': unittest.main()
