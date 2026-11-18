import unittest
from copy import deepcopy
from unittest.mock import patch
from fx_system.standard_technicals import frame, refresh
from fx_system.murphy_timing_context import describe
from fx_system.span_special import observe
from fx_system.technical_entry import describe as conditions
from test_technical_entry import record


def bars(prices, seconds=300):
    return [dict(timestamp=i*seconds, open=p, high=p+1, low=p-1, close=p)
            for i,p in enumerate(prices)]


class MurphyTimingContextTests(unittest.TestCase):
    def test_reference_span_calculation_and_lag_location(self):
        data = bars(list(range(100, 200)))
        obs = observe(data, 'm5')
        # Last 9 midpoint = 195, last 26 midpoint = 186.5.
        self.assertEqual(obs['last']['blue'], 190.75)
        self.assertEqual(obs['last']['red'], 173.5)
        self.assertEqual(obs['lag_intervals'], 26)
        # Isolate the old candle used by the explicit index-26 convention.
        data[73].update(high=201, low=197, open=199, close=199)
        data[74].update(high=211, low=209, open=210, close=210)
        self.assertEqual(observe(data, 'm5')['last']['lag_candle'], 'inside')

    def test_both_directions_have_sb_and_all_span_components(self):
        for sign, direction in ((1, 'long'), (-1, 'short')):
            data = bars([200+sign*i for i in range(90)])
            f = frame(data, 'm5', 90*300, True)
            result = describe(f, direction)
            self.assertEqual(result['observations']['sb_movement'], direction)
            self.assertEqual(result['opposing_components'], [])
            self.assertIn('遅行', result['summary'])
            opposite = describe(f, 'short' if sign == 1 else 'long')
            for name in ('sb_movement','blue_position','lag_candle','lag_zone','red_slope'):
                self.assertIn(name, opposite['opposing_components'])

    def test_partial_span_does_not_block_verified_sb(self):
        f = frame(bars(list(range(100, 140))), 'm5', 40*300, True)
        result = describe(f, 'long')
        self.assertEqual(result['observations']['sb_movement'], 'long')
        self.assertEqual(result['observations']['span_model']['status'], 'unavailable')
        self.assertIn('スパン未確認', result['summary'])
        partial = describe(frame(bars(list(range(100,160))), 'm5', 60*300, True), 'long')
        self.assertIn('lag_zone', partial['unavailable_components'])
        self.assertIn('遅行と雲は未確認', partial['concise_summary'])

    def test_local_oscillator_event_is_not_total_confirmation(self):
        r = record()
        with patch('fx_system.technical_entry.timing_signals', return_value=['rci9_extreme_recovery']):
            result = conditions(r)
        self.assertEqual(result['status'], 'conditions_observed')
        self.assertIn('murphy_context', result['evidence'])
        self.assertIn('シナリオ全体の成立ではない', result['summary'])
        self.assertIsNone(result['formation_price'])

    def test_old_records_restore_without_new_evidence(self):
        r = record()
        old = deepcopy(r); old.pop('murphy_timing_context_version'); refresh(old)
        self.assertNotIn('murphy_context', old['scenario_conditions'].get('evidence', {}))
        self.assertEqual(refresh(deepcopy(old)), old)
        for key in ('direction','grade','assessment','reference_levels'):
            self.assertEqual(r[key], old[key])
        r['murphy_timing_context_version'] = True
        with self.assertRaises(ValueError):
            refresh(r)
