"""Additional alert categories are opt-in, bounded, persisted, and stale-safe."""
import hashlib
import os
from .storage import dumps,loads

CATEGORIES={'breakout','reversal','confluence','flip','scalp','settlement','daily','directional'}
class Notifications:
    def __init__(self,db,telegram):
        self.db,self.telegram=db,telegram
        self.enabled={x.strip() for x in os.environ.get('INTELLIGENCE_ALERT_CATEGORIES','').split(',')}&CATEGORIES
    def enqueue(self,category,ticker,key,message,now,expires):
        if category not in self.enabled or not self.telegram or not self.telegram.enabled or expires<=now:return False
        previous=self.db.execute('SELECT created FROM intel_alerts WHERE category=? AND ticker=? ORDER BY created DESC LIMIT 1',(category,ticker)).fetchone()
        if previous and now-previous['created']<300:return False
        with self.db:self.db.execute('INSERT OR IGNORE INTO intel_alerts(key,category,ticker,created,expires,message) VALUES(?,?,?,?,?,?)',(key,category,ticker,now,expires,message))
        return True
    def signals(self,s,engines,flips,scalps):
        if s.get('fee_valid') is False or s.get('mode')!='live' or s['now']-s.get('quote_ts',0)>3 or s['now']-s.get('book_ts',0)>3:return
        for r in engines:
            if r.get('quality')!='LIVE' or not r.get('direction'):continue
            if r['engine']=='breakout' and r['signal']!='LONG BREAKOUT — CONFIRMED':continue
            if r['engine']=='reversal' and s['now']-r.get('observed_at',0)>3:continue
            age=s['now']-s['quote_ts'];m=s['market']
            text=(f"{r['engine'].upper()}: {r['signal']} / {r['direction']}\n{m['ticker']}\nBTC ${s['price']:,.2f}; strike {m.get('strike')}\nRemaining {m['closed']-s['now']:.0f}s; data age {age:.1f}s\n{r['reason']}\nRisk: unvalidated strategy; spread/fees/slippage apply. Manual trading only.")
            bar=int(s['now']//900)
            self.enqueue(r['engine'],m['ticker'],f"{r['engine']}:{m['ticker']}:{bar}:{r['signal']}",text,s['now'],min(m['closed']-90,s['now']+30))
        for category,radar in [('flip',flips),('scalp',scalps)]:
            for r in radar['rows']:
                if r['status'] not in ('POTENTIAL OPPORTUNITY','OPPORTUNITY'):continue
                m=s['market'];text=f"{category.upper()} {r['side']} {m['ticker']}\nEntry+slip ${r['entry']:.3f}; exit−slip ${r['executable_exit']:.3f}; conditional raw-bid target ${r['possible_exit_target']:.3f}\nTime {m['closed']-s['now']:.0f}s; data age {s['now']-s['book_ts']:.1f}s\n{r['reason']}\nRisk: target not guaranteed, two fees and slippage. Manual only."
                self.enqueue(category,m['ticker'],f"{category}:{m['ticker']}:{r['side']}:{int(s['now']//300)}",text,s['now'],s['now']+10)
    def flush(self,now):
        if not self.telegram or not self.telegram.enabled:return
        with self.db:self.db.execute("UPDATE intel_alerts SET state='expired' WHERE state='pending' AND expires<=?",(now,))
        recent=self.db.execute("SELECT count(*) FROM intel_alerts WHERE sent>?",(now-3600,)).fetchone()[0]
        if recent>=6:return
        for r in self.db.execute("SELECT * FROM intel_alerts WHERE state='pending' AND expires>? AND next_try<=? ORDER BY id LIMIT ?",(now,now,min(2,6-recent))).fetchall():
            try:self.telegram.send(r['message'])
            except Exception:
                with self.db:self.db.execute('UPDATE intel_alerts SET attempts=attempts+1,next_try=? WHERE id=?',(now+min(300,15*2**min(r['attempts'],4)),r['id']))
            else:
                with self.db:self.db.execute("UPDATE intel_alerts SET state='sent',sent=?,attempts=attempts+1 WHERE id=?",(now,r['id']))
    def status(self):
        return {'enabled_categories':sorted(self.enabled),'new_categories_default':'OFF until explicitly enabled in INTELLIGENCE_ALERT_CATEGORIES','limit':'6 additional alerts/hour; 5-minute category/market cooldown; expiration enforced','pending':self.db.execute("SELECT count(*) FROM intel_alerts WHERE state='pending'").fetchone()[0],'legacy_alerts':'Existing directional and settlement alerts preserved separately'}
