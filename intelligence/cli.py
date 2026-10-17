"""Read-only research commands; explicit time windows and no secret output."""
import argparse
from pathlib import Path
import time
from .storage import migrate,dumps
from .models import retrain
from .research import Backfill,report

def main(argv=None):
    from scanner import HTTP,ROOT
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=['backfill','backfill-trades','train','report','run'])
    p.add_argument('--db',type=Path,default=ROOT/'data'/'live.sqlite3')
    p.add_argument('--days',type=int,choices=[7,30,90],default=7)
    p.add_argument('--max-pages',type=int,default=10)
    p.add_argument('--seconds',type=float,default=30)
    a=p.parse_args(argv)
    if a.action=='run':
        from .service import IntelligenceWorker
        # This diagnostic never starts a Telegram sender or an execution capability.
        worker=IntelligenceWorker(a.db,telegram=None);worker.start()
        try:time.sleep(max(1,min(a.seconds,3600)))
        finally:worker.close()
        print(dumps({'error':worker.error,'database':str(a.db),'telegram':False}));return 1 if worker.error else 0
    db=migrate(a.db)
    try:
        result=Backfill(db,HTTP()).trade_session(a.max_pages) if a.action=='backfill-trades' else Backfill(db,HTTP()).run(a.days,a.max_pages) if a.action=='backfill' else retrain(db,time.time()) if a.action=='train' else report(db,a.days)
        print(dumps(result));return 1 if result.get('status')=='FAILED' else 0
    finally:db.close()
if __name__=='__main__':raise SystemExit(main())
