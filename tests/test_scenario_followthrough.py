"""Synthetic frozen-condition chronology, coverage and price-plan regressions."""
from copy import deepcopy
import unittest
from fx_system.scenario_followthrough import observe_frozen_condition
from test_scenario_conditions import sample, compute, CLOCK


def saved(tf='m5', direction='long', phase='pullback_wait'):
    bars, r = sample(tf, direction, phase)
    bars[-1]['open'] = bars[-1]['close']
    r.update(pair='EURUSD', strategy='swing' if tf == 'm15' else 'daytrade', grade='B')
    r['scenario_conditions'] = compute(bars, r)
    return r


def feed(bars, hourly=()):
    return {'decision_data': {'raw': {'m5': bars, 'h1': list(hourly)},
        'provenance': {f'{tf}:{b["timestamp"]}': 'Twelve Data'
                       for tf, rows in [('m5', bars), ('h1', hourly)] for b in rows}}}


def bar(i, o=100, h=102, l=98, c=100, seconds=300):
    return {'timestamp': CLOCK+i*seconds, 'open': o, 'high': h, 'low': l, 'close': c}


class FrozenFollowthroughTests(unittest.TestCase):
    def test_fixed_waiting_level_and_actual_confirmation_close_margin(self):
        r = saved(); data = feed([bar(0, c=100), bar(1, o=99, c=100)])
        before = deepcopy((r, data))
        out = observe_frozen_condition(r, data, CLOCK+600)
        self.assertEqual(out['status'], 'frozen_condition_observed')
        self.assertEqual(out['original_level'], 99)
        observed = out['condition_observation']
        self.assertEqual(observed['closed_at'], CLOCK+600)
        self.assertEqual(observed['reference_rr'], 1)
        self.assertFalse(observed['margin_sufficient_before_costs'])
        self.assertFalse(observed['is_entry_or_fill'])
        self.assertEqual((r, data), before)

    def test_short_rejection_and_sufficient_margin(self):
        r = saved(direction='short')
        out = observe_frozen_condition(r, feed([bar(0, o=102, h=103, l=98, c=101)]), CLOCK+300)
        self.assertEqual(out['status'], 'frozen_condition_observed')
        self.assertGreater(out['condition_observation']['reference_rr'], 1)

    def test_swing_requires_three_complete_m5_not_a_single_wick(self):
        r = saved(tf='m15')
        bars = [bar(i, o=99, h=101, l=98, c=100) for i in range(3)]
        self.assertEqual(observe_frozen_condition(r, feed(bars), CLOCK+600)['status'],
                         'awaiting_whole_future_candles')
        out = observe_frozen_condition(r, feed(bars), CLOCK+900)
        self.assertEqual(out['condition_observation']['closed_at'], CLOCK+900)
        self.assertEqual(out['whole_confirmation_candle_count'], 1)

    def test_partial_publication_candle_is_excluded_even_if_condition_matches(self):
        r = saved(); r['evaluated_at'] += 2
        r['scenario_conditions']['evaluated_at'] += 2
        bars = [bar(0, o=99, c=100), bar(1, o=100, c=100)]
        out = observe_frozen_condition(r, feed(bars), CLOCK+600)
        self.assertEqual(out['status'], 'frozen_condition_not_seen_in_whole_candles')
        self.assertEqual(out['excluded_initial_m5_seconds'], 298)

    def test_missing_unknown_duplicate_and_malformed_bars_cannot_confirm(self):
        r = saved(); bars = [bar(0), bar(1, o=99, c=100)]
        for data, status in [(feed(bars[1:]), 'incomplete_saved_candles'),
                             (feed(bars+bars[-1:]), 'followup_input_invalid')]:
            self.assertEqual(observe_frozen_condition(r, data, CLOCK+600)['status'], status)
        data = feed(bars); data['decision_data']['provenance']['m5:'+str(CLOCK)] = 'unknown'
        self.assertEqual(observe_frozen_condition(r, data, CLOCK+600)['status'], 'incomplete_saved_candles')
        data = feed(bars); data['decision_data']['raw']['m5'][0]['high'] = 1
        self.assertEqual(observe_frozen_condition(r, data, CLOCK+600)['status'], 'followup_input_invalid')

    def test_breakout_and_retest_must_be_separate_and_failed_retest_is_preserved(self):
        r = saved(phase='transition_context')
        bars = [bar(0, o=100, h=104, l=99, c=103), bar(1, o=103, h=104, l=102, c=103)]
        self.assertEqual(observe_frozen_condition(r, feed(bars[:1]), CLOCK+300)['status'],
                         'frozen_condition_not_seen_in_whole_candles')
        self.assertEqual(observe_frozen_condition(r, feed(bars), CLOCK+600)['status'], 'frozen_condition_observed')
        bars[1]['close'] = 102
        self.assertEqual(observe_frozen_condition(r, feed(bars), CLOCK+600)['status'], 'frozen_retest_failed')

    def test_saved_breakout_can_be_retested_after_publication(self):
        bars, r = sample(phase='transition_context'); bars[-1].update(high=104, close=103)
        r.update(pair='EURUSD', strategy='daytrade', grade='B'); r['scenario_conditions'] = compute(bars, r)
        out = observe_frozen_condition(r, feed([bar(0, o=103, h=104, l=102, c=103)]), CLOCK+300)
        self.assertEqual(out['status'], 'frozen_condition_observed')

    def test_target_wick_is_not_withdrawal_but_trigger_close_is(self):
        r = saved()
        out = observe_frozen_condition(r, feed([bar(0, h=112, l=99, c=100)]), CLOCK+300)
        self.assertIsNotNone(out['target_touch'])
        self.assertIsNone(out['trigger_close_withdrawal'])
        bars = [bar(0, o=100, h=112, l=99, c=111), bar(1, o=98, h=101, l=97, c=100)]
        out = observe_frozen_condition(r, feed(bars), CLOCK+600)
        self.assertEqual(out['status'], 'close_based_withdrawal_observed')
        self.assertIsNone(out['condition_observation'])

    def test_primary_h1_close_not_resampled_m5_determines_base_withdrawal(self):
        r = saved(); bars = [bar(i) for i in range(13)]
        bars[-1].update(open=99, close=100)
        # Intentionally different synthetic primary H1/M5 quotes.
        hourly = [bar(0, o=100, h=112, l=99, c=111, seconds=3600)]
        out = observe_frozen_condition(r, feed(bars, hourly), CLOCK+3900)
        self.assertEqual(out['base_close_withdrawal']['closed_at'], CLOCK+3600)
        self.assertIsNone(out['condition_observation'])
        self.assertTrue(out['base_close_coverage_complete'])
        out = observe_frozen_condition(r, feed(bars), CLOCK+3900)
        self.assertFalse(out['base_close_coverage_complete'])
        self.assertEqual(out['status'], 'frozen_condition_observed')
        self.assertFalse(out['condition_observation']['base_close_coverage_complete'])

    def test_already_observed_skip_and_missing_plan_are_not_new_signals(self):
        r = saved(); data = feed([bar(0, o=99, c=100)])
        r['assessment'] = 'skip'
        self.assertEqual(observe_frozen_condition(r, data, CLOCK+300)['status'], 'not_monitorable_at_save')
        r = saved(); r['reference_levels'].pop('structural_target')
        self.assertNotEqual(observe_frozen_condition(r, data, CLOCK+300)['status'], 'frozen_condition_observed')

    def test_observation_before_later_withdrawal_is_retained_without_calling_it_profit(self):
        r = saved()
        bars = [bar(0, o=98, h=101, l=97, c=99.5), bar(1, o=100, h=111, l=99, c=110)]
        out = observe_frozen_condition(r, feed(bars), CLOCK+600)
        self.assertEqual(out['condition_observation']['closed_at'], CLOCK+300)
        self.assertEqual(out['trigger_close_withdrawal']['closed_at'], CLOCK+600)
        self.assertTrue(out['condition_observation']['margin_sufficient_before_costs'])
        self.assertEqual(out['trade_performance'], 'not_measured')

    def test_already_observed_at_save_is_not_counted_as_new_and_bad_evidence_is_rejected(self):
        bars, r = sample(phase='pullback_wait')
        r.update(pair='EURUSD',strategy='daytrade',grade='B');r['scenario_conditions']=compute(bars,r)
        data=feed([bar(0,o=99,c=100)])
        out=observe_frozen_condition(r,data,CLOCK+300)
        self.assertEqual(out['status'],'already_observed_at_save')
        self.assertIsNone(out['condition_observation'])
        r['scenario_conditions']['observed_close']=1
        self.assertEqual(observe_frozen_condition(r,data,CLOCK+300)['status'],'saved_condition_unverified')


if __name__ == '__main__':
    unittest.main()
