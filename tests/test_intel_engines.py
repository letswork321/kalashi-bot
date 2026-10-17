import unittest
from unittest.mock import patch
from intelligence.engines import *
from intel_helpers import snapshot

class EngineTests(unittest.TestCase):
    def breakout(self):
        s=snapshot();last=s['candles15'][-1];last.update(low=130,high=134,open=131,close=133)
        return s
    def test_breakout_completed_entire_candle_above_both(self):
        s=self.breakout();r=breakout_engine(s)
        self.assertEqual(r['signal'],'LONG BREAKOUT — CONFIRMED');self.assertEqual(r['direction'],'UP')
    def test_breakout_wick_below_invalidates_confirmation(self):
        s=self.breakout();s['candles15'][-1]['low']=99
        self.assertNotEqual(breakout_engine(s)['signal'],'LONG BREAKOUT — CONFIRMED')
    def test_breakout_previous25_excludes_trigger(self):
        s=self.breakout();r=breakout_engine(s)
        self.assertLess(r['readings']['previous_25_high'],133)
    def test_breakout_cannot_retroactively_predict_finished_market(self):
        s=self.breakout();s['market']['opened']-=900
        self.assertEqual(breakout_engine(s)['signal'],'NEXT MARKET INFORMATION')
    def test_breakout_vwap_time_must_match_close(self):
        s=self.breakout();s['vwap_at_close']['asof']+=1
        self.assertEqual(breakout_engine(s)['quality'],'INSUFFICIENT DATA')
    def test_unconfirmed_watch_not_confirmed(self):
        s=snapshot();s['price']=110
        self.assertEqual(breakout_engine(s)['signal'],'UNCONFIRMED BREAKOUT WATCH')
    def test_no_vwap_and_stale_feed_not_guessed(self):
        s=snapshot();s['vwap']=None
        self.assertEqual(breakout_engine(s)['quality'],'INSUFFICIENT DATA')
        s=snapshot();s['quote_ts']-=5
        self.assertEqual(confluence_engine(s)['quality'],'INSUFFICIENT DATA')
    def votes(self,velocity=.001,accel=.001,rsi_value=20,ratio=2):
        s=snapshot();s['candles15'][-1]['volume']=100*ratio;s['price']=102
        with patch('intelligence.engines.ema',side_effect=lambda values,p:[110] if p==27 else [100]),patch('intelligence.engines.rsi',return_value=rsi_value),patch('intelligence.engines.macd',return_value={'histogram':2,'previous_histogram':1}),patch('intelligence.engines.tick_metrics',return_value={'velocity':velocity,'acceleration':accel}):
            return confluence_engine(s)
    def test_seven_votes_and_threshold(self):
        r=self.votes();self.assertEqual(len(r['votes']),7);self.assertEqual(r['score'],7);self.assertEqual(r['signal'],'CONFLUENCE BUY')
        self.assertEqual(self.votes(velocity=0)['score'],6)
        self.assertEqual(self.votes(velocity=0,accel=0)['signal'],'NO MAJOR CONFLUENCE')
    def test_rsi_overbought_votes_bearish(self):
        self.assertEqual(self.votes(rsi_value=75)['votes']['RSI14'],-1)
    def test_volume_1point5_uses_previous20_excluding_current(self):
        self.assertEqual(self.votes(ratio=1.5)['votes']['Volume surge'],1)
        self.assertEqual(self.votes(ratio=1.499)['votes']['Volume surge'],0)
    def test_reversal_never_claims_unvalidated_probability(self):
        s=snapshot();s['reversal']={'state':'OBSERVED','band':'UPPER','direction':'DOWN','price':102,'upper':101,'lower':99,'observed':s['now']}
        r=reversal_engine(s);self.assertEqual(r['signal'],'REVERSAL RISK / FADE OPPORTUNITY');self.assertIsNone(r['probability']);self.assertEqual(r['probability_status'],'PROBABILITY NOT VALIDATED')
    def test_independent_engine_disagreement(self):
        s=self.breakout();s['reversal']={'state':'OBSERVED','band':'UPPER','direction':'DOWN','price':132,'upper':102,'lower':98,'observed':s['now']}
        self.assertEqual(breakout_engine(s)['direction'],'UP');self.assertEqual(reversal_engine(s)['direction'],'DOWN')
    def test_regime_context_does_not_change_breakout(self):
        s=self.breakout();s['regime']={'regime':'Strong downward trend'}
        self.assertEqual(breakout_engine(s)['signal'],'LONG BREAKOUT — CONFIRMED')

class BearishConfluenceTests(unittest.TestCase):
    def test_all_seven_bearish_votes(self):
        s=snapshot();s['candles15'][-1]['volume']=200;s['candles15'][-1]['open']=s['candles15'][-1]['close']+.2;s['price']=98
        with patch('intelligence.engines.ema',side_effect=lambda values,p:[90] if p==27 else [100]),patch('intelligence.engines.rsi',return_value=80),patch('intelligence.engines.macd',return_value={'histogram':-2,'previous_histogram':-1}),patch('intelligence.engines.tick_metrics',return_value={'velocity':-.001,'acceleration':-.001}):
            r=confluence_engine(s)
        self.assertEqual(r['score'],-7);self.assertEqual(r['signal'],'CONFLUENCE SELL')
