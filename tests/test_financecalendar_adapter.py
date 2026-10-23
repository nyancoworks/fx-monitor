"""Synthetic documentation-contract tests; no API, captured responses or prices."""
from copy import deepcopy
from datetime import datetime, timezone
import json
import unittest
from unittest.mock import patch
from fx_system.financecalendar_adapter import normalize_calendar
from fx_system.economic_calendar_context import enrich_outlook
from fx_system.economic_calendar_report import calendar_lines
from fx_system.strategy_report import _clock
from test_economic_calendar_context import outlook

CLOCK = 1000000


def iso(stamp):
    return datetime.fromtimestamp(stamp, timezone.utc).isoformat()


def event(**updates):
    row = {'id': 'synthetic-only', 'country': 'US', 'category': 'economic-indicators',
           'status': 'confirmed', 'title': 'Synthetic release', 'time_precision': 'minute',
           'release_at_utc': iso(CLOCK+3600), 'date': iso(CLOCK+3600)[:10],
           'updated_at': iso(CLOCK-100), 'actual': '0', 'prior': '2%', 'consensus': None,
           'source_name': 'Synthetic publisher', 'source_url': 'https://example.com/synthetic'}
    row.update(updates)
    return row


def page(*rows, **updates):
    value = {'events': list(rows), 'count': len(rows), 'total': len(rows),
             'attribution': {'source': 'financecalendar.com', 'terms': 'Synthetic attribution fixture'}}
    value.update(updates)
    return value


def normalize(payload):
    return normalize_calendar(payload, observed_at_utc=CLOCK)


def context(payload):
    return enrich_outlook(outlook(), normalize(payload))['strategy_assessments'][0]['economic_calendar_context']


class AdapterTests(unittest.TestCase):
    def test_offline_projection_input_immutable_and_future_actual_hidden(self):
        source = page(event(api_key='SYNTHETIC_DO_NOT_COPY', observations=[{'actual': 'secret-like-test'}]))
        before = deepcopy(source)
        with patch('socket.socket', side_effect=AssertionError('network prohibited')):
            normalized = normalize(source)
        self.assertEqual(source, before)
        row = normalized['events'][0]
        self.assertEqual(row['currency'], 'USD')
        self.assertIsNone(row['actual_raw'])
        self.assertNotIn('observations', row)
        self.assertNotIn('api_key', row)
        self.assertFalse(normalized['complete'])
        self.assertTrue(normalized['page_complete'])
        self.assertEqual(json.loads(json.dumps(normalized, allow_nan=False)), normalized)

    def test_source_verification_is_not_acquisition_or_build_freshness(self):
        normalized = normalize(page(event(last_verified_at=iso(CLOCK-86400), data_stale=False),
                                    generated_at=iso(CLOCK)))
        row = normalized['events'][0]
        self.assertEqual(row['source_verification_age_seconds'], 86400)
        self.assertEqual(row['freshness'], 'unverified')
        self.assertEqual(normalize(page(event(data_stale=True)))['events'][0]['freshness'], 'stale')
        row = normalize(page(event()))['events'][0]
        self.assertIsNone(row['last_verified_at_utc'])
        self.assertEqual(row['freshness'], 'unverified')

    def test_future_metadata_does_not_enter_saved_view(self):
        for field in ('updated_at', 'last_verified_at', 'manually_reviewed_at'):
            normalized = normalize(page(event(**{field: iso(CLOCK+1)})))
            self.assertEqual(normalized['events'], [])
            self.assertEqual(normalized['omitted_count'], 1)

    def test_zero_actual_string_is_not_missing_and_numeric_values_not_inferred(self):
        row = normalize(page(event(release_at_utc=iso(CLOCK-1), status='released')))['events'][0]
        self.assertEqual(row['actual_raw'], '0')
        self.assertIsNone(row['actual'])
        self.assertIsNone(row['surprise'])
        self.assertIsNone(row['consensus_raw'])
        self.assertEqual(row['prior_raw'], '2%')
        row = normalize(page(event(release_at_utc=iso(CLOCK-1), actual=None, status='released')))['events'][0]
        self.assertIsNone(row['actual_raw'])
        row = normalize(page(event(release_at_utc=iso(CLOCK-1), actual=float('nan'))))['events'][0]
        self.assertIsNone(row['actual_raw'])
        json.dumps(row, allow_nan=False)

    def test_estimated_cancelled_and_stale_results_are_not_claimed_actuals(self):
        for changes in ({'status':'estimated'}, {'status':'cancelled'}, {'observation_status':'stale'}):
            row = normalize(page(event(release_at_utc=iso(CLOCK-1), **changes)))['events'][0]
            self.assertIsNone(row['actual_raw'])

    def test_date_only_is_in_context_without_midnight_or_actual(self):
        item = context(page(event(release_at_utc=None, time_precision='date')))['events'][0]
        self.assertIsNone(item['scheduled_at_utc'])
        self.assertIsNone(item['actual_raw'])
        self.assertEqual(item['timing'], 'uncertain')
        lines = '\n'.join(calendar_lines({'economic_calendar_context': context(page(event(release_at_utc=None, time_precision='date')))}, _clock))
        self.assertIn('JST換算未確定', lines)
        self.assertIn('時刻', lines)

    def test_range_bound_is_not_exact_release(self):
        row = event(time_precision='range', time_window_start=iso(CLOCK+10), time_window_end=iso(CLOCK+20))
        item = context(page(row))['events'][0]
        self.assertIsNone(item['scheduled_at_utc'])
        self.assertEqual(item['time_window_start_utc'], CLOCK+10)
        lines = '\n'.join(calendar_lines({'economic_calendar_context': context(page(row))}, _clock))
        self.assertIn('正確な時刻未確定', lines)

    def test_month_window_retains_interval_not_lower_index_as_occurrence(self):
        row = event(time_precision='month', date_window_start='1970-01-01', date_window_end='1970-01-31')
        item = context(page(row))['events'][0]
        self.assertIsNone(item['scheduled_at_utc'])
        self.assertEqual(item['date_window_end'], '1970-01-31')
        self.assertIn('日付範囲', '\n'.join(calendar_lines({'economic_calendar_context':context(page(row))},_clock)))

    def test_unknown_and_far_away_dates(self):
        self.assertEqual(context(page(event(release_at_utc=None, date='2099-01-01', time_precision='date')))['events'], [])
        self.assertEqual(len(context(page(event(release_at_utc=None, date=None, time_precision='unknown')))['events']), 1)

    def test_naive_conflicting_and_impossible_instants_not_exact(self):
        for updates in ({'release_at_utc':'1970-01-12T00:00:00'},
                        {'time_utc':iso(CLOCK+7200)}, {'release_at_utc':'not-a-time'},
                        {'release_at_utc':iso(CLOCK+3600), 'all_day':True}):
            item = normalize(page(event(**updates)))['events'][0]
            self.assertIsNone(item['scheduled_at_utc'])
        # UTC offsets represent instants; never replace the timezone with UTC.
        row = event(release_at_utc=datetime.fromtimestamp(CLOCK+3600, timezone.utc).isoformat())
        self.assertEqual(normalize(page(row))['events'][0]['scheduled_at_utc'], CLOCK+3600)

    def test_country_scope_filters_holidays_crypto_unknown_and_duplicate_ids(self):
        for updates in ({'country':'CN'}, {'country':None}, {'country':[]},
                        {'category':'market-holidays'}, {'category':'crypto'}, {'status':[]}):
            self.assertEqual(normalize(page(event(**updates)))['events'], [])
        for country, currency in (('EU','EUR'), ('DE','EUR'), ('NZ','NZD'), ('CH','CHF')):
            self.assertEqual(normalize(page(event(country=country)))['events'][0]['currency'], currency)
        duplicate = normalize(page(event(), event(status='cancelled')))
        self.assertEqual(duplicate['events'], [])
        self.assertEqual(duplicate['omitted_count'], 2)

    def test_empty_truncated_and_invalid_pages_never_claim_comprehensive_coverage(self):
        for payload in (None, [], {'error':'synthetic'}, page(), page(event(), total=2), page(event(), count=True)):
            result = normalize(payload)
            self.assertFalse(result['complete'])
            self.assertEqual(result['coverage'], 'unverified')
        self.assertFalse(normalize(page(event(), total=2))['page_complete'])
        self.assertTrue(normalize(page())['page_complete'])
        with self.assertRaises(ValueError):
            normalize_calendar(page(), observed_at_utc=True)

    def test_credit_rights_and_full_notice_preserved_but_unknown_fields_not_copied(self):
        license = {'id':'synthetic', 'url':'https://example.com/license', 'attribution':'Synthetic credit',
                   'attribution_url':'https://example.com/credit', 'notice':'Full synthetic notice', 'adapted':True}
        rights = {'basis':'synthetic', 'attribution':'Synthetic factual source',
                  'source_url':'https://example.com/evidence', 'notice':'Synthetic rights notice'}
        ctx = context(page(event(source_license=license, source_rights=rights)))
        item = ctx['events'][0]
        self.assertEqual(item['source_license'], license)
        self.assertEqual(item['source_rights'], rights)
        self.assertEqual(ctx['attribution']['source'], 'financecalendar.com')
        lines = '\n'.join(calendar_lines({'economic_calendar_context':ctx}, _clock))
        for value in ('Full synthetic notice', 'Synthetic factual source', 'https://example.com/credit',
                      'https://example.com/synthetic', 'financecalendar.com', '鮮度・網羅性は未検証'):
            self.assertIn(value, lines)

    def test_future_numeric_vintage_is_hidden_and_observation_credit_is_preserved(self):
        for field in ('known_at', 'first_seen_at', 'source_updated_at'):
            row = event(release_at_utc=iso(CLOCK-1), observations=[
                {'role':'actual', field:iso(CLOCK+1)}])
            self.assertIsNone(normalize(page(row))['events'][0]['actual_raw'])
        credit = {'spdx':'CC0-1.0', 'url':'https://example.com/license',
                  'attribution':'Synthetic observation credit', 'vintage_notice':'Synthetic current vintage'}
        row = event(release_at_utc=iso(CLOCK-1), observations=[
            {'role':'actual', 'known_at':iso(CLOCK), 'source_license':credit}])
        ctx = context(page(row))
        self.assertEqual(ctx['events'][0]['observation_credits'][0]['source_license'], credit)
        self.assertIn('Synthetic current vintage', '\n'.join(calendar_lines({'economic_calendar_context':ctx}, _clock)))

    def test_non_utc_offset_and_second_precision_retain_exact_instant(self):
        row = event(release_at_utc='1970-01-12T23:46:41+09:00', time_precision='second')
        expected = int(datetime.fromisoformat(row['release_at_utc']).timestamp())
        self.assertEqual(normalize(page(row))['events'][0]['scheduled_at_utc'], expected)
