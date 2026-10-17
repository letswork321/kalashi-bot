"""Side-by-side Windows installer. Backs up/imports data; never overwrites old code."""
from datetime import datetime,timezone
from pathlib import Path
import json
import os
import shutil
import sqlite3
import sys

ROOT=Path(__file__).resolve().parent

def online_copy(source,destination):
    source=Path(source);destination=Path(destination)
    destination.parent.mkdir(parents=True,exist_ok=True)
    incoming=sqlite3.connect(source.resolve().as_uri()+'?mode=ro',uri=True)
    outgoing=sqlite3.connect(destination)
    try:
        incoming.backup(outgoing)
        if outgoing.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('Backup integrity check failed')
    finally:outgoing.close();incoming.close()

def lock_old(path):
    handle=open(str(path)+'.lock','a+b')
    try:
        if os.name=='nt':
            import msvcrt
            if handle.seek(0,2)==0:handle.write(b'0');handle.flush()
            handle.seek(0);msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
        else:
            import fcntl
            fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except OSError:
        handle.close();raise ValueError('The old LOCAL scanner is still running. Stop it with Ctrl+C before importing data. Cloud services are not affected.') from None
    return handle

def import_data(old,new=ROOT):
    old=Path(old).expanduser().resolve();new=Path(new).resolve()
    if old==new or old in new.parents or new in old.parents:raise ValueError('Extract the upgrade beside the old folder, not inside it')
    if not (old/'scanner.py').is_file() or not (old/'data').is_dir():raise ValueError('Choose the old project folder containing scanner.py and data')
    if (new/'data').exists() and any((new/'data').iterdir()):raise ValueError('New data folder is already populated. Nothing will be overwritten; use a fresh extraction')
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    recovery=new/'recovery'/stamp;stage=new/('data-import-'+stamp)
    guard=lock_old(old/'data'/'live.sqlite3')
    try:
        recovery.mkdir(parents=True);stage.mkdir()
        for path in sorted((old/'data').rglob('*')):
            if path.is_symlink():raise ValueError('Data contains a symlink; refusing to copy outside your project')
            relative=path.relative_to(old/'data')
            if path.is_dir():continue
            if path.name.endswith(('-wal','-shm','.lock')):continue
            destination=recovery/relative
            destination.parent.mkdir(parents=True,exist_ok=True)
            if path.suffix in ('.sqlite3','.sqlite','.db'):
                online_copy(path,destination)
            else:shutil.copy2(path,destination)
            target=stage/relative;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(destination,target)
        if (new/'data').exists():(new/'data').rmdir()
        stage.rename(new/'data')
        manifest={'old_folder':str(old),'new_folder':str(new),'backup':str(recovery),'created_utc':stamp,'rollback':'Stop upgraded local console, then run start-windows.cmd from old_folder. Old code/history was not overwritten. Keep both data folders; new forecasts are not automatically merged backward.'}
        (recovery/'INSTALL-MANIFEST.json').write_text(json.dumps(manifest,indent=2))
        return manifest
    finally:guard.close()

def main():
    print('Side-by-side upgrade. Stop only your LOCAL Windows bot before importing. Your old folder stays intact.')
    old=input('Paste the old project folder path (not a ZIP), or leave blank to cancel: ').strip().strip('"')
    if not old:return 0
    try:
        m=import_data(old);print('Backup and import complete. Old version retained at: '+m['old_folder']);print('Now double-click start-windows.cmd in THIS new folder. A second database backup is made before schema migration.');return 0
    except (ValueError,OSError,sqlite3.Error) as exc:print('Import stopped: '+str(exc));return 1
if __name__=='__main__':raise SystemExit(main())
