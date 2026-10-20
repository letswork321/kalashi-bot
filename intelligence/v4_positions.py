"""Cents input and user-confirmed realized results. Never reads an account."""
import math
from scanner import fee
from .early_exit import add_watch,settings,target_bid
from .economics import executable


def number(value,name,low,high):
    if type(value) not in (int,float) or not math.isfinite(value) or not low<=value<=high:raise ValueError('Invalid '+name)
    return value


def create(db,v,now):
    if not isinstance(v,dict) or set(v)-{'ticker','side','entry_cents','quantity','entry_fee','target_roi'}:raise ValueError('Unknown position fields')
    cents=number(v.get('entry_cents'),'entry cents',.01,99.99);q=number(v.get('quantity',1),'quantity',1,10000)
    m=db.execute('SELECT ticker,opened,closed,payload FROM intel_markets WHERE ticker=?',(v.get('ticker'),)).fetchone()
    if not m or not m['opened']<=now<m['closed']:raise ValueError('Choose a known still-active ticker')
    ef=v.get('entry_fee');basis='USER_SUPPLIED' if ef is not None else 'ESTIMATED standard taker fee, multiplier1; verify actual fee'
    if ef is None:ef=fee(cents/100,q,.07,1)
    identifier=add_watch(db,{'ticker':v['ticker'],'side':v.get('side'),'entry':cents/100,'quantity':q,'entry_fee':ef,'target_roi':v.get('target_roi',settings(db)['target_roi'])},now)
    with db:db.execute('INSERT INTO v4_position_details(watch_id,fee_basis) VALUES(?,?)',(identifier,basis))
    return identifier


def realized(db,v,now):
    if not isinstance(v,dict) or set(v)!={'id','exit_cents','exit_fee'}:raise ValueError('Record id, actual exit cents and total exit fee')
    if type(v['id']) is not int:raise ValueError('Invalid id')
    r=db.execute("SELECT * FROM v3_watch_positions WHERE id=? AND state='WATCHING'",(v['id'],)).fetchone()
    if not r:raise ValueError('Active manual watch not found')
    price=number(v['exit_cents'],'exit cents',0,100)/100;ef=number(v['exit_fee'],'exit fee',0,r['quantity'])
    net=r['quantity']*(price-r['entry'])-r['entry_fee']-ef
    detail=db.execute('SELECT fee_basis FROM v4_position_details WHERE watch_id=?',(r['id'],)).fetchone()
    basis='USER_CONFIRMED EXIT — NOT ACCOUNT VERIFIED'+('; ESTIMATED ENTRY FEE' if detail and 'ESTIMATED' in detail['fee_basis'] else '')
    with db:
        db.execute("UPDATE v3_watch_positions SET state='REALIZED_BY_USER' WHERE id=?",(r['id'],))
        db.execute("INSERT INTO v4_position_details(watch_id,fee_basis,realized_ts,exit_price,exit_fee,realized_net,realized_basis) VALUES(?,'EXISTING BASIS',?,?,?,?,?) ON CONFLICT(watch_id) DO UPDATE SET realized_ts=excluded.realized_ts,exit_price=excluded.exit_price,exit_fee=excluded.exit_fee,realized_net=excluded.realized_net,realized_basis=excluded.realized_basis",(r['id'],now,price,ef,net,basis))
    return net


def quote(db,s):
    out=[]
    for row in db.execute("SELECT w.*,d.fee_basis,d.max_roi FROM v3_watch_positions w LEFT JOIN v4_position_details d ON d.watch_id=w.id WHERE state='WATCHING'").fetchall():
        r=dict(row);r.update(status='UNAVAILABLE',target_bid=None)
        if s and s['market']['ticker']==r['ticker'] and s.get('fee_valid'):
            r['target_bid']=target_bid(r['entry'],r['quantity'],r['entry_fee'],r['target_roi'],s['fee_multiplier'])
            r['target_status']='IMPOSSIBLE' if r['target_bid'] is None else 'CONDITIONAL GOAL'
            if s.get('book_event_verified') and 0<=s['now']-s.get('book_event_ts',0)<=1:
                try:
                    bid=executable(s['book'],r['side'],'sell',r['quantity']);cost=r['entry']*r['quantity']+r['entry_fee'];exitfee=fee(bid,r['quantity'],.07,s['fee_multiplier']);net=bid*r['quantity']-exitfee-cost;roi=net/cost
                    r.update(status='LIVE',bid=bid,net=net,roi=roi,exit_fee=exitfee,goal_hit=roi>=r['target_roi'],max_roi=max(r['max_roi'] if r['max_roi'] is not None else roi,roi),remaining=s['market']['closed']-s['now'])
                    with db:db.execute("INSERT INTO v4_position_details(watch_id,fee_basis,max_roi) VALUES(?,'EXISTING BASIS',?) ON CONFLICT(watch_id) DO UPDATE SET max_roi=excluded.max_roi",(r['id'],r['max_roi']))
                except ValueError:r['status']='INSUFFICIENT DEPTH'
        out.append(r)
    return out
