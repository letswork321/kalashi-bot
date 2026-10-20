"""Lifetime counts are database-backed and independent of market-data workers."""
import base64,os,sqlite3,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import dashboard
from intelligence.storage import migrate,register_market,lock_forecast
from intelligence.v3_dashboard import settlement_summary
from intel_helpers import market

class LifetimeScoreTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'history.sqlite3';self.db=migrate(self.path)
  self.env=patch.dict(os.environ,{'DASHBOARD_PASSWORD':'score-test-password'});self.env.start();self.override=patch.object(dashboard,'DB',self.path);self.override.start();self.client=dashboard.app.test_client();self.auth={'Authorization':'Basic '+base64.b64encode(b'viewer:score-test-password').decode()}
 def tearDown(self):self.override.stop();self.env.stop();self.db.close();self.tmp.cleanup()
 def seed(self,i,direction,result=None):
  op=1700000000+i*900;m=market(op,'KXBTC15M-HIST-'+str(i));register_market(self.db,m,op)
  lock_forecast(self.db,m,{'p_up':.6 if direction=='UP' else .4,'model':'V3 baseline','observed_at':op+60,'btc_timestamp':op+60},op+60,{},'RANGE')
  if result:m.update(status='finalized',result=result);register_market(self.db,m,op+901)
  return m
 def test_imported_lifetime_accuracy_pending_missed_and_shared_v3_definition(self):
  self.seed(0,'UP','yes');self.seed(1,'DOWN','no');self.seed(2,'DOWN','yes');self.seed(3,'UP')
  register_market(self.db,market(1700004000,'KXBTC15M-MISSED'),1700005000)
  self.db.execute("INSERT INTO intel_late_locks(ticker,scheduled,deadline,direction,p_up,observed,features,model,reason,strike,btc_price,result) VALUES('late',1,2,'UP',.6,3,'{}','old','late',100,101,'yes')");self.db.commit()
  before=[tuple(r) for r in self.db.execute('SELECT * FROM intel_locks')]
  r=self.client.get('/api/v4/scoreboard',headers=self.auth);self.assertEqual(r.status_code,200);s=r.json['settlement_score'];self.assertEqual(s,settlement_summary(self.db));self.assertEqual((s['wins'],s['losses'],s['pending'],s['missed']),(2,1,1,1));self.assertAlmostEqual(s['accuracy'],2/3)
  self.assertEqual(before,[tuple(r) for r in self.db.execute('SELECT * FROM intel_locks')]);self.assertEqual(r.json['scope'],'lifetime')
 def test_official_settlement_updates_without_observer_or_price_feed(self):
  m=self.seed(0,'DOWN');first=self.client.get('/api/v4/scoreboard',headers=self.auth).json['settlement_score'];self.assertEqual(first['pending'],1)
  m.update(status='finalized',result='yes');register_market(self.db,m,1700001000)
  second=self.client.get('/api/v4/scoreboard',headers=self.auth).json['settlement_score'];self.assertEqual((second['losses'],second['pending']),(1,0))
 def test_protected_read_only_route_and_no_cache(self):
  self.assertEqual(self.client.get('/api/v4/scoreboard').status_code,401);r=self.client.get('/api/v4/scoreboard',headers=self.auth);self.assertEqual(r.headers['Cache-Control'],'no-store');self.assertIsNone(r.json['settlement_score']['accuracy']);self.assertEqual(self.client.post('/api/v4/scoreboard',headers=self.auth).status_code,405)
 def test_unavailable_database_does_not_return_fake_zero_results(self):
  with patch.object(dashboard,'DB',Path(self.tmp.name)/'missing.sqlite3'):
   r=self.client.get('/api/v4/scoreboard',headers=self.auth);self.assertEqual(r.status_code,503);self.assertNotIn('settlement_score',r.json)
 def test_no_hidden_dom_dependency(self):
  source=(Path(__file__).resolve().parents[1]/'static/scoreboard.js').read_text();self.assertIn('/api/v4/scoreboard',source);self.assertNotIn('pro-settlement-score',source);self.assertNotIn('pro-settlement-detail',(Path(__file__).resolve().parents[1]/'static/v4.js').read_text())
