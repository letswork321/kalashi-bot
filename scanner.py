#!/usr/bin/env python3
"""Read-only KXBTC15M research scanner. No account, order, or fund APIs."""
from __future__ import annotations
import argparse
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from decimal import Decimal, ROUND_CEILING
import json
import math
import os
from pathlib import Path
import sqlite3
import statistics
import sys
import time
from urllib.parse import quote
import requests

KALSHI = 'https://api.elections.kalshi.com/trade-api/v2'
COINBASE = 'https://api.exchange.coinbase.com'
ROOT = Path(__file__).resolve().parent
MODEL = 'heuristic-v1-uncalibrated'

class DataError(Exception):
    pass

def timestamp(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp()

def number(value, positive=False):
    try:
        x = float(value)
    except (TypeError, ValueError):
        raise DataError('Missing or invalid numeric data') from None
    if not math.isfinite(x) or (positive and x <= 0):
        raise DataError('Nonfinite or nonpositive numeric data')
    return x

def emit(data):
    print(json.dumps(data, sort_keys=True, allow_nan=False), flush=True)

class HTTP:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': 'kalashi-research-scanner/1.0', 'Cache-Control': 'no-cache'})

    def get(self, base, path, params=None):
        # Only public data GETs. Never retry malformed JSON as if it were good data.
        for attempt in range(3):
            try:
                r = self.session.get(base + path, params=params, timeout=(5, 12))
            except requests.RequestException:
                raise DataError(f'Network/TLS/proxy failure reaching {base}; check allowed domains') from None
            if r.status_code == 429 or r.status_code >= 500:
                if attempt < 2:
                    delay = r.headers.get('Retry-After', '1')
                    time.sleep(min(10, max(1, float(delay))) if delay.isdigit() else 2)
                    continue
            if r.status_code != 200:
                raise DataError(f'{base}{path}: HTTP {r.status_code}')
            try:
                result = r.json()
            except ValueError:
                raise DataError(f'{base}: expected JSON') from None
            if not isinstance(result, (dict, list)):
                raise DataError(f'{base}: unexpected JSON schema')
            return result
        raise DataError('HTTP retries exhausted')

class Kalshi:
    def __init__(self, http):
        self.http = http

    def market(self, ticker):
        return self.http.get(KALSHI, '/markets/' + quote(ticker, safe=''))['market']

    def current(self, now):
        markets, cursor = [], ''
        for _ in range(20):
            data = self.http.get(KALSHI, '/markets', {'series_ticker': 'KXBTC15M', 'status': 'open', 'limit': 200, 'cursor': cursor, 'min_close_ts': int(now), 'max_close_ts': int(now+3600)})
            markets.extend(data.get('markets', []))
            cursor = data.get('cursor', '')
            if not cursor:
                break
        else:
            raise DataError('Market discovery pagination incomplete')
        eligible = [m for m in markets if m.get('ticker', '').startswith('KXBTC15M-')
                    and m.get('status') in ('active', 'open')
                    and timestamp(m['open_time']) <= now < timestamp(m['close_time'])]
        if not eligible:
            raise DataError('No currently active KXBTC15M market')
        selected = min(eligible, key=lambda m: timestamp(m['close_time']))
        return self.market(selected['ticker'])

    def book(self, ticker):
        data = self.http.get(KALSHI, '/markets/' + quote(ticker, safe='') + '/orderbook', {'depth': 100})
        if 'orderbook_fp' not in data:
            raise DataError('Expected fixed-point dollar orderbook_fp schema')
        return Book.parse(data['orderbook_fp'])

    def series(self):
        s = self.http.get(KALSHI, '/series/KXBTC15M')['series']
        if s.get('fee_type') not in ('quadratic', 'quadratic_with_maker_fees', 'quadratic_with_combo_maker_fees'):
            raise DataError('Unsupported Kalshi fee type; verify the current schedule')
        multiplier = number(s.get('fee_multiplier'))
        if multiplier < 0:
            raise DataError('Invalid fee multiplier')
        return multiplier

    def fees(self, market, now):
        multiplier = self.series()
        event = market.get('event_ticker')
        if not event:
            raise DataError('Missing event ticker for fee verification')
        changes, cursor = [], ''
        for _ in range(20):
            data = self.http.get(KALSHI, '/events/fee_changes', {'event_ticker':event,'limit':200,'cursor':cursor})
            changes.extend(data['event_fee_changes'])
            cursor = data.get('cursor', '')
            if not cursor:
                break
        else:
            raise DataError('Fee override pagination incomplete')
        effective = [c for c in changes if c['event_ticker'] == event and timestamp(c['scheduled_ts']) <= now]
        if effective:
            latest = max(effective, key=lambda c:timestamp(c['scheduled_ts']))
            kind, value = latest.get('fee_type_override'), latest.get('fee_multiplier_override')
            if kind is not None:
                if kind not in ('quadratic','quadratic_with_maker_fees','quadratic_with_combo_maker_fees') or value is None:
                    raise DataError('Unsupported event fee override')
                multiplier = number(value)
                if multiplier < 0:
                    raise DataError('Negative event fee multiplier')
        return multiplier

@dataclass
class Book:
    yes: list
    no: list

    @classmethod
    def parse(cls, data):
        def side(name):
            rows = []
            for p, q in data.get(name, []):
                p, q = number(p), number(q)
                if not 0 < p < 1 or q < 0:
                    raise DataError('Invalid dollar price or orderbook quantity')
                if q:
                    rows.append((p, q))
            return sorted(rows, reverse=True)
        b = cls(side('yes_dollars'), side('no_dollars'))
        if not b.yes or not b.no:
            raise DataError('Two-sided orderbook unavailable')
        if b.yes[0][0] + b.no[0][0] > 1.000001:
            raise DataError('Crossed orderbook; wait for a fresh snapshot')
        return b

    @property
    def spread(self):
        return 1 - self.yes[0][0] - self.no[0][0]

    @property
    def implied(self):
        return (self.yes[0][0] + 1 - self.no[0][0]) / 2

    @property
    def imbalance(self):
        y, n = sum(q for _, q in self.yes[:5]), sum(q for _, q in self.no[:5])
        return (y - n) / (y + n)

    def entry(self, direction, quantity, slippage):
        # YES asks are complements of NO bids; NO asks complement YES bids.
        levels = self.no if direction == 'UP' else self.yes
        remaining, cost = quantity, 0.0
        for p, available in levels:
            take = min(remaining, available)
            cost += take * (1 - p)
            remaining -= take
            if remaining <= 1e-9:
                price = cost / quantity + slippage
                if price >= 1:
                    raise DataError('Entry plus slippage is not below payout')
                return price
        raise DataError('Insufficient visible depth for paper size')

@dataclass
class Feed:
    price: float
    time: float
    candles: list

class Coinbase:
    def __init__(self, http):
        self.http = http
        self.cached = None
        self.cached_at = 0

    def snapshot(self, now):
        ticker = self.http.get(COINBASE, '/products/BTC-USD/ticker')
        price, tick_time = number(ticker.get('price'), True), timestamp(ticker['time'])
        if self.cached is None or now - self.cached_at >= 30:
            iso = lambda t: datetime.fromtimestamp(t,timezone.utc).isoformat()
            # A rolling explicit window avoids stale CDN responses for the bare URL.
            candles = self.http.get(COINBASE, '/products/BTC-USD/candles',
                                    {'granularity':60,'start':iso(now-180*60),'end':iso(now)})
            if not isinstance(candles, list):
                raise DataError('Expected Coinbase candle list')
            self.cached, self.cached_at = candles, now
        return Feed(price, tick_time, self.cached)

def indicators(feed, now):
    if not -5 <= now - feed.time <= 20:
        raise DataError('BTC trade timestamp stale or in the future')
    rows = sorted(feed.candles, key=lambda r: r[0])
    if any(len(r) != 6 for r in rows):
        raise DataError('Invalid OHLCV schema')
    rows = [r for r in rows if number(r[0]) + 60 <= now]
    rows = rows[-120:]
    if len(rows) < 60:
        raise DataError('Need at least 60 closed one-minute candles')
    if not 0 <= now - rows[-1][0] - 60 <= 120:
        raise DataError('BTC candles stale')
    if any(b[0] - a[0] != 60 for a, b in zip(rows, rows[1:])):
        raise DataError('Missing or duplicate one-minute candles')
    for t, low, high, op, close, volume in rows:
        low, high, op, close = [number(x, True) for x in (low, high, op, close)]
        if low > min(op, close) or high < max(op, close) or number(volume) < 0:
            raise DataError('Invalid candle bounds or volume')
    closes = [number(r[4], True) for r in rows]
    volumes = [number(r[5]) for r in rows]
    returns = [math.log(b/a) for a, b in zip(closes, closes[1:])]
    def ema(period):
        e, alpha = closes[0], 2/(period+1)
        for c in closes[1:]:
            e += alpha * (c - e)
        return e
    deltas = [b-a for a,b in zip(closes, closes[1:])]
    gain = sum(max(d, 0) for d in deltas[:14])/14
    loss = sum(max(-d, 0) for d in deltas[:14])/14
    for d in deltas[14:]:
        gain = (gain*13 + max(d, 0))/14
        loss = (loss*13 + max(-d, 0))/14
    rsi = 50 if gain == loss == 0 else (100 if loss == 0 else 100 - 100/(1+gain/loss))
    baseline = statistics.mean(volumes[-21:-1])
    return {'rsi14': rsi, 'ema9': ema(9), 'ema21': ema(21),
            'momentum_3m': math.log(feed.price / closes[-4]),
            'momentum_10m': math.log(feed.price / closes[-11]),
            'volatility_1m': max(statistics.stdev(returns[-60:]), 0.00005),
            'volume_ratio': volumes[-1]/baseline if baseline > 0 else 0,
            'last_candle_end': rows[-1][0] + 60}

@dataclass
class Config:
    poll: float = 10
    quantity: int = 1
    min_edge: float = 0.05
    min_probability: float = 0.60
    max_spread: float = 0.08
    slippage: float = 0.002
    fee_rate: float = 0.07
    min_seconds: float = 90
    alert_cooldown: float = 60
    alert_delta: float = 0.05

def fee(price, quantity, rate, multiplier):
    raw = Decimal(str(rate)) * Decimal(str(multiplier)) * Decimal(str(quantity)) * Decimal(str(price)) * (1-Decimal(str(price)))
    cost = Decimal(str(price)) * Decimal(str(quantity))
    return float((cost+raw).quantize(Decimal('0.0001'), rounding=ROUND_CEILING)-cost)

def forecast_components(market, book, feed, now):
    if market.get('status') not in ('active', 'open'):
        raise DataError('Market is not active')
    if market.get('market_type') != 'binary' or market.get('strike_type') != 'greater_or_equal':
        raise DataError('Unsupported contract settlement direction')
    if not market.get('ticker', '').startswith('KXBTC15M-'):
        raise DataError('Unexpected market series')
    strike = number(market.get('floor_strike'), True)
    remaining = timestamp(market['close_time']) - now
    opened = timestamp(market['open_time'])
    if now < opened or remaining <= 0 or not 0 < timestamp(market['close_time'])-opened <= 901:
        raise DataError('Market is outside its 15-minute trading window')
    f = indicators(feed, now)
    # Explicit heuristic, not a trained or calibrated probability model.
    # Damp momentum and blend with book consensus to reduce overconfidence.
    horizon = remaining / 60
    vol = f['volatility_1m']
    trend = (f['ema9']-f['ema21']) / feed.price
    drift = max(-vol, min(vol, 0.15*f['momentum_3m']/3 + 0.10*trend))
    z = (math.log(feed.price/strike) + drift*horizon) / (vol*math.sqrt(max(horizon, 1)))
    price_prob = (1 + math.erf(z/math.sqrt(2)))/2
    adjustment = 0.015*math.tanh((f['rsi14']-50)/20) + 0.015*book.imbalance
    adjustment += 0.01*math.tanh(f['momentum_10m']/max(vol, 1e-6))*min(f['volume_ratio'], 2)/2
    p_up = min(0.95, max(0.05, 0.60*price_prob + 0.40*book.implied + adjustment))
    return f,p_up,strike,remaining

def analyze(market, book, feed, now, config, multiplier):
    f,p_up,strike,remaining=forecast_components(market,book,feed,now)
    candidates = []
    for direction, p in [('UP', p_up), ('DOWN', 1-p_up)]:
        try:
            entry = book.entry(direction, config.quantity, config.slippage)
            entry_fee = fee(entry, config.quantity, config.fee_rate, multiplier)
            candidates.append({'direction': direction, 'probability': p, 'entry': entry,
                               'fee': entry_fee, 'edge': p-entry-entry_fee/config.quantity})
        except DataError:
            pass
    best = max(candidates, key=lambda x:x['edge']) if candidates else None
    reason = 'Estimated edge and probability pass thresholds'
    signal = best['direction'] if best else 'NO TRADE'
    if remaining < config.min_seconds:
        signal, reason = 'NO TRADE', 'Inside final settlement averaging window / time buffer'
    elif book.spread > config.max_spread:
        signal, reason = 'NO TRADE', 'Orderbook spread too wide'
    elif not best or best['edge'] < config.min_edge or best['probability'] < config.min_probability:
        signal, reason = 'NO TRADE', 'Insufficient estimated edge, confidence, or depth'
    strength = 'NONE' if signal == 'NO TRADE' else ('STRONG' if best['probability'] >= 0.75 and best['edge'] >= 0.10 else 'WEAK')
    return {'ticker': market['ticker'], 'signal': signal, 'strength': strength, 'p_up': p_up,
            'p_down': 1-p_up, 'reason': reason, 'model': MODEL, 'calibrated': False,
            'btc_source': 'Coinbase BTC-USD (not settlement index)', 'btc_price': feed.price,
            'btc_timestamp': feed.time, 'official_strike': strike, 'strike_source': 'Kalshi floor_strike',
            'close_time': market['close_time'], 'seconds_remaining': remaining,
            'spread': book.spread, 'book_p_up': book.implied, 'imbalance': book.imbalance,
            'features': f, 'candidate': best, 'quantity': config.quantity,
            'fee_rate_assumption': config.fee_rate, 'fee_multiplier': multiplier,
            'rules_primary': market.get('rules_primary', ''), 'observed_at': now}

class Store:
    def __init__(self, path, mode='live'):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS predictions(
          id INTEGER PRIMARY KEY, observed REAL NOT NULL, ticker TEXT, signal TEXT NOT NULL,
          p_up REAL, payload TEXT NOT NULL, result TEXT);
        CREATE INDEX IF NOT EXISTS prediction_pending ON predictions(result,ticker);
        CREATE TABLE IF NOT EXISTS paper(
          ticker TEXT PRIMARY KEY, prediction_id INTEGER NOT NULL, direction TEXT NOT NULL,
          quantity INTEGER NOT NULL, entry REAL NOT NULL, fee REAL NOT NULL,
          opened REAL NOT NULL, result TEXT, pnl REAL, settled REAL);
        CREATE TABLE IF NOT EXISTS settlements(
          ticker TEXT PRIMARY KEY,result TEXT NOT NULL,checked REAL NOT NULL,payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS alerts(
          id INTEGER PRIMARY KEY,prediction_id INTEGER UNIQUE NOT NULL,ticker TEXT NOT NULL,
          created REAL NOT NULL,expires REAL NOT NULL,payload TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'pending',attempts INTEGER NOT NULL DEFAULT 0,
          next_try REAL NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS outcome_alerts(
          ticker TEXT PRIMARY KEY,created REAL NOT NULL,message TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'pending',attempts INTEGER NOT NULL DEFAULT 0,
          next_try REAL NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS alert_state(
          ticker TEXT PRIMARY KEY, signal TEXT NOT NULL,strength TEXT NOT NULL,p_up REAL,
          queued REAL NOT NULL);
        ''')
        row = self.db.execute("SELECT value FROM metadata WHERE key='mode'").fetchone()
        if row and row[0] != mode:
            raise DataError('Refusing to mix mock and live databases')
        self.db.execute("INSERT OR IGNORE INTO metadata VALUES('mode',?)", (mode,))
        self.db.commit()

    def record(self, p, config, alerts=False):
        now = p['observed_at']
        with self.db:
            cur = self.db.execute('INSERT INTO predictions(observed,ticker,signal,p_up,payload) VALUES(?,?,?,?,?)',
                                  (now,p.get('ticker'),p['signal'],p.get('p_up'),json.dumps(p, allow_nan=False)))
            pid = cur.lastrowid
            c = p.get('candidate')
            if p['signal'] != 'NO TRADE' and c:
                self.db.execute('INSERT OR IGNORE INTO paper(ticker,prediction_id,direction,quantity,entry,fee,opened) VALUES(?,?,?,?,?,?,?)',
                                (p['ticker'],pid,p['signal'],config.quantity,c['entry'],c['fee'],now))
            from intelligence.alert_settings import settings
            advanced=self.db.execute("SELECT 1 FROM sqlite_master WHERE name='intel_entry_state'").fetchone()
            if alerts and not advanced and settings(self.db)['directional'] and p.get('ticker'):
                prev = self.db.execute('SELECT * FROM alert_state WHERE ticker=?',(p['ticker'],)).fetchone()
                # First NO TRADE is quiet; a change from an actionable signal is useful.
                actionable = p['signal'] in ('UP','DOWN')
                strong = actionable and p['strength'] == 'STRONG'
                reversal = bool(prev and actionable and prev['signal'] in ('UP','DOWN')
                                and p['signal'] != prev['signal'] and p.get('candidate',{}).get('probability',0) >= 0.65)
                withdrawn = bool(prev and p['signal'] == 'NO TRADE' and prev['signal'] != 'NO TRADE')
                changed = (strong and (not prev or p['signal'] != prev['signal'] or prev['strength'] != 'STRONG'
                           or (p.get('p_up') is not None and prev['p_up'] is not None
                               and abs(p['p_up']-prev['p_up']) >= config.alert_delta))) or reversal or withdrawn
                if changed and (not prev or now-prev['queued'] >= config.alert_cooldown):
                    self.db.execute("UPDATE alerts SET status='superseded' WHERE ticker=? AND status='pending'", (p['ticker'],))
                    expires = min(timestamp(p['close_time'])-config.min_seconds, now+120) if p['signal'] != 'NO TRADE' else now+120
                    self.db.execute('INSERT INTO alerts(prediction_id,ticker,created,expires,payload) VALUES(?,?,?,?,?)',
                                    (pid,p['ticker'],now,expires,json.dumps(p)))
                    self.db.execute('INSERT OR REPLACE INTO alert_state VALUES(?,?,?,?,?)',
                                    (p['ticker'],p['signal'],p['strength'],p.get('p_up'),now))
            # Invalidate stale opposing messages immediately, even during cooldown.
            if p.get('ticker'):
                rows = self.db.execute("SELECT id,payload FROM alerts WHERE ticker=? AND status='pending'", (p['ticker'],)).fetchall()
                for row in rows:
                    if json.loads(row['payload'])['signal'] != p['signal']:
                        self.db.execute("UPDATE alerts SET status='superseded' WHERE id=?",(row['id'],))
        return pid

    def pending(self):
        return [r[0] for r in self.db.execute('SELECT DISTINCT ticker FROM predictions WHERE ticker IS NOT NULL AND result IS NULL')]

    def settle(self, market, now, alerts=False):
        # Never infer settlement from spot, price, close_time, or expiration_value.
        result = market.get('result')
        if market.get('status') not in ('finalized', 'settled') or result not in ('yes','no'):
            return False
        ticker = market['ticker']
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO settlements VALUES(?,?,?,?)', (ticker,result,now,json.dumps(market)))
            self.db.execute('UPDATE predictions SET result=? WHERE ticker=? AND result IS NULL',(result,ticker))
            pos = self.db.execute('SELECT * FROM paper WHERE ticker=? AND result IS NULL',(ticker,)).fetchone()
            if pos:
                won = (pos['direction']=='UP') == (result=='yes')
                pnl = pos['quantity']*(int(won)-pos['entry'])-pos['fee']
                self.db.execute('UPDATE paper SET result=?,pnl=?,settled=? WHERE ticker=?',(result,pnl,now,ticker))
                if alerts:
                    message = (f"Kalshi FINAL {ticker}: {result.upper()} / {'UP' if result=='yes' else 'DOWN'}\n"
                               f"Paper {pos['direction']}: {'WIN' if won else 'LOSS'}; net P&L ${pnl:+.3f}\n"
                               'Official Kalshi settlement. Paper accounting only; no real orders.')
                    self.db.execute('INSERT OR IGNORE INTO outcome_alerts(ticker,created,message) VALUES(?,?,?)',
                                    (ticker,now,message))
        return True

    def report(self):
        rows = self.db.execute('SELECT * FROM predictions WHERE result IS NOT NULL AND p_up IS NOT NULL ORDER BY id').fetchall()
        first = {}
        for r in rows:
            first.setdefault(r['ticker'], r)
        directional = [r for r in rows if r['signal'] in ('UP','DOWN')]
        accuracy = lambda rs: sum((r['p_up']>=0.5)==(r['result']=='yes') for r in rs)/len(rs) if rs else None
        paper = self.db.execute('SELECT * FROM paper WHERE pnl IS NOT NULL ORDER BY settled,ticker').fetchall()
        costs = sum(p['quantity']*p['entry']+p['fee'] for p in paper)
        equity = peak = drawdown = 0
        for p in paper:
            equity += p['pnl']; peak = max(peak,equity); drawdown = max(drawdown,peak-equity)
        calibration = []
        for lo in range(0, 10):
            bucket = [r for r in rows if lo/10 <= r['p_up'] < (lo+1)/10]
            if bucket:
                calibration.append({'p_range':[lo/10,(lo+1)/10], 'n':len(bucket),
                                    'mean_p':statistics.mean(r['p_up'] for r in bucket),
                                    'observed_up_rate':sum(r['result']=='yes' for r in bucket)/len(bucket)})
        return {'mode':self.db.execute("SELECT value FROM metadata WHERE key='mode'").fetchone()[0],
                'predictions_total':self.db.execute('SELECT count(*) FROM predictions').fetchone()[0],
                'no_trade_total':self.db.execute("SELECT count(*) FROM predictions WHERE signal='NO TRADE'").fetchone()[0],
                'settled_forecasts':len(rows), 'settled_distinct_markets':len(first),
                'forecast_accuracy_all_snapshots':accuracy(rows),
                'first_forecast_per_market_accuracy':accuracy(list(first.values())),
                'actionable_signal_accuracy':sum((r['signal']=='UP')==(r['result']=='yes') for r in directional)/len(directional) if directional else None,
                'brier_score':statistics.mean((r['p_up']-int(r['result']=='yes'))**2 for r in rows) if rows else None,
                'calibration_bins':calibration, 'pending_markets':len(self.pending()),
                'paper_settled':len(paper), 'paper_open':self.db.execute('SELECT count(*) FROM paper WHERE result IS NULL').fetchone()[0],
                'paper_net_pnl':equity, 'paper_roi_on_cost':equity/costs if costs else None,
                'paper_win_rate':sum(p['pnl']>0 for p in paper)/len(paper) if paper else None,
                'paper_max_realized_drawdown':drawdown,
                'note':'Heuristic uncalibrated probabilities; repeated forecasts are correlated. Paper fills/fees are estimates; no real trades.'}

class Telegram:
    def __init__(self):
        self.token = os.environ.get('TELEGRAM_BOT_TOKEN', '')
        self.chat = os.environ.get('TELEGRAM_CHAT_ID', '')
        self.session = requests.Session()

    @property
    def enabled(self):
        return bool(self.token and self.chat)

    def send(self, message):
        if not self.enabled:
            raise DataError('Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID securely in environment settings')
        # Never log Telegram URL or raw exception: it contains the bot token.
        try:
            r = self.session.post('https://api.telegram.org/bot'+self.token+'/sendMessage',
                                  json={'chat_id':self.chat,'text':message,'disable_web_page_preview':True},timeout=(5,12))
        except requests.RequestException:
            raise DataError('Telegram network/TLS/proxy failure (credentials redacted)') from None
        try:
            data = r.json()
        except ValueError:
            raise DataError('Telegram non-JSON response (details redacted)') from None
        if not r.ok or data.get('ok') is not True:
            raise DataError(f'Telegram delivery failed: HTTP {r.status_code} (details redacted)')
        return True

    def chat_ids(self):
        if not self.token:
            raise DataError('Set TELEGRAM_BOT_TOKEN securely first')
        try:
            r = self.session.get('https://api.telegram.org/bot'+self.token+'/getUpdates',timeout=(5,12))
            data = r.json()
        except (requests.RequestException,ValueError):
            raise DataError('Telegram chat lookup failed (credentials redacted)') from None
        if not r.ok or data.get('ok') is not True:
            raise DataError('Telegram chat lookup rejected (credentials redacted); check token or existing webhook')
        chats = {}
        for update in data.get('result',[]):
            chat = update.get('message',{}).get('chat',{})
            if 'id' in chat:
                chats[str(chat['id'])] = chat.get('type','unknown')
        return chats

    @staticmethod
    def message(p):
        text = f"Kalshi {p['ticker']}\n{p['signal']} / {p['strength']}\n"
        if p.get('p_up') is not None:
            text += f"Estimated UP {p['p_up']:.1%}, DOWN {p['p_down']:.1%} (uncalibrated)\n"
            text += f"BTC Coinbase ${p['btc_price']:,.2f}; official strike ${p['official_strike']:,.2f}\n"
            text += f"Remaining {p['seconds_remaining']:.0f}s; spread ${p['spread']:.3f}\n"
            c = p.get('candidate')
            if c:
                text += f"Paper {c['direction']} entry ${c['entry']:.3f}, fee ${c['fee']:.4f}, estimated edge {c['edge']:.1%}\n"
        return text+p['reason']+'\nCF Benchmarks settles; Coinbase is a proxy. Manual trades only.'

    def flush(self, store, now, signals=True):
        if not self.enabled:
            return
        with store.db:
            store.db.execute("UPDATE alerts SET status='expired' WHERE status='pending' AND expires<=?",(now,))
        from intelligence.alert_settings import settings
        from intelligence.notifications import record_legacy_delivery,settlement_sent,Notifications
        switches=settings(store.db)
        advanced=store.db.execute("SELECT 1 FROM sqlite_master WHERE name='intel_entry_state'").fetchone()
        with store.db:
            if advanced:store.db.execute("UPDATE alerts SET status='superseded' WHERE status='pending'")
            if not switches['directional']:store.db.execute("UPDATE alerts SET status='disabled' WHERE status='pending'")
            if not switches['settlement']:store.db.execute("UPDATE outcome_alerts SET status='disabled' WHERE status='pending'")
        for row in store.db.execute("SELECT * FROM alerts WHERE status='pending' AND next_try<=? ORDER BY id LIMIT 3",(now if signals else -1,)).fetchall():
            observation=json.loads(row['payload'])
            # Do not deliver an old entry merely because its retry is now due.
            if observation.get('signal') in ('UP','DOWN') and not (0<=now-observation.get('observed_at',0)<=5 and 0<=now-observation.get('btc_timestamp',0)<=5):
                with store.db:store.db.execute("UPDATE alerts SET status='expired' WHERE id=?",(row['id'],))
                continue
            try:
                self.send(self.message(observation))
            except DataError as e:
                with store.db:
                    store.db.execute('UPDATE alerts SET attempts=attempts+1,next_try=? WHERE id=?',
                                     (now+min(300,15*2**min(row['attempts'],4)),row['id']))
                emit({'telegram_error':str(e)})
            else:
                with store.db:
                    store.db.execute("UPDATE alerts SET status='sent',attempts=attempts+1 WHERE id=?",(row['id'],))
                record_legacy_delivery(store.db,'legacy-entry:'+str(row['id']),'directional',row['ticker'],time.time(),observation,observation.get('signal') if observation.get('signal') in ('UP','DOWN') else None,row['created'])

        for row in store.db.execute("SELECT * FROM outcome_alerts WHERE status='pending' AND next_try<=? ORDER BY created LIMIT 3",(now,)).fetchall():
            if advanced:
                # One persisted dispatcher/outbox owns outcomes after migration.
                # This prevents races between original and intelligence senders.
                key='final:'+row['ticker']
                Notifications(store.db,self).enqueue('settlement',row['ticker'],key,row['message'],now,now+3600)
                if store.db.execute('SELECT 1 FROM intel_alerts WHERE key=?',(key,)).fetchone():
                    with store.db:store.db.execute("UPDATE outcome_alerts SET status='forwarded' WHERE ticker=?",(row['ticker'],))
                continue
            if settlement_sent(store.db,row['ticker']):
                with store.db:store.db.execute("UPDATE outcome_alerts SET status='superseded' WHERE ticker=?",(row['ticker'],))
                continue
            try:
                self.send(row['message'])
            except DataError as e:
                with store.db:
                    store.db.execute('UPDATE outcome_alerts SET attempts=attempts+1,next_try=? WHERE ticker=?',
                                     (now+min(300,15*2**min(row['attempts'],4)),row['ticker']))
                emit({'telegram_error':str(e)})
            else:
                with store.db:
                    store.db.execute("UPDATE outcome_alerts SET status='sent',attempts=attempts+1 WHERE ticker=?",(row['ticker'],))
                record_legacy_delivery(store.db,'legacy-outcome:'+row['ticker'],'settlement',row['ticker'],time.time(),{'message':row['message']},created=row['created'])

class Engine:
    def __init__(self, store, config, telegram=None):
        self.store, self.config, self.telegram = store, config, telegram
        self.http = HTTP()
        self.kalshi, self.btc = Kalshi(self.http), Coinbase(self.http)
        self.last_settle = 0
        self.multiplier = None
        self.last_series = 0
        self.fee_ticker = None

    def reconcile(self, now):
        for ticker in self.store.pending():
            try:
                m = self.kalshi.market(ticker)
                if self.store.settle(m, now, alerts=bool(self.telegram and self.telegram.enabled)):
                    emit({'settled':ticker,'result':m['result']})
            except (DataError, KeyError, TypeError, ValueError) as e:
                emit({'settlement_pending':ticker,'reason':str(e)})

    def cycle(self):
        now, market = time.time(), None
        if now-self.last_settle >= 60:
            self.reconcile(now)
            self.last_settle = now
        try:
            market = self.kalshi.current(now)
            if self.multiplier is None or market['ticker'] != self.fee_ticker or now-self.last_series >= 60:
                self.multiplier = self.kalshi.fees(market,now)
                self.last_series = now
                self.fee_ticker = market['ticker']
            book = self.kalshi.book(market['ticker'])
            feed = self.btc.snapshot(time.time())
            observed = time.time()
            if observed-now > 15:
                raise DataError('Market/book snapshot too old after slow input fetch')
            p = analyze(market,book,feed,observed,self.config,self.multiplier)
        except (DataError, KeyError, TypeError, ValueError, OverflowError) as e:
            p = {'ticker':market.get('ticker') if market else None,'signal':'NO TRADE','strength':'NONE',
                 'p_up':None,'reason':str(e),'observed_at':time.time(),'model':MODEL,
                 'close_time':market.get('close_time') if market else None,
                 'official_strike':market.get('floor_strike') if market else None,
                 'kalshi_connected':market is not None}
        self.store.record(p,self.config,alerts=bool(self.telegram and self.telegram.enabled))
        emit(p)
        if self.telegram:
            # If discovery failed, don't deliver old alerts without current validation.
            self.telegram.flush(self.store,time.time(),signals=market is not None)
        return p

def mock_inputs(now):
    # Explicit test fixture. Never reachable from the live Engine.
    closes = [80000+8*i+3*math.sin(i) for i in range(100)]
    start = int(now//60)*60-100*60
    candles = [[start+i*60,c-10,c+10,c-2,c,5+i%3] for i,c in enumerate(closes)]
    iso = lambda x: datetime.fromtimestamp(x,timezone.utc).isoformat()
    m = {'ticker':'KXBTC15M-MOCK-TEST','market_type':'binary','strike_type':'greater_or_equal',
         'status':'active','floor_strike':80500,'open_time':iso(now-300),'close_time':iso(now+600),
         'rules_primary':'MOCK TEST ONLY'}
    return m, Book.parse({'yes_dollars':[['0.48','100']], 'no_dollars':[['0.48','100']]}), Feed(closes[-1]+5,now,candles)

def acquire_lock(db):
    handle = open(str(db)+'.lock','a+b')
    try:
        if os.name == 'nt':
            import msvcrt
            handle.seek(0,2)
            if handle.tell() == 0:
                handle.write(b'0'); handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
        else:
            import fcntl
            fcntl.flock(handle,fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        raise DataError('Another scanner is already running for this database') from None
    return handle

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--once',action='store_true')
    parser.add_argument('--check-live',action='store_true',help='Probe real sources, no signals, paper entries or Telegram messages')
    parser.add_argument('--report',action='store_true')
    parser.add_argument('--settle',action='store_true',help='Reconcile existing predictions against official results once')
    parser.add_argument('--telegram-chat-id',action='store_true',help='Read chat IDs after you send /start to your own bot')
    parser.add_argument('--telegram-test',action='store_true',help='Send one explicit Telegram test message')
    parser.add_argument('--mock',action='store_true',help='One isolated synthetic test cycle; no network or Telegram')
    parser.add_argument('--db',type=Path,default=Path(os.environ.get('SCANNER_DB',str(ROOT/'data'/'live.sqlite3'))))
    parser.add_argument('--poll',type=float,default=10)
    parser.add_argument('--quantity',type=int,default=1)
    parser.add_argument('--fee-rate',type=float,default=0.07,help='Estimated quadratic taker fee coefficient; verify current schedule')
    args = parser.parse_args(argv)
    if not math.isfinite(args.poll) or args.poll < 5 or args.quantity < 1 or not 0 <= args.fee_rate <= 1:
        parser.error('poll must be >=5s, quantity >=1, and fee-rate between 0 and 1')
    if sum([args.check_live,args.report,args.settle,args.telegram_test,args.telegram_chat_id,args.mock]) > 1:
        parser.error('Choose only one action mode')
    config = Config(poll=args.poll,quantity=args.quantity,fee_rate=args.fee_rate)
    if args.telegram_chat_id:
        emit({'chat_ids':Telegram().chat_ids(),'tip':'Send /start to your bot first if this is empty'})
        return 0
    if args.telegram_test:
        Telegram().send('Kalshi scanner connection test. Manual trades only; no trading API configured.')
        emit({'telegram_test':'delivered'})
        return 0
    if args.check_live:
        http, checks = HTTP(), {}
        k = Kalshi(http)
        m = None
        try:
            m = k.current(time.time())
            b = k.book(m['ticker'])
            multiplier = k.fees(m,time.time())
            number(m.get('floor_strike'),True)
            checks['kalshi'] = {'ticker':m['ticker'],'official_strike':m['floor_strike'],
                                'spread':b.spread,'fee_multiplier':multiplier,'close_time':m['close_time'],
                                'rules':m.get('rules_primary')}
        except (DataError,KeyError,ValueError,TypeError) as e:
            checks['kalshi_error'] = str(e)
        try:
            f = Coinbase(http).snapshot(time.time())
            features = indicators(f,time.time())
            checks['coinbase'] = {'btc_price':f.price,'trade_time':f.time,'features':features}
        except (DataError,KeyError,ValueError,TypeError) as e:
            checks['coinbase_error'] = str(e)
        checks['telegram_configured'] = Telegram().enabled
        checks['ready_for_prediction'] = 'kalshi' in checks and 'coinbase' in checks
        emit(checks)
        return 0 if checks['ready_for_prediction'] else 1
    db = ROOT/'data'/'mock.sqlite3' if args.mock else args.db
    upgrade_worker = None
    store = Store(db,'mock' if args.mock else 'live')
    try:
        if args.report:
            emit(store.report())
            return 0
        if args.mock:
            now = time.time()
            p = analyze(*mock_inputs(now),now,config,1)
            p['mode']='MOCK TEST ONLY'
            p['btc_source']='SYNTHETIC TEST FIXTURE'
            p['strike_source']='SYNTHETIC TEST FIXTURE'
            store.record(p,config,alerts=False)
            emit(p)
            return 0
        # One live scanner per database, including across deployment workers/restarts.
        lock = acquire_lock(db)
        engine = Engine(store,config,Telegram())
        if args.settle:
            engine.reconcile(time.time())
            emit(store.report())
            return 0
        if not args.once and os.environ.get('INTELLIGENCE_ENABLED','true').lower() == 'true':
            from intelligence.service import IntelligenceWorker
            upgrade_worker = IntelligenceWorker(db, engine.telegram)
            upgrade_worker.start()
        emit({'mode':'LIVE READ-ONLY','model':MODEL,'telegram_enabled':engine.telegram.enabled,
              'database':str(db),'trade_execution':False})
        while True:
            p = engine.cycle()
            if args.once:
                return 0 if p.get('p_up') is not None else 1
            time.sleep(config.poll)
    finally:
        if upgrade_worker: upgrade_worker.close()
        store.db.close()

if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print('\nScanner stopped.',flush=True)
    except DataError as e:
        emit({'error':str(e)})
        sys.exit(1)
