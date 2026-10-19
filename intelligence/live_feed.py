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
    def __init__(self):
        self.rows=deque(maxlen=30000);self.last_id=None;self.epoch=0;self.gaps=0;self.last_received=0;self.status='CONNECTING';self.rejected=0
    def reset(self):
        self.epoch+=1;self.last_id=None;self.status='RESYNCING'
    def apply(self,msg,received):
        if msg.get('product_id')!='BTC-USD' or msg.get('type') not in ('match','last_match'):return None
        try:
            event=datetime.fromisoformat(msg['time'].replace('Z','+00:00')).timestamp()
            price,size=float(msg['price']),float(msg['size']);identifier=int(msg['trade_id'])
            if not math.isfinite(price+size+event) or price<=0 or size<=0 or event>received+1:raise ValueError('Clock or value invalid')
        except (KeyError,ValueError,TypeError):self.rejected+=1;return None
        if self.last_id is not None and identifier<=self.last_id:return None
        continuous=self.last_id is not None and identifier==self.last_id+1 and bool(self.rows) and self.rows[-1]['epoch']==self.epoch and event>=self.rows[-1]['ts'] and event-self.rows[-1]['ts']<=3
        if self.last_id is not None and not continuous:self.gaps+=1;self.epoch+=1
        row={'id':identifier,'ts':event,'received':received,'price':price,'size':size,'epoch':self.epoch,'continuous':continuous,'side':msg.get('side'),'source':'Coinbase WebSocket'}
        self.rows.append(row);self.last_id=identifier;self.last_received=received;self.status='STREAMING' if continuous else 'RESYNCING';return row
    def snapshot(self,now):
        last=self.rows[-1] if self.rows else None
        fresh=bool(last and 0<=now-last['ts']<=3 and 0<=now-self.last_received<=3 and self.status=='STREAMING')
        return {'source':'Coinbase BTC-USD WebSocket','status':'LIVE' if fresh else 'STALE' if last else self.status,'event_ts':last['ts'] if last else None,'received_ts':self.last_received or None,'age':now-last['ts'] if last else None,'price':last['price'] if last else None,'gaps':self.gaps,'epoch':self.epoch,'rejected':self.rejected,'rows':list(self.rows)}

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
                with self.lock:self.tape.reset()
                delay=1
                while not self.stop.is_set():
                    message=json.loads(self.ws.recv())
                    if message.get('type')=='error':raise ValueError('Subscription rejected')
                    with self.lock:self.tape.apply(message,time.time())
            except Exception:
                with self.lock:self.tape.status='DISCONNECTED';self.tape.reset()
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
