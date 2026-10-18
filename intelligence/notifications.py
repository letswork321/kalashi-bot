"""Persisted, expiring Telegram delivery plus strictly post-delivery paper evaluation."""
import time
from datetime import datetime
from .storage import dumps,loads,ET
from .alert_settings import CATEGORIES,settings
from .economics import fast_scalp_data,Simulator
from scanner import timestamp


def record_legacy_delivery(db, key, category, ticker, now, observation, side=None, created=None):
    """Preserve original outboxes; older DBs work before the additive migration."""
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='intel_alert_evidence'").fetchone():return
    with db:
        db.execute("INSERT OR IGNORE INTO intel_alert_evidence(key,category,ticker,created,side,snapshot,sent,evaluation) VALUES(?,?,?,?,?,?,?,?)",
                   (key,category,ticker,created if created is not None else now,side,dumps(observation),now,'AWAITING_LIVE_OBSERVATION' if side else 'OUTCOME_NOTIFICATION'))


def settlement_sent(db,ticker):
    for table,column in (('intel_alerts','state'),('outcome_alerts','status')):
        if db.execute("SELECT 1 FROM sqlite_master WHERE name=?",(table,)).fetchone():
            sql=f"SELECT 1 FROM {table} WHERE ticker=? AND {column}='sent'"
            if table=='intel_alerts':sql+=" AND category='settlement'"
            if db.execute(sql,(ticker,)).fetchone():return True
    return False


class Notifications:
    def __init__(self,db,telegram):self.db,self.telegram=db,telegram;self.defaults=settings(db)
    @property
    def enabled(self):return {c for c,v in settings(self.db,self.defaults).items() if v}
    def enqueue(self,category,ticker,key,message,now,expires,evidence=None,scope=None):
        if category not in self.enabled or not self.telegram or not self.telegram.enabled or expires<=now:return False
        scope=scope or category
        previous=self.db.execute('SELECT created FROM intel_alerts WHERE category=? AND ticker=? AND COALESCE(scope,category)=? ORDER BY created DESC LIMIT 1',(category,ticker,scope)).fetchone()
        cooldown=60 if category=='scalp' else 300
        if previous and now-previous['created']<cooldown:return False
        with self.db:
            cur=self.db.execute('INSERT OR IGNORE INTO intel_alerts(key,category,ticker,created,expires,message,scope) VALUES(?,?,?,?,?,?,?)',(key,category,ticker,now,expires,message,scope))
            if not cur.rowcount:return False
            if evidence is not None:
                self.db.execute('INSERT INTO intel_alert_evidence(key,alert_id,category,ticker,created,side,hold,snapshot) VALUES(?,?,?,?,?,?,?,?)',
                                (key,cur.lastrowid,category,ticker,now,evidence.get('side'),evidence.get('window',60 if category=='flip' else None),dumps(evidence)))
        return True
    def callout(self,s,call):
        """Queue an auditable, plainly worded BTC WATCH with no trade claims."""
        if not call or 'callout' not in self.enabled:return False
        from .callouts import message,record
        key=f"callout:{call['ticker']}:{int(call['candle_time'])}:{call['direction']}"
        ok=self.enqueue('callout',call['ticker'],key,message(call),s['now'],
                        min(s['now']+15,s['market']['closed']-15),scope='callout')
        if ok:record(self.db,call,key)
        return ok
    def locked(self,s,record):
        m=s['market'];p=record['p_up'] if record['direction']=='UP' else 1-record['p_up'];late=record['state']=='LATE'
        title='LATE FORECAST — SEPARATE ACCURACY COHORT' if late else 'LOCKED 15-MINUTE FORECAST'
        text=(f"{title} · {record['direction']}\n{m['ticker']}\nEstimated side probability {p:.1%} — UNCALIBRATED baseline\n"
              f"Official price to beat ${m['strike']:,.2f}; BTC Coinbase ${s['price']:,.2f} (proxy)\n"
              f"Recorded {datetime.fromtimestamp(record['observed'],ET).strftime('%Y-%m-%d %H:%M:%S %Z')}; {m['closed']-s['now']:.0f}s remaining\n"
              f"Model {record['model']}; distance/volatility, EMA, RSI, momentum and book consensus.\n"
              f"{record['reason']}\nAccuracy forecast only: not an entry recommendation. Manual trading only.")
        e={'side':record['direction'],'p_up':record['p_up'],'strike':m['strike'],'btc_price':s['price'],'model':record['model'],'calibrated':False,'recorded_at':record['observed'],'state':record['state'],'alert_type':title}
        self.enqueue('locked',m['ticker'],'locked:'+m['ticker'],text,s['now'],min(s['now']+30,m['closed']),e)
    def preliminary(self,cache,now):
        if 'preliminary' not in self.enabled:return
        meta=cache.get('metadata') or {};quote=cache.get('quote') or {}
        if now-meta.get('received',0)>30 or not 0<=now-quote.get('timestamp',0)<=2:return
        future=sorted([m for m in meta.get('markets',[]) if 30<=timestamp(m['open_time'])-now<=60],key=lambda m:timestamp(m['open_time']))
        if not future or not cache.get('candles'):return
        try:
            from scanner import indicators,Feed
            f=indicators(Feed(quote['price'],quote['timestamp'],cache['candles']),now)
            direction='UP' if f['ema9']>f['ema21'] else 'DOWN'
            if f['momentum_3m']*(1 if direction=='UP' else -1)<.0001:return
        except Exception:return
        m=future[0];strike=m.get('floor_strike');strike_text=f"${strike:,.2f}" if strike else 'UNKNOWN — direction may change when official strike is established'
        text=(f"PRELIMINARY OUTLOOK — NOT LOCKED · {direction}\n{m['ticker']} opens in {timestamp(m['open_time'])-now:.0f}s\n"
              f"Official strike: {strike_text}\nBTC ${quote['price']:,.2f}; 3m momentum {f['momentum_3m']:.3%}; RSI {f['rsi14']:.1f}; 1m volatility {f['volatility_1m']:.3%}\n"
              'EMA/momentum agreement only; no validated probability or trade recommendation. Manual only.')
        self.enqueue('preliminary',m['ticker'],'preliminary:'+m['ticker'],text,now,min(now+20,timestamp(m['open_time'])),{'side':direction,'alert_type':'PRELIMINARY','strike':strike,'btc_price':quote['price'],'momentum':f['momentum_3m']})
    def directional(self,s,fair,candidate):
        if s.get('mode')!='live' or not candidate.get('validated') or not (0<=s['now']-s.get('quote_ts',0)<=2 and 0<=s['now']-s.get('book_ts',0)<=2):
            self.withdraw(s,[]);return
        qualifying=[]
        for r in fair.get('rows',[]):
            side=r['side'];book=s.get('book');levels=book.no if side=='UP' else book.yes
            depth=sum(q for _,q in levels[:5]);remaining=s['market']['closed']-s['now']
            if r.get('estimated_edge',-1)<.05 or book.spread>.04 or depth<5 or remaining<120 or s.get('book_latency',99)>1:continue
            qualifying.append(side)
            m=s['market'];f=(s.get('baseline') or {}).get('features',{});now=s['now']
            message=(f"POTENTIAL {side} ENTRY\n{m['ticker']}\nExecutable ask ${r['observed_entry_ask']:.3f}; slippage +$0.002; taker fee ${r['taker_fee']:.4f}; estimated total ${r['executable_entry']+r['taker_fee']:.4f} / contract\n"
                     f"Estimated side probability {r['estimated_probability']:.1%}; after-cost edge {r['estimated_edge']:.1%}\n"
                     f"Out-of-sample calibrated SHADOW model {candidate.get('version')} n={candidate.get('sample_size')}; not promoted, live reliability unproven\n"
                     f"Momentum {f.get('momentum_3m',0):.3%}; regime {(s.get('regime') or {}).get('regime','UNKNOWN')}\n"
                     f"Top-5 entry depth {depth:.1f}; spread ${book.spread:.3f}; {remaining:.0f}s remaining\n"
                     f"{datetime.fromtimestamp(now,ET).strftime('%Y-%m-%d %H:%M:%S %Z')}; BTC/book age {now-s['quote_ts']:.2f}/{now-s['book_ts']:.2f}s\n"
                     'Qualifies: validated shadow input support, >=5% after-cost edge, <=4c spread, observed depth. Expires in 10s. Recheck quotes; model risk and fees apply. Manual only.')
            e={**r,'side':side,'p_up':candidate.get('probability'),'model':candidate.get('version'),'sample_size':candidate.get('sample_size'),'calibrated':True,'window':None,'book_id':s.get('book_id'),'expires_at':now+10,'status':'OPPORTUNITY','alert_type':f'POTENTIAL {side} ENTRY'}
            key=f"entry:{m['ticker']}:{side}:{int(now//300)}"
            if self.enqueue('directional',m['ticker'],key,message,now,now+10,e,'entry:'+side):
                with self.db:self.db.execute('INSERT OR REPLACE INTO intel_entry_state(ticker,side,key,issued,expires,active) VALUES(?,?,?,?,?,1)',(m['ticker'],side,key,now,now+10))
        self.withdraw(s,qualifying)
    def withdraw(self,s,qualifying,expired_only=False):
        for r in self.db.execute('SELECT * FROM intel_entry_state WHERE active=1').fetchall():
            if expired_only and s['now']<r['expires']:continue
            if r['ticker']==s['market']['ticker'] and r['side'] in qualifying and s['now']<r['expires']:continue
            # Cancel unsent entries; send at most one withdrawal for a delivered entry.
            sent=self.db.execute('SELECT sent FROM intel_alerts WHERE key=?',(r['key'],)).fetchone()
            with self.db:
                self.db.execute("UPDATE intel_alerts SET state='superseded' WHERE key=? AND state='pending'",(r['key'],))
                self.db.execute('UPDATE intel_entry_state SET active=0,withdrawn=? WHERE ticker=?',(s['now'],r['ticker']))
            if sent and sent['sent'] is not None and 'directional' in self.enabled:
                self.enqueue('withdrawal',r['ticker'],'withdraw:'+r['key'],f"ENTRY WITHDRAWN / EXPIRED · {r['side']}\n{r['ticker']}\nEarlier opportunity no longer verified or its 10s window expired. Do not act on the old quote. This is not an instruction to sell a position. Manual only.",s['now'],s['now']+30)
    def signals(self,s,engines,flips,scalps):
        if s.get('fee_valid') is False or s.get('mode')!='live' or not 0<=s['now']-s.get('quote_ts',0)<=3 or not 0<=s['now']-s.get('book_ts',0)<=3:return
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
                if r['status'] not in (('OPPORTUNITY','WATCH') if category=='scalp' else ('POTENTIAL OPPORTUNITY',)):continue
                if category=='scalp' and not fast_scalp_data(s):continue
                m=s['market'];hold=r.get('window',r.get('holding_seconds',60));ttl=3 if category=='scalp' else 10
                # Watch alerts require aligned real momentum too. WATCH never means enter.
                if category=='scalp' and (not r.get('btc_direction_aligned') or r.get('reversal_risk')):continue
                title=('POTENTIAL SCALP ENTRY' if r['status']=='OPPORTUNITY' else 'SCALP WATCH — NOT AN ENTRY') if category=='scalp' else 'POTENTIAL FLIP OPPORTUNITY'
                text=(f"{title} · {r['side']} · {hold}s\n{m['ticker']}\nObserved executable ask ${r['observed_entry_ask']:.3f}; current bid ${r['observed_exit_bid']:.3f} (1 contract)\n"
                      f"Conditional exit BID target ${r['possible_exit_target']:.3f}; requires +${r['required_bid_movement']:.3f}\n"
                      f"Scenario net ${r['conditional_net']:.4f}/contract after both fees + $0.002 slippage/leg; NOT expected/guaranteed profit\n"
                      f"{r.get('liquidity','Verified one-contract depth')}; spread ${r['spread']:.3f}; risk {r.get('risk','HIGH')}\n"
                      f"Holding window {hold}s; expires {datetime.fromtimestamp(s['now']+ttl,ET).strftime('%H:%M:%S %Z')} ({ttl}s); settlement in {m['closed']-s['now']:.0f}s\n"
                      f"Book age {s['now']-s['book_ts']:.2f}s; exchange latency {s.get('book_latency',99):.2f}s; BTC 60s volume {r.get('btc_volume_60s')} BTC\n"
                      f"Signal {datetime.fromtimestamp(s['now'],ET).strftime('%Y-%m-%d %H:%M:%S %Z')}; confidence: {r.get('entry_validation','scenario only, not calibrated')}\n"
                      f"{r['reason']}\nDelivery can arrive late: recheck live ask/bid and expiry. Manual trades only.")
                scope=f"{category}:{r['side']}:{hold}"
                key=f"{scope}:{m['ticker']}:{int(s['now']//60)}"
                evidence={**r,'category':category,'window':hold,'quote_ts':s['quote_ts'],'book_ts':s['book_ts'],'btc_price':s['price'],'book_source':s.get('book_source'),'book_latency':s.get('book_latency'),'fee_multiplier':s.get('fee_multiplier'),'expires_at':s['now']+ttl,'alert_type':title,'book_id':s.get('book_id')}
                self.enqueue(category,m['ticker'],key,text,s['now'],min(s['now']+ttl,m['closed']-hold-10),evidence,scope)
    def flush(self,now,s=None):
        if not self.telegram or not self.telegram.enabled:return
        enabled=self.enabled
        with self.db:
            self.db.execute("UPDATE intel_alerts SET state='expired' WHERE state='pending' AND expires<=?",(now,))
            for r in self.db.execute("SELECT id,category FROM intel_alerts WHERE state='pending'").fetchall():
                if r['category'] not in enabled:self.db.execute("UPDATE intel_alerts SET state='disabled' WHERE id=?",(r['id'],))
        recent=self.db.execute("SELECT count(*) FROM intel_alerts WHERE sent>? AND category NOT IN ('locked','preliminary','settlement','daily','withdrawal')",(now-3600,)).fetchone()[0]
        rows=self.db.execute("SELECT * FROM intel_alerts WHERE state='pending' AND expires>? AND next_try<=? ORDER BY CASE WHEN category='scalp' THEN 0 ELSE 1 END,id LIMIT ?",(now,now,8)).fetchall()
        for r in rows:
            if r['category'] not in ('locked','preliminary','settlement','daily','withdrawal') and recent>=6:continue
            check=time.time() if s is not None else now
            invalid=check>=r['expires']
            if r['category'] in ('scalp','flip','directional'):
                invalid=invalid or not s or s['market']['ticker']!=r['ticker'] or s.get('mode')!='live'
                if s:
                    check_s={**s,'now':check}
                    invalid=invalid or (not fast_scalp_data(check_s) if r['category']=='scalp' else not (0<=check-s.get('quote_ts',0)<=3 and 0<=check-s.get('book_ts',0)<=3))
                    # Do not send a queued direction after its evidence reverses or quote moves.
                    e=self.db.execute('SELECT snapshot FROM intel_alert_evidence WHERE alert_id=?',(r['id'],)).fetchone()
                    if e:
                        e=loads(e['snapshot']);from .economics import executable,scalp_radar
                        try:
                            ask=executable(s.get('book'),e['side'],'buy',slippage=0)
                            invalid=invalid or abs(ask-e['observed_entry_ask'])>.005
                            if r['category']=='directional':
                                from .models import shadow
                                from .economics import fair_value
                                fv=fair_value(check_s,shadow(self.db,check_s))
                                levels=s['book'].no if e['side']=='UP' else s['book'].yes
                                invalid=invalid or s['book'].spread>.04 or sum(q for _,q in levels[:5])<5 or check_s['market']['closed']-check<120 or check-s.get('quote_ts',0)>2 or check-s.get('book_ts',0)>2 or s.get('book_latency',99)>1
                                invalid=invalid or not any(v.get('side')==e['side'] and v.get('estimated_edge',-1)>=.05 for v in fv.get('rows',[]))
                            if r['category']=='scalp':
                                current=next((v for v in scalp_radar(check_s)['rows'] if v.get('side')==e['side'] and v.get('window')==e['window']),{})
                                invalid=invalid or current.get('status') not in ('WATCH','OPPORTUNITY') or (e.get('status')=='OPPORTUNITY' and current.get('status')!='OPPORTUNITY')
                        except (ValueError,KeyError,TypeError):invalid=True
                    else:invalid=True
            if r['category']=='callout':
                invalid=invalid or not s or s.get('mode')!='live' or s.get('market',{}).get('ticker')!=r['ticker']
                if s:
                    invalid=invalid or not (0<=check-s.get('quote_ts',0)<=2 and 0<=check-s.get('book_ts',0)<=2)
            if r['category']=='settlement' and settlement_sent(self.db,r['ticker']):invalid=True
            if invalid:
                with self.db:self.db.execute("UPDATE intel_alerts SET state='expired' WHERE id=?",(r['id'],))
                continue
            try:self.telegram.send(r['message'])
            except Exception:
                retry=check+min(300,15*2**min(r['attempts'],4))
                with self.db:self.db.execute("UPDATE intel_alerts SET attempts=attempts+1,next_try=?,state=? WHERE id=?",(retry,'pending' if retry<r['expires'] else 'failed',r['id']))
            else:
                if r['category'] not in ('locked','preliminary','settlement','daily','withdrawal'):recent+=1
                sent=time.time() if s is not None else now
                with self.db:
                    self.db.execute("UPDATE intel_alerts SET state='sent',sent=?,attempts=attempts+1 WHERE id=?",(sent,r['id']))
                    if r['category']=='callout':
                        from .callouts import acknowledged
                        acknowledged(self.db,r['key'],sent)
                    self.db.execute("UPDATE intel_alert_evidence SET sent=?,evaluation=? WHERE alert_id=?",(sent,'FORECAST_OR_OUTCOME_NOTIFICATION' if r['category'] in ('locked','preliminary','settlement','daily','withdrawal') else 'DELIVERED_LATE_NO_ENTRY' if sent>=r['expires'] else 'AWAITING_LIVE_OBSERVATION',r['id']))
        with self.db:
            self.db.execute("UPDATE intel_alert_evidence SET evaluation='NOT_DELIVERED' WHERE sent IS NULL AND alert_id IN (SELECT id FROM intel_alerts WHERE state NOT IN ('pending','sent'))")
    def evaluate_delivered(self,s):
        """Start only after ACK; signal-time observations are never retroactive fills."""
        for r in self.db.execute("SELECT * FROM intel_alert_evidence WHERE evaluation='AWAITING_LIVE_OBSERVATION' AND sent IS NOT NULL").fetchall():
            reason=None
            if s['now']<r['sent']:continue
            if s['now']-r['sent']>3 or s['market']['ticker']!=r['ticker']:reason='MISSED_POST_DELIVERY_OBSERVATION'
            elif r['category']=='scalp' and not fast_scalp_data(s):continue
            else:
                key='telegram:'+r['key'];kind='directional' if r['category']=='directional' else r['category']
                pid=Simulator(self.db).propose(key,kind,'telegram_'+kind,s,r['side'],r['hold'])
                if pid:
                    with self.db:self.db.execute("UPDATE intel_alert_evidence SET sim_key=?,evaluation='PAPER_TRACKED' WHERE key=?",(key,r['key']))
                    continue
                reason='NO_EXECUTABLE_EVALUATION_OR_CAPACITY'
            with self.db:self.db.execute('UPDATE intel_alert_evidence SET evaluation=? WHERE key=?',(reason,r['key']))
    def status(self):
        return {'enabled_categories':sorted(self.enabled),'settings':settings(self.db),'new_categories_default':'Scalp and flip OFF until enabled in dashboard settings; fast data gates still required','limit':'6 additional alerts/hour; scalp 60s cooldown per side/horizon; 3s expiry. Telegram/phone latency is not guaranteed.','pending':self.db.execute("SELECT count(*) FROM intel_alerts WHERE state='pending'").fetchone()[0],'legacy_alerts':'Regular entry and settlement switches apply to existing alerts too'}


def performance(db,start=0):
    """All selected-range aggregates; only the audit table is paged/bounded."""
    join="""FROM intel_alert_evidence e LEFT JOIN intel_alerts a ON e.alert_id=a.id
        LEFT JOIN intel_sim p ON e.sim_key=p.key LEFT JOIN intel_markets m ON e.ticker=m.ticker WHERE e.created>=?"""
    rows=[dict(r) for r in db.execute("SELECT e.*,a.state delivery_state,a.attempts,a.expires,p.state paper_state,p.entry_ts,p.entry,p.entry_fee,p.exit_ts,p.exit,p.exit_fee,p.pnl,p.quantity,p.reason,m.result official_result "+join+" ORDER BY e.created DESC LIMIT 100",(start,))]
    aggregate={}
    for r in db.execute("""SELECT e.category,CASE WHEN e.category='scalp' THEN e.hold ELSE NULL END horizon,
        count(*) recorded,sum(e.sent IS NOT NULL) delivered,sum(p.state='CLOSED') closed,
        sum(CASE WHEN p.state='CLOSED' THEN p.pnl ELSE 0 END) net_pnl,
        sum(CASE WHEN p.state='CLOSED' THEN p.quantity*p.entry+p.entry_fee ELSE 0 END) cost,
        sum(p.state='CLOSED' AND p.pnl>0) positive,sum(p.state='MISSED_EXIT') unresolved,
        sum(e.sent IS NOT NULL AND e.side IN ('UP','DOWN') AND m.result IN ('yes','no')) directional_settled,
        sum(e.sent IS NOT NULL AND e.side IN ('UP','DOWN') AND m.result IN ('yes','no') AND ((e.side='UP')=(m.result='yes'))) directional_wins,
        sum(json_extract(e.snapshot,'$.status')='WATCH') watch_samples,
        sum(json_extract(e.snapshot,'$.status')='OPPORTUNITY') entry_samples,
        sum(p.state='CLOSED' AND json_extract(e.snapshot,'$.status')='WATCH') watch_closed,
        sum(p.state='CLOSED' AND json_extract(e.snapshot,'$.status')='OPPORTUNITY') entry_closed,
        sum(CASE WHEN p.state='CLOSED' AND json_extract(e.snapshot,'$.status')='WATCH' THEN p.pnl ELSE 0 END) watch_net,
        sum(CASE WHEN p.state='CLOSED' AND json_extract(e.snapshot,'$.status')='OPPORTUNITY' THEN p.pnl ELSE 0 END) entry_net
        """+join+" GROUP BY e.category,horizon",(start,)):
        aggregate[(r['category'],r['horizon'])]=dict(r)
    groups=[]
    for category,hold in [('locked',None),('directional',None),('flip',None),('scalp',20),('scalp',40),('scalp',60)]:
        g=aggregate.get((category,hold),{})
        for key in ('recorded','delivered','closed','net_pnl','cost','positive','unresolved','directional_settled','directional_wins','watch_samples','entry_samples','watch_closed','entry_closed','watch_net','entry_net'):g[key]=g.get(key) or 0
        g.update(category=category,window=hold,roi=g['net_pnl']/g['cost'] if g['cost'] else None,win_rate=g['positive']/g['closed'] if g['closed'] else None)
        groups.append(g)
    for r in rows:
        r['directional_correct']=None if r['sent'] is None or r['side'] not in ('UP','DOWN') or r['official_result'] not in ('yes','no') else (r['side']=='UP')==(r['official_result']=='yes')
        r['observation']=loads(r.pop('snapshot'));r['delivery_state']=r['delivery_state'] or ('sent' if r['sent'] is not None else 'unknown')
    from .storage import window_start
    today=window_start('today',time.time())
    sent_today=db.execute('SELECT count(*) FROM intel_alerts WHERE sent>=?',(today,)).fetchone()[0]+db.execute('SELECT count(*) FROM intel_alert_evidence WHERE alert_id IS NULL AND sent>=?',(today,)).fetchone()[0]
    return {'sent_today':sent_today,'groups':groups,'rows':rows,'display_limit':100,'aggregation':'All recorded alerts in selected range','note':'Metrics use all recorded notifications in selected range; latest100 audit rows shown. Telegram API acknowledgement is not proof the phone displayed/read it. Paper entries require a supported observation after acknowledgement + another2s delay, never earlier prices. Watch observations are separately labeled; no real money.'}
