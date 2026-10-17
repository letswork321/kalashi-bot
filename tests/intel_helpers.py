import math
from datetime import datetime,timezone
from scanner import Book

NOW=1800000000+650

def market(opened=1800000000,ticker='KXBTC15M-TEST'):
    iso=lambda t:datetime.fromtimestamp(t,timezone.utc).isoformat()
    return {'ticker':ticker,'event_ticker':'E','market_type':'binary','strike_type':'greater_or_equal','open_time':iso(opened),'close_time':iso(opened+900),'floor_strike':100,'status':'active','result':''}

def candles(n=100,end=1800000000):
    rows=[]
    for i in range(n):
        c=100+math.sin(i/5)
        rows.append({'ts':end-(n-i)*900,'low':c-1,'high':c+1,'open':c-.2,'close':c,'volume':100})
    return rows

def snapshot(now=NOW):
    m=market();book=Book.parse({'yes_dollars':[['.48','100'],['.47','100']],'no_dollars':[['.49','100'],['.48','100']]})
    tick=[{'id':i,'ts':now-60+i,'price':100+i*.001,'size':1} for i in range(61)]
    p={'model':'heuristic-v1-uncalibrated','p_up':.65,'observed_at':now,'btc_timestamp':now,'features':{'ema9':101,'ema21':100,'rsi14':55,'volatility_1m':.001,'momentum_3m':.002,'volume_ratio':1.2}}
    return {'now':now,'mode':'live','market':{'ticker':m['ticker'],'opened':1800000000,'closed':1800000900,'strike':100,'raw':m},'quote_ts':now,'price':101,'candles15':candles(),'trades':tick,'vwap':{'value':100,'sd':.5,'asof':now,'anchor':int(now//86400)*86400},'vwap_at_close':{'value':100,'sd':.5,'asof':1800000000},'book':book,'book_id':1,'book_ts':now,'book_latency':.1,'book_source':'REST','ws_sequence_valid':False,'fee_multiplier':1,'baseline':p,'book_history':[{'ticker':m['ticker'],'side':side,'ts':now-60+i*10,'bid':.4+i*.015} for i in range(7) for side in ['UP','DOWN']]}
