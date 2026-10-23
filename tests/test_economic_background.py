"""Synthetic calendar evidence and backward-compatible saved report rendering."""
from copy import deepcopy
import unittest

from fx_system.economic_background import summarize_background
from fx_system.strategy_report_export import build_strategy_report_export, restore_strategy_report_export
import test_economic_calendar_integration as integration
from test_range_scenario import CLOCK
import json


class EconomicBackgroundTests(unittest.TestCase):
    def test_policy_calendar_is_not_a_rate_or_policy_stance(self):
        events = [dict(currency='USD', category='central-banks-monetary-policy',
                       timing='upcoming', scheduled_at_utc=CLOCK+3600,
                       actual_raw='synthetic future value', consensus_raw=None),
                  dict(currency='USD', category='central-banks-monetary-policy',
                       timing='uncertain', provider_status='estimated'),
                  dict(currency='USD', category='economic-indicators',
                       timing='past_release_window', actual_raw='synthetic actual',
                       consensus_raw='synthetic forecast', prior_raw='synthetic prior'),
                  dict(currency='USD', category='central-banks-monetary-policy',
                       timing='upcoming', scheduled_at_utc=CLOCK+1, provider_status='cancelled')]
        original = deepcopy(events)
        result = summarize_background(events, ('USD', 'JPY'))
        usd, jpy = result['currencies']
        self.assertEqual(usd['policy']['next_scheduled_at_utc'], CLOCK+3600)
        self.assertEqual(usd['policy']['uncertain_count'], 1)
        self.assertEqual(usd['policy']['cancelled_count'], 1)
        self.assertEqual(usd['saved_values'], dict(actual=1, consensus=1, prior=1))
        self.assertEqual(usd['policy_rate'], 'unassessed')
        self.assertEqual(usd['policy_stance'], 'unassessed')
        self.assertEqual(jpy['policy']['event_count'], 0)
        self.assertEqual(events, original)

    def test_missing_stale_cancelled_and_blank_values_are_not_evidence(self):
        events = [dict(currency='USD', timing='past_release_window', actual_raw=' ', consensus_raw=None),
                  dict(currency='USD', timing='past_release_window', actual_raw='synthetic', freshness='stale'),
                  dict(currency='USD', timing='past_release_window', actual_raw='synthetic', provider_status='cancelled'),
                  dict(currency='USD', timing='uncertain', actual_raw='synthetic')]
        self.assertEqual(summarize_background(events, ('USD',))['currencies'][0]['saved_values'],
                         dict(actual=0, consensus=0, prior=0))

    def test_pipeline_round_trip_and_legacy_report(self):
        outlook = integration.CalendarIntegrationTests().build({
            'observed_at_utc': CLOCK, 'complete': False, 'events': [
                dict(currency='USD', category='central-banks-monetary-policy',
                     scheduled_at_utc=CLOCK+3600, observed_at_utc=CLOCK,
                     reference_only=True, title='Synthetic policy event')]})
        snapshot = dict(evaluated_at=CLOCK, scheduled_outlook=outlook)
        source = dict(source_repository='nyancoworks/fx-monitor', source_commit='a'*40,
                      run_id=1, evaluated_at=CLOCK)
        def export(value):
            bundle = build_strategy_report_export(json.dumps(value).encode(), source)
            self.assertEqual(bundle['status'], 'saved')
            restore_strategy_report_export(bundle, source, bundle['snapshot_git_blob_sha'])
            return bundle
        bundle = export(snapshot)
        self.assertIn('政策関連：次の予定', bundle['report_text'])
        self.assertIn('金利水準・政策方針・市場反応は未評価', bundle['report_text'])
        # Simulate a frozen pre-feature generation, including row copies.
        for record in outlook['strategy_assessments']:
            record['economic_calendar_context'].pop('background')
        for row in outlook['rows']:
            for record in row['strategy_assessments'].values():
                record['economic_calendar_context'].pop('background')
        legacy = export(snapshot)
        self.assertNotIn('経済背景（保存範囲）', legacy['report_text'])
        self.assertIn('経済指標は参考情報。市場反応未評価', legacy['report_text'])


if __name__ == '__main__':
    unittest.main()
