import math
import unittest
from intelligence.indicators import *
from intel_helpers import candles,snapshot,NOW

class IndicatorTests(unittest.TestCase):
    def test_ema_seed_and_updates(self):
        self.assertEqual(ema([1,2,3,4,5],3),[2,3,4])
    def test_rsi_neutral_and_extremes(self):
        self.assertEqual(rsi([5]*30),50);self.assertEqual(rsi(list(range(1,31))),100);self.assertEqual(rsi(list(range(30,0,-1))),0)
    def test_bollinger_population_std(self):
        b=bollinger(list(range(1,21)));self.assertEqual(b['mean'],10.5);self.assertAlmostEqual(b['sd'],math.sqrt(33.25))
    def test_macd_constant_and_causal(self):
        self.assertEqual(macd([100]*100)['histogram'],0)
        prefix=list(range(1,101));before=macd(prefix);prefix.append(10000)
        self.assertNotEqual(before['histogram'],macd(prefix)['histogram'])
    def test_exact_candle_boundaries_exclude_developing(self):
        rows=candles(30);rows.append({'ts':1800000000,'open':100,'close':200,'low':99,'high':201,'volume':10})
        self.assertEqual(len(completed(rows,1800000899,minimum=30)),30)
        self.assertEqual(len(completed(rows,1800000900,minimum=30)),31)
    def test_gap_and_invalid_timestamp_rejected(self):
        rows=candles();rows.pop(20)
        with self.assertRaises(InsufficientData):completed(rows,NOW,minimum=20)
        rows=candles();rows[0]['ts']+=1
        with self.assertRaises(InsufficientData):completed(rows,NOW)
    def test_vwap_uses_actual_trade_size_not_typical_price(self):
        trades=[{'ts':1,'price':100,'size':1},{'ts':2,'price':110,'size':9}]
        v=trade_vwap(trades,0,3,[(0,3)])
        self.assertEqual(v['value'],109);self.assertAlmostEqual(v['sd'],3)
    def test_vwap_cannot_use_future_or_missing_coverage(self):
        trades=[{'ts':1,'price':100,'size':1},{'ts':10,'price':999,'size':999}]
        self.assertEqual(trade_vwap(trades,0,3,[(0,3)])['value'],100)
        with self.assertRaises(InsufficientData):trade_vwap(trades,0,3,[(1,3)])
    def test_coverage_merging_and_holes(self):
        self.assertTrue(covered([(0,2),(2,5)],0,5));self.assertFalse(covered([(0,2),(3,5)],0,5))
    def test_tick_sequence_freshness_and_metrics(self):
        s=snapshot();t=tick_metrics(s['trades'],s['now']);self.assertGreater(t['velocity'],0)
        s['trades'].pop(20)
        with self.assertRaises(InsufficientData):tick_metrics(s['trades'],s['now'])
    def test_tick_stale_is_insufficient(self):
        s=snapshot()
        with self.assertRaises(InsufficientData):tick_metrics(s['trades'],s['now']+10)
