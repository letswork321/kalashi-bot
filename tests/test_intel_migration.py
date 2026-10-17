import json
import sqlite3
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
from install_upgrade import import_data,lock_old
from intelligence.credentials import save,load,CredentialError
from intelligence.storage import migrate

class UpgradeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.old=Path(self.tmp.name)/'old';self.new=Path(self.tmp.name)/'new';self.old.mkdir();self.new.mkdir();(self.old/'scanner.py').write_text('# existing');(self.old/'data').mkdir()
        db=sqlite3.connect(self.old/'data/live.sqlite3');db.execute('CREATE TABLE predictions(id INTEGER,payload TEXT)');db.execute("INSERT INTO predictions VALUES(1,'unchanged')");db.commit();db.close()
    def tearDown(self):self.tmp.cleanup()
    def test_side_by_side_import_preserves_history_and_rollback(self):
        (self.old/'data/research.csv').write_text('old research')
        (self.old/'data/credentials.dpapi').write_bytes(b'encrypted-example')
        manifest=import_data(self.old,self.new)
        self.assertTrue(Path(manifest['backup']).exists());self.assertEqual((self.old/'scanner.py').read_text(),'# existing')
        db=migrate(self.new/'data/live.sqlite3');self.assertEqual(db.execute('SELECT payload FROM predictions').fetchone()[0],'unchanged');db.close()
        self.assertEqual((self.new/'data/credentials.dpapi').read_bytes(),b'encrypted-example');self.assertEqual((self.new/'data/research.csv').read_text(),'old research')
    def test_rejects_existing_destination_history(self):
        (self.new/'data').mkdir();(self.new/'data/important').write_text('keep')
        with self.assertRaises(ValueError):import_data(self.old,self.new)
        self.assertEqual((self.new/'data/important').read_text(),'keep')
    def test_never_installs_over_old_code(self):
        with self.assertRaises(ValueError):import_data(self.old,self.old)
    def test_running_local_scanner_blocks_import(self):
        guard=lock_old(self.old/'data/live.sqlite3')
        try:
            with self.assertRaises(ValueError):import_data(self.old,self.new)
        finally:guard.close()
    def test_symlinks_do_not_escape_data(self):
        (self.old/'data/link').symlink_to(self.old/'scanner.py')
        with self.assertRaises(ValueError):import_data(self.old,self.new)
    def test_dpapi_cache_never_writes_plaintext(self):
        path=self.new/'cache';values={'TELEGRAM_BOT_TOKEN':'token-test','TELEGRAM_CHAT_ID':'123','DASHBOARD_PASSWORD':'password-test'}
        with patch('intelligence.credentials._transform',side_effect=[b'protected',json.dumps(values).encode()]):
            save(path,values);self.assertEqual(path.read_bytes(),b'protected');self.assertEqual(load(path),values)
    def test_dpapi_corruption_is_redacted(self):
        path=self.new/'cache';path.write_bytes(b'bad')
        with patch('intelligence.credentials._transform',return_value=b'not-json'):
            with self.assertRaises(CredentialError):load(path)
