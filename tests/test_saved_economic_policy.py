"""Synthetic official-document references; no live rates or network calls."""
from copy import deepcopy
from datetime import datetime, timezone, timedelta
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fx_system.saved_economic_policy import load_saved_policy, normalize_policy_reference, policy_lines, RELATIVE_PATH
from fx_system.saved_economic_calendar import configured_calendar
from fx_system.strategy_report_export import build_strategy_report_export, restore_strategy_report_export
from diagnostics.monitoring_result_history import pack_generation, restore_generation
import test_economic_calendar_integration as integration
from test_range_scenario import CLOCK


def fact(**changes):
    day = datetime.fromtimestamp(CLOCK-86400, timezone.utc).date().isoformat()
    result = dict(currency='USD', instrument='Synthetic target range', rate_text='1.00–1.25%',
                  decision='held', published_date=day, effective_date=day, observed_at_utc=CLOCK-1,
                  source_name='Synthetic official document',
                  source_url='https://www.federalreserve.gov/synthetic-policy-document.htm',
                  source_credit='Synthetic reference credit')
    result.update(changes)
    return result


def envelope(*facts):
    return dict(schema='saved_policy_reference_v1', facts=list(facts))


class SavedPolicyTests(unittest.TestCase):
    def test_unspecified_effective_date_and_change_direction_are_not_invented(self):
        reference = normalize_policy_reference(envelope(fact(effective_date=None, decision='changed')),
                                                evaluated_at=CLOCK)
        self.assertIsNone(reference['facts'][0]['effective_date'])
        text = '\n'.join(policy_lines(reference, ('USD',), str))
        self.assertIn('資料の適用日 資料に明記なし', text)
        self.assertIn('（変更・方向は未評価）', text)
        missing = fact(); missing.pop('effective_date')
        self.assertEqual(normalize_policy_reference(envelope(missing), evaluated_at=CLOCK)['facts'], [])

    def test_malformed_policy_context_cannot_break_core_assessments(self):
        builder = integration.CalendarIntegrationTests()
        baseline = builder.build()
        for reference in ({'status': 'bad', 'facts': 'bad'},
                          {'status': 'saved_reference', 'facts': None, 'rejected_count': 'bad'}):
            outlook = builder.build(dict(events=[], observed_at_utc=CLOCK, complete=False,
                                         policy_reference=reference))
            for old, new in zip(baseline['strategy_assessments'], outlook['strategy_assessments']):
                stripped = deepcopy(new); context = stripped.pop('economic_calendar_context')
                self.assertEqual(stripped, old)
                self.assertEqual(context['policy_reference']['status'], 'unavailable')

    def test_clock_dates_and_exact_source_origin_reject_bad_or_future_evidence(self):
        tomorrow = (datetime.fromtimestamp(CLOCK, timezone.utc).date()+timedelta(days=1)).isoformat()
        cases = [dict(observed_at_utc=CLOCK+1), dict(observed_at_utc=True),
                 dict(published_date=tomorrow, effective_date=tomorrow),
                 dict(source_url='https://federalreserve.gov.evil.example/document'),
                 dict(source_url='https://www.federalreserve.gov@evil.example/document'),
                 dict(source_url='https://user:password@www.federalreserve.gov/document'),
                 dict(source_url='http://www.federalreserve.gov/document'),
                 dict(source_url='https://www.federalreserve.gov/document?secret=synthetic'),
                 dict(rate_text=''), dict(rate_text=1.25), dict(instrument='bad\nfield'),
                 dict(currency='XYZ'), dict(effective_date='bad'), dict(decision='hawkish')]
        for changes in cases:
            with self.subTest(changes=changes):
                self.assertEqual(normalize_policy_reference(envelope(fact(**changes)),
                                                            evaluated_at=CLOCK)['facts'], [])
        # Future implementation dates stay labelled dates, not current rates.
        value = normalize_policy_reference(envelope(fact(effective_date=tomorrow)), evaluated_at=CLOCK)
        self.assertEqual(value['facts'][0]['effective_date'], tomorrow)
        self.assertEqual(value['freshness'], 'unverified')
        self.assertFalse(value['complete'])

    def test_duplicate_documents_not_arbitrarily_selected_and_latest_known_is_dated(self):
        current = fact(); older = fact(published_date=(datetime.fromtimestamp(CLOCK-2*86400, timezone.utc).date().isoformat()))
        value = normalize_policy_reference(envelope(older, current), evaluated_at=CLOCK)
        self.assertEqual(value['facts'], [current])
        self.assertEqual(value['superseded_count'], 1)
        value = normalize_policy_reference(envelope(current, fact(rate_text='synthetic conflict')),
                                           evaluated_at=CLOCK)
        self.assertEqual(value['facts'], [])
        self.assertEqual(value['rejected_count'], 2)

    def test_private_input_bounds_and_unchanged_disabled_or_absent_path(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertIsNone(load_saved_policy(root, evaluated_at=CLOCK))
            target = Path(root)/RELATIVE_PATH; target.parent.mkdir(parents=True)
            target.write_text(json.dumps(envelope(fact())))
            self.assertEqual(load_saved_policy(root, evaluated_at=CLOCK)['status'], 'saved_reference')
            with patch.dict(os.environ, {'FX_DATA_ROOT': root, 'FX_ECONOMIC_CALENDAR_SAVED_ENABLED': 'false'}):
                self.assertIsNone(configured_calendar(evaluated_at=CLOCK))
            with patch.dict(os.environ, {'FX_DATA_ROOT': root, 'FX_ECONOMIC_CALENDAR_SAVED_ENABLED': 'true'}):
                # Calendar missing is not a reason to discard separate policy facts.
                self.assertEqual(configured_calendar(evaluated_at=CLOCK)['policy_reference']['facts'], [fact()])
            target.write_text('x'*65537)
            self.assertEqual(load_saved_policy(root, evaluated_at=CLOCK)['reason'], 'oversized_policy_input')
            target.unlink(); target.symlink_to(Path(root)/'absent')
            self.assertEqual(load_saved_policy(root, evaluated_at=CLOCK)['reason'], 'invalid_policy_input')

    def test_32_decisions_history_export_and_missing_currency_remain_honest(self):
        reference = normalize_policy_reference(envelope(fact(), fact(
            currency='EUR', effective_date=None, decision='changed',
            source_url='https://www.ecb.europa.eu/synthetic-policy-document.html')),
            evaluated_at=CLOCK)
        calendar = dict(events=[], observed_at_utc=CLOCK, complete=False, policy_reference=reference)
        original = deepcopy(calendar)
        builder = integration.CalendarIntegrationTests()
        baseline, outlook = builder.build(), builder.build(calendar)
        for old, new in zip(baseline['strategy_assessments'], outlook['strategy_assessments']):
            stripped = deepcopy(new); stripped.pop('economic_calendar_context')
            self.assertEqual(old, stripped)
            policy = new['economic_calendar_context']['policy_reference']
            self.assertTrue(all(f['currency'] in (new['pair'][:3], new['pair'][3:]) for f in policy['facts']))
        self.assertEqual(calendar, original)
        self.assertEqual(restore_generation(pack_generation(outlook['rows'], evaluated_at=CLOCK))['rows'], outlook['rows'])
        snapshot = dict(evaluated_at=CLOCK, scheduled_outlook=outlook)
        source = dict(source_repository='nyancoworks/fx-monitor', source_commit='a'*40, run_id=1, evaluated_at=CLOCK)
        bundle = build_strategy_report_export(json.dumps(snapshot).encode(), source)
        self.assertEqual(bundle['status'], 'saved')
        restore_strategy_report_export(bundle, source, bundle['snapshot_git_blob_sha'])
        self.assertIn('Synthetic target range', bundle['report_text'])
        self.assertIn('Synthetic reference credit', bundle['report_text'])
        self.assertIn('資料の適用日 資料に明記なし', bundle['report_text'])
        self.assertIn('未収録（政策変更なしを意味しない）',
                      '\n'.join(policy_lines(reference, ('JPY',), str)))
        self.assertIn('最新性・適用済みかは未検証', bundle['report_text'])
