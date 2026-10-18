"""Checks for honest chart callouts: no hindsight, no fake alerts or scores."""
import sqlite3
import unittest

from intelligence import callouts

def candles(now, period, n=30, slope=.5):
    return [
        {'ts':now-(n-i)*period, 'open':100+i*slope-.15,
         'close':100+i*slope,'low':100+i*slope-.3,
         'high':100+i*slope+.2,'volume':10+i}
        for i in range(n)
    ]

def snapshot(now):
    ones=candles(now,60)
    fives=candles(now,300)
    return {
        'mode':'live','now':now,
        'market':{'ticker':'KXBTC15M-TEST','closed':now+600},
        'price':ones[-1]['close']+.1,'quote_ts':now-1,
        'book_ts':now-1,'book':object(),'candles1':ones,'candles5':fives,
    }

class TestChartCallouts(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:')
        self.db.row_factory=sqlite3.Row
        self.db.execute('CREATE TABLE intel_alerts(key TEXT, state TEXT)')
        callouts.ensure(self.db)
        self.now=900000

    def tearDown(self):
        self.db.close()

    def test_agreement_and_breakout_watch(self):
        signal=callouts.build(snapshot(self.now))
        self.assertIsNotNone(signal)
        self.assertEqual(signal['direction'],'UP')
        self.assertEqual(signal['entry'],'WAIT — no validated entry signal')
        self.assertEqual(signal['horizon'],180)
        self.assertIn('1-minute and 5-minute', signal['reason'])
        self.assertIn('Not reliable enough',signal['exit_target'])

    def test_stale_or_missing_data_does_not_call(self):
        s=snapshot(self.now)
        s['quote_ts']=self.now-7
        self.assertIsNone(callouts.build(s))
        s=snapshot(self.now)
        s['candles5']=[]
        self.assertIsNone(callouts.build(s))
        s=snapshot(self.now)
        s['market']['closed']=self.now+100
        self.assertIsNone(callouts.build(s))

    def test_hit_scored_only_after_sent_and_observed(self):
        c=callouts.build(snapshot(self.now))
        key='callout:test'
        self.assertEqual(callouts.record(self.db,c,key),1)
        self.assertEqual(callouts.record(self.db,c,key),0)
        due=self.now+180
        callouts.observe(self.db,due+1,due+1,c['btc_price']*1.002)
        self.assertEqual(callouts.summary(self.db)['total'],0)  # unsent not scored
        callouts.acknowledged(self.db,key,self.now+2)
        callouts.observe(self.db,due+1,due+1,c['btc_price']*1.0007)
        summary=callouts.summary(self.db)
        self.assertEqual((summary['hits'],summary['not_hits'],summary['missed']),(1,0,0))
        self.assertEqual(summary['hit_rate'],1.0)

    def test_failed_direction_and_missed_endpoint(self):
        c=callouts.build(snapshot(self.now));key='miss'
        callouts.record(self.db,c,key)
        callouts.acknowledged(self.db,key,self.now+2)
        callouts.observe(self.db,self.now+193)
        self.assertEqual(callouts.summary(self.db)['missed'],1)
        self.assertEqual(callouts.summary(self.db)['hit_rate'],None)
        c2=dict(c)
        c2['observed']+=600
        c2['quote_ts']+=600
        callouts.record(self.db,c2,'loss')
        callouts.acknowledged(self.db,'loss',self.now+601)
        callouts.observe(self.db,self.now+781,self.now+781,c2['btc_price']*1.0001)
        self.assertEqual(callouts.summary(self.db)['not_hits'],1)

    def test_no_outcome_from_late_quote(self):
        c=callouts.build(snapshot(self.now));callouts.record(self.db,c,'late')
        callouts.acknowledged(self.db,'late',self.now+1)
        callouts.observe(self.db,self.now+194,self.now+194,c['btc_price']*1.01)
        summary=callouts.summary(self.db)
        self.assertEqual(summary['hits'],0)
        self.assertEqual(summary['missed'],1)

if __name__=='__main__':
    unittest.main()
