"""Release maintainer helper (not required on the user's laptop)."""
from pathlib import Path
import hashlib
import json
import subprocess

ROOT=Path(__file__).resolve().parent

def build(root=ROOT):
    paths=subprocess.check_output(['git','ls-files','--cached','--others','--exclude-standard','-z'],cwd=root).decode().split('\0')
    entries={}
    for name in sorted(set(paths)):
        if not name or name=='update-files.json':continue
        p=root/name
        if p.is_symlink() or not p.is_file():raise ValueError('Release contains missing file or symlink: '+name)
        if Path(name).parts[0] in ('data','recovery','.venv') or name.endswith(('.pem','.key','.dpapi')) or Path(name).name.startswith('.env'):raise ValueError('Secret/runtime file cannot ship: '+name)
        entries[name]=hashlib.sha256(p.read_bytes()).hexdigest()
    (root/'update-files.json').write_text(json.dumps(entries,indent=2)+'\n',encoding='utf-8')
    return len(entries)
if __name__=='__main__':print('Release source files verified:',build())
