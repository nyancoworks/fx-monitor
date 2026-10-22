"""Exact production pipeline with synthetic candles and offline calendar only."""
from copy import deepcopy
import json
import unittest
from test_range_scenario import sample, CLOCK
from fx_system.scheduled_outlook import build_scheduled_outlook
from fx_system.validate_strategy_snapshot import validate_strategy_snapshot
from fx_system.strategy_report import render_strategy_report, _clock
from fx_system.economic_calendar_report import calendar_lines
from diagnostics.monitoring_result_history import pack_generation, restore_generation


class CalendarIntegrationTests(unittest.TestCase):
    def build(self, calendar=None):
        data, _ = sample()
        quality = {'timeframes': {'h1': {'ok': True, 'count': 20},
                                  'm5': {'ok': True, 'count': 5, 'age_minutes': 0}}}
        data['decision_quality'] = {**deepcopy(quality), 'evaluated_at': CLOCK}
        data['technical'] = {'h1': {'status': 'ok', 'structure': 'mixed'}}
        return build_scheduled_outlook({'EURUSD': data}, {'EURUSD': quality},
                                       evaluated_at=CLOCK, economic_calendar=calendar)

    def test_snapshot_json_history_and_report_preserve_32_assessments(self):
        baseline = self.build()
        calendar = {'observed_at_utc': CLOCK, 'complete': True,
                    'attribution_url': 'https://www.financecalendar.com', 'events': [
                        {'currency': 'USD', 'scheduled_at_utc': CLOCK + 3600,
                         'observed_at_utc': CLOCK, 'reference_only': True,
                         'title': 'Synthetic employment', 'actual': 99, 'actual_raw': '99'}]}
        original = deepcopy(calendar)
        enriched = self.build(calendar)
        snapshot = json.loads(json.dumps({'evaluated_at': CLOCK, 'scheduled_outlook': enriched}, allow_nan=False))
        self.assertEqual(validate_strategy_snapshot(snapshot), [])
        restored = restore_generation(pack_generation(enriched['rows'], evaluated_at=CLOCK))
        self.assertEqual(restored['rows'], enriched['rows'])
        report = render_strategy_report(snapshot)
        self.assertIn('Synthetic employment', report)
        self.assertIn('JST', report)
        self.assertIn('https://www.financecalendar.com', report)
        self.assertEqual(len(enriched['strategy_assessments']), 32)
        for old, new in zip(baseline['strategy_assessments'], enriched['strategy_assessments']):
            remaining = deepcopy(new)
            context = remaining.pop('economic_calendar_context')
            self.assertEqual(old, remaining)
            for event in context['events']:
                self.assertIsNone(event['actual'])
        self.assertEqual(calendar, original)

    def test_event_cannot_be_observed_after_its_container_snapshot(self):
        enriched = self.build({'observed_at_utc': CLOCK - 100, 'complete': True, 'events': [
            {'currency': 'USD', 'scheduled_at_utc': CLOCK - 50,
             'observed_at_utc': CLOCK, 'reference_only': True, 'actual': 99}]})
        for assessment in enriched['strategy_assessments']:
            self.assertEqual(assessment['economic_calendar_context']['events'], [])

    def test_malformed_calendar_does_not_change_core_decisions(self):
        baseline = self.build()
        for calendar in ([], False, 'bad', {'events': []}, {'observed_at_utc': CLOCK + 1, 'events': []}):
            actual = self.build(calendar)
            self.assertEqual(validate_strategy_snapshot({'evaluated_at': CLOCK, 'scheduled_outlook': actual}), [])
            for old, new in zip(baseline['strategy_assessments'], actual['strategy_assessments']):
                remaining = deepcopy(new)
                context = remaining.pop('economic_calendar_context')
                self.assertEqual(context['status'], 'unavailable')
                self.assertEqual(old, remaining)

    def test_unrepresentable_event_timestamp_cannot_break_report(self):
        lines = calendar_lines({'economic_calendar_context': {'status': 'available', 'events': [
            {'currency': 'USD', 'scheduled_at_utc': 10**100, 'title': 'Synthetic'}]}}, _clock)
        self.assertIn('保存形式未確認', '\n'.join(lines))
