import os
import unittest
from unittest.mock import Mock,patch
import windows_runner
import private_setup

class LocalLaunchTests(unittest.TestCase):
    def test_web_spawn_failure_cleans_up_scanner(self):
        child=Mock();child.poll.return_value=None;child.wait.return_value=0
        settings={'TELEGRAM_BOT_TOKEN':'unit-test-token','TELEGRAM_CHAT_ID':'123','DASHBOARD_PASSWORD':'unit-test-password'}
        with patch.dict(os.environ,settings),patch.object(windows_runner.socket,'socket',return_value=Mock()),patch.object(windows_runner.subprocess,'Popen',side_effect=[child,OSError('test spawn failure')]):
            self.assertEqual(windows_runner.main(),1)
        child.terminate.assert_called_once()
    def test_existing_environment_credentials_reused_without_prompts(self):
        settings={'TELEGRAM_BOT_TOKEN':'unit-test-token','TELEGRAM_CHAT_ID':'123','DASHBOARD_PASSWORD':'unit-test-password','SCANNER_DB':'/tmp/not-opened-by-test.sqlite3'}
        with patch.dict(os.environ,settings),patch('builtins.input',side_effect=AssertionError('No prompt expected')),patch.object(private_setup.getpass,'getpass',side_effect=AssertionError('No hidden prompt expected')),patch('intelligence.storage.migrate',return_value=Mock()),patch.object(private_setup,'Telegram',return_value=Mock()),patch.object(private_setup.subprocess,'call',return_value=0):
            self.assertEqual(private_setup.main(),0)
