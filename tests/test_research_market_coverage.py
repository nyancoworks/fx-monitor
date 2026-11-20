import datetime as dt
import unittest
from zoneinfo import ZoneInfo

from fx_system.research_followup import _advance_market_coverage

NY = ZoneInfo('America/New_York')


class TestMarketCoverage(unittest.TestCase):
    def test_friday_plan_separates_observed_hour_from_weekend_pause(self):
        start = int(dt.datetime(2026, 6, 5, 16, tzinfo=NY).timestamp())
        until = start + 24*3600
        anchor = {'strategy': 'daytrade', 'start_at': start, 'until': until}
        bars = [{'timestamp': start+i*300} for i in range(12)]
        record = {'standard_inputs': {'trigger': {'timeframe': 'm5', 'verified': True,
                                                   'bars': bars}}}
        _advance_market_coverage(anchor, record, start+3600)
        self.assertEqual(anchor['market_coverage']['open_observed'], 12)
        _advance_market_coverage(anchor, record, until)
        coverage = anchor['market_coverage']
        self.assertEqual(coverage['open_observed'], 12)
        self.assertEqual(coverage['open_missing'], 0)
        self.assertEqual(coverage['closed_empty'], 276)
        self.assertEqual(coverage['observed_trigger_hours'], 1)
        self.assertEqual(coverage['status'], 'calendar_window_interrupted_by_weekend')
        _advance_market_coverage(anchor, record, until)
        self.assertEqual(anchor['market_coverage'], coverage)

    def test_weekday_swing_full_window_is_observed(self):
        start = int(dt.datetime(2026, 6, 1, 9, tzinfo=NY).timestamp())
        until = start + 72*3600
        anchor = {'strategy': 'swing', 'start_at': start, 'until': until}
        record = {'standard_inputs': {'trigger': {'timeframe': 'm15', 'verified': True,
                                                   'bars': [{'timestamp': start+i*900}
                                                            for i in range(288)]}}}
        _advance_market_coverage(anchor, record, until)
        coverage = anchor['market_coverage']
        self.assertEqual(coverage['open_observed'], 288)
        self.assertEqual(coverage['closed_empty'], 0)
        self.assertEqual(coverage['observed_trigger_hours'], 72)
        self.assertEqual(coverage['status'], 'calendar_window_observed')

    def test_nominal_open_absence_is_not_called_market_closure(self):
        start = int(dt.datetime(2026, 6, 1, 9, tzinfo=NY).timestamp())
        anchor = {'strategy': 'daytrade', 'start_at': start, 'until': start+24*3600}
        record = {'standard_inputs': {'trigger': {'timeframe': 'm5', 'verified': True,
                                                   'bars': []}}}
        _advance_market_coverage(anchor, record, anchor['until'])
        self.assertEqual(anchor['market_coverage']['open_missing'], 288)
        self.assertEqual(anchor['market_coverage']['status'], 'unverified_open_hours')
