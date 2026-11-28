"""Verified NY17 history can extend live inputs without changing formal bars."""
from datetime import date, datetime, time, timedelta
import unittest
from zoneinfo import ZoneInfo

from fx_system.core import ny17_frames
from fx_system.indicator_calendar import NY17
from fx_system.indicator_inputs import contiguous_indicator_frames


class MacroIndicatorHistoryTest(unittest.TestCase):
    def test_archive_reuses_only_contiguous_exactly_overlapping_sessions(self):
        ny = ZoneInfo('America/New_York')
        first = date(2025, 9, 1)
        candles = []
        for offset in range(400):
            day = first + timedelta(days=offset)
            if day.weekday() >= 5:
                continue
            end = int(datetime.combine(day, time(17), ny).timestamp())
            candles.append({'trading_date_ny': day.isoformat(), 'session_start_utc': end - 86400,
                            'session_end_utc': end, 'h1_count': 24,
                            'ohlc': dict(open=1, high=2, low=1, close=2)})
        clock = candles[-1]['session_end_utc']
        frames = ny17_frames({'d1': candles[-60:], 'w1': []}, clock)
        quality = {'evaluated_at': clock, 'timeframes': {'d1': {'calendar': NY17, 'ok': True}}}
        for archived, expected in ((candles, 250), (candles[:-91] + candles[-90:], 90),
                                   (candles[:-1], 60)):
            with self.subTest(expected=expected):
                inputs, counts = contiguous_indicator_frames(
                    frames, quality, ny_study={'indicator_d1': archived})
                self.assertEqual(len(inputs['d1']), expected)
                self.assertEqual(counts['d1']['input_count'], expected)
                self.assertEqual(len(frames['d1']), 60)
