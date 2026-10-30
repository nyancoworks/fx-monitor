"""Directional forecasts, contradictions and immutable historical readers."""
from copy import deepcopy
import json
import math
import unittest
from unittest.mock import patch
from fx_system.technical_forecast import METHOD, forecast, prepare_track
from fx_system.strategy_scenario_assessment import assess_strategy
from fx_system.technical_scenario import refresh
from fx_system.scheduled_outlook import build_scheduled_outlook, _one
from fx_system.strategy_report_export import build_strategy_report_export, restore_strategy_report_export
from fx_system.validate_strategy_snapshot import validate_strategy_snapshot
from test_technical_evolution import temporal_track
from test_strategy_strength import CLOCK
from test_strategy_report_export import SOURCE
from test_swing_horizon import with_record


def track(strategy='swing', direction='long', **kwargs):
    t=temporal_track(strategy,direction,**kwargs)
    t['assessment_method']=METHOD
    notes=t['indicator_context']['frames']['base']['observations']
    notes[0]['centerline_direction']='up' if direction=='long' else 'down'
    if direction=='short':
        for p in notes[1]['application']['positions'].values():
            p.update(price_side='below',slope_movement='falling')
    return t


def assess(t,strategy='swing'):
    return assess_strategy('EURUSD',strategy,t,CLOCK)


class ForecastTests(unittest.TestCase):
    def test_real_pipeline_rebuilds_direction_wave_and_conditions_from_synthetic_candles(self):
        from fx_system.core import technical
        from fx_system.indicator_refresh import refresh_strategy_indicators
        from fx_system.dinapoli_research import dma_snapshot, confirmed_fibonacci
        for sign in (1,-1):
            frames={}
            for tf,sec in (('h4',14400),('h1',3600),('m15',900),('m5',300),('d1',86400),('w1',604800)):
                last=(CLOCK//sec-1)*sec
                bars=[]
                for i in range(100):
                    c=200+sign*(.1*i+math.sin(i*.6))
                    bars.append({'timestamp':last-(99-i)*sec,'open':c-.02,'high':c+.15,'low':c-.15,'close':c})
                frames[tf]=bars
            q={'evaluated_at':CLOCK,'timeframes':{tf:{'ok':True,'count':100} for tf in frames}}
            data={tf:{'candles':bars} for tf,bars in frames.items()}
            data['decision_quality']=q
            data['technical']={tf:technical(bars) for tf,bars in frames.items()}
            # A deliberately contrary structural label cannot override the
            # actual indicator measurements. Confirmed pivots remain untouched.
            for tf in ('h1','h4'):
                data['technical'][tf]['structure']='LH_LL' if sign==1 else 'HH_HL'
            data['h4_setup_shadow']={'dinapoli':{**dma_snapshot(frames['h4']),
                'confirmed_fibonacci':confirmed_fibonacci(frames['h4'],'long' if sign==1 else 'short')}}
            refresh_strategy_indicators(data,frames,frames,q,{})
            o=build_scheduled_outlook({'EURUSD':data},{'EURUSD':{'timeframes':q['timeframes']}},evaluated_at=CLOCK)
            r=next(r for r in o['strategy_assessments'] if r['pair']=='EURUSD' and r['strategy']=='swing')
            self.assertEqual(r['direction'],'long' if sign==1 else 'short')
            self.assertEqual(r['wave_price_plan']['status'],'available')
            p=r['wave_price_plan'];self.assertGreater(sign*(p['end_pivot']['price']-p['start_pivot']['price']),0)
            self.assertEqual(r['entry_condition_inputs']['timeframe'],'m15')
            self.assertEqual(validate_strategy_snapshot({'evaluated_at':CLOCK,'scheduled_outlook':o}),[])

    def test_structure_cannot_choose_direction_or_force_opposite_forecast(self):
        for strategy in ('swing','daytrade'):
            for direction in ('long','short'):
                t=track(strategy,direction)
                t['base_structure']='LH_LL' if direction=='long' else 'HH_HL'
                r=assess(t,strategy)
                self.assertEqual(r['direction'],direction)
                self.assertEqual(r['technical_outlook']['forecast']['direction'],direction)
                self.assertEqual(r['grade'],'C')
                self.assertEqual(r['practical_review']['status'],'technical_recheck')

    def test_transition_can_forecast_against_sb_without_indicator_vote(self):
        t=track(hist=(-.1,-.2,-.3))
        pos=t['indicator_context']['frames']['base']['observations'][1]['application']['positions']
        pos['25x5'].update(price_side='below',slope_movement='falling')
        # Standalone interpreter must propose the opposite, rather than accept
        # either supplied direction. Building a plan is a separate operation.
        r=assess(track());r['indicator_context']=t['indicator_context']
        r['base_evolution_inputs']=t['base_evolution_inputs']
        f=forecast(r)
        self.assertEqual(f['direction'],'short')
        self.assertEqual(f['phase'],'reversal_developing')
        self.assertEqual(f['conviction'],'weak')
        with self.assertRaises(ValueError):refresh(r)

    def test_deepening_is_c_not_optimistic_b_and_pa_cannot_rescue_it(self):
        for strategy in ('swing','daytrade'):
            r=assess(track(strategy,hist=(-.1,-.2,-.3)),strategy)
            self.assertEqual(r['grade'],'C')
            self.assertIn('再開を先取りしない',r['technical_outlook']['path'])
            before=r['direction'],r['grade'],r['technical_outlook']
            r['scenario_conditions']={'status':'conditions_observed'}
            refresh(r)
            self.assertEqual(before,(r['direction'],r['grade'],r['technical_outlook']))

    def test_fading_easing_and_one_rebound_are_different_forecasts(self):
        for h,phase in [((.5,.4,.3),'pullback_expected'),((-.5,-.4,-.3),'pullback_easing'),
                        ((-.3,-.4,.3),'reacceleration_unconfirmed')]:
            r=assess(track(hist=h));self.assertEqual(r['technical_outlook']['forecast']['phase'],phase)
            self.assertNotEqual(r['grade'],'A')

    def test_auxiliary_rci_stochastic_cannot_reverse_direction(self):
        t=track();n=t['indicator_context']['frames']['base']['observations']
        n[2]['preferred_stochastic']['k_movement']='falling'
        t['rci_observation']['frames']['base']['periods']['9']['movement']='falling'
        r=assess(t);self.assertEqual(r['direction'],'long')

    def test_missing_primary_is_pending_not_consolidation_or_forced_direction(self):
        t=track();t['indicator_context']['frames']['base']['observations']=[]
        r=assess(t);self.assertEqual(r['assessment'],'evaluation_pending')
        self.assertIsNone(r['grade'])

    def test_sorted_export_restore_and_tamper_detection(self):
        r=assess(track());self.assertEqual(refresh(json.loads(json.dumps(r,sort_keys=True))),r)
        s=with_record(r);self.assertEqual(validate_strategy_snapshot(s),[])
        b=build_strategy_report_export(json.dumps(s).encode(),SOURCE)
        self.assertEqual(b['status'],'saved')
        restored=restore_strategy_report_export(b,SOURCE,b['snapshot_git_blob_sha'])
        self.assertEqual(restored['scheduled_outlook']['strategy_assessments'][0],s['scheduled_outlook']['strategy_assessments'][0])
        broken=deepcopy(s);broken['scheduled_outlook']['strategy_assessments'][0]['direction']='short'
        self.assertTrue(validate_strategy_snapshot(broken))

    def test_all32_calendar_dispatch_and_restore(self):
        def row(pair,data,quality,clock,method=None):
            out=_one(pair,{}, {},clock)
            for strategy in ('swing','daytrade'):
                t=track(strategy);t.update(state='watch',reference_timeframe=t['base_timeframe'],
                                          reference_plan={},reference_levels={},scenario_explanation={})
                out['strategy_tracks'][strategy]=t
            return out
        with patch('fx_system.scheduled_outlook._one',side_effect=row):
            o=build_scheduled_outlook({}, {},evaluated_at=CLOCK,economic_calendar={'observed_at_utc':CLOCK,'complete':False,'events':[]})
        self.assertEqual(len(o['strategy_assessments']),32)
        self.assertEqual({r['method_version'] for r in o['strategy_assessments']},{METHOD})
        s={'evaluated_at':CLOCK,'scheduled_outlook':o}
        self.assertEqual(validate_strategy_snapshot(s),[])
        b=build_strategy_report_export(json.dumps(s).encode(),SOURCE)
        self.assertEqual(b['status'],'saved')
        restore_strategy_report_export(b,SOURCE,b['snapshot_git_blob_sha'])
