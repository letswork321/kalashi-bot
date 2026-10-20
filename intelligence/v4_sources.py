"""Optional public data adapters. Macro context is background-only; partial liquidations labeled."""
from collections import deque
from datetime import datetime,timezone
from urllib.parse import urlparse
from zoneinfo import ZoneInfo
import json,math,os,threading,time
import requests
from .storage import dumps
from .live_feed import proxy_options

BLS='https://www.bls.gov/schedule/news_release/bls.ics'


def calendar_events(text,now,source=BLS):
    if urlparse(source).scheme!='https' or urlparse(source).hostname not in ('www.bls.gov','www.federalreserve.gov'):raise ValueError('Official calendar source required')
    # RFC5545 line unfolding; local TZID dates converted to UTC storage.
    lines=text.replace('\r\n','\n').replace('\n ','').splitlines();events=[];item=None
    for line in lines:
        if line=='BEGIN:VEVENT':item={}
        elif line=='END:VEVENT' and item is not None:
            if 'scheduled' in item and item.get('title'):events.append({**item,'source':source,'received':now,'published':None,'actual':None,'consensus':None,'surprise':None})
            item=None
        elif item is not None and ':' in line:
            key,value=line.split(':',1)
            if key.startswith('DTSTART'):
                try:
                    tz=timezone.utc if value.endswith('Z') else ZoneInfo(key.split('TZID=')[1]) if 'TZID=' in key else ZoneInfo('America/New_York')
                    item['scheduled']=datetime.strptime(value.rstrip('Z'),'%Y%m%dT%H%M%S').replace(tzinfo=tz).timestamp()
                except (ValueError,KeyError):continue
            elif key=='SUMMARY':item['title']=value.replace('\\,',',')[:160]
            elif key=='UID':item['id']=value[:200]
    for e in events:e.setdefault('id',source+':'+str(e['scheduled'])+':'+e['title'])
    return events


def save_calendar(db,text,now):
    events=calendar_events(text,now)
    with db:
        for e in events:db.execute('INSERT OR REPLACE INTO v4_macro VALUES(?,?,NULL,NULL,NULL,NULL,?,?,?)',(e['id'],e['scheduled'],e['source'],now,e['title']))
    return len(events)


def macro_context(db,now):
    rows=[dict(r) for r in db.execute('SELECT * FROM v4_macro WHERE scheduled BETWEEN ? AND ? ORDER BY scheduled',(now-900,now+1800))]
    return {'state':'SCHEDULED RELEASE WINDOW' if any(abs(r['scheduled']-now)<=900 and now-r['received']<=86400 for r in rows) else 'NO VERIFIED NEARBY EVENT' if rows else 'CALENDAR UNAVAILABLE / NO NEARBY EVENTS','events':rows,'consensus_status':'UNAVAILABLE — no licensed consensus feed configured','forex_factory':'NOT CONNECTED — licensed structured access required','news':'UNAVAILABLE — no verified timestamped news feed configured','influence':'No unvalidated macro surprise used in production forecasts'}

class Liquidations:
    def __init__(self):self.rows=deque(maxlen=500);self.lock=threading.Lock();self.stop=threading.Event();self.ws=None;self.state='UNAVAILABLE — optional partial Binance USD-M feed disabled';self.thread=None
    def apply(self,msg,received):
        if msg.get('e')!='forceOrder':return
        r=msg.get('o',{})
        if r.get('s')!='BTCUSDT':return
        event=float(r['T'])/1000;quantity=float(r['z']);price=float(r['ap'])
        if not math.isfinite(event+quantity+price) or not 0<=received-event<=5 or quantity<=0 or price<=0 or r.get('S') not in ('BUY','SELL'):return
        row={'event':event,'side':r['S'],'filled_btc':quantity,'average_price':price,'notional_usdt':price*quantity,'meaning':'Observed partial Binance USD-M liquidation snapshot; not market-wide totals'}
        with self.lock:
            if not any(x['event']==event and x['side']==row['side'] for x in self.rows):self.rows.append(row)
    def start(self):
        if os.environ.get('V4_LIQUIDATION_WS','').lower()=='true':self.thread=threading.Thread(target=self.run,daemon=True,name='v4-optional-liquidations');self.thread.start()
    def run(self):
        while not self.stop.is_set():
            try:
                import websocket
                self.ws=websocket.create_connection('wss://fstream.binance.com/ws/!forceOrder@arr',timeout=5,**proxy_options());self.state='CONNECTED — PARTIAL USD-M snapshots'
                while not self.stop.is_set():
                    msg=json.loads(self.ws.recv())
                    for event in msg if isinstance(msg,list) else [msg]:self.apply(event,time.time())
            except Exception as exc:self.state='UNAVAILABLE — '+type(exc).__name__
            finally:
                if self.ws:self.ws.close();self.ws=None
            self.stop.wait(5)
    def snapshot(self,now):
        with self.lock:rows=[r for r in self.rows if now-r['event']<=60]
        return {'status':self.state,'observed':rows,'coverage':'At most latest liquidation order per symbol per 1000ms on Binance USD-M; excludes other venues and unreported events','interpretation':'No events received is not proof that no liquidations occurred','open_interest':None,'funding':None}
    def close(self):
        self.stop.set()
        if self.ws:self.ws.close()
        if self.thread:self.thread.join(timeout=1)


def save_release(db,event,now):
    """Structured official release adapter. Consensus is optional, never invented."""
    host=urlparse(event['source']).hostname
    if urlparse(event['source']).scheme!='https' or host not in ('www.bls.gov','www.federalreserve.gov','www.bea.gov'):raise ValueError('Verified official release source required')
    scheduled=float(event['scheduled']);published=float(event['published']);actual=event.get('actual');consensus=event.get('consensus')
    if not math.isfinite(scheduled+published) or published>now or any(type(x) not in (int,float) or not math.isfinite(x) for x in (actual,consensus) if x is not None):raise ValueError('Invalid publication time or value')
    surprise=actual-consensus if actual is not None and consensus is not None else None
    with db:db.execute('INSERT OR REPLACE INTO v4_macro VALUES(?,?,?,?,?,?,?,?,?)',(str(event['id'])[:200],scheduled,published,consensus,actual,surprise,event['source'],now,str(event['title'])[:160]))
