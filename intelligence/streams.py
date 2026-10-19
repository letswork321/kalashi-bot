"""Optional authenticated market-data-only Kalshi WebSocket; OFF by default."""
from collections import deque
import base64
import json
import math
import os
from pathlib import Path
import threading
import time
from urllib.parse import urlparse

WS_URL='wss://api.elections.kalshi.com/trade-api/ws/v2'

class SequencedBook:
    def __init__(self):self.reset()
    def reset(self):self.ticker=None;self.sid=None;self.seq=None;self.yes={};self.no={};self.received=0;self.latency=99;self.event_ts=None;self.history=deque(maxlen=4000)
    def apply(self,message,now):
        kind=message.get('type');m=message.get('msg',{})
        if kind not in ('orderbook_snapshot','orderbook_delta'):return
        if kind=='orderbook_snapshot':
            self.ticker=m['market_ticker'];self.sid=message['sid'];self.seq=message['seq']
            self.yes={float(p):float(q) for p,q in m.get('yes_dollars_fp',[])}
            self.no={float(p):float(q) for p,q in m.get('no_dollars_fp',[])}
            if any(not math.isfinite(p+q) or not 0<p<1 or q<0 for p,q in list(self.yes.items())+list(self.no.items())):
                self.reset();raise ValueError('Invalid snapshot price/quantity')
        else:
            if self.seq is None or message.get('sid')!=self.sid or message['seq']!=self.seq+1 or m['market_ticker']!=self.ticker:
                self.reset();raise ValueError('Orderbook sequence gap; reconnect for a fresh snapshot')
            book=self.yes if m['side']=='yes' else self.no if m['side']=='no' else None
            if book is None:raise ValueError('Unknown book side')
            price=float(m['price_dollars']);delta=float(m['delta_fp'])
            if not math.isfinite(price+delta) or not 0<price<1:
                self.reset();raise ValueError('Invalid delta price/quantity')
            quantity=book.get(price,0)+delta
            if quantity<-.000001:self.reset();raise ValueError('Negative book quantity')
            if quantity<=0:book.pop(price,None)
            else:book[price]=quantity
            self.seq=message['seq']
        self.received=now
        event=message.get('sending_ts_ms') or m.get('ts_ms')
        self.event_ts=event/1000 if event is not None else None
        self.latency=abs(now-self.event_ts) if self.event_ts is not None else 99
        for side,book,opposite in [('UP',self.yes,self.no),('DOWN',self.no,self.yes)]:
            if book and opposite:
                bid=max(book);ask=1-max(opposite)
                self.history.append({'ticker':self.ticker,'ts':self.event_ts if self.event_ts is not None else now,'side':side,'bid':bid,'ask':ask,'spread':ask-bid,'bid_size':book[bid],'ask_size':opposite[max(opposite)]})
    def snapshot(self):
        if self.seq is None:return None
        return {'ticker':self.ticker,'yes':sorted(self.yes.items(),reverse=True),'no':sorted(self.no.items(),reverse=True),'received':self.received,'event_ts':self.event_ts,'latency':self.latency,'seq':self.seq,'history':list(self.history)}

class OptionalStream:
    def __init__(self):
        self.enabled=os.environ.get('KALSHI_WS_ENABLED','').lower()=='true'
        self.book=SequencedBook();self.lock=threading.Lock();self.stop=threading.Event();self.market=None;self.thread=None;self.state='DISABLED';self.ws=None
    def start(self):
        if self.enabled:
            if os.environ.get('KALSHI_DATA_SECURITY_CONFIRMED','').lower()!='true':
                self.state='BLOCKED — RESOLVE WINDOWS SECURITY ISSUE BEFORE CONNECTING PRIVATE DATA KEYS';return
            if not os.environ.get('KALSHI_DATA_KEY_ID') or not os.environ.get('KALSHI_DATA_PRIVATE_KEY_FILE'):
                self.state='MISSING READ-ONLY DATA CREDENTIALS';return
            self.thread=threading.Thread(target=self.run,daemon=True,name='optional-market-data-ws');self.thread.start()
    def set_market(self,ticker):
        if ticker!=self.market:
            self.market=ticker
            with self.lock:self.book.reset()
            if self.ws:
                try:self.ws.close()
                except Exception:pass
    def snapshot(self):
        with self.lock:return self.book.snapshot()
    def headers(self):
        from cryptography.hazmat.primitives import hashes,serialization
        from cryptography.hazmat.primitives.asymmetric import padding
        stamp=str(int(time.time()*1000))
        key=serialization.load_pem_private_key(Path(os.environ['KALSHI_DATA_PRIVATE_KEY_FILE']).read_bytes(),password=None)
        sig=key.sign((stamp+'GET/trade-api/ws/v2').encode(),padding.PSS(mgf=padding.MGF1(hashes.SHA256()),salt_length=padding.PSS.DIGEST_LENGTH),hashes.SHA256())
        return {'KALSHI-ACCESS-KEY':os.environ['KALSHI_DATA_KEY_ID'],'KALSHI-ACCESS-TIMESTAMP':stamp,'KALSHI-ACCESS-SIGNATURE':base64.b64encode(sig).decode()}
    def run(self):
        delay=1
        while not self.stop.is_set():
            if not self.market:self.stop.wait(.5);continue
            try:
                import websocket
                proxy=os.environ.get('HTTPS_PROXY') or os.environ.get('https_proxy');options={}
                if proxy:
                    p=urlparse(proxy);options={'http_proxy_host':p.hostname,'http_proxy_port':p.port or 80}
                    if p.username:options['http_proxy_auth']=(p.username,p.password or '')
                self.ws=websocket.create_connection(WS_URL,header=self.headers(),timeout=5,**options)
                # Explicit legacy NO-leg prices; fail closed when unsupported.
                self.ws.send(json.dumps({'id':1,'cmd':'subscribe','params':{'channels':['orderbook_delta'],'market_ticker':self.market,'use_yes_price':False}}))
                self.state='CONNECTED — WAITING FOR SNAPSHOT';delay=1
                while not self.stop.is_set():
                    message=json.loads(self.ws.recv())
                    if message.get('type')=='error':raise ValueError('Subscription rejected')
                    with self.lock:self.book.apply(message,time.time())
                    self.state='SEQUENCED MARKET DATA'
            except Exception:
                # Never print private key, headers, signatures, or raw socket errors.
                self.state='RECONNECTING / OPTIONAL DEPENDENCY OR AUTH REQUIRED'
                with self.lock:self.book.reset()
                self.stop.wait(delay);delay=min(60,delay*2)
            finally:
                if self.ws:
                    try:self.ws.close()
                    except Exception:pass
                self.ws=None
    def close(self):
        self.stop.set()
        if self.ws:
            try:self.ws.close()
            except Exception:pass
        if self.thread:self.thread.join(timeout=6)


class BRTIStream(OptionalStream):
    """Official authenticated CF benchmark channel, isolated from the spot chart."""
    def __init__(self):
        super().__init__();self.enabled=os.environ.get('KALSHI_BRTI_ENABLED','').lower()=='true';self.value=None;self.last_seq=None;self.last_sid=None
    def apply_value(self,message,now):
        if message.get('type')!='cfbenchmarks_value':return
        m=message.get('msg',{})
        if m.get('index_id')!='BRTI':return
        data=json.loads(m['data']) if isinstance(m.get('data'),str) else m['data']
        event=float(data['time'])/1000;price=float(data['value'])
        if not math.isfinite(event+price) or price<=0 or event>now+1:raise ValueError('Invalid benchmark event')
        if self.value and event<=self.value['event_ts']:return
        seq=message.get('seq');sid=message.get('sid')
        contiguous=self.last_seq is None or sid==self.last_sid and seq==self.last_seq+1
        if not contiguous:self.value=None;raise ValueError('BRTI sequence gap')
        self.last_seq=seq;self.last_sid=sid
        self.value={'source':'CF Benchmarks BRTI via Kalshi','price':price,'event_ts':event,'received_ts':now,'average_60s':m.get('avg_60s_data'),'final_minute_average':m.get('last_60s_windowed_average_15min'),'status':'LIVE' if 0<=now-event<=3 else 'STALE'}
    def set_market(self,ticker):pass
    def run(self):
        from .live_feed import proxy_options
        delay=1
        while not self.stop.is_set():
            try:
                import websocket
                self.ws=websocket.create_connection(WS_URL,header=self.headers(),timeout=5,**proxy_options())
                self.ws.send(json.dumps({'id':1,'cmd':'subscribe','params':{'channels':['cfbenchmarks_value'],'index_ids':['BRTI']}}))
                self.state='CONNECTED — BRTI ACCESS NOT YET VERIFIED';delay=1
                while not self.stop.is_set():
                    message=json.loads(self.ws.recv())
                    if message.get('type')=='error':raise ValueError('BRTI subscription denied or unavailable')
                    with self.lock:self.apply_value(message,time.time())
                    if self.value:self.state='BRTI DATA RECEIVED'
            except Exception:
                self.state='BRTI UNAVAILABLE — ENTITLEMENT / AUTH / NETWORK NOT VERIFIED'
                with self.lock:self.value=None;self.last_seq=None;self.last_sid=None
                self.stop.wait(delay);delay=min(60,delay*2)
            finally:
                if self.ws:
                    try:self.ws.close()
                    except Exception:pass
                self.ws=None
    def snapshot(self,now=None):
        now=time.time() if now is None else now
        with self.lock:
            if not self.value:return {'source':'CF Benchmarks BRTI via Kalshi','status':self.state,'price':None,'event_ts':None}
            return {**self.value,'status':'LIVE' if 0<=now-self.value['event_ts']<=3 else 'STALE','age':now-self.value['event_ts']}
