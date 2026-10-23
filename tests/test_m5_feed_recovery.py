"""Unverified fallback is retained evidence, never a primary decision feed."""
from copy import deepcopy
import unittest

from fx_system.data_quality import evaluate_pair


CLOCK = 1800000000


def data(sources):
    bars = [{'timestamp': CLOCK-(len(sources)-i)*300, 'open': 100, 'high': 102,
             'low': 99, 'close': 101} for i in range(len(sources))]
    return {'decision_data': {'raw': {'m5': bars}, 'provenance': {
        'm5:'+str(bar['timestamp']): source for bar, source in zip(bars, sources)}},
        'decision_quality': {'ready': True}, 'm5': {'candles': deepcopy(bars)}}


class M5FeedRecoveryTests(unittest.TestCase):
    def test_fresh_fallback_tail_cannot_reuse_older_primary_history_or_saved_ready_flag(self):
        saved = data(['Twelve Data']*30+['Yahoo']*10); before = deepcopy(saved)
        frames, quality = evaluate_pair(saved, CLOCK)
        self.assertEqual(frames['m5'], [])
        self.assertFalse(quality['ready'])
        self.assertFalse(quality['closed_candle_freshness']['m5']['latest_closed_present'])
        self.assertIn('m5: verified history insufficient (0/24)', quality['reasons'])
        self.assertIn('m5: recent 12-bar window has 12 gaps', quality['reasons'])
        self.assertEqual(saved, before)

    def test_returned_contiguous_primary_window_recovers_without_erasing_fallback_originals(self):
        saved = data(['Yahoo']*16+['Twelve Data']*24); before = deepcopy(saved)
        frames, quality = evaluate_pair(saved, CLOCK)
        self.assertEqual(len(frames['m5']), 24)
        self.assertTrue(quality['timeframes']['m5']['ok'])
        self.assertTrue(quality['closed_candle_freshness']['m5']['latest_closed_present'])
        self.assertFalse(any(reason.startswith('m5:') for reason in quality['reasons']))
        self.assertEqual(saved, before)


if __name__ == '__main__':
    unittest.main()
