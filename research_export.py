"""Bounded read-only research export. Python standard library only; no bot startup."""
import json
import math
from pathlib import Path
import sqlite3
import time

def decode(value,kind):
    try:
        out=json.loads(value) if value else kind()
        return out if isinstance(out,kind) else kind()
    except (ValueError,TypeError):return kind()

# Free text, Telegram messages and arbitrary JSON blobs are deliberately excluded.
EXPORT={'intel_locks':['features','ticker','scheduled','deadline','state','direction','p_up','observed','model','result'], 'intel_lock_attempts':['ticker','observed','reason','outcome'], 'intel_markets':['ticker','opened','closed','strike','result','status','settled_at'], 'intel_callouts':['key','ticker','observed','sent','direction','btc_price','quote_ts','due','metric','outcome','state'], 'v3_call_paths':['key','last_event','last_id','gaps','hit_ts','hit_price','state'], 'intel_books':['yes','no','source','ticker','ts','event_ts','spread','imbalance','latency','fee_multiplier'], 'intel_btc_trades':['id','ts','price','size','received'], 'v3_ticks':['source','id','event','received','price','size','continuous'], 'intel_health':['name','ts','payload'], 'v4_health':['payload','observed','source','state'], 'v4_profit_paths':['ticker','side','issued','state','goal','max_roi','hit','barrier','coverage']}


def export(path,destination,limit=2000,seconds=5):
    if not 1<=limit<=10000 or not 0<seconds<=15:raise ValueError('Export bounds exceeded')
    path=Path(path).resolve();dest=Path(destination).resolve()
    if dest==path or dest.exists():raise ValueError('Use a new export filename, never the database')
    db=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=.2);db.row_factory=sqlite3.Row;deadline=time.monotonic()+seconds
    db.set_progress_handler(lambda:int(time.monotonic()>deadline),1000)
    out={'format':'sanitized-v4-1','created':time.time(),'limit_per_table':limit,'tables':{},'partial':False,'notes':'Bounded live read, no full SQLite backup, no credential/message/feature JSON fields. Review before sharing.'}
    try:
        db.execute('PRAGMA query_only=ON')
        for table,columns in EXPORT.items():
            if time.monotonic()>deadline:out['partial']=True;break
            available={r[1] for r in db.execute('PRAGMA table_info('+table+')')};cols=[c for c in columns if c in available]
            if not cols:continue
            try:
                records=[dict(r) for r in db.execute('SELECT '+','.join(cols)+' FROM '+table+' ORDER BY rowid DESC LIMIT ?',(limit,))]
                for row in records:
                    for field in ('yes','no'):
                        if field in row:
                            raw=decode(row[field],list);row[field]=[[float(p),float(q)] for p,q in raw[:20] if type(p) in (int,float) and type(q) in (int,float) and math.isfinite(p+q) and 0<p<1 and q>0]
                    for field in ('features','payload'):
                        if field in row:
                            raw=decode(row.pop(field),dict);row['numeric_'+field]={k:v for k,v in raw.items() if k in ('age','last_id','gaps','rejected','reconnects','ok','distance','remaining','volatility','momentum','rsi','ema_gap','volume_ratio','market_p','imbalance','tick_available') and type(v) in (int,float,bool) and math.isfinite(v)}
                    if 'key' in row:
                        import hashlib
                        row['key']=hashlib.sha256(row['key'].encode()).hexdigest()
                out['tables'][table]=records
            except sqlite3.OperationalError:out['partial']=True;break
    finally:db.close()
    dest.parent.mkdir(parents=True,exist_ok=True)
    with dest.open('x',encoding='utf-8') as f:json.dump(out,f,allow_nan=False,separators=(',',':'))
    return {'file':str(dest),'partial':out['partial'],'tables':len(out['tables'])}



def main():
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--limit',type=int,default=2000)
    args=parser.parse_args()
    try:
        print(json.dumps(export(args.db,args.output,args.limit)));return 0
    except (OSError,ValueError,sqlite3.Error):
        print('Export failed safely. Check the database path, new output filename and read access; no source data was changed.');return 1
if __name__=='__main__':raise SystemExit(main())
