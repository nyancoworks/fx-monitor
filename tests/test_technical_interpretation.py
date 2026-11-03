from copy import deepcopy
import json
import unittest
from unittest.mock import patch
from fx_system.technical_scenario import refresh
from fx_system.strategy_report import report_records
from fx_system.strategy_report_export import build_strategy_report_export,restore_strategy_report_export
from fx_system.scheduled_outlook import _one,build_scheduled_outlook
from test_technical_forecast import track,assess
from test_span_model import span_track
from test_swing_horizon import with_record
from test_strategy_report_export import SOURCE
from test_strategy_strength import CLOCK


def contextual(strategy='swing',direction='long',**kwargs):
    t=track(strategy,direction,**kwargs);t['technical_interpretation_version']=1;t['technical_order_version']=1
    return t


class TechnicalInterpretationTests(unittest.TestCase):
    def test_legacy_pa_candidate_order_cannot_rank_new_equal_context_reviews(self):
        from fx_system.strategy_report import _ordered_reviews
        a=assess(contextual());b=deepcopy(a);b['pair']='GBPUSD'
        outlook={'strategy_assessments':[a,b],
                 'strategy_candidates':[{'pair':'GBPUSD','strategy':'swing','priority':'pattern_observed'},
                                        {'pair':'EURUSD','strategy':'swing','priority':'directional_watch'}]}
        self.assertEqual([r['pair'] for r in _ordered_reviews(outlook)],['EURUSD','GBPUSD'])
        for r in outlook['strategy_assessments']:r.pop('technical_order_version')
        self.assertEqual([r['pair'] for r in _ordered_reviews(outlook)],['GBPUSD','EURUSD'])

    def test_thesis_distance_alone_cannot_suppress_defined_monitoring_or_promote_a(self):
        for strategy in ('swing','daytrade'):
            for direction in ('long','short'):
                t=contextual(strategy,direction)
                t['technical_plan_inputs']['projection']['start_pivot']['price']=50 if direction=='long' else 170
                stops=t['technical_plan_inputs']['lows' if direction=='long' else 'highs']
                stops[0]['price']=50 if direction=='long' else 170
                r=assess(t,strategy);legacy=deepcopy(r);legacy.pop('technical_interpretation_version');legacy.pop('technical_order_version');refresh(legacy)
                self.assertFalse(r['practical_review']['reference_margin_sufficient'])
                self.assertEqual(r['practical_review']['status'],'technical_watch')
                self.assertEqual(r['grade'],'B');self.assertEqual(legacy['practical_review']['status'],'price_plan_recheck')
                self.assertEqual(r['reference_levels'],legacy['reference_levels'])
                self.assertEqual(r['wave_price_plan'],legacy['wave_price_plan'])
                self.assertIsNone(r['trigger_price_review']['formation_rr'])
                self.assertIn('未確定',r['grade_reason'])

    def test_mixed_counter_momentum_with_intact_background_is_pullback_wait_not_reversal(self):
        r=assess(contextual(hist=(-.2,-.3,-.2)))
        self.assertEqual(r['direction'],'long');self.assertEqual(r['grade'],'B')
        self.assertEqual(r['technical_outlook']['forecast']['phase'],'pullback_unsettled')
        self.assertEqual(r['practical_review']['status'],'technical_watch')

    def test_expanding_counterpressure_still_defers_monitoring_priority(self):
        for strategy in ('swing','daytrade'):
            r=assess(contextual(strategy,hist=(-.1,-.2,-.3)),strategy)
            self.assertEqual(r['direction'],'long');self.assertEqual(r['grade'],'B')
            self.assertEqual(r['practical_review']['status'],'technical_recheck')
            self.assertEqual(report_records({'strategy_assessments':[r]}),[])

    def test_structure_or_slow_background_conflict_is_not_rescued_by_short_oscillators(self):
        for mode in ('structure','dma'):
            t=contextual()
            if mode=='structure':t['base_structure']='LH_LL'
            else:t['indicator_context']['frames']['base']['observations'][1]['application']['positions']['25x5']['price_side']='below'
            r=assess(t);self.assertEqual(r['grade'],'C')
            self.assertEqual(r['practical_review']['status'],'technical_recheck')

    def test_short_rci_reversal_and_directional_pinning_are_read_in_trend_context(self):
        t=contextual();p=t['rci_observation']['frames']['base']['periods']
        p['9']['movement']='falling'
        for k in ('26','52'):p[k]['extreme_run']={'zone':'upper'}
        r=assess(t);f=r['technical_outlook']['forecast']
        self.assertEqual(r['direction'],'long');self.assertNotEqual(r['grade'],'A')
        self.assertTrue(any('押し戻り' in s and 'RCI9' in s for s in f['support']))
        self.assertTrue(any('極端域' in s for s in f['support']))

    def test_trigger_cloud_alone_does_not_cancel_intact_background_but_local_failure_does(self):
        t=span_track(trigger='failed');t['technical_interpretation_version']=1
        r=assess(t);self.assertEqual(r['direction'],'long')
        self.assertEqual(r['practical_review']['status'],'technical_watch');self.assertEqual(r['grade'],'B')
        # An actual local invalidation remains a stop to the old setup.
        t['trigger_price_reference']['close']=103
        last=t['condition_inputs']['bars'][-1]
        for key in ('open','high','low','close'):last[key]-=2
        from fx_system.span_model import calculate
        n=t['indicator_context']['frames']['trigger']['observations'][-1]
        n['inputs']['closes'][-1]=103;n['observation']=calculate(n['inputs'])
        r=assess(t);self.assertEqual(r['practical_review']['status'],'entry_recheck')

    def test_base_cloud_conflict_does_not_alone_override_intact_sb_dma_background(self):
        t=span_track(base='failed');t['technical_interpretation_version']=1
        r=assess(t);self.assertEqual(r['direction'],'long');self.assertEqual(r['grade'],'B')
        self.assertEqual(r['technical_outlook']['forecast']['phase'],'pullback_unsettled')
        self.assertTrue(r['technical_outlook']['cautions'])

    def test_passed_obstacle_unavailable_condition_and_stale_data_are_not_rescued(self):
        for mode in ('obstacle','condition','stale'):
            t=contextual()
            if mode=='obstacle':
                # Base obstacle ahead of the base bar, already behind trigger.
                t['technical_plan_inputs']['highs'].append({'price':105.5,'timestamp':t['technical_plan_inputs']['bar']['timestamp']-3*14400})
                t['trigger_price_reference']['close']=106
            if mode=='condition':
                for b in t['condition_inputs']['bars'][:-1]:b['high']=130
            if mode=='stale':t['trigger_price_reference']['closed_at']-=900
            r=assess(t);self.assertNotEqual(r['practical_review']['status'],'technical_watch',mode)

    def test_old_saved_interpretation_and_original_report_remain_exact(self):
        old=assess(track());self.assertNotIn('technical_interpretation_version',old)
        self.assertEqual(refresh(json.loads(json.dumps(old,sort_keys=True))),old)
        s=with_record(old);b=build_strategy_report_export(json.dumps(s).encode(),SOURCE)
        self.assertEqual(b['status'],'saved');restore_strategy_report_export(b,SOURCE,b['snapshot_git_blob_sha'])
        r=assess(contextual())
        for value in (True,2,'1'):
            broken=deepcopy(r);broken['technical_interpretation_version']=value
            with self.assertRaises(ValueError):refresh(broken)
            broken=deepcopy(r);broken['technical_order_version']=value
            with self.assertRaises(ValueError):refresh(broken)

    def test_all32_save_restore_reports_monitoring_as_waiting_not_entry_opportunity(self):
        def row(pair,data,quality,clock,method=None):
            out=_one(pair,{}, {},clock)
            for strategy in ('swing','daytrade'):
                t=contextual(strategy,hist=(.5,.4,.3))
                t.update(state='watch',reference_timeframe=t['base_timeframe'],reference_plan={},reference_levels={},scenario_explanation={})
                out['strategy_tracks'][strategy]=t
            return out
        with patch('fx_system.scheduled_outlook._one',side_effect=row):o=build_scheduled_outlook({}, {},evaluated_at=CLOCK)
        b=build_strategy_report_export(json.dumps({'evaluated_at':CLOCK,'scheduled_outlook':o}).encode(),SOURCE)
        self.assertEqual(b['status'],'saved');v=restore_strategy_report_export(b,SOURCE,b['snapshot_git_blob_sha'])
        self.assertEqual(v['scheduled_outlook']['strategy_assessments'],o['strategy_assessments'])
        self.assertIn('仕掛け価格・損失幅・費用',b['report_text'])
        self.assertIn('条件前に追わない',b['report_text'])
