"""Chronological transition routes and separate forecast/entry explanations."""
from copy import deepcopy
import unittest
from fx_system.judgment_review import build
from fx_system.technical_scenario import refresh
from fx_system.validate_strategy_snapshot import validate_strategy_snapshot
from test_technical_forecast import track, assess
from test_swing_horizon import with_record
from test_scenario_conditions import sample, compute


class JudgmentReviewTests(unittest.TestCase):
    def test_transition_route_cannot_be_overridden_by_one_local_pullback(self):
        for tf in ('m5','m15'):
            for direction in ('long','short'):
                bars,t=sample(tf=tf,direction=direction,phase='transition_context')
                if direction=='long':bars[-2].update(open=102,close=100)
                else:bars[-2].update(open=99,close=102)
                # Historical interpretation is explicitly retained.
                self.assertEqual(compute(bars,t)['route'],'pullback_rejection')
                t['contextual_review_version']=1
                self.assertEqual(compute(bars,t)['route'],'breakout_retest')
                self.assertNotEqual(compute(bars,t)['status'],'conditions_observed')

    def test_counter_trigger_structure_is_not_a_base_reversal(self):
        r=assess(track());r['trigger_structure_input']={'verified':True,'evaluated_at':r['evaluated_at'],
            'timeframe':r['trigger_timeframe'],'closed_at':r['trigger_price_review']['closed_at'],'structure':'LH_LL'}
        original=r['direction'],r['grade'],deepcopy(r['wave_price_plan'])
        refresh(r)
        self.assertEqual(r['judgment_review']['trigger']['state'],'counter_structure')
        self.assertEqual(original,(r['direction'],r['grade'],r['wave_price_plan']))
        self.assertIn('基準足転換とは断定しない',r['judgment_review']['trigger']['summary'])

    def test_stale_or_wrong_frame_structure_cannot_be_used(self):
        r=assess(track())
        r['trigger_structure_input']={'verified':True,'evaluated_at':r['evaluated_at'],
            'timeframe':'m5','closed_at':r['evaluated_at'],'structure':'LH_LL'}
        self.assertNotEqual(build(r)['trigger']['state'],'counter_structure')
        r['trigger_structure_input']['timeframe']=r['trigger_timeframe']
        r['trigger_structure_input']['closed_at']-=900
        self.assertNotEqual(build(r)['trigger']['state'],'counter_structure')

    def test_strength_opposition_has_price_based_explanation_not_ban(self):
        r=assess(track());r['currency_strength_context'].update(relation='opposed',movement='weakening',material_opposition=True)
        a=build(r)
        self.assertEqual(a['currency_strength']['relation'],'opposed')
        self.assertIn('反転自体は未確認',a['currency_strength']['explanation'])
        r['base_structure']='LH_LL'
        self.assertIn('未完成',build(r)['currency_strength']['explanation'])
        self.assertEqual(r['direction'],'long')

    def test_shape_and_condition_status_do_not_imply_fill_or_accuracy(self):
        r=assess(track());j=r['judgment_review'];shape=j['trigger']['candle_shape']
        self.assertIsNotNone(shape)
        self.assertGreaterEqual(shape['body'],0);self.assertGreaterEqual(shape['lower_wick'],0)
        self.assertEqual(j['scenario_grade'],r['grade'])
        self.assertEqual(j['prediction_accuracy'],'not_measured')
        self.assertIsNone(r['scenario_conditions']['formation_price'])

    def test_context_is_validated_and_unmarked_v12_remains_restorable(self):
        r=assess(track());s=with_record(r)
        self.assertEqual(validate_strategy_snapshot(s),[])
        s['scheduled_outlook']['strategy_assessments'][0]['judgment_review']['trigger']['state']='base_withdrawn'
        self.assertTrue(validate_strategy_snapshot(s))
        r.pop('contextual_review_version');r.pop('judgment_review');r.pop('trigger_structure_input')
        refresh(r);self.assertNotIn('judgment_review',r)
        self.assertEqual(refresh(deepcopy(r)),r)
