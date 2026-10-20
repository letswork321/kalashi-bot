"""Persistent notification switches; never contains Telegram credentials."""
import os
import sqlite3
import time

CATEGORIES = {'preliminary', 'locked', 'withdrawal', 'directional', 'scalp', 'flip', 'settlement', 'breakout', 'reversal', 'confluence', 'daily', 'callout', 'exit', 'live_change', 'cashout'}

def settings(db, base=None):
    defaults = {c: c in {'directional', 'settlement','locked','withdrawal','callout'} for c in CATEGORIES}
    defaults.update({c.strip(): True for c in os.environ.get('INTELLIGENCE_ALERT_CATEGORIES', '').split(',') if c.strip() in CATEGORIES})
    if base is not None:defaults=dict(base)
    try:
        defaults.update({r[0]: bool(r[1]) for r in db.execute('SELECT category,enabled FROM intel_alert_settings') if r[0] in CATEGORIES})
    except sqlite3.OperationalError:
        pass  # The original scanner also works before the additive migration.
    return defaults

def save(db, values, now=None):
    if not isinstance(values, dict) or not values or any(k not in CATEGORIES or type(v) is not bool for k,v in values.items()):
        raise ValueError('Settings must be known category names and true/false values')
    now = time.time() if now is None else now
    with db:
        for category, enabled in values.items():
            db.execute('INSERT INTO intel_alert_settings VALUES(?,?,?) ON CONFLICT(category) DO UPDATE SET enabled=excluded.enabled,updated=excluded.updated', (category,int(enabled),now))
            if not enabled:
                db.execute("UPDATE intel_alerts SET state='disabled' WHERE category=? AND state='pending'", (category,))
                if category in ('directional','settlement'):
                    table = 'alerts' if category == 'directional' else 'outcome_alerts'
                    if db.execute("SELECT 1 FROM sqlite_master WHERE name=?", (table,)).fetchone():
                        db.execute("UPDATE "+table+" SET status='disabled' WHERE status='pending'")
    return settings(db)
