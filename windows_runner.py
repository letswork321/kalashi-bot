"""Run the scanner and a private Windows dashboard until Ctrl-C."""
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import webbrowser
import requests

ROOT=Path(__file__).resolve().parent

def main():
    missing=[n for n in ('TELEGRAM_BOT_TOKEN','TELEGRAM_CHAT_ID','DASHBOARD_PASSWORD') if not os.environ.get(n)]
    if missing:
        print('Missing settings: '+', '.join(missing));return 1
    s=socket.socket()
    try:s.bind(('127.0.0.1',8000))
    except OSError:
        print('Port 8000 is already in use. Close the earlier dashboard before starting another.');return 1
    finally:s.close()
    # Network quality issues remain visible as NO TRADE; never switch to fixtures.
    scanner=subprocess.Popen([sys.executable,'scanner.py'],cwd=ROOT)
    web=subprocess.Popen([sys.executable,'-m','waitress','--listen=127.0.0.1:8000','dashboard:app'],cwd=ROOT)
    try:
        for _ in range(40):
            if scanner.poll() is not None or web.poll() is not None:
                print('A service could not start; read the error above.');return 1
            try:
                r=requests.get('http://127.0.0.1:8000/healthz',timeout=1)
                if r.ok:break
            except requests.RequestException:pass
            time.sleep(.25)
        else:
            print('Dashboard did not become ready.');return 1
        print('Private dashboard started. Username: viewer. Use the dashboard password you just entered.')
        print('Keep this window open. Ctrl-C stops the scanner and dashboard. No trades can be executed.')
        webbrowser.open('http://127.0.0.1:8000/')
        while scanner.poll() is None and web.poll() is None:time.sleep(1)
        print('A service stopped; shutting down its companion.');return 1
    except KeyboardInterrupt:
        print('\nStopping private dashboard and alerts.');return 0
    finally:
        for p in (scanner,web):
            if p.poll() is None:p.terminate()
        for p in (scanner,web):
            try:p.wait(timeout=10)
            except subprocess.TimeoutExpired:p.kill();p.wait()

if __name__=='__main__':sys.exit(main())
