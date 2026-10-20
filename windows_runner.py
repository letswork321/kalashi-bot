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

def supervise(children,clock=time.monotonic,pause=time.sleep,commands=None):
    """One failed child never takes down the other; back off and restart independently."""
    commands=commands or {'scanner':[sys.executable,'scanner.py'],'dashboard':[sys.executable,'-m','waitress','--listen=127.0.0.1:8000','dashboard:app']}
    delays={name:1 for name in children};due={name:None for name in children};started={name:clock() for name in children}
    while True:
        now=clock()
        for name,child in list(children.items()):
            if child.poll() is None:
                if now-started[name]>=300:delays[name]=1
                continue
            if due[name] is None:
                due[name]=now+delays[name]
                print(name+' stopped; restarting in '+str(delays[name])+'s. Other service remains running.',flush=True)
            if now<due[name]:continue
            try:children[name]=subprocess.Popen(commands[name],cwd=ROOT)
            except OSError:
                delays[name]=min(30,delays[name]*2);due[name]=now+delays[name];continue
            started[name]=now;due[name]=None;delays[name]=min(30,delays[name]*2)
        pause(.5)

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
    web=None
    try:
        web=subprocess.Popen([sys.executable,'-m','waitress','--listen=127.0.0.1:8000','dashboard:app'],cwd=ROOT)
        for _ in range(40):
            if web.poll() is not None:
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
        children={'scanner':scanner,'dashboard':web}
        try:supervise(children)
        finally:scanner=children['scanner'];web=children['dashboard']
        return 0
    except OSError as exc:
        print('A local service could not start: '+str(exc));return 1
    except KeyboardInterrupt:
        print('\nStopping private dashboard and alerts.');return 0
    finally:
        for p in (p for p in (scanner,web) if p is not None):
            if p.poll() is None:p.terminate()
        for p in (p for p in (scanner,web) if p is not None):
            try:p.wait(timeout=10)
            except subprocess.TimeoutExpired:p.kill();p.wait()

if __name__=='__main__':sys.exit(main())
