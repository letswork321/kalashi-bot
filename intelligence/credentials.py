"""Optional Windows DPAPI cache, current-user protected; no plaintext secrets on disk."""
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path

class CredentialError(ValueError):pass

class Blob(ctypes.Structure):
    _fields_=[('size',wintypes.DWORD),('data',ctypes.POINTER(ctypes.c_ubyte))]

def _transform(raw,decrypt=False):
    if os.name!='nt':raise CredentialError('Encrypted credential persistence is supported only with Windows DPAPI')
    incoming_buffer=ctypes.create_string_buffer(raw)
    incoming=Blob(len(raw),ctypes.cast(incoming_buffer,ctypes.POINTER(ctypes.c_ubyte)));out=Blob()
    crypt=ctypes.WinDLL('crypt32',use_last_error=True);kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    crypt.CryptProtectData.argtypes=[ctypes.POINTER(Blob),wintypes.LPCWSTR,ctypes.POINTER(Blob),ctypes.c_void_p,ctypes.c_void_p,wintypes.DWORD,ctypes.POINTER(Blob)]
    crypt.CryptUnprotectData.argtypes=[ctypes.POINTER(Blob),ctypes.c_void_p,ctypes.POINTER(Blob),ctypes.c_void_p,ctypes.c_void_p,wintypes.DWORD,ctypes.POINTER(Blob)]
    kernel.LocalFree.argtypes=[ctypes.c_void_p];kernel.LocalFree.restype=ctypes.c_void_p
    ok=crypt.CryptUnprotectData(ctypes.byref(incoming),None,None,None,None,1,ctypes.byref(out)) if decrypt else crypt.CryptProtectData(ctypes.byref(incoming),'Kalshi private dashboard',None,None,None,1,ctypes.byref(out))
    if not ok:raise CredentialError('Windows could not protect/read the credential cache for this user account')
    try:return ctypes.string_at(out.data,out.size)
    finally:kernel.LocalFree(ctypes.cast(out.data,ctypes.c_void_p))

NAMES=('TELEGRAM_BOT_TOKEN','TELEGRAM_CHAT_ID','DASHBOARD_PASSWORD')
def save(path,values):
    values={k:values[k] for k in NAMES if values.get(k)}
    if len(values)!=len(NAMES):raise CredentialError('Incomplete credentials cannot be cached')
    encrypted=_transform(json.dumps(values).encode())
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_suffix('.tmp')
    with open(temporary,'wb') as f:f.write(encrypted)
    os.replace(temporary,path)

def load(path):
    path=Path(path)
    if not path.exists():return {}
    try:
        values=json.loads(_transform(path.read_bytes(),True))
        if not isinstance(values,dict) or any(not isinstance(values.get(k),str) for k in NAMES):raise ValueError()
        return {k:values[k] for k in NAMES}
    except (ValueError,OSError) as exc:raise CredentialError('Could not read encrypted credentials; keep the file and re-enter credentials. It is never logged.') from None
