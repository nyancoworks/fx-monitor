"""Synthetic frozen scenarios and candles; no network or private fixtures."""
from copy import deepcopy
import json
import unittest

from diagnostics.candidate_followup_archive import build_followup
from diagnostics.monitoring_result_history import pack_generation
from diagnostics.scenario_quality_review import review_saved_followup
from fx_system.scheduled_outlook import build_scheduled_outlook
from fx_system.strategy_report_export import build_strategy_report_export
from test_strategy_report_export import snapshot, SOURCE, CLOCK


def inputs(*, missing=False, unknown=False, extra_seconds=0):
    saved = snapshot()
    bundle = build_strategy_report_export(json.dumps(saved).encode(), SOURCE)
    bars = [{'timestamp': CLOCK+i*300, 'open': 96, 'high': 115, 'low': 85, 'close': 97}
            for i in range(12) if not (missing and i == 5)]
    pair = {'decision_data': {'raw': {'m5': bars}, 'provenance': {
        'm5:'+str(b['timestamp']): 'unverified' if unknown and i == 5 else 'Twelve Data'
        for i, b in enumerate(bars)}}}
    through = CLOCK+3600+extra_seconds
    current = {'evaluated_at': through, 'pairs': {'EURUSD': pair},
               'scheduled_outlook': build_scheduled_outlook({}, {}, evaluated_at=through)}
    prior_source = {k: SOURCE[k] for k in ('source_repository', 'source_commit', 'run_id')}
    previous = {'history': [pack_generation(saved['scheduled_outlook']['rows'], evaluated_at=CLOCK)],
                'provenance': {str(CLOCK): prior_source}}
    followup = build_followup(previous, current, {**prior_source, 'run_id': 124})
    return bundle, followup


def review(bundle, followup):
    return review_saved_followup(bundle, SOURCE, bundle['snapshot_git_blob_sha'], followup)


class SavedScenarioQualityTests(unittest.TestCase):
    def test_full_pipeline_preserves_inputs_and_does_not_label_touches_as_wins(self):
        bundle, followup = inputs()
        before = deepcopy((bundle, followup))
        result = review(bundle, followup)
        self.assertEqual(result['canonical_count'], 32)
        self.assertEqual(result['condition_status_counts'], {'conditions_observed': 1})
        self.assertEqual(result['review_count'], 1)
        self.assertEqual(result['complete_saved_window_count'], 1)
        self.assertEqual(result['continuous_saved_evaluation_window_count'], 1)
        self.assertEqual(result['target_touch_observable_count'], 1)
        case = result['cases'][0]
        self.assertTrue(case['observation']['same_bar_touch_order_unknown'])
        self.assertEqual(case['observation']['trade_performance'], 'not_measured')
        self.assertEqual(case['next_saved_evaluation']['assessment'], 'evaluation_pending')
        self.assertEqual(case['condition_status_at_save'], 'conditions_observed')
        self.assertNotIn('win_rate', result)
        self.assertFalse(result['window']['publication_time_verified'])
        self.assertEqual(result['selection_review'][0]['ordering_basis'], 'saved_order_no_matching_peer')
        self.assertEqual((bundle, followup), before)

    def test_complete_grid_does_not_claim_partial_clock_boundaries_were_observed(self):
        bundle, followup = inputs(extra_seconds=62)
        result = review(bundle, followup)
        self.assertEqual(result['complete_saved_window_count'], 1)
        self.assertEqual(result['continuous_saved_evaluation_window_count'], 0)
        coverage = result['cases'][0]['saved_m5_coverage']
        self.assertEqual(coverage['saved_evaluation_window_seconds'], 3662)
        self.assertEqual(coverage['expected_whole_m5_seconds'], 3600)
        self.assertEqual(coverage['observed_whole_m5_seconds'], 3600)
        self.assertEqual(coverage['excluded_clock_boundary_seconds'], 62)
        self.assertTrue(coverage['whole_m5_grid_complete'])
        self.assertFalse(coverage['continuous_saved_evaluation_window'])
        self.assertEqual(coverage['notification_to_notification_coverage'], 'unverified')

    def test_gap_or_unknown_source_keeps_case_but_excludes_complete_window_counts(self):
        for options in ({'missing': True}, {'unknown': True}):
            bundle, followup = inputs(**options)
            result = review(bundle, followup)
            self.assertEqual(result['review_count'], 1)
            self.assertEqual(result['complete_saved_window_count'], 0)
            self.assertEqual(result['continuous_saved_evaluation_window_count'], 0)
            self.assertEqual(result['target_touch_observable_count'], 0)
            self.assertEqual(result['invalidation_touch_observable_count'], 0)

    def test_wrong_generation_duplicate_missing_or_tampered_observation_is_rejected(self):
        bundle, original = inputs()
        changes = [lambda f: f['previous_source'].update(run_id=999),
                   lambda f: f['source'].update(source_repository='unexpected/repo'),
                   lambda f: f['source'].update(run_id=True),
                   lambda f: f['candidate_observations'].append(deepcopy(f['candidate_observations'][0])),
                   lambda f: f['candidate_observations'].clear(),
                   lambda f: f['candidate_observations'][0].update(favorable_excursion_pips=999),
                   lambda f: f['observation_window'].update(through_saved_evaluation=CLOCK+7200)]
        for change in changes:
            followup = deepcopy(original); change(followup)
            with self.assertRaises(ValueError):
                review(bundle, followup)

    def test_nonreview_and_no_future_bars_do_not_become_failed_trades(self):
        bundle, followup = inputs()
        feed = followup['m5_observations']['EURUSD']
        feed.update(candles=[], status='no_verified_future_bars')
        from fx_system.candidate_followup import observe
        from diagnostics.monitoring_result_history import restore_generation
        from diagnostics.candidate_followup_archive import canonical_records
        record = next(r for r in canonical_records(restore_generation(followup['previous_saved_evaluation']))
                      if r['assessment'] == 'review')
        observation = observe(record, [], followup['evaluated_at'])
        observation.update(followup_data_status=feed['status'], unverified_source_count=0)
        followup['candidate_observations'] = [observation]
        result = review(bundle, followup)
        self.assertEqual(result['complete_saved_window_count'], 0)
        self.assertEqual(result['cases'][0]['observation']['status'], 'awaiting_future_saved_candles')
        self.assertEqual(result['review_count'], 1)


if __name__ == '__main__':
    unittest.main()
