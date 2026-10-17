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

if __name__ == '__main__':
    # Local testing only; production uses gunicorn in start.sh.
    app.run(host='127.0.0.1',port=8000,debug=False)
