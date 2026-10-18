"""Time-locked, Telegram-acknowledged BTC chart callout evaluation.

This does NOT measure trade profitability: it scores an objectively specified spot
price move three minutes after the original alert. Every call requires fresh live
data; no historical OHLC reconstructs a missed observation.
"""
import math
import sqlite3

from .indicators import ema

HORIZON_SECONDS = 180
MIN_MOVE = 0.0005  # 0.05% BTC move in the originally predicted direction
TOLERANCE_SECONDS = 10

SCHEMA = """
CREATE TABLE IF NOT EXISTS intel_callouts(
 key TEXT PRIMARY KEY,
 ticker TEXT NOT NULL,
 observed REAL NOT NULL,
 direction TEXT NOT NULL CHECK(direction IN ('UP','DOWN')),
 btc_price REAL NOT NULL CHECK(btc_price>0),
 quote_ts REAL NOT NULL,
 horizon INTEGER NOT NULL,
 due REAL NOT NULL,
 minimum_move REAL NOT NULL,
 reason TEXT NOT NULL,
 state TEXT NOT NULL DEFAULT 'QUEUED',
 sent REAL,
 outcome_ts REAL,
 outcome_price REAL,
 outcome TEXT CHECK(outcome IN ('HIT','NOT_HIT','MISSED') OR outcome IS NULL)
);
CREATE INDEX IF NOT EXISTS ico_due ON intel_callouts(due,state);
CREATE INDEX IF NOT EXISTS ico_observed ON intel_callouts(observed);
CREATE TRIGGER IF NOT EXISTS ico_immutable BEFORE UPDATE OF
 key,ticker,observed,direction,btc_price,quote_ts,horizon,due,minimum_move,reason
 ON intel_callouts BEGIN SELECT RAISE(ABORT,'Callout forecast cannot be rewritten'); END;
"""

def ensure(db):
    with db:
        db.executescript(SCHEMA)

def _closed(candles, seconds, now):
    rows = [r for r in candles if r.get('ts') is not None and r['ts'] + seconds <= now]
    return sorted(rows, key=lambda r: r['ts'])

def build(snapshot):
    """Generate only a conservative research WATCH, never an entry recommendation."""
    s = snapshot
    now = s.get('now', 0)
    market = s.get('market') or {}
    if s.get('mode') != 'live' or market.get('closed', 0)-now < HORIZON_SECONDS+30:
        return None
    if not (0 <= now-s.get('quote_ts', 0) <= 2 and
            0 <= now-s.get('book_ts', 0) <= 2 and s.get('book') is not None):
        return None
    price = s.get('price')
    if not isinstance(price, (int, float)) or not math.isfinite(price) or price <= 0:
        return None
    one = _closed(s.get('candles1') or [], 60, now)
    five = _closed(s.get('candles5') or [], 300, now)
    if len(one) < 26 or len(five) < 26 or now-(one[-1]['ts']+60)>90 or now-(five[-1]['ts']+300)>360:
        return None
    if len({r['ts'] for r in one[-26:]}) != 26 or any(b['ts']-a['ts']!=60 for a,b in zip(one[-26:-1],one[-25:])):
        return None
    if len({r['ts'] for r in five[-26:]}) != 26 or any(b['ts']-a['ts']!=300 for a,b in zip(five[-26:-1],five[-25:])):
        return None
    closes1 = [r['close'] for r in one]
    closes5 = [r['close'] for r in five]
    if any(not math.isfinite(float(x)) or float(x)<=0 for x in closes1[-26:]+closes5[-26:]):
        return None
    fast1, slow1 = ema(closes1, 9)[-1], ema(closes1, 21)[-1]
    fast5, slow5 = ema(closes5, 9)[-1], ema(closes5, 21)[-1]
    direction = 'UP' if fast1>slow1 and fast5>slow5 else 'DOWN' if fast1<slow1 and fast5<slow5 else None
    if not direction:
        return None
    # Support/resistance uses only *already completed* 1-minute candles.
    recent = one[-6:-1]
    if direction=='DOWN':
        broke = one[-1]['close'] < min(r['low'] for r in recent)
        aligned = price <= one[-1]['close'] * 1.001
        wording = 'The last completed 1-minute candle closed below recent support.'
    else:
        broke = one[-1]['close'] > max(r['high'] for r in recent)
        aligned = price >= one[-1]['close'] * .999
        wording = 'The last completed 1-minute candle closed above recent resistance.'
    if not broke or not aligned:
        return None
    volume = one[-1].get('volume')
    previous = [r.get('volume') for r in one[-21:-1]]
    active_volume = bool(isinstance(volume,(int,float)) and all(isinstance(v,(int,float)) for v in previous) and
                         sum(previous)>0 and volume >= 1.2*sum(previous)/len(previous))
    reason = f'BTC 1-minute and 5-minute EMA trends both point {direction.lower()}. {wording}'
    if active_volume:
        reason += ' Completed-candle volume is elevated.'
    return {
        'ticker':market['ticker'], 'direction':direction, 'observed':now,
        'quote_ts':s['quote_ts'], 'btc_price':float(price), 'reason':reason,
        'horizon':HORIZON_SECONDS, 'minimum_move':MIN_MOVE,
        'title':f'BTC {direction} momentum building — WATCH',
        'entry':'WAIT — no validated entry signal',
        'exit_target':'Not reliable enough to estimate yet',
        'confidence':'Trend agreement only — no calibrated probability',
        'book_age':now-s['book_ts'], 'quote_age':now-s['quote_ts'],
    }

def message(c):
    return (
        f"{c['title']} (not an entry recommendation)\n"
        f"{c['reason']}\n"
        f"Entry: {c['entry']}\nExit target: {c['exit_target']}\n"
        f"BTC at callout: ${c['btc_price']:,.2f}\n"
        "Record check: exactly 3 minutes after the original observation, "
        "BTC must move at least 0.05% in the predicted direction. "
        "A missing live observation is UNSCORED, not a win.\n"
        "Market prices can change before you see this. Manual trading only."
    )

def record(db, c, key):
    with db:
        return db.execute(
            """INSERT OR IGNORE INTO intel_callouts
             (key,ticker,observed,direction,btc_price,quote_ts,horizon,due,minimum_move,reason,state)
             VALUES(?,?,?,?,?,?,?,?,?,?,'QUEUED')""",
            (key,c['ticker'],c['observed'],c['direction'],c['btc_price'],
             c['quote_ts'],c['horizon'],c['observed']+c['horizon'],
             c['minimum_move'],c['reason'])
        ).rowcount

def acknowledged(db, key, sent):
    with db:
        db.execute(
            "UPDATE intel_callouts SET sent=?,state='PENDING' WHERE key=? AND sent IS NULL",
            (sent,key)
        )

def observe(db, now, quote_ts=None, price=None):
    """Score from a source-time-stamped near-exact endpoint, not later candles."""
    rows = db.execute(
        "SELECT key,btc_price,direction,due,minimum_move FROM intel_callouts WHERE sent IS NOT NULL AND outcome IS NULL AND due<=?",
        (now,)
    ).fetchall()
    for r in rows:
        quote_valid = (isinstance(quote_ts,(int,float)) and isinstance(price,(int,float))
                       and math.isfinite(price) and price>0 and
                       r['due']<=quote_ts<=r['due']+TOLERANCE_SECONDS and
                       0<=now-quote_ts<=2)
        if quote_valid:
            signed = (price/r['btc_price']-1)*(1 if r['direction']=='UP' else -1)
            outcome = 'HIT' if signed>=r['minimum_move'] else 'NOT_HIT'
            with db:
                db.execute(
                    "UPDATE intel_callouts SET outcome=?,outcome_ts=?,outcome_price=?,state='SCORED' WHERE key=? AND outcome IS NULL",
                    (outcome,quote_ts,price,r['key'])
                )
        elif now>r['due']+TOLERANCE_SECONDS+2:
            with db:
                db.execute(
                    "UPDATE intel_callouts SET outcome='MISSED',state='UNSCORED' WHERE key=? AND outcome IS NULL",
                    (r['key'],)
                )
    with db:
        db.execute(
            """UPDATE intel_callouts SET state='NOT_DELIVERED'
               WHERE sent IS NULL AND state='QUEUED'
               AND key IN (SELECT key FROM intel_alerts
                           WHERE state IN ('expired','failed','disabled','superseded'))"""
        )

def summary(db, limit=15):
    try:
        rows = db.execute(
            "SELECT key,ticker,observed,direction,btc_price,reason,due,minimum_move,sent,outcome,outcome_price,outcome_ts,state FROM intel_callouts WHERE sent IS NOT NULL ORDER BY observed DESC LIMIT ?",
            (limit,)
        ).fetchall()
        totals = dict(db.execute(
            """SELECT count(*) AS total,
               sum(CASE WHEN outcome='HIT' THEN 1 ELSE 0 END) hits,
               sum(CASE WHEN outcome='NOT_HIT' THEN 1 ELSE 0 END) not_hits,
               sum(CASE WHEN outcome='MISSED' THEN 1 ELSE 0 END) missed,
               sum(CASE WHEN outcome IS NULL THEN 1 ELSE 0 END) pending
               FROM intel_callouts WHERE sent IS NOT NULL"""
        ).fetchone())
    except sqlite3.OperationalError:
        return {'status':'WARMING UP', 'rows':[], 'total':0, 'hits':0, 'not_hits':0, 'missed':0, 'pending':0, 'hit_rate':None}
    values = {k:int(totals[k] or 0) for k in ('total','hits','not_hits','missed','pending')}
    measured = values['hits']+values['not_hits']
    return {**values,'hit_rate':values['hits']/measured if measured else None,
            'status':'RESEARCH — NOT TRADE RETURNS',
            'definition':'3-minute endpoint: >=0.05% BTC move in the original predicted direction; observed fresh live quotes only. Not a Kalshi trade win rate.',
            'rows':[dict(r) for r in rows]}
