"""Independent V4 research thread plus bounded fast observations; no trading code."""
import threading,time
import requests
from .recovery import resilient
from sqlite_runtime import health_write,rollback
from .storage import migrate,dumps,loads
from .v4_analysis import analyze
from .early_exit import settings
from .v4_positions import quote
from .v4_paths import observe,quotes,summary,verified,path_forecast
from .v4_research import investigate,diagnostics
from .v4_models import comparison,retrain
from .v4_sources import Liquidations,BLS,save_calendar,macro_context

class Runtime:
    def __init__(self,owner):self.owner=owner;self.last=0;self.last_event={};self.previous=None;self.stop=threading.Event();self.thread=None;self.liquidations=Liquidations();self.started=time.time();self.forecasts={};self.forecast_at=0
    def start(self):
        self.liquidations.start();self.thread=threading.Thread(target=self.research,daemon=True,name='v4-background-research');self.thread.start()
    @resilient
    def research(self):
        db=migrate(self.owner.path);trained=calendar=0
        try:
            while not self.stop.is_set() and not self.owner.stop.is_set():
                now=time.time()
                try:
                    investigate(db,now,3)
                    if now-trained>=1800:retrain(db,now);trained=now
                    if now-calendar>=3600:
                        calendar=now
                        try:
                            r=requests.get(BLS,timeout=(2,3));r.raise_for_status();save_calendar(db,r.text,now)
                        except (requests.RequestException,ValueError):
                            with health_write(db) as health:health.execute('INSERT INTO v4_health(observed,source,state,payload) VALUES(?,?,?,?)',(now,'BLS calendar','UNAVAILABLE',dumps({'reason':'Official calendar access failed; no event influence fabricated'})))
                except Exception as exc:
                    with health_write(db) as health:health.execute('INSERT INTO v4_health(observed,source,state,payload) VALUES(?,?,?,?)',(now,'research','ERROR',dumps({'type':type(exc).__name__})))
                self.stop.wait(15)
        finally:db.close()
    def step(self,db,s,ticks,spot,notify):
        now=s['now']
        if now-self.last<1:return
        self.last=now
        lock=db.execute('SELECT direction FROM intel_locks WHERE ticker=?',(s['market']['ticker'],)).fetchone();s['locked_direction']=lock['direction'] if lock else None
        a=analyze(s,ticks,self.previous);self.previous=a
        a['book_event_ts']=s.get('book_event_ts');a['spot_event_ts']=s.get('quote_ts')
        observe(db,s);positions=quote(db,s)
        if now-self.forecast_at>=30:
            self.forecast_at=now;self.forecasts={side:path_forecast(db,s,side,settings(db)['target_roi']) for side in ('UP','DOWN')}
        a['cashout']={'first_passage_shadow':self.forecasts,'guidance':'WAIT','reason':'Observed quotes and conditional goals are not validated target forecasts','sides':quotes(s,goal=settings(db)['target_roi'])}
        for position in positions:
            if position['status']!='LIVE':continue
            if a['outlook']['side'] and a['outlook']['side']!=position['side'] and 'REVERSAL' in a['outlook']['state']:
                notify.enqueue('exit',position['ticker'],f"v4-watch-reversal:{position['id']}:{int(now//300)}",f"""POSITION RISK · {position['side']}
{a['outlook']['state']}; supplied-basis net {position['roi']:.0%}.
Sellable bid ${position['bid']:.3f}; costs estimated. {a['outlook']['remaining']:.0f}s left; book age {now-s['book_event_ts']:.1f}s.
Recheck your exit plan. Manual only.""",now,now+5,scope=f"v4-watch:{position['id']}:reversal")
            if position['roi']>=position['target_roi']*.9:
                notify.enqueue('cashout',position['ticker'],f"v4-cashout:{position['id']}:{int(now//300)}",f"""CASH-OUT WATCH · {position['side']}
Supplied entry ${position['entry']:.3f}; sellable bid ${position['bid']:.3f}; estimated net {position['roi']:.0%}.
Goal {position['target_roi']:.0%}; not a sale. {position.get('fee_basis') or 'Supplied fee basis'}.
{position['ticker']} · {a['outlook']['remaining']:.0f}s left; age {now-s['book_event_ts']:.1f}s. Manual only.""",now,now+5,scope=f"v4-watch:{position['id']}:cashout")
        a['positions']=positions;a['whale']['liquidations']=self.liquidations.snapshot(now);a['macro']=macro_context(db,now)
        a['models']=comparison(db)
        a['active_tickers']=[r[0] for r in db.execute('SELECT ticker FROM intel_markets WHERE opened<=? AND closed>? ORDER BY closed LIMIT 10',(now,now))]
        for kind,state,side in [('outlook',a['outlook']['state'],a['outlook']['side']),('flip',a['flip']['state'],a['flip']['side']),('extreme',a['extreme']['state'],a['extreme']['side'])]:
            sig=(s['market']['ticker'],kind,state,side,int(now//15))
            if self.last_event.get(kind)!=sig:
                self.last_event[kind]=sig
                event_side=side if state not in ('QUIET','WAIT') else None
                with db:db.execute('INSERT INTO v4_events(ticker,observed,kind,side,state,payload,result) VALUES(?,?,?,?,?,?,?)',(s['market']['ticker'],now,kind,event_side,state,dumps({**a[kind],'pressure':a['pressure'],'pressure_long':a['pressure_long'],'microprice':a['whale']['microprice_yes'],'regime':a['regime'],'spot_at_issue':s['price'],'due':now+60,'metric':'60s endpoint ≥0.05% in issued direction; gaps at endpoint unverified','version':'warning-endpoint-v4'}),'NO CALL' if event_side is None else None))
            if kind=='outlook' and 'REVERSAL' in state and verified(s):
                notify.enqueue('live_change',s['market']['ticker'],f"v4-change:{s['market']['ticker']}:{side}:{int(now//300)}",f"{state} — WATCH\n{a['outlook']['reason']}\nEntry: WAIT; exit target unvalidated. {a['outlook']['remaining']:.0f}s left; data age {now-s['quote_ts']:.1f}s. Manual only.",now,now+5)
            if kind=='flip' and state=='ALERT' and verified(s):
                f=a['flip'];notify.enqueue('flip',s['market']['ticker'],f"v4-flip:{s['market']['ticker']}:{side}:{int(now//300)}",f"FLIP WATCH · {side}\n{'; '.join(f['evidence'])}\nAsk ${f['ask']:.3f}; gross SETTLEMENT payout {f['gross_settlement_multiplier']:.2f}x, not cash-out ROI.\nTarget unvalidated; spread ${f['spread']:.3f}; {f['remaining']:.0f}s left; book age {now-s['book_event_ts']:.1f}s. Manual only.""",now,now+5)
            # Extreme Move Radar deliberately has NO notification branch/category.
        if int(now)%5==0:
            with health_write(db) as health:health.execute('INSERT INTO v4_health(observed,source,state,payload) VALUES(?,?,?,?)',(now,'Coinbase',spot['status'],dumps({k:spot.get(k) for k in ('age','last_id','gaps','rejected','error','reconnects','heartbeat')})))
        self.endpoints(db,ticks,now)
        for warning in db.execute("SELECT id,observed,side,payload FROM v4_events WHERE result IS NULL AND observed+60<=? AND side IS NOT NULL ORDER BY id LIMIT 100",(now,)).fetchall():
            due=warning['observed']+60
            tick=next((t for t in ticks if due<=t['ts']<=due+2 and t['received']<=now and 0<=t['received']-t['ts']<=2),None)
            basis=loads(warning['payload']).get('spot_at_issue')
            result=None
            if tick and basis:
                move=(tick['price']/basis-1)*(1 if warning['side']=='UP' else -1)
                result='DIRECTION HIT' if move>=.0005 else 'OPPOSITE MOVE' if move<=-.0005 else 'FLAT'
            elif now>due+2:result='UNVERIFIED'
            if result:
                with db:db.execute('UPDATE v4_events SET result=? WHERE id=?',(result,warning['id']))
        with db:db.execute("INSERT OR REPLACE INTO v3_state VALUES('v4',?,?)",(now,dumps(a)))
        if int(now)%3600<2:
            with db:
                db.execute('DELETE FROM v4_health WHERE observed<?',(now-14*86400,));db.execute('DELETE FROM v4_events WHERE observed<?',(now-30*86400,))
    def endpoints(self,db,ticks,now):
        for r in db.execute('SELECT key,observed,sent,direction,target_price FROM intel_callouts WHERE observed>=? AND sent IS NOT NULL AND sent<=observed+3 AND target_price IS NOT NULL',(self.started,)).fetchall():
            with db:db.execute('INSERT OR IGNORE INTO v4_call_endpoints(key,issued,ack,due,side,target) VALUES(?,?,?,?,?,?)',(r['key'],r['observed'],r['sent'],r['sent']+180,r['direction'],r['target_price']))
        for r in db.execute("SELECT * FROM v4_call_endpoints WHERE state='PENDING'").fetchall():
            found=next((t for t in sorted(ticks,key=lambda t:t['ts']) if r['due']<=t['ts']<=r['due']+2 and r['ack']<=t['received']<=now and 0<=t['received']-t['ts']<=2),None)
            if found:
                hit=found['price']>=r['target'] if r['side']=='UP' else found['price']<=r['target']
                with db:db.execute('UPDATE v4_call_endpoints SET state=?,observed=?,price=? WHERE key=?',('HIT' if hit else 'NOT_HIT',found['ts'],found['price'],r['key']))
            elif now>r['due']+2:
                with db:db.execute("UPDATE v4_call_endpoints SET state='UNVERIFIED' WHERE key=?",(r['key'],))
    def close(self):
        self.stop.set();self.liquidations.close()
        if self.thread:self.thread.join(timeout=1)


def snapshot(db,now):
    r=db.execute("SELECT * FROM v3_state WHERE name='v4'").fetchone();v=loads(r['payload']) if r else {'status':'WARMING UP','cashout':{'guidance':'WAIT'},'positions':[]}
    if not r or not 0<=now-r['ts']<=2:
        v['status']='STALE';v['cashout']={'guidance':'WAIT','reason':'V4 observer stale','sides':[]};v['pressure']={'status':'STALE','buy_share':None,'sell_share':None}
        for k in ('flip','extreme'):v[k]={'state':'UNAVAILABLE','side':None,'score':None}
        v['outlook']={'state':'WAIT','reason':'Observer stale'}
        for p in v.get('positions',[]):p.update(status='STALE',goal_hit=False,bid=None,net=None,roi=None)
    if v.get('book_event_ts') is None or not 0<=now-v['book_event_ts']<=1:
        v['cashout']={'guidance':'WAIT','reason':'Executable book event stale or unverified','sides':[]}
        if 'flip' in v:v['flip'].update(gross_settlement_multiplier=None,ask=None,book_verified=False)
        for p in v.get('positions',[]):p.update(status='STALE BOOK',goal_hit=False,bid=None,net=None,roi=None)
    v['cashout_performance']=summary(db);v['manual_results']=[dict(r) for r in db.execute('SELECT * FROM v4_position_details WHERE realized_ts IS NOT NULL ORDER BY realized_ts DESC LIMIT 50')]
    v['mistakes']=[{'ticker':r['ticker'],'created':r['created'],**loads(r['payload'])} for r in db.execute('SELECT * FROM v4_mistakes ORDER BY created DESC LIMIT 30')]
    v['diagnostics']=diagnostics(db);v['endpoint_score']=[dict(r) for r in db.execute('SELECT state,count(*) n FROM v4_call_endpoints GROUP BY state')];v['warning_performance']=[dict(r) for r in db.execute("SELECT kind,state,result,count(*) n FROM v4_events GROUP BY kind,state,result")];v['now']=now
    return v
