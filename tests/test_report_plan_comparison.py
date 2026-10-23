"""Synthetic saved scenarios; no quotes, collection, or network access."""
from copy import deepcopy
import json
import unittest

from fx_system.report_plan_comparison import saved_plan_comparison
from fx_system.strategy_report import report_records, render_strategy_report
from fx_system.scheduled_outlook import build_scheduled_outlook
from fx_system.validate_strategy_snapshot import validate_strategy_snapshot
from diagnostics.monitoring_result_history import pack_generation, restore_generation


CLOCK = 1800000300


def row(pair, ratio, *, strategy='daytrade', direction='long', trigger_ratio=None):
    # Base/trigger closes are hypothetical, not execution or formation prices.
    close = 100
    stop = 90 if direction == 'long' else 110
    target = close + ratio*10 if direction == 'long' else close-ratio*10
    base, trigger = ('h4', 'm15') if strategy == 'swing' else ('h1', 'm5')
    base_seconds = 14400 if strategy == 'swing' else 3600
    trigger_seconds = 900 if strategy == 'swing' else 300
    result = {'pair': pair, 'strategy': strategy, 'grade': 'B', 'assessment': 'review',
        'direction': direction, 'evaluated_at': CLOCK, 'reference_timeframe': base,
        'trigger_timeframe': trigger, 'market_phase': 'directional_structure_wait',
        'reference_plan': {'reference_close': close,
                           'reference_close_timestamp': CLOCK//base_seconds*base_seconds-base_seconds},
        'reference_levels': {'invalidation': stop, 'structural_target': target, 'reference_rr': ratio},
        'scenario_conditions': {'evaluated_at': CLOCK, 'timeframe': trigger, 'direction': direction,
                                'status': 'waiting', 'route': 'continuation_breakout'},
        'opposing_evidence': [], 'uncertainties': [], 'expiry': {'status': 'active'}}
    if ratio < 1.5:
        result['opposing_evidence'].append('構造目標の参考RRが1.5未満。採算余地を再検討（執行RRではない）')
    if trigger_ratio is not None:
        # Solve (target-price)/(price-stop)=RR for long, and its short mirror.
        price = (target+trigger_ratio*stop)/(1+trigger_ratio)
        risk, reward = ((price-stop, target-price) if direction == 'long' else (stop-price, price-target))
        result['trigger_price_review'] = {'status': 'observed_reference', 'saved_close': price,
            'closed_at': CLOCK//trigger_seconds*trigger_seconds,
            'risk_distance': risk, 'reward_distance': reward, 'reference_rr': round(trigger_ratio, 2)}
        if reward < risk:
            result['opposing_evidence'].append(f'{trigger}保存終値基準では目標までの余地{reward:g}が無効化距離{risk:g}より小さい。勝率・優位性は未検証')
    return result


def selected(*rows):
    return [r['pair'] for r in report_records({'strategy_assessments': list(rows)})]


class PlanComparisonTests(unittest.TestCase):
    def test_comparable_same_grade_headroom_changes_display_only(self):
        rows = [row('EURUSD', .1), row('GBPUSD', .8), row('AUDUSD', 2)]
        outlook = {'strategy_assessments': rows,
                   'strategy_candidates': [{'pair': r['pair'], 'strategy': r['strategy']} for r in rows]}
        original = deepcopy(outlook)
        self.assertEqual([r['pair'] for r in report_records(outlook)], ['AUDUSD', 'GBPUSD', 'EURUSD'])
        self.assertEqual(outlook, original)

    def test_large_rr_cannot_promote_weaker_or_different_context(self):
        low, weak, good = row('EURUSD', .1), row('GBPUSD', 5), row('AUDUSD', 2)
        for change in ({'market_phase': 'pullback_wait'},
                       {'opposing_evidence': ['h4構造は逆方向']},
                       {'uncertainties': ['確認足品質を再確認']},
                       {'scenario_type': 'range_reversal'},
                       {'currency_strength_context': {'status': 'available', 'relation': 'opposed'}}):
            changed = deepcopy(weak); changed.update(change)
            self.assertEqual(selected(low, changed, good), ['AUDUSD', 'GBPUSD', 'EURUSD'])
        for field, value in (('status', 'retest_failed'), ('route', 'breakout_retest')):
            changed = deepcopy(weak); changed['scenario_conditions'][field] = value
            self.assertEqual(selected(low, changed, good), ['AUDUSD', 'GBPUSD', 'EURUSD'])

    def test_grade_priority_and_three_each_are_preserved(self):
        rows = [row(str(i), i/5+.1, strategy=s) for s in ('swing', 'daytrade') for i in range(5)]
        rows[0]['grade'] = 'A'
        self.assertEqual(selected(*rows), ['0', '4', '3', '4', '3', '2'])
        rows[0]['grade'] = 'C'
        self.assertNotIn(rows[0], report_records({'strategy_assessments': rows}))

    def test_newer_trigger_close_drives_comparison_in_both_directions(self):
        for direction in ('long', 'short'):
            a = row('EURUSD', 3, trigger_ratio=.1, direction=direction)
            b = row('GBPUSD', 2, trigger_ratio=.8, direction=direction)
            self.assertEqual(selected(a, b), ['GBPUSD', 'EURUSD'])
            self.assertIn('目標までの余地が無効化までの距離より小さい', saved_plan_comparison(a)[2])
            self.assertAlmostEqual(saved_plan_comparison(a)[1], .1)

    def test_missing_target_or_inconsistent_rr_does_not_use_projection(self):
        for change in ({'structural_target': None}, {'structural_target': 100}, {'reference_rr': 99},
                       {'reference_rr': float('nan')}, {'structural_target': True}):
            bad = row('EURUSD', 4); bad['reference_levels'].update(change)
            bad['reference_projection'] = {'targets': [{'price': 1000, 'reference_rr': 100}]}
            self.assertIsNone(saved_plan_comparison(bad)[0])
            self.assertEqual(selected(bad, row('GBPUSD', 2)), ['EURUSD', 'GBPUSD'])
        self.assertIn('未確認', saved_plan_comparison(bad)[2])

    def test_stale_future_or_crossed_trigger_never_falls_back_to_base(self):
        for change in ({'closed_at': CLOCK+1}, {'closed_at': CLOCK-300},
                       {'saved_close': 90}, {'saved_close': 140}, {'saved_close': float('inf')},
                       {'saved_close': True}):
            bad = row('EURUSD', 4, trigger_ratio=2); bad['trigger_price_review'].update(change)
            self.assertEqual(saved_plan_comparison(bad)[:2], (None, None))

    def test_base_only_and_trigger_contexts_are_not_compared(self):
        a, b, c = row('EURUSD', .1), row('GBPUSD', 4, trigger_ratio=4), row('AUDUSD', 2)
        self.assertEqual(selected(a, b, c), ['AUDUSD', 'GBPUSD', 'EURUSD'])
        self.assertIn('後の確認足価格は未確認', saved_plan_comparison(a)[2])

    def test_unverified_reference_pattern_does_not_take_observed_pattern_slot(self):
        a, b = row('EURUSD', .1), row('GBPUSD', 4)
        a['formation_observation'] = {'status': 'observed_reference', 'timeframe': 'm5',
                                      'closed_at': CLOCK, 'scenario_withdrawn': False}
        self.assertEqual(selected(a, b), ['EURUSD', 'GBPUSD'])
        a['formation_observation']['closed_at'] -= 300
        self.assertIsNone(saved_plan_comparison(a)[0])

    def test_context_or_clock_missing_preserves_slot_and_ties_preserve_saved_order(self):
        a, b = row('EURUSD', 2), row('GBPUSD', 2)
        self.assertEqual(selected(a, b), ['EURUSD', 'GBPUSD'])
        for field, value in (('evaluated_at', CLOCK-300), ('direction', 'short')):
            bad = row('EURUSD', .1); bad['scenario_conditions'][field] = value
            self.assertIsNone(saved_plan_comparison(bad)[0])
        bad = row('EURUSD', .1); bad['reference_plan']['reference_close_timestamp'] -= 3600
        self.assertIsNone(saved_plan_comparison(bad)[0])
        a['assessment'] = 'skip'; a['grade'] = None
        self.assertEqual(selected(a, b), ['GBPUSD'])

    def test_unknown_opposition_is_preserved_even_if_it_mentions_rr(self):
        a, b = row('EURUSD', .1), row('GBPUSD', 3)
        b['opposing_evidence'] = ['独自のRR関連注意。反対根拠として保持']
        self.assertEqual(selected(a, b), ['EURUSD', 'GBPUSD'])

    def test_candidate_saved_order_is_final_tie_break(self):
        rows = [row('EURUSD', 2), row('GBPUSD', 2)]
        outlook = {'strategy_assessments': rows, 'strategy_candidates': [rows[1], rows[0]]}
        self.assertEqual([r['pair'] for r in report_records(outlook)], ['GBPUSD', 'EURUSD'])

    def test_full_32_json_history_report_pipeline_keeps_assessments_and_counts(self):
        from test_range_scenario import sample, CLOCK as SAMPLE_CLOCK
        data, _ = sample()
        quality = {'timeframes': {'h1': {'ok': True, 'count': 20},
                                 'm5': {'ok': True, 'count': 5, 'age_minutes': 0}}}
        data['decision_quality'] = {**deepcopy(quality), 'evaluated_at': SAMPLE_CLOCK}
        data['technical'] = {'h1': {'status': 'ok', 'structure': 'mixed'}}
        outlook = build_scheduled_outlook({'EURUSD': data}, {'EURUSD': quality}, evaluated_at=SAMPLE_CLOCK)
        snapshot = json.loads(json.dumps({'evaluated_at': SAMPLE_CLOCK, 'scheduled_outlook': outlook}))
        original = deepcopy(snapshot)
        self.assertEqual(validate_strategy_snapshot(snapshot), [])
        text = render_strategy_report(snapshot)
        self.assertIn('32戦略', text)
        self.assertIn('非掲載の検討候補', text)
        self.assertIn('同じ確認段階と反対根拠', text)
        restored = restore_generation(pack_generation(outlook['rows'], evaluated_at=SAMPLE_CLOCK))
        self.assertEqual(restored['rows'], outlook['rows'])
        self.assertEqual(snapshot, original)
        self.assertEqual(validate_strategy_snapshot(snapshot), [])


if __name__ == '__main__':
    unittest.main()
