"""Synthetic trend-only policy, independent M15 pullbacks and legacy restore."""
from copy import deepcopy
import json
import unittest

from fx_system.swing_environment import build_environment, METHOD
from fx_system.strategy_scenario_assessment import assess_strategy
from fx_system.strategy_report import _ordered_reviews
from fx_system.strategy_report_export import build_strategy_report_export, restore_strategy_report_export
from fx_system.validate_strategy_snapshot import validate_strategy_snapshot
from test_strategy_strength import mature_track, CLOCK
from test_strategy_report_export import snapshot, SOURCE


def swing_track(direction='long'):
    t = mature_track()
    t.update(base_timeframe='h4', trigger_timeframe='m15', direction=direction,
             base_structure='HH_HL' if direction == 'long' else 'LH_LL')
    if direction == 'short':
        t['reference_levels'].update(invalidation=110,structural_target=70)
    t['indicator_context'] = {'schema': 'contextual_indicator_context_v2', 'evaluated_at': CLOCK,
        'frames': {role: {'timeframe': tf, 'observations': [{
            'indicator': 'super_bollinger', 'status': 'calculated', 'lagging_span_location': 'inside',
            'application': {'closed_at': CLOCK // seconds * seconds, 'price_zone': 'inside_1sigma',
                            'bandwidth_state': 'contracting'}}]}
        for role, tf, seconds in [('base','h4',14400), ('trigger','m15',900)]}}
    return t


def note(track, role='base'):
    return track['indicator_context']['frames'][role]['observations'][0]


class SwingEnvironmentTests(unittest.TestCase):
    def test_h4_consolidation_excluded_for_both_directions_without_withdrawal(self):
        for direction in ('long', 'short'):
            t = swing_track(direction); before = deepcopy(t)
            r = assess_strategy('EURUSD','swing',t,CLOCK)
            self.assertEqual((r['assessment'],r['grade']), ('skip',None))
            self.assertEqual(r['skip_reason'],'h4_consolidation_excluded')
            self.assertTrue(r['swing_environment']['exclude_from_monitoring'])
            self.assertEqual(r['scenario_conditions']['status'],'not_applicable')
            self.assertNotEqual(r['expiry']['status'],'withdrawn')
            self.assertEqual(_ordered_reviews({'strategy_assessments':[r]}),[])
            self.assertEqual(t,before)

    def test_width_alone_does_not_remove_trend_or_m15_pullback(self):
        for field, value in [('lagging_span_location','above'), ('price_zone','above_upper_1sigma'),
                             ('bandwidth_state','expanding'), ('bandwidth_state','flat')]:
            t=swing_track()
            if field=='lagging_span_location':note(t)[field]=value
            else:note(t)['application'][field]=value
            r=assess_strategy('EURUSD','swing',t,CLOCK)
            self.assertEqual(r['assessment'],'review')
            self.assertFalse(r['swing_environment']['exclude_from_monitoring'])
            # M15 is still fully compressed; it must not veto H4's direction.
            self.assertEqual(note(t,'trigger')['lagging_span_location'],'inside')

    def test_unknown_auxiliary_keeps_price_structure(self):
        for change in ('stale','future','missing','wrong_tf','duplicate'):
            t=swing_track();n=note(t)
            if change=='stale':n['application']['closed_at']-=14400
            if change=='future':n['application']['closed_at']+=14400
            if change=='missing':n['application']['bandwidth_state']='unverified'
            if change=='wrong_tf':t['indicator_context']['frames']['base']['timeframe']='h1'
            if change=='duplicate':t['indicator_context']['frames']['base']['observations'].append(deepcopy(n))
            r=assess_strategy('EURUSD','swing',t,CLOCK)
            self.assertEqual(r['assessment'],'review')
            self.assertEqual(r['swing_environment']['state'],'structure_only')

    def test_primary_quality_and_direction_not_invented(self):
        t=swing_track();t['base_verified']=False
        r=assess_strategy('EURUSD','swing',t,CLOCK)
        self.assertEqual(r['assessment'],'evaluation_pending')
        self.assertFalse(r['swing_environment']['exclude_from_monitoring'])
        t=swing_track();t.update(direction=None,base_structure='unconfirmed')
        r=assess_strategy('EURUSD','swing',t,CLOCK)
        self.assertEqual(r['assessment'],'skip')
        self.assertEqual(r['swing_environment']['state'],'direction_unconfirmed')

    def test_daytrade_untouched_and_no_indicator_votes(self):
        t=mature_track()
        t['indicator_context']=swing_track()['indicator_context']
        r=assess_strategy('EURUSD','daytrade',t,CLOCK)
        self.assertNotIn('swing_environment',r)
        self.assertEqual(r['assessment'],'review')
        self.assertFalse(r['technical_context']['indicator_votes'])
        self.assertEqual(r['technical_context']['schema'],'saved_technical_context_v2')
        self.assertIn('momentum',r['technical_context']['roles'])

    def test_price_withdrawal_keeps_priority_over_environment_exclusion(self):
        t=swing_track();t['reference_plan']['reference_close']=80
        r=assess_strategy('EURUSD','swing',t,CLOCK)
        self.assertEqual(r['skip_reason'],'saved_base_invalidation_crossed')
        self.assertEqual(r['expiry']['status'],'withdrawn')

    def test_dma_macd_rci_are_not_additional_environment_vetoes(self):
        t=swing_track();note(t)['lagging_span_location']='above'
        t['indicator_context']['frames']['base']['observations'] += [
            {'indicator':'dinapoli_macd_preferred_stochastic','status':'provisional_reference',
             'macd_histogram_relation':'opposed','macd':{'histogram':-1},'preferred_stochastic':{}},
            {'indicator':'standard_fibonacci_and_dma','application':{'positions':{
                '25x5':{'status':'observed_reference','price_relation':'opposed','slope_relation':'opposed'}}}}]
        r=assess_strategy('EURUSD','swing',t,CLOCK)
        self.assertEqual(r['assessment'],'review')
        self.assertTrue(r['opposing_evidence'])
        self.assertFalse(r['swing_environment']['exclude_from_monitoring'])

    def test_32_records_export_restore_and_tampered_environment_rejected(self):
        s=snapshot();r=assess_strategy('EURUSD','swing',swing_track(),CLOCK)
        o=s['scheduled_outlook']
        old=next(x for x in o['strategy_assessments'] if x['pair']=='EURUSD' and x['strategy']=='swing')
        o['assessment_counts'][old['assessment']]-=1
        o['assessment_counts'][r['assessment']]+=1
        o['strategy_assessments'][o['strategy_assessments'].index(old)]=r
        next(x for x in o['rows'] if x['pair']=='EURUSD')['strategy_assessments']['swing']=deepcopy(r)
        self.assertEqual(validate_strategy_snapshot(s),[])
        raw=json.dumps(s).encode();b=build_strategy_report_export(raw,SOURCE)
        restored=restore_strategy_report_export(b,SOURCE,b['snapshot_git_blob_sha'])
        self.assertEqual(len(restored['scheduled_outlook']['strategy_assessments']),32)
        self.assertEqual(restored['scheduled_outlook']['strategy_assessments'],o['strategy_assessments'])
        r['swing_environment']['exclude_from_monitoring']=False
        self.assertIn('scheduled swing environment mismatch',validate_strategy_snapshot(s))


if __name__=='__main__':
    unittest.main()
