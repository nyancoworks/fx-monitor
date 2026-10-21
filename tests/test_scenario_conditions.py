"""Synthetic prices only; no network, saved market observations or fills."""
from copy import deepcopy
import unittest

from fx_system.scenario_conditions import condition_inputs, describe_conditions, validate_conditions
from fx_system.strategy_scenario_assessment import assess_strategy


CLOCK = 1800000000  # divisible by both confirmation timeframes


def candle(index, o=100, h=102, l=99, c=101, seconds=300):
    return {'timestamp': CLOCK-(5-index)*seconds, 'open': o, 'high': h, 'low': l, 'close': c}


def sample(tf='m5', direction='long', phase='directional_structure_wait'):
    seconds = {'m5': 300, 'm15': 900}[tf]
    bars = [candle(i, seconds=seconds) for i in range(5)]
    t = {'base_timeframe': 'h1' if tf == 'm5' else 'h4', 'trigger_timeframe': tf,
         'base_verified': True, 'trigger_verified': True, 'direction': direction,
         'base_structure': 'HH_HL' if direction == 'long' else 'LH_LL',
         'reference_levels': {'invalidation': 90 if direction == 'long' else 110,
                              'structural_target': 110 if direction == 'long' else 90,
                              'reference_rr': 1},
         'reference_plan': {'reference_close': 100}, 'market_phase': phase,
         'assessment': 'review', 'evaluated_at': CLOCK, 'reference_timeframe': 'h1' if tf == 'm5' else 'h4',
         'expiry': {'status': 'reference_recheck', 'withdrawal_conditions': []}}
    return bars, t


def compute(bars, t):
    i = condition_inputs({t['trigger_timeframe']: {'candles': bars}}, t, CLOCK)
    return describe_conditions(t, i)


class ScenarioConditionsTests(unittest.TestCase):
    def test_continuation_is_numeric_and_waiting_not_undefined(self):
        bars, t = sample()
        r = compute(bars, t)
        self.assertEqual((r['route'], r['status'], r['level']), ('continuation_breakout', 'waiting', 102))
        self.assertIn('5分足終値', r['summary']); self.assertIn('102', r['summary'])
        self.assertLessEqual(r['anchor_closed_at'], bars[-1]['timestamp'])
        self.assertIsNone(r['formation_price']); self.assertIsNone(r['observed_at'])

    def test_breakout_close_only_not_wick_or_equality(self):
        for close, status in ((102, 'waiting'), (103, 'conditions_observed')):
            bars, t = sample(); bars[-1].update(high=104, close=close)
            r = compute(bars, t)
            self.assertEqual(r['status'], status)
            if status == 'conditions_observed':
                self.assertEqual((r['observed_at'], r['observed_close']), (CLOCK, 103))
                self.assertIsNone(r['formation_price'])

    def test_short_breakout_mirrors_long(self):
        bars, t = sample(direction='short'); bars[-1].update(low=97, close=98)
        r = compute(bars, t)
        self.assertEqual((r['level'], r['status']), (99, 'conditions_observed'))
        self.assertIn('下回る', r['summary'])

    def test_pullback_rejection_is_not_a_universal_breakout(self):
        bars, t = sample(phase='pullback_wait')
        bars[-1].update(open=99, low=98, close=100)
        r = compute(bars, t)
        self.assertEqual((r['route'], r['status'], r['level']), ('pullback_rejection', 'conditions_observed', 99))
        self.assertIn('始値より高く', r['summary'])
        bars[-1].update(open=101)
        self.assertEqual(compute(bars, t)['status'], 'waiting')

    def test_local_pullback_can_choose_rejection_for_swing(self):
        bars, t = sample(tf='m15')
        bars[-2].update(open=101, close=100)
        r = compute(bars, t)
        self.assertEqual(r['route'], 'pullback_rejection')
        self.assertIn('15分足', r['summary'])

    def test_short_pullback_rejection(self):
        bars, t = sample(direction='short', phase='pullback_wait')
        bars[-1].update(open=102, high=103, close=101)
        r = compute(bars, t)
        self.assertEqual((r['route'], r['status'], r['level']), ('pullback_rejection', 'conditions_observed', 102))

    def test_transition_does_not_treat_breakout_as_completed_retest(self):
        bars, t = sample(phase='transition_context'); bars[-1].update(high=104, close=103)
        r = compute(bars, t)
        self.assertEqual((r['route'], r['status']), ('breakout_retest', 'awaiting_retest'))
        self.assertIsNone(r['observed_at']); self.assertEqual(r['breakout_observed_at'], CLOCK)

    def test_later_retest_has_chronological_pre_breakout_anchor(self):
        bars, t = sample(phase='transition_context')
        bars[-2].update(high=104, close=103)
        bars[-1].update(open=103, high=104, low=102, close=103)
        r = compute(bars, t)
        self.assertEqual(r['status'], 'conditions_observed')
        self.assertEqual(r['anchor_closed_at'], CLOCK-600)
        self.assertEqual(r['breakout_observed_at'], CLOCK-300)
        self.assertEqual(r['observed_at'], CLOCK)
        bars[-1].update(close=102)
        self.assertEqual(compute(bars, t)['status'], 'retest_failed')

    def test_short_retest_is_symmetric(self):
        bars, t = sample(direction='short', phase='transition_context')
        bars[-2].update(low=97, close=98)
        bars[-1].update(open=98, low=97, high=99, close=98)
        self.assertEqual(compute(bars, t)['status'], 'conditions_observed')

    def test_unavailable_quality_keeps_a_specific_reason(self):
        bars, t = sample(); t['trigger_verified'] = False
        r = compute(bars, t)
        self.assertEqual(r['status'], 'unavailable'); self.assertIn('品質', r['reason'])
        self.assertEqual(r['conditions'], [])

    def test_bad_candle_windows_are_not_silently_repaired(self):
        bars, t = sample()
        mutations = [('timestamp', CLOCK), ('timestamp', CLOCK-150), ('close', float('nan')),
                     ('high', 1), ('open', True)]
        for key, value in mutations:
            with self.subTest(key=key, value=value):
                bad = deepcopy(bars); bad[-1][key] = value
                self.assertEqual(compute(bad, t)['status'], 'unavailable')
        bad = deepcopy(bars); bad[-2]['timestamp'] -= 300
        self.assertEqual(compute(bad, t)['status'], 'unavailable')

    def test_stale_missing_future_and_short_windows(self):
        bars, t = sample()
        for seconds in (-300, 300):
            changed = [{**b, 'timestamp': b['timestamp']+seconds} for b in bars]
            self.assertEqual(compute(changed, t)['status'], 'unavailable')
        self.assertEqual(compute(bars[-4:], t)['status'], 'unavailable')

    def test_gap_outside_used_window_does_not_block_conditions(self):
        bars, t = sample()
        bars.insert(0, candle(-3))
        self.assertEqual(compute(bars, t)['status'], 'waiting')

    def test_wrong_source_clock_or_direction_is_not_reused(self):
        bars, t = sample(); i = condition_inputs({'m5': {'candles': bars}}, t, CLOCK)
        for key, value in (('evaluated_at', CLOCK-300), ('direction', 'short'), ('closed_at', CLOCK-300)):
            bad = {**i, key: value}
            self.assertEqual(describe_conditions(t, bad)['status'], 'unavailable')

    def test_no_condition_beyond_target_and_no_projection_substitution(self):
        bars, t = sample(); t['reference_levels']['structural_target'] = 101.5
        r = compute(bars, t)
        self.assertEqual(r['status'], 'unavailable'); self.assertEqual(r['conditions'], [])
        t['reference_levels']['structural_target'] = None
        t['reference_projection'] = {'targets': [{'price': 120}]}
        self.assertEqual(compute(bars, t)['status'], 'unavailable')

    def test_withdrawn_pending_skip_and_unset_direction_do_not_form(self):
        bars, t = sample()
        for status in ('skip', 'evaluation_pending'):
            t['assessment'] = status
            self.assertEqual(compute(bars, t)['status'], 'not_applicable')
        t['assessment'] = 'review'; t['expiry']['status'] = 'withdrawn'
        self.assertEqual(compute(bars, t)['status'], 'withdrawn')
        t['expiry']['status'] = 'reference_recheck'; t['direction'] = None
        self.assertEqual(compute(bars, t)['status'], 'unavailable')

    def test_input_and_grade_are_preserved_but_explanation_is_concrete(self):
        bars, t = sample(); before = deepcopy((bars, t))
        inputs = condition_inputs({'m5': {'candles': bars}}, t, CLOCK)
        old = assess_strategy('EURUSD', 'daytrade', t, CLOCK)
        new = assess_strategy('EURUSD', 'daytrade', {**t, 'condition_inputs': inputs}, CLOCK)
        for key in ('grade', 'assessment', 'grade_reason', 'reference_levels', 'trigger_price_review', 'expiry'):
            self.assertEqual(old.get(key), new.get(key))
        self.assertEqual(new['scenario_conditions']['status'], 'waiting')
        self.assertIn('102', new['formation_conditions'][0]); self.assertNotIn('未定義', new['formation_conditions'][0])
        self.assertEqual(new['execution_authority'], 'none'); self.assertNotIn('entry_permission', new)
        self.assertEqual((bars, t), before)

    def test_new_saved_conditions_reproduce_and_tampering_is_detected(self):
        bars, t = sample(); plan = compute(bars, t)
        saved = {**t, 'scenario_conditions': plan}
        self.assertEqual(validate_conditions(saved), [])
        for key, value in (('level', 107), ('status', 'conditions_observed'),
                           ('evaluated_at', CLOCK-300), ('observed_close', 105),
                           ('formation_price', 100)):
            bad = deepcopy(saved); bad['scenario_conditions'][key] = value
            self.assertTrue(validate_conditions(bad), key)
        self.assertEqual(validate_conditions(t), [])  # legacy reader compatibility

    def test_each_route_and_stage_passes_saved_evidence_validation(self):
        cases = []
        for direction in ('long', 'short'):
            for tf in ('m5', 'm15'):
                for phase in ('directional_structure_wait', 'pullback_wait', 'transition_context'):
                    bars, t = sample(tf, direction, phase)
                    cases.append((bars, t))
                    rising = direction == 'long'
                    bars = deepcopy(bars); bars[-1].update(high=104, low=97, close=103 if rising else 98)
                    cases.append((bars, t))
                    if phase == 'transition_context':
                        bars = deepcopy(bars)
                        bars[-2].update(high=104, low=97, close=103 if rising else 98)
                        bars[-1].update(open=103 if rising else 98, high=104 if rising else 99,
                                        low=102 if rising else 97, close=103 if rising else 98)
                        cases.append((bars, t))
        for bars, t in cases:
            plan = compute(bars, t)
            with self.subTest(direction=t['direction'], tf=t['trigger_timeframe'], route=plan['route'], status=plan['status']):
                self.assertEqual(validate_conditions({**t, 'scenario_conditions': plan}), [])
                self.assertNotIn('input_window', plan)

    def test_canonical_32_validation_and_history_keep_compact_evidence(self):
        from fx_system.scheduled_outlook import build_scheduled_outlook
        from fx_system.validate_strategy_snapshot import validate_strategy_snapshot
        from diagnostics.monitoring_result_history import pack_generation, restore_generation
        bars, t = sample()
        t['condition_inputs'] = condition_inputs({'m5': {'candles': bars}}, t, CLOCK)
        record = assess_strategy('EURUSD', 'daytrade', t, CLOCK)
        outlook = build_scheduled_outlook({}, {}, evaluated_at=CLOCK)
        for row in outlook['rows']:
            if row['pair'] == 'EURUSD': row['strategy_assessments']['daytrade'] = record
        outlook['strategy_assessments'] = [record if r['pair']=='EURUSD' and r['strategy']=='daytrade' else r
                                           for r in outlook['strategy_assessments']]
        outlook['assessment_counts'] = {'review': 1, 'skip': 0, 'evaluation_pending': 31}
        snapshot = {'evaluated_at': CLOCK, 'scheduled_outlook': outlook}
        self.assertEqual(validate_strategy_snapshot(snapshot), [])
        restored = restore_generation(pack_generation(outlook['rows'], evaluated_at=CLOCK))
        self.assertEqual(restored['rows'], outlook['rows'])
        record['scenario_conditions']['observed_close'] = 103
        self.assertTrue(validate_strategy_snapshot(snapshot))


if __name__ == '__main__':
    unittest.main()
