"""Read-only dashboard. Run behind an HTTPS reverse proxy with DASHBOARD_PASSWORD."""
import hmac
import json
import os
from pathlib import Path
import sqlite3
import time
import threading
import secrets
from flask import Flask, Response, jsonify, render_template, request
from scanner import ROOT, Store, timestamp

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 1024
DB = Path(os.environ.get('SCANNER_DB', str(ROOT/'data'/'live.sqlite3')))
_report_cache = {}
_report_lock = threading.Lock()
_alert_csrf = secrets.token_urlsafe(32)

@app.before_request
def authenticate():
    if request.path == '/healthz':
        return None
    password = os.environ.get('DASHBOARD_PASSWORD', '')
    if not password:
        return Response('Set DASHBOARD_PASSWORD before starting the dashboard.',status=503)
    auth = request.authorization
    if not auth or not hmac.compare_digest((auth.username or '').encode(), b'viewer') or not hmac.compare_digest((auth.password or '').encode(), password.encode()):
        return Response('Authentication required',401,{'WWW-Authenticate':'Basic realm="Kalshi monitor", charset="UTF-8"'})

@app.after_request
def headers(response):
    response.headers['Cache-Control']='no-store'
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['X-Frame-Options']='DENY'
    response.headers['Referrer-Policy']='no-referrer'
    response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'self'"
    return response

def snapshot():
    now = time.time()
    if not DB.is_file():
        return {'now':now,'state':'WAITING','reason':'Scanner has not created its database yet','latest':None,'recent':[],'paper':[],'stats':None}
    # No DB initialization or writes in HTTP workers; scanner owns the schema.
    db = sqlite3.connect(DB.resolve().as_uri()+'?mode=ro', uri=True,timeout=5)
    db.row_factory=sqlite3.Row
    try:
        latest = db.execute('SELECT * FROM predictions ORDER BY id DESC LIMIT 1').fetchone()
        recent = [dict(r) for r in db.execute('SELECT id,observed,ticker,signal,p_up,result FROM predictions ORDER BY id DESC LIMIT 80')]
        paper = [dict(r) for r in db.execute('SELECT * FROM paper ORDER BY opened DESC LIMIT 30')]
        # Reuse report logic with the existing read-only connection.
        reporting = object.__new__(Store)
        reporting.db = db
        with _report_lock:
            key = str(DB)
            cached = _report_cache.get(key)
            # Heavy settled-history statistics refresh once a minute; prices/history
            # and active paper positions remain live on every request.
            if not cached or now-cached[0] >= 60:
                cached = (now,reporting.report())
                _report_cache[key] = cached
            stats = dict(cached[1])
            stats['paper_open'] = db.execute('SELECT count(*) FROM paper WHERE result IS NULL').fetchone()[0]
            stats['predictions_total'] = db.execute('SELECT count(*) FROM predictions').fetchone()[0]
        price_rows = db.execute('SELECT observed,payload FROM predictions ORDER BY id DESC LIMIT 180').fetchall()
        prices = []
        for row in reversed(price_rows):
            payload = json.loads(row['payload'])
            if payload.get('btc_price') is not None:
                prices.append({'time':row['observed'],'price':payload['btc_price']})
        p=json.loads(latest['payload']) if latest else None
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='intel_snapshots'").fetchone():
            current=db.execute('SELECT ts,payload FROM intel_snapshots ORDER BY id DESC LIMIT 1').fetchone()
            if current and 0<=now-current['ts']<=3:
                advanced=json.loads(current['payload']);forecast=advanced.get('baseline')
                if advanced.get('mode')=='LIVE' and forecast and forecast.get('p_up') is not None:
                    p=forecast
        age=now-p['observed_at'] if p else None
        fresh = (p and p.get('p_up') is not None and age <= 30
                 and now-p.get('btc_timestamp',0) <= 20
                 and p.get('close_time') and timestamp(p['close_time']) > now)
        state='LIVE' if fresh else ('STALE' if p and age > 30 else 'BLOCKED')
        if stats['mode'] != 'live':
            state='MOCK TEST ONLY'
        return {'now':now,'state':state,'age':age,'latest':p,'recent':recent,'paper':paper,'stats':stats,
                'prices':prices,'reason':p.get('reason') if p else 'Waiting for first scan'}
    finally:
        db.close()

@app.get('/')
def index():
    return render_template('dashboard.html')

@app.get('/api/state')
def state():
    try:
        return jsonify(snapshot())
    except (sqlite3.Error, ValueError, KeyError):
        return jsonify({'state':'ERROR','reason':'Database unavailable; scanner may be initializing','now':time.time()}),503

_intel_cache={}
_intel_lock=threading.Lock()

@app.get('/api/intelligence')
def intelligence_state():
    selection=request.args.get('range','today');days=request.args.get('days','7')
    if selection not in ('today','7','30','all') or days not in ('7','30','90'):
        return jsonify({'error':'Unsupported range'}),400
    try:page=int(request.args.get('page','0'))
    except ValueError:return jsonify({'error':'Invalid page'}),400
    if not 0<=page<=100000:return jsonify({'error':'Invalid page'}),400
    now=time.time();key=(str(DB),selection,days,page)
    try:
        with _intel_lock:
            cached=_intel_cache.get(key)
            if not cached or now-cached[0]>=1.5:
                from intelligence.service import dashboard_snapshot
                payload=dashboard_snapshot(DB,selection,days,now,page)
                # Full evaluation audit remains in SQLite; browser gets compact rows.
                latest=payload.get('models',{}).get('latest',{})
                if 'predictions' in latest:latest['predictions']=latest['predictions'][-100:]
                _intel_cache[key]=(now,payload)
            payload=_intel_cache[key][1]
        return jsonify(payload)
    except (sqlite3.Error,ValueError,KeyError):
        return jsonify({'status':'WARMING UP','reason':'Intelligence worker has not initialized this database yet','now':now})

@app.get('/healthz')
def health():
    # Process health only. /api/state reports source freshness separately.
    return jsonify({'web':'ok'})

@app.route('/api/alert-settings', methods=['GET','POST'])
def alert_settings():
    """Only authenticated, same-origin JSON writes with a process-bound CSRF token."""
    from intelligence.alert_settings import settings,save
    from intelligence.storage import connect
    if request.method=='POST':
        if not request.is_json or not hmac.compare_digest(request.headers.get('X-Alert-CSRF','').encode(),_alert_csrf.encode()):
            return jsonify({'error':'Reload settings before saving; CSRF token required'}),403
        origin=request.headers.get('Origin')
        if origin and origin.rstrip('/')!=request.host_url.rstrip('/'):
            return jsonify({'error':'Same-origin settings only'}),403
    if not DB.is_file():return jsonify({'error':'Start the scanner before changing settings'}),409
    db=connect(DB)
    try:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='intel_alert_settings'").fetchone():
            return jsonify({'error':'Wait for the intelligence schema migration'}),409
        values=save(db,request.get_json(silent=True)) if request.method=='POST' else settings(db)
        with _intel_lock:_intel_cache.clear()
        return jsonify({'settings':values,'csrf':_alert_csrf,'note':'Scalp switch never bypasses fast-data verification; no credentials stored here.'})
    except ValueError as exc:return jsonify({'error':str(exc)}),400
    except sqlite3.Error:return jsonify({'error':'Settings database busy or unavailable; retry'}),503
    finally:db.close()


# V3 uses short local polling; socket credentials never cross this boundary.
_v3_chart_cache={}
_v3_chart_lock=threading.Lock()

def _v3_write_guard():
    if not request.is_json or not hmac.compare_digest(request.headers.get('X-Alert-CSRF','').encode(),_alert_csrf.encode()):
        return jsonify({'error':'Reload settings; valid CSRF token required'}),403
    origin=request.headers.get('Origin')
    if origin and origin.rstrip('/')!=request.host_url.rstrip('/'):
        return jsonify({'error':'Same-origin requests only'}),403

def _v3_db():
    from intelligence.storage import connect
    if not DB.is_file():raise sqlite3.OperationalError('Scanner initializing')
    db=connect(DB,True)
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='v3_state'").fetchone():db.close();raise sqlite3.OperationalError('V3 migration initializing')
    return db

@app.get('/api/v3/state')
def v3_state():
    db=None
    try:
        from intelligence.v3_dashboard import snapshot as pro_snapshot
        db=_v3_db();return jsonify(pro_snapshot(db))
    except (sqlite3.Error,ValueError,KeyError):return jsonify({'status':'WARMING UP','caller':{'guidance':'WAIT','reason':'Start the upgraded scanner; data collection/migration initializing'}})
    finally:
        if db:db.close()

@app.get('/api/v3/chart')
def v3_chart():
    from intelligence.chart_data import PERIODS,history,payload
    timeframe=request.args.get('timeframe','1m')
    if timeframe not in PERIODS:return jsonify({'error':'Use1m,5m,15m (15s only with verified live tick coverage)'}),400
    db=None
    try:
        db=_v3_db();now=time.time();key=(str(DB),timeframe)
        with _v3_chart_lock:
            cached=_v3_chart_cache.get(key)
            if not cached or now-cached[0]>5:cached=(now,history(db,PERIODS[timeframe],now));_v3_chart_cache[key]=cached
        return jsonify(payload(db,timeframe,now,cached[1]))
    except (sqlite3.Error,ValueError,KeyError):return jsonify({'status':'WARMING UP','candles':[],'indicators':{},'reason':'V3 chart collector initializing'})
    finally:
        if db:db.close()

@app.route('/api/v3/settings',methods=['GET','POST'])
def v3_settings():
    from intelligence.early_exit import settings,set_target
    from intelligence.storage import connect
    if request.method=='POST':
        guard=_v3_write_guard()
        if guard:return guard
    db=None
    try:
        check=_v3_db();check.close();db=connect(DB)
        if request.method=='POST':
            values=request.get_json(silent=True)
            if not isinstance(values,dict) or set(values)!={'target_roi'}:raise ValueError('Only target_roi can be changed here')
            out=set_target(db,values['target_roi'],time.time())
        else:out=settings(db)
        return jsonify({'settings':out,'csrf':_alert_csrf})
    except ValueError as exc:return jsonify({'error':str(exc)}),400
    except sqlite3.Error:return jsonify({'error':'V3 schema not ready'}),409
    finally:
        if db:db.close()

@app.post('/api/v3/watch')
def v3_watch():
    guard=_v3_write_guard()
    if guard:return guard
    from intelligence.early_exit import add_watch
    from intelligence.storage import connect
    db=None
    try:
        check=_v3_db();check.close();db=connect(DB);values=request.get_json(silent=True)
        if isinstance(values,dict) and set(values)=={'close_id'}:
            if type(values['close_id']) is not int or values['close_id']<=0:raise ValueError('Invalid watch id')
            with db:db.execute("UPDATE v3_watch_positions SET state='CLOSED_BY_USER' WHERE id=?",(values['close_id'],))
            return jsonify({'status':'Watch ended; no real position was changed'})
        identifier=add_watch(db,values,time.time());return jsonify({'id':identifier,'status':'USER-SUPPLIED WATCH BASIS ONLY; no orders placed'})
    except ValueError as exc:return jsonify({'error':str(exc)}),400
    except sqlite3.Error:return jsonify({'error':'V3 schema not ready'}),409
    finally:
        if db:db.close()

@app.get('/api/v4/scoreboard')
def v4_scoreboard():
    db=None
    try:
        from intelligence.storage import connect
        from intelligence.v3_dashboard import settlement_summary
        if not DB.is_file():return jsonify({'error':'Database initializing'}),503
        db=connect(DB,True)
        return jsonify({'settlement_score':settlement_summary(db),'as_of':time.time(),'scope':'lifetime','source':'immutable locked forecasts; official settlement only'})
    except sqlite3.Error:return jsonify({'error':'Lifetime results temporarily unavailable; retrying'}),503
    finally:
        if db:db.close()

@app.get('/api/v4/state')
def v4_state():
    db=None
    try:
        from intelligence.v4_runtime import snapshot
        db=_v3_db();return jsonify(snapshot(db,time.time()))
    except (sqlite3.Error,ValueError,KeyError):return jsonify({'status':'WARMING UP','cashout':{'guidance':'WAIT','sides':[]},'positions':[]})
    finally:
        if db:db.close()

@app.post('/api/v4/positions')
def v4_positions():
    guard=_v3_write_guard()
    if guard:return guard
    db=None
    try:
        from intelligence.storage import connect
        from intelligence.v4_positions import create,realized
        check=_v3_db();check.close();db=connect(DB);v=request.get_json(silent=True)
        if isinstance(v,dict) and v.get('action')=='realized':
            v=dict(v);v.pop('action');return jsonify({'net':realized(db,v,time.time()),'status':'USER CONFIRMED; no account verification or order'})
        identifier=create(db,v,time.time());return jsonify({'id':identifier,'status':'Manual basis saved; no trade placed'})
    except ValueError as exc:return jsonify({'error':str(exc)}),400
    except sqlite3.Error:return jsonify({'error':'V4 schema initializing'}),409
    finally:
        if db:db.close()

if __name__ == '__main__':
    # Local testing only; production uses gunicorn in start.sh.
    app.run(host='127.0.0.1',port=8000,debug=False)
