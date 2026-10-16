"""Hidden credential prompts for a private local session; never save credentials."""
import getpass
import os
import subprocess
import sys
from pathlib import Path
from scanner import Telegram, DataError

def main():
    print('Private Kalshi dashboard setup. Credentials stay in this session, not in files.')
    print('Do not screen-share while copying credentials. Hidden prompts show no characters as you paste.')
    token=getpass.getpass('Paste your BotFather token (hidden): ').strip()
    chat=input('Enter your verified Telegram chat ID: ').strip()
    password=getpass.getpass('Choose a dashboard password (hidden; remember it): ')
    if not token or not chat or len(password)<12:
        print('Token/chat ID are required. Use a dashboard password of at least 12 characters.');return 1
    os.environ['TELEGRAM_BOT_TOKEN']=token
    os.environ['TELEGRAM_CHAT_ID']=chat
    os.environ['DASHBOARD_PASSWORD']=password
    os.environ['SCANNER_DB']=str(Path(__file__).resolve().parent/'data'/'live.sqlite3')
    try:
        Telegram().send('Windows Kalshi dashboard connection test. This is not a trading signal. Trading remains manual.')
        print('Telegram confirmed the connection test was sent.')
        return subprocess.call([sys.executable,'windows_runner.py'],cwd=Path(__file__).resolve().parent)
    except DataError as exc:
        print(str(exc));return 1
    except KeyboardInterrupt:
        return 0
    finally:
        for name in ('TELEGRAM_BOT_TOKEN','TELEGRAM_CHAT_ID','DASHBOARD_PASSWORD'):
            os.environ.pop(name,None)

if __name__=='__main__':sys.exit(main())
