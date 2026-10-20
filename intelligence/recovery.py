"""Worker recovery outside transactions; no replay of alerts or earlier decisions."""
from functools import wraps
import logging
import threading
from sqlite_runtime import rollback


def resilient(fn):
    @wraps(fn)
    def run(self,*args,**kwargs):
        delay=1
        while True:
            try:return fn(self,*args,**kwargs)
            except Exception as exc:
                logging.getLogger(__name__).warning('%s unavailable (%s); restarting with fresh observations',fn.__qualname__,type(exc).__name__)
            if self.stop.is_set() or (hasattr(self,'owner') and self.owner.stop.is_set()):return
            self.stop.wait(delay);delay=min(30,delay*2)
    return run

class Supervisor:
    """Restart a failed coordinator only after stopping its old child workers."""
    def __init__(self,path,telegram):self.path=path;self.telegram=telegram;self.stop=threading.Event();self.thread=None;self.worker=None
    def start(self):
        self.thread=threading.Thread(target=self.run,daemon=True,name='intelligence-supervisor');self.thread.start()
    def run(self):
        from .service import IntelligenceWorker
        delay=1
        while not self.stop.is_set():
            self.worker=IntelligenceWorker(self.path,self.telegram);self.worker.start()
            while not self.stop.wait(1) and self.worker.thread.is_alive():pass
            self.worker.close()
            if self.stop.is_set():return
            logging.getLogger(__name__).warning('Coordinator stopped; recovering without backdating missed markets')
            self.stop.wait(delay);delay=min(30,delay*2)
    def close(self):
        self.stop.set()
        if self.worker:self.worker.close()
        if self.thread:self.thread.join(timeout=3)
