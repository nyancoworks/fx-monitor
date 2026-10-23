"""Synthetic event times and immutable saved-price follow-ups only."""
from copy import deepcopy
import json
import unittest

from diagnostics.calendar_price_windows import review_calendar_price_windows
from diagnostics.candidate_followup_archive import build_followup
from diagnostics.monitoring_result_history import pack_generation
from fx_system.scheduled_outlook import build_scheduled_outlook
from fx_system.strategy_report_export import build_strategy_report_export
from test_strategy_report_export import snapshot, SOURCE, CLOCK


def inputs(*, gap=False, unknown=False, event_changes=None, overlap=False):
    saved = snapshot()
    all_records = saved['scheduled_outlook']['strategy_assessments'] + [
        r for row in saved['scheduled_outlook']['rows'] for r in row['strategy_assessments'].values()]
    for record in all_records:
        for event in record['economic_calendar_context']['events']:
            event.update(id='synthetic-event', scheduled_at_utc=CLOCK+900,
                         provider_status='confirmed')
            event.update(event_changes or {})
        if overlap and record['economic_calendar_context']['events']:
            other = deepcopy(record['economic_calendar_context']['events'][0]); other['id'] = 'synthetic-overlap'
            record['economic_calendar_context']['events'].append(other)
    bundle = build_strategy_report_export(json.dumps(saved).encode(), SOURCE)
    bars = [dict(timestamp=CLOCK+i*300, open=1+i*.0001, high=1+i*.0001+.0002,
                 low=1+i*.0001-.0002, close=1+i*.0001+.000025)
            for i in range(12) if not (gap and i == 4)]
    pair = {'decision_data': {'raw': {'m5': bars}, 'provenance': {
        'm5:'+str(b['timestamp']): 'unverified' if unknown and i == 4 else 'Twelve Data'
        for i, b in enumerate(bars)}}}
    current = {'evaluated_at': CLOCK+3600, 'pairs': {'EURUSD': pair},
               'scheduled_outlook': build_scheduled_outlook({}, {}, evaluated_at=CLOCK+3600)}
    prior = {k: SOURCE[k] for k in ('source_repository', 'source_commit', 'run_id')}
    previous = {'history': [pack_generation(saved['scheduled_outlook']['rows'], evaluated_at=CLOCK)],
                'provenance': {str(CLOCK): prior}}
    return bundle, build_followup(previous, current, {**prior, 'run_id': 124})


def review(bundle, followup):
    return review_calendar_price_windows(bundle, SOURCE, bundle['snapshot_git_blob_sha'], followup)


class CalendarPriceWindowTests(unittest.TestCase):
    def test_exact_closed_bar_windows_deduplicate_strategies_and_preserve_inputs(self):
        bundle, followup = inputs(overlap=True); original = deepcopy((bundle, followup))
        result = review(bundle, followup)
        cases = [c for c in result['cases'] if c['pair'] == 'EURUSD' and c['event_id'] == 'synthetic-event']
        self.assertEqual(len(cases), 3)
        for case, expected in zip(cases[:2], (1, 3)):
            self.assertEqual(case['observation']['status'], 'saved_price_observation')
            self.assertAlmostEqual(case['observation']['pair_quote_change']/.0001, expected)
            self.assertEqual(case['overlapping_scheduled_event_ids'], ['synthetic-overlap'])
            self.assertFalse(case['release_time_verified'])
            self.assertEqual(case['causal_attribution'], 'unassessed')
        self.assertEqual(cases[2]['observation']['reason'], 'horizon_not_yet_saved')
        self.assertEqual((bundle, followup), original)

    def test_gap_and_unknown_source_cannot_be_filled_or_given_measured_counts(self):
        for options, reason in (({'gap': True}, 'missing_baseline_endpoint_or_internal_bar'),
                                ({'unknown': True}, 'saved_source_unverified_or_unavailable')):
            result = review(*inputs(**options))
            case = next(c for c in result['cases'] if c['pair'] == 'EURUSD' and c['horizon_seconds'] == 900)
            self.assertEqual(case['observation'], dict(status='unavailable', reason=reason))

    def test_uncertain_cancelled_or_nonrelease_instants_are_not_reinterpreted(self):
        for changes, reason in (({'scheduled_at_utc': None}, 'scheduled_instant_unconfirmed'),
                                ({'observed_at_utc': CLOCK+1}, 'event_observation_clock_invalid'),
                                ({'provider_status': 'cancelled'}, 'cancelled_estimated_or_stale_event'),
                                ({'time_role': 'auction-close'}, 'non_release_or_unknown_time_role')):
            result = review(*inputs(event_changes=changes))
            self.assertEqual(result['measurable_window_count'], 0)
            self.assertIn(reason, result['unavailable_reason_counts'])

    def test_wrong_generation_and_invalid_horizons_are_rejected(self):
        bundle, followup = inputs(); followup['previous_source']['run_id'] = 999
        with self.assertRaises(ValueError):
            review(bundle, followup)
        for horizons in ((True,), (60,), (300, 300), (), [300]):
            with self.assertRaises(ValueError):
                review_calendar_price_windows(bundle, SOURCE, bundle['snapshot_git_blob_sha'], followup,
                                              horizons=horizons)
