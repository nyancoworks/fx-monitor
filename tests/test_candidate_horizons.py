"""Synthetic cache horizons only; no private observations or network."""
from copy import deepcopy
import hashlib
import json
import unittest
from diagnostics.candidate_horizons import review_candidate_horizons
from fx_system.strategy_report_export import build_strategy_report_export
from test_strategy_report_export import snapshot, SOURCE, CLOCK


class CandidateHorizonTests(unittest.TestCase):
    def run_review(self, *, gap=False, unknown=False, horizons=(3600, 7200), bad_hash=False):
        saved = snapshot()
        bundle = build_strategy_report_export(json.dumps(saved).encode(), SOURCE)
        later = deepcopy(saved); later['evaluated_at'] = CLOCK+3600
        # A fresh pending snapshot avoids carrying the prior assessment clock forward.
        from fx_system.scheduled_outlook import build_scheduled_outlook
        later['scheduled_outlook'] = build_scheduled_outlook({}, {}, evaluated_at=CLOCK+3600)
        price_source = {**SOURCE, 'evaluated_at': CLOCK+3600, 'run_id': SOURCE['run_id']+1}
        price = build_strategy_report_export(json.dumps(later).encode(), price_source)
        bars = [{'timestamp': CLOCK+i*300, 'open': 96, 'high': 115, 'low': 85, 'close': 97}
                for i in range(12) if not (gap and i == 5)]
        cache = {'EURUSD': {'m5': bars, 'bar_provenance': {
            'm5:'+str(b['timestamp']): 'unknown' if unknown and i == 5 else 'Twelve Data'
            for i, b in enumerate(bars)}}}
        raw = json.dumps(cache).encode()
        sha = hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()
        before = deepcopy((bundle, price, cache))
        result = review_candidate_horizons(bundle, SOURCE, bundle['snapshot_git_blob_sha'],
            price, price_source, price['snapshot_git_blob_sha'], raw,
            '0'*40 if bad_hash else sha, private_commit='a'*40, horizons=horizons)
        self.assertEqual((bundle, price, cache), before)
        return result

    def test_complete_and_beyond_clock_cases_both_preserved(self):
        r = self.run_review()
        self.assertEqual(len(r['cases']), 2)
        first, later = r['cases']
        self.assertTrue(first['whole_m5_grid_complete'])
        self.assertTrue(first['observation']['same_bar_touch_order_unknown'])
        self.assertEqual(first['observation']['trade_performance'], 'not_measured')
        self.assertEqual(later['status'], 'beyond_saved_cache_evaluation')
        self.assertIsNone(later['observation'])
        self.assertFalse(later['target_touch_observable'])

    def test_gaps_and_unverified_sources_are_not_complete(self):
        for options in ({'gap': True}, {'unknown': True}):
            c = self.run_review(**options)['cases'][0]
            self.assertFalse(c['whole_m5_grid_complete'])
            self.assertFalse(c['target_touch_observable'])

    def test_cache_identity_mismatch_rejected(self):
        with self.assertRaises(ValueError): self.run_review(bad_hash=True)

    def test_horizons_are_bounded_unique_whole_m5_integers(self):
        for h in ((), (True,), (1,), (301,), (3600,3600), (32*86400,)):
            with self.assertRaises(ValueError): self.run_review(horizons=h)
