"""A later validation boundary must not change the saved evaluation horizon."""
from copy import deepcopy
import unittest
from unittest.mock import patch
from fx_system.validate_snapshot import validate

CLOCK = 1800000240  # synthetic evaluation, 60 seconds before an M5 boundary


def fixture():
    return {'generated_at': CLOCK-240, 'evaluated_at': CLOCK,
            'pairs': {'EURUSD': {tf: {'candles': [
                {'timestamp': (CLOCK//seconds-1)*seconds-i*seconds}
                for i in reversed(range(12))]}
                for tf, seconds in [('m5',300),('h1',3600)]}},
            'quality': {'EURUSD': {'ok': True}}}


class ValidationClockTests(unittest.TestCase):
    def check(self, value, now):
        with patch('fx_system.validate_snapshot.PAIRS', ['EUR/USD']), patch(
                'fx_system.validate_snapshot.evaluate_pair', return_value=({}, {'reasons': []})) as evaluate:
            result = validate(value, now=now)
            if evaluate.called:
                self.assertEqual(evaluate.call_args.args[1], value.get('evaluated_at', now))
            return result

    def test_boundary_crossing_keeps_evaluation_horizon_and_input(self):
        value=fixture(); before=deepcopy(value)
        self.assertEqual(self.check(value, CLOCK+90), [])
        self.assertEqual(value, before)

    def test_actual_missing_evaluation_bar_still_fails(self):
        value=fixture(); value['pairs']['EURUSD']['m5']['candles'].pop()
        self.assertIn('EURUSD:m5 missing latest closed candle', self.check(value, CLOCK+90))

    def test_stale_snapshot_and_future_clock_still_fail(self):
        self.assertIn('snapshot older than 10 minutes', self.check(fixture(), CLOCK+601))
        value=fixture(); value['evaluated_at']=CLOCK+91
        self.assertIn('invalid snapshot evaluation clock', self.check(value, CLOCK+90))

    def test_backdated_clock_cannot_mask_missing_data(self):
        value=fixture(); value['evaluated_at']=value['generated_at']-1
        self.assertIn('invalid snapshot evaluation clock', self.check(value, CLOCK+90))

    def test_legacy_without_clock_uses_validation_time(self):
        value=fixture(); value.pop('evaluated_at')
        self.assertEqual(self.check(value, CLOCK), [])
        self.assertIn('EURUSD:m5 missing latest closed candle', self.check(value, CLOCK+90))
