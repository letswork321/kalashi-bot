"""Stdlib-only, backed-up local code update. No network calls or secret rewriting."""
from datetime import datetime,timezone
from pathlib import Path
import hashlib
import json
import os
import shutil
import sqlite3
import sys
from install_upgrade import lock_old,online_copy

ROOT=Path(__file__).resolve().parent
MANIFEST='update-files.json'

def files(source):
    entries=json.loads((source/MANIFEST).read_text(encoding='utf-8'))
    if not isinstance(entries,dict) or not entries:raise ValueError('Missing update manifest')
    for name,expected in entries.items():
        relative=Path(name)
        if relative.is_absolute() or '..' in relative.parts or relative.parts[0] in ('data','recovery','.venv','.git'):
            raise ValueError('Unsafe update path')
        path=source/relative
        if path.is_symlink() or not path.is_file() or source not in path.resolve().parents:raise ValueError('Invalid update source')
        if hashlib.sha256(path.read_bytes()).hexdigest()!=expected:raise ValueError('Update package integrity check failed: '+name)
    return entries

def update(target,source=ROOT):
    target=Path(target).expanduser().resolve();source=Path(source).resolve()
    if target==source or target in source.parents or source in target.parents:raise ValueError('Extract the ZIP into a separate folder before updating')
    if not (target/'scanner.py').is_file() or not (target/'data'/'live.sqlite3').is_file():raise ValueError('Choose the existing project folder containing scanner.py and data/live.sqlite3')
    entries=files(source)
    if (target/'data').is_symlink() or (target/'recovery').is_symlink():raise ValueError('Data/recovery folder must not be a symlink')
    for name in entries:
        dest=target/name
        if target not in dest.resolve().parents or dest.is_symlink() or any(p.is_symlink() for p in dest.parents if p!=target and target in p.parents):
            raise ValueError('Unsafe destination or symlink')
        if dest.exists() and not dest.is_file():raise ValueError('Destination is not a file: '+name)
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ');recovery=target/'recovery'/('in-place-'+stamp)
    guard=lock_old(target/'data'/'live.sqlite3')
    changed=[]
    try:
        # Refuse data symlinks, and copy EVERY historical/research file before code changes.
        paths=sorted((target/'data').rglob('*'))
        if any(p.is_symlink() for p in paths):raise ValueError('Data contains symlinks; refusing update')
        recovery.mkdir(parents=True)
        for path in paths:
            if not path.is_file() or path.name.endswith(('-wal','-shm','.lock')):continue
            dest=recovery/'data'/path.relative_to(target/'data');dest.parent.mkdir(parents=True,exist_ok=True)
            if path.suffix in ('.sqlite3','.sqlite','.db'):online_copy(path,dest)
            else:shutil.copy2(path,dest)
        old=[];added=[]
        for name in entries:
            dest=target/name
            if dest.exists():
                saved=recovery/'code'/name;saved.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(dest,saved);old.append(name)
            else:added.append(name)
        manifest={'target':str(target),'created_utc':stamp,'original_files':old,'added_files':added,'status':'BACKED_UP','data_backup':'data','instruction':'Stop local bot, run rollback-update.cmd and paste this recovery folder. Restores code and matching data; post-update records remain in a before-rollback backup.'}
        (recovery/'UPDATE.json').write_text(json.dumps(manifest,indent=2))
        try:
            for name in entries:
                dest=target/name;dest.parent.mkdir(parents=True,exist_ok=True)
                staging=dest.with_name(dest.name+'.update-tmp')
                shutil.copy2(source/name,staging);changed.append(name);os.replace(staging,dest)
        except Exception:
            for name in reversed(changed):
                dest=target/name;tmp=dest.with_name(dest.name+'.update-tmp')
                if tmp.exists():tmp.unlink()
                saved=recovery/'code'/name
                if saved.exists():shutil.copy2(saved,dest)
                elif dest.exists():dest.unlink()
            manifest['status']='CODE_RESTORED_AFTER_FAILURE';(recovery/'UPDATE.json').write_text(json.dumps(manifest,indent=2));raise
        manifest['status']='INSTALLED';(recovery/'UPDATE.json').write_text(json.dumps(manifest,indent=2))
        return recovery
    finally:guard.close()

def rollback(recovery):
    recovery=Path(recovery).resolve();manifest=json.loads((recovery/'UPDATE.json').read_text());target=Path(manifest['target']).resolve()
    if recovery.parent!=target/'recovery' or not recovery.name.startswith('in-place-'):raise ValueError('Recovery folder must belong to this installation')
    names=manifest['original_files']+manifest['added_files']
    for name in names:
        p=Path(name)
        if p.is_absolute() or '..' in p.parts or p.parts[0] in ('data','recovery','.git','.venv'):raise ValueError('Unsafe recovery manifest')
        if target not in (target/p).resolve().parents:raise ValueError('Unsafe recovery destination')
    data=recovery/'data';code=recovery/'code'
    if not (data/'live.sqlite3').is_file():raise ValueError('Missing recovery database')
    if any(p.is_symlink() for base in (data,code,target/'data') for p in base.rglob('*')):raise ValueError('Recovery contains symlinks')
    guard=lock_old(target/'data'/'live.sqlite3')
    try:
        stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        previous=target/'recovery'/('before-rollback-'+stamp);previous.mkdir()
        # Keep the scanner guard in place. Renaming a locked directory fails on Windows.
        for path in (target/'data').rglob('*'):
            if not path.is_file() or path.name.endswith(('-wal','-shm','.lock')):continue
            saved=previous/path.relative_to(target/'data');saved.parent.mkdir(parents=True,exist_ok=True)
            if path.suffix in ('.sqlite3','.sqlite','.db'):online_copy(path,saved)
            else:shutil.copy2(path,saved)
        for path in data.rglob('*'):
            if not path.is_file():continue
            dest=target/'data'/path.relative_to(data);dest.parent.mkdir(parents=True,exist_ok=True)
            staging=dest.with_name(dest.name+'.restore-tmp');shutil.copy2(path,staging)
            if path.suffix in ('.sqlite3','.sqlite','.db'):
                for suffix in ('-wal','-shm'):
                    extra=Path(str(dest)+suffix)
                    if extra.exists():extra.unlink()
            os.replace(staging,dest)
        for name in manifest['original_files']:
            dest=target/name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(code/name,dest)
        for name in manifest['added_files']:
            dest=target/name
            if dest.is_file():dest.unlink()
        return previous
    finally:guard.close()

def main():
    restore='--rollback' in sys.argv
    print('Stop only the LOCAL Windows bot with Ctrl+C before continuing. No cloud service will be changed.')
    value=input('Paste '+('the recovery folder printed by the updater' if restore else 'your EXISTING project folder path')+', or leave blank to cancel: ').strip().strip('"')
    if not value:return 0
    try:
        result=rollback(value) if restore else update(value)
        print(('Rollback complete. Post-upgrade data retained at: ' if restore else 'Update installed. Backup and rollback folder: ')+str(result))
        print('Run start-windows.cmd in your EXISTING installation folder. Keep using http://127.0.0.1:8000.');return 0
    except (ValueError,OSError,KeyError,sqlite3.Error,json.JSONDecodeError) as exc:
        print('Update stopped: '+str(exc));return 1
if __name__=='__main__':raise SystemExit(main())
