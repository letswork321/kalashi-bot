"""Explicit side-by-side V5 setup. Old installation is never overwritten."""
import os
from pathlib import Path
import subprocess
import sys
ROOT=Path(__file__).resolve().parent

def initialize(old,new=ROOT):
    from install_upgrade import import_data
    from intelligence.storage import migrate
    from intelligence.v5_storage import ensure
    result=import_data(old,new)
    db=migrate(Path(new)/'data/live.sqlite3')
    try:ensure(db)
    finally:db.close()
    (Path(new)/'data/v5-isolated.txt').write_text('Separate V5 writable database. Original V4 remains unchanged.\n',encoding='utf-8')
    return result

def main():
    try:
        from windows_setup import prepare
        python=prepare()
        if not (ROOT/'data/v5-isolated.txt').is_file():
            print('V5 must run in a NEW extracted folder beside V4. Stop your LOCAL V4 with Ctrl+C only when ready to import. Keep it as a fallback.')
            old=input('Paste your EXISTING V4 project folder path, or blank to cancel: ').strip().strip('"')
            if not old:return 0
            # Migration runs with installed dependencies, not an incomplete base distribution.
            command='import sys; from windows_v5 import initialize; m=initialize(sys.argv[1]); print("V4 preserved. Backup: "+m["backup"])'
            if subprocess.call([str(python),'-c',command,old],cwd=ROOT):return 1
        env=dict(os.environ,BTC_PRO_V5='true',SCANNER_DB=str(ROOT/'data/live.sqlite3'))
        return subprocess.call([str(python),str(ROOT/'private_setup.py')],cwd=ROOT,env=env)
    except (OSError,ValueError) as exc:
        print('V5 setup stopped safely: '+str(exc));return 1
    except KeyboardInterrupt:return 0
if __name__=='__main__':raise SystemExit(main())
