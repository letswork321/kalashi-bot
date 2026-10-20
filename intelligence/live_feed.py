"""Public Coinbase matched-trade stream. Event time, continuity and partial OHLC are explicit."""
from collections import deque
from datetime import datetime
import json
import math
import os
import threading
import time
from urllib.parse import urlparse

URL='wss://ws-feed.exchange.coinbase.com'

def proxy_options():
    proxy=os.environ.get('HTTPS_PROXY') or os.environ.get('https_proxy')
    if not proxy:return {}
    p=urlparse(proxy);out={'http_proxy_host':p.hostname,'http_proxy_port':p.port or 80}
    if p.username:out['http_proxy_auth']=(p.username,p.password or '')
    return out

class TradeTape:
    REORDER_SECONDS=.25
    MAX_PENDING=256
    def __init__(self):
        self.rows=deque(maxlen=30000);self.last_id=None;self.epoch=0;self.gaps=0;self.last_received=0;self.status='CONNECTING';self.rejected=0;self.heartbeat=None;self.error=None;self.reconnects=0;self.pending={};self.gap_since=None;self.last_gap=None;self.duplicates=0
    def reset(self):
        self.epoch+=1;self.last_id=None;self.last_received=0;self.heartbeat=None;self.pending.clear();self.gap_since=None;self.status='RESYNCING'
    def _append(self,row,continuous):
        row.update(epoch=self.epoch,continuous=continuous)
        self.rows.append(row);self.last_id=row['id'];self.last_received=row['received'];self.status='STREAMING' if continuous else 'RESYNCING'
    def _drain(self,now):
        while self.last_id is not None and self.last_id+1 in self.pending:
            row=self.pending.pop(self.last_id+1)
            continuous=bool(self.rows and self.rows[-1]['epoch']==self.epoch and row['ts']>=self.rows[-1]['ts'])
            if not continuous:
                self.gaps+=1;self.epoch+=1;self.last_gap={'reason':'EVENT_TIME_REGRESSION','id':row['id'],'received':row['received']}
            self._append(row,continuous)
        if self.pending:
            if self.gap_since is None:self.gap_since=now
            self.status='RESYNCING'
            if now-self.gap_since>=self.REORDER_SECONDS or len(self.pending)>=self.MAX_PENDING:
                key=min(self.pending);row=self.pending.pop(key)
                self.last_gap={'reason':'MISSING_TRADE_IDS','expected':self.last_id+1,'received_id':key,'received':row['received']}
                self.gaps+=1;self.epoch+=1;self._append(row,False);self.gap_since=None;self._drain(now)
        else:self.gap_since=None
    def apply(self,msg,received):
        if msg.get('type')=='heartbeat' and msg.get('product_id')=='BTC-USD':
            try:
                stamp=datetime.fromisoformat(msg['time'].replace('Z','+00:00'))
                if stamp.tzinfo is None:raise ValueError('Missing timezone')
                event=stamp.timestamp();identifier=int(msg['last_trade_id'])
                if not math.isfinite(event+received) or event>received+1:raise ValueError('Invalid clock')
                self.heartbeat={'event':event,'received':received,'last_id':identifier}
            except (KeyError,ValueError,TypeError):self.rejected+=1
            return None
        if msg.get('product_id')!='BTC-USD' or msg.get('type') not in ('match','last_match'):return None
        try:
            stamp=datetime.fromisoformat(msg['time'].replace('Z','+00:00'))
            if stamp.tzinfo is None:raise ValueError('Missing timezone')
            event=stamp.timestamp();price,size=float(msg['price']),float(msg['size']);identifier=int(msg['trade_id'])
            if not math.isfinite(price+size+event+received) or price<=0 or size<=0 or identifier<0 or event>received+1:raise ValueError('Clock or value invalid')
        except (KeyError,ValueError,TypeError):self.rejected+=1;return None
        if msg['type']=='last_match' and self.last_id is not None:return None
        if self.last_id is not None and (identifier<=self.last_id or identifier in self.pending):self.duplicates+=1;return None
        row={'id':identifier,'ts':event,'received':received,'price':price,'size':size,'side':msg.get('side'),'source':'Coinbase WebSocket'}
        if self.last_id is None:self._append(row,False);return row
        old=self.last_id;self.pending[identifier]=row;self._drain(received)
        return self.rows[-1] if self.last_id!=old else None
    def snapshot(self,now):
        self._drain(now)
        last=self.rows[-1] if self.rows and self.rows[-1]['epoch']==self.epoch else None
        fresh=bool(last and 0<=now-last['ts']<=3 and 0<=now-self.last_received<=3)
        if self.status in ('UNAVAILABLE','DISABLED','CONNECTING'):status=self.status
        elif last and last['ts']>now:status='CLOCK SKEW'
        elif fresh and self.status=='STREAMING' and not self.pending:status='LIVE'
        elif fresh:status='RESYNCING'
        else:status='STALE' if last else self.status
        reason='Verified consecutive trade IDs and fresh event/receipt times' if status=='LIVE' else 'Trade-ID continuity being verified' if status=='RESYNCING' else 'Source event is ahead of the local clock; verify Windows time synchronization' if status=='CLOCK SKEW' else 'No current verified quote'
        return {'source':'Coinbase BTC-USD WebSocket','status':status,'verification_reason':reason,'event_ts':last['ts'] if last else None,'received_ts':self.last_received or None,'age':now-last['ts'] if last else None,'price':last['price'] if last else None,'gaps':self.gaps,'last_gap':self.last_gap,'pending_ids':len(self.pending),'duplicates':self.duplicates,'epoch':self.epoch,'rejected':self.rejected,'rows':list(self.rows),'last_id':self.last_id,'heartbeat':self.heartbeat,'error':self.error,'reconnects':self.reconnects}

class CoinbaseStream:
    def __init__(self):
        self.enabled=os.environ.get('COINBASE_WS_ENABLED','true').lower()=='true';self.tape=TradeTape();self.lock=threading.Lock();self.stop=threading.Event();self.thread=None;self.ws=None
    def start(self):
        if self.enabled:self.thread=threading.Thread(target=self.run,daemon=True,name='coinbase-public-trades');self.thread.start()
        else:self.tape.status='DISABLED'
    def run(self):
        delay=1
        while not self.stop.is_set():
            try:
                import websocket
                self.ws=websocket.create_connection(URL,timeout=5,**proxy_options())
                self.ws.send(json.dumps({'type':'subscribe','product_ids':['BTC-USD'],'channels':['matches','heartbeat']}))
                with self.lock:self.tape.reset();self.tape.error=None
                connected=time.monotonic()
                while not self.stop.is_set():
                    message=json.loads(self.ws.recv())
                    if message.get('type')=='error':raise ValueError('Subscription rejected')
                    received=time.time()
                    with self.lock:
                        self.tape.apply(message,received)
                        last=self.tape.last_received
                        session_age=time.monotonic()-connected
                        stale=last and received-last>10
                        silent=not last and session_age>10
                        heartbeat=self.tape.heartbeat
                        missing=heartbeat and heartbeat['last_id']>(self.tape.last_id or 0) and session_age>10 and (not last or received-last>3)
                    if stale or silent or missing:raise TimeoutError('Trade stream stalled; resubscribe required')
                    if session_age>=30:delay=1
            except Exception as exc:
                with self.lock:
                    self.tape.reset();self.tape.status='UNAVAILABLE';self.tape.reconnects+=1
                    self.tape.error={'type':type(exc).__name__,'http_status':getattr(exc,'status_code',None),'at':time.time(),'reason':'Connection/Upgrade failed' if self.ws is None else 'Stream disconnected or subscription rejected'}
                self.stop.wait(delay);delay=min(30,delay*2)
            finally:
                if self.ws:
                    try:self.ws.close()
                    except Exception:pass
                self.ws=None
    def snapshot(self,now=None):
        with self.lock:return self.tape.snapshot(time.time() if now is None else now)
    def close(self):
        self.stop.set()
        if self.ws:
            try:self.ws.close()
            except Exception:pass
        if self.thread:self.thread.join(timeout=1)

def candle_rows(ticks,period,now):
    """Only observed prints; partial coverage never impersonates a full period."""
    groups={}
    for t in sorted((x for x in ticks if x['ts']<=now),key=lambda x:(x['ts'],x['id'])):
        start=int(t['ts']//period)*period;r=groups.get(start)
        if not r:
            r={'time':start,'open':t['price'],'high':t['price'],'low':t['price'],'close':t['price'],'volume':0,'event_ts':t['ts'],'first_event':t['ts'],'last_id':t['id']-1,'epoch':t['epoch'],'partial':t['ts']-start>1,'source':'Coinbase WebSocket actual trades'};groups[start]=r
        if t['id']!=r['last_id']+1 or t['epoch']!=r['epoch'] or t['ts']-r['event_ts']>3:r['partial']=True
        r.update(high=max(r['high'],t['price']),low=min(r['low'],t['price']),close=t['price'],event_ts=t['ts'],last_id=t['id']);r['volume']+=t['size']
    return list(groups.values())
