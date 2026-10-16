"""Read-only dashboard. Run behind an HTTPS reverse proxy with DASHBOARD_PASSWORD."""
import hmac
import json
import os
from pathlib import Path
import sqlite3
import time
import threading
from flask import Flask, Response, jsonify, render_template, request
from scanner import ROOT, Store, timestamp

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 1024
DB = Path(os.environ.get('SCANNER_DB', str(ROOT/'data'/'live.sqlite3')))
_report_cache = {}
_report_lock = threading.Lock()

@app.before_request
def authenticate():
    if request.path == '/healthz':
        return None
    password = os.environ.get('DASHBOARD_PASSWORD', '')
    if not password:
        return Response('Set DASHBOARD_PASSWORD before starting the dashboard.',status=503)
    auth = request.authorization
    if not auth or not hmac.compare_digest(auth.username or '', 'viewer') or not hmac.compare_digest((auth.password or '').encode(), password.encode()):
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
    db = sqlite3.connect('file:'+str(DB)+'?mode=ro', uri=True,timeout=5)
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

@app.get('/healthz')
def health():
    # Process health only. /api/state reports source freshness separately.
    return jsonify({'web':'ok'})

if __name__ == '__main__':
    # Local testing only; production uses gunicorn in start.sh.
    app.run(host='127.0.0.1',port=8000,debug=False)
