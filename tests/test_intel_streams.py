import unittest
from intelligence.streams import SequencedBook,OptionalStream

class StreamTests(unittest.TestCase):
    def snap(self):return {'type':'orderbook_snapshot','sid':1,'seq':10,'msg':{'market_ticker':'M','yes_dollars_fp':[['.4','10']],'no_dollars_fp':[['.5','10']]}}
    def test_snapshot_delta_fixed_point_prices(self):
        b=SequencedBook();b.apply(self.snap(),100)
        b.apply({'type':'orderbook_delta','sid':1,'seq':11,'msg':{'market_ticker':'M','side':'yes','price_dollars':'.4','delta_fp':'-2'}},101)
        self.assertEqual(b.snapshot()['yes'],[(.4,8)]);self.assertEqual(b.seq,11)
    def test_gap_invalidates_entire_book(self):
        b=SequencedBook();b.apply(self.snap(),100)
        with self.assertRaises(ValueError):b.apply({'type':'orderbook_delta','sid':1,'seq':12,'msg':{'market_ticker':'M','side':'yes','price_dollars':'.4','delta_fp':'1'}},101)
        self.assertIsNone(b.snapshot())
    def test_market_rollover_requires_fresh_snapshot(self):
        b=SequencedBook();b.apply(self.snap(),100)
        with self.assertRaises(ValueError):b.apply({'type':'orderbook_delta','sid':1,'seq':11,'msg':{'market_ticker':'NEW','side':'yes','price_dollars':'.4','delta_fp':'1'}},101)
        self.assertIsNone(b.snapshot())
    def test_negative_depth_rejected(self):
        b=SequencedBook();b.apply(self.snap(),100)
        with self.assertRaises(ValueError):b.apply({'type':'orderbook_delta','sid':1,'seq':11,'msg':{'market_ticker':'M','side':'yes','price_dollars':'.4','delta_fp':'-100'}},101)
    def test_disabled_transport_never_connects(self):
        from unittest.mock import patch
        with patch.dict('os.environ',{'KALSHI_WS_ENABLED':''}):
            stream=OptionalStream();stream.start();self.assertIsNone(stream.thread);self.assertEqual(stream.state,'DISABLED')

class StreamValidationTests(unittest.TestCase):
    def test_nonfinite_snapshot_never_becomes_a_quote(self):
        b=SequencedBook()
        with self.assertRaises(ValueError):b.apply({'type':'orderbook_snapshot','sid':1,'seq':1,'msg':{'market_ticker':'M','yes_dollars_fp':[['NaN','10']]}},100)
        self.assertIsNone(b.snapshot())
