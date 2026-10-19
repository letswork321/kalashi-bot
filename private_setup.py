"""Hidden prompts, environment reuse and optional current-user encrypted Windows cache."""
import getpass
import os
import subprocess
import sys
import sqlite3
from pathlib import Path
from scanner import Telegram, DataError

def main():
    print('Private Kalshi dashboard setup. No plaintext credentials are saved; Windows encrypted remembering is optional.')
    print('Do not screen-share while copying credentials. Hidden prompts show no characters as you paste.')
    from intelligence.credentials import load,save,CredentialError
    cache=Path(__file__).resolve().parent/'data'/'credentials.dpapi'
    remembered={}
    if os.name=='nt':
        try:remembered=load(cache)
        except CredentialError as exc:print(str(exc))
    supplied_by_environment=all(os.environ.get(name) for name in ('TELEGRAM_BOT_TOKEN','TELEGRAM_CHAT_ID','DASHBOARD_PASSWORD'))
    token=os.environ.get('TELEGRAM_BOT_TOKEN') or remembered.get('TELEGRAM_BOT_TOKEN') or getpass.getpass('Paste your BotFather token (hidden): ').strip()
    chat=os.environ.get('TELEGRAM_CHAT_ID') or remembered.get('TELEGRAM_CHAT_ID') or input('Enter your verified Telegram chat ID: ').strip()
    password=os.environ.get('DASHBOARD_PASSWORD') or remembered.get('DASHBOARD_PASSWORD') or getpass.getpass('Dashboard password (hidden; existing password may be reused): ')
    if not token or not chat or len(password)<12:
        print('Token/chat ID required; dashboard password must be at least 12 characters.');return 1
    remember = os.name=='nt' and not supplied_by_environment and not remembered and input('Remember credentials encrypted for this Windows user? [y/N]: ').strip().lower()=='y'
    os.environ['TELEGRAM_BOT_TOKEN']=token
    os.environ['TELEGRAM_CHAT_ID']=chat
    os.environ['DASHBOARD_PASSWORD']=password
    # Preserve the Windows launcher's project-local DB contract, so an old
    # inherited SCANNER_DB cannot accidentally migrate the original installation.
    os.environ['SCANNER_DB']=str(Path(__file__).resolve().parent/'data'/'live.sqlite3')
    try:
        from intelligence.storage import migrate
        database=migrate(os.environ['SCANNER_DB']);database.close()
        Telegram().send('Windows Kalshi dashboard connection test. This is not a trading signal. Trading remains manual.')
        print('Telegram confirmed the connection test was sent.')
        if remember:
            try:save(cache,{'TELEGRAM_BOT_TOKEN':token,'TELEGRAM_CHAT_ID':chat,'DASHBOARD_PASSWORD':password})
            except CredentialError as exc:print(str(exc))
        return subprocess.call([sys.executable,'windows_runner.py'],cwd=Path(__file__).resolve().parent)
    except (DataError,OSError,sqlite3.Error,ValueError) as exc:
        print(str(exc));return 1
    except KeyboardInterrupt:
        return 0
    finally:
        for name in ('TELEGRAM_BOT_TOKEN','TELEGRAM_CHAT_ID','DASHBOARD_PASSWORD'):
            os.environ.pop(name,None)

if __name__=='__main__':sys.exit(main())
