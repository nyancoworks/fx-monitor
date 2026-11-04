"""Synthetic MT4 NY-close convention and MACD signal compatibility checks."""
import math
import unittest
from datetime import datetime
from fx_system.mt4_calendar import aggregate_h4, expected_h4, h4_start
from fx_system.standard_technicals import macd, frame


def stamp(value):
    return int(datetime.fromisoformat(value).timestamp())


class MT4ProfileTests(unittest.TestCase):
    def test_quality_expects_same_complete_h4_as_aggregation(self):
        from fx_system.data_quality import evaluate_data
        from fx_system.provenance import key
        now=stamp('2026-11-04T22:29:00+09:00')
        last=now//3600*3600-3600
        rows=[dict(timestamp=last-i*3600,open=10,high=11,low=9,close=10)
              for i in reversed(range(100))]
        frames,quality=evaluate_data({'h1':rows,'m5':[],'d1':[]},
            {key('h1',r['timestamp']):'Twelve Data' for r in rows},now)
        expected=stamp('2026-11-04T15:00:00+09:00')
        self.assertEqual(frames['h4'][-1]['timestamp'],expected)
        self.assertEqual(quality['closed_candle_freshness']['h4']['expected_last_closed'],expected)
        self.assertTrue(quality['closed_candle_freshness']['h4']['latest_closed_present'])

    def test_winter_summer_and_dst_weeks_use_ny_close_server_grid(self):
        for now,start,end in (
            ('2026-11-04T22:29:00+09:00','2026-11-04T19:00:00+09:00','2026-11-04T23:00:00+09:00'),
            ('2026-07-08T21:29:00+09:00','2026-07-08T18:00:00+09:00','2026-07-08T22:00:00+09:00'),
            ('2026-10-30T21:29:00+09:00','2026-10-30T18:00:00+09:00','2026-10-30T22:00:00+09:00'),
            ('2026-03-09T21:29:00+09:00','2026-03-09T18:00:00+09:00','2026-03-09T22:00:00+09:00')):
            self.assertEqual(h4_start(stamp(now)),stamp(start))
            self.assertEqual(expected_h4(stamp(now)),stamp(start)-14400)
            self.assertEqual(expected_h4(stamp(end)),stamp(start))

    def test_only_four_observed_h1_bars_form_a_candle(self):
        start=stamp('2026-11-04T15:00:00+09:00')
        rows=[dict(timestamp=start+i*3600,open=10+i,high=11+i,low=9+i,close=10.5+i)
              for i in range(4)]
        self.assertEqual(aggregate_h4(rows),[dict(timestamp=start,open=10,high=14,low=9,close=13.5)])
        self.assertEqual(aggregate_h4(rows[:-1]),[])
        self.assertEqual(aggregate_h4(rows[1:]),[])
        with self.assertRaises(ValueError):aggregate_h4(rows+[rows[0]])

    def test_saved_frame_versions_recalculate_independently(self):
        start=stamp('2026-11-01T00:00:00+00:00')
        rows=[dict(timestamp=start+i*3600,open=100,high=102,low=98,close=100+math.sin(i*.3))
              for i in range(100)]
        old=frame(rows,'h1',start+100*3600,True)
        new=frame(rows,'h1',start+100*3600,True,calculation_version=2)
        self.assertNotIn('calculation_version',old)
        self.assertEqual(new['calculation_version'],2)
        self.assertEqual(old['rci'],new['rci'])
        self.assertEqual(old['sma'],new['sma'])
        self.assertEqual(old['macd'],new['macd'])
        with self.assertRaises(ValueError):frame(rows,'h1',start,True,calculation_version=True)
