"""Bounded SQLite contention handling shared by every application writer.
Autocommit outside explicit scopes prevents idle transactions spanning network IO.
Write scopes reserve the writer before reading; nested scopes use savepoints.
Only SQLITE_BUSY/LOCKED is retried, never whole transactions or external effects.
"""
from contextlib import contextmanager
from pathlib import Path
import sqlite3
import threading
import time

_locks={}
_registry_lock=threading.Lock()
RETRY_SECONDS=2.0


def busy(exc):
    code=getattr(exc,'sqlite_errorcode',None)
    return isinstance(exc,sqlite3.OperationalError) and ((code is not None and code&255 in (sqlite3.SQLITE_BUSY,sqlite3.SQLITE_LOCKED)) or any(s in str(exc).lower() for s in ('database is locked','database table is locked','database schema is locked')))


def retry(operation,seconds=None):
    seconds=RETRY_SECONDS if seconds is None else seconds
    deadline=time.monotonic()+seconds;delay=.02
    while True:
        try:return operation()
        except sqlite3.OperationalError as exc:
            if not busy(exc) or time.monotonic()>=deadline:raise
            time.sleep(min(delay,max(0,deadline-time.monotonic())));delay=min(.15,delay*2)

class Connection(sqlite3.Connection):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs);self.writer_lock=threading.RLock();self.readonly=False;self.scopes=[];self.sequence=0
    def execute(self,*args,**kwargs):
        # A failed statement inside a transaction must unwind the caller's scope.
        # Retrying a stale read snapshot or replaying earlier DML would be unsafe.
        operation=lambda:super(Connection,self).execute(*args,**kwargs)
        return operation() if self.in_transaction else retry(operation)
    def __enter__(self):
        locked=False
        if not self.readonly:
            if not self.writer_lock.acquire(timeout=RETRY_SECONDS):raise sqlite3.OperationalError('database is locked (writer queue deadline exceeded)')
            locked=True
        try:
            token=None
            if self.in_transaction:
                self.sequence+=1;token='app_scope_'+str(self.sequence)
                super().execute('SAVEPOINT '+token)
            else:retry(lambda:super(Connection,self).execute('BEGIN' if self.readonly else 'BEGIN IMMEDIATE'))
            self.scopes.append((token,locked));return self
        except BaseException:
            if locked:self.writer_lock.release()
            raise
    def __exit__(self,kind,value,trace):
        token,locked=self.scopes.pop()
        try:
            if token:
                if kind:super().execute('ROLLBACK TO '+token)
                super().execute('RELEASE '+token)
            elif kind:self.rollback()
            else:
                try:self.commit()
                except BaseException:self.rollback();raise
        finally:
            if locked:self.writer_lock.release()
        return False
    def commit(self):return retry(lambda:super(Connection,self).commit())
    def close(self):
        try:super().close()
        finally:
            while self.scopes:
                _,locked=self.scopes.pop()
                if locked:self.writer_lock.release()


def open_database(path,readonly=False):
    path=Path(path).resolve()
    if not readonly:path.parent.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(path.as_uri()+'?mode=ro' if readonly else path,uri=readonly,timeout=.1,isolation_level=None,factory=Connection)
    try:
        db.row_factory=sqlite3.Row
        if isinstance(db,Connection):
            db.readonly=readonly
            with _registry_lock:db.writer_lock=_locks.setdefault(str(path).casefold() if __import__('os').name=='nt' else str(path),threading.RLock())
        db.execute('PRAGMA busy_timeout=100')
        if readonly:db.execute('PRAGMA query_only=ON')
        else:
            if db.execute('PRAGMA journal_mode').fetchone()[0].lower()!='wal':db.execute('PRAGMA journal_mode=WAL').fetchone()
            db.execute('PRAGMA synchronous=NORMAL')
        return db
    except BaseException:db.close();raise


def rollback(db):
    try:
        if db and db.in_transaction:db.rollback()
    except sqlite3.Error:pass

class _UnavailableHealth:
    def execute(self,*args,**kwargs):return None

@contextmanager
def health_write(db):
    """Best-effort logging; callers use the yielded writer, which may be a no-op."""
    rollback(db)
    try:db.__enter__()
    except sqlite3.Error:
        yield _UnavailableHealth();return
    try:yield db
    except BaseException as exc:
        try:db.__exit__(type(exc),exc,exc.__traceback__)
        except sqlite3.Error:rollback(db)
        if not isinstance(exc,sqlite3.Error):raise
    else:
        try:db.__exit__(None,None,None)
        except sqlite3.Error:rollback(db)
