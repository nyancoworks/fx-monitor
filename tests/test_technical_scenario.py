"""Synthetic wave forecasts: technical thesis, obstacle risk and local timing."""
from copy import deepcopy
import json
import unittest
from unittest.mock import patch

from fx_system.technical_scenario import METHOD, build_outlook, build_plan, refresh
from fx_system.strategy_scenario_assessment import assess_strategy
from fx_system.scenario_conditions import condition_inputs
from fx_system.strategy_report import report_records, render_strategy_report
from fx_system.strategy_report_export import build_strategy_report_export, restore_strategy_report_export
from fx_system.validate_strategy_snapshot import validate_strategy_snapshot
from fx_system.economic_calendar_context import enrich_outlook
from fx_system.scheduled_outlook import build_scheduled_outlook
from test_swing_horizon import with_record
from test_strategy_report_export import SOURCE
from test_strategy_strength import CLOCK


def track(strategy='swing', direction='long'):
    tf, trigger, sec, tsecs=('h4','m15',14400,900) if strategy=='swing' else ('h1','m5',3600,300)
    stamp=(CLOCK//sec-1)*sec
    start={'price':100,'timestamp':stamp-10*sec};end={'price':120,'timestamp':stamp-5*sec}
    bar={'timestamp':stamp,'open':104,'high':106,'low':103,'close':105}
    closed=stamp+sec
    positions={n:{'status':'observed_reference','price_relation':'aligned',
                  'slope_relation':'aligned','price_side':'above','slope_movement':'rising'}
               for n in ('3x3','7x5','25x5')}
    notes=[{'indicator':'super_bollinger','status':'calculated','centerline_relation':'aligned',
            'lagging_span_location':'above','application':{'closed_at':closed,'lagging_relation':'aligned',
             'price_zone':'above_upper_1sigma','bandwidth_state':'expanding'}},
           {'indicator':'standard_fibonacci_and_dma','application':{'positions':positions}},
           {'indicator':'dinapoli_macd_preferred_stochastic','status':'provisional_reference',
            'macd_histogram_relation':'aligned','preferred_stochastic':{'k_movement':'rising'}}]
    rci={'status':'observed_reference','timeframe':tf,'last_timestamp':stamp,
         'periods':{str(p):{'movement':'rising'} for p in (9,26,52)}}
    m=[{'timestamp':CLOCK-(5-i)*tsecs,'open':105,'high':106,'low':104,'close':105} for i in range(5)]
    inp={'evaluated_at':CLOCK,'timeframe':tf,'quality_verified':True,'bar':bar,
         'projection':{'status':'reference_only','start_pivot':start,'end_pivot':end},
         'highs':[end,{'price':130,'timestamp':stamp-3*sec}],
         'lows':[start,{'price':104,'timestamp':stamp-2*sec}]}
    t={'assessment_method':METHOD,'base_timeframe':tf,'trigger_timeframe':trigger,
       'base_verified':True,'trigger_verified':True,'direction':direction,
       'base_structure':'HH_HL','technical_plan_inputs':inp,
       'indicator_context':{'schema':'contextual_indicator_context_v2','evaluated_at':CLOCK,
                            'frames':{'base':{'timeframe':tf,'observations':notes},
                                      'trigger':{'timeframe':trigger,'observations':[]}}},
       'rci_observation':{'frames':{'base':rci}},
       'trigger_price_reference':{'status':'observed_reference','timeframe':trigger,
             'evaluated_at':CLOCK,'closed_at':CLOCK,'close':105}}
    if direction=='short':
        # Independent objects avoid mirroring a shared anchor twice.
        inp=deepcopy(inp)
        def pivot(p):return {**p,'price':220-p['price']}
        inp['projection']={'status':'reference_only','start_pivot':pivot(start),'end_pivot':pivot(end)}
        inp['highs'],inp['lows']=[pivot(p) for p in inp['lows']],[pivot(p) for p in inp['highs']]
        inp['bar']={**bar,'open':220-bar['open'],'close':220-bar['close'],
                    'high':220-bar['low'],'low':220-bar['high']}
        t['technical_plan_inputs']=inp;t['base_structure']='LH_LL'
        notes[0]['lagging_span_location']='below';notes[0]['application']['price_zone']='below_lower_1sigma'
        notes[2]['preferred_stochastic']['k_movement']='falling'
        for p in rci['periods'].values():p['movement']='falling'
        for b in m:
            b.update(open=115,high=116,low=114,close=115)
        t['trigger_price_reference']['close']=115
    t['condition_inputs']=condition_inputs({trigger:{'candles':m}},t,CLOCK)
    return t


def assess(t=None,strategy='swing',direction='long'):
    return assess_strategy('EURUSD',strategy,t or track(strategy,direction),CLOCK)


class TechnicalScenarioTests(unittest.TestCase):
    def test_macro_caution_order_survives_sorted_json_and_lossless_export(self):
        t=track();t['macro_context']={tf:{'verified':True,'relation':'countertrend'} for tf in ('w1','d1')}
        r=assess(t);before=deepcopy(r)
        reordered=json.loads(json.dumps(r,sort_keys=True))
        self.assertEqual(refresh(reordered),before)
        self.assertTrue(r['technical_outlook']['cautions'][0].startswith('w1'))
        self.assertTrue(r['technical_outlook']['cautions'][1].startswith('d1'))
        s=with_record(r);b=build_strategy_report_export(json.dumps(s).encode(),SOURCE)
        self.assertEqual(b['status'],'saved')
        v=restore_strategy_report_export(b,SOURCE,b['snapshot_git_blob_sha'])
        saved=next(x for x in v['scheduled_outlook']['strategy_assessments'] if x['pair']=='EURUSD' and x['strategy']=='swing')
        self.assertEqual(saved,r)

    def test_both_strategies_and_directions_use_wave_origin_and_conditional_projection(self):
        for strategy in ('swing','daytrade'):
            for direction in ('long','short'):
                t=track(strategy,direction);original=deepcopy(t);r=assess(t,strategy,direction);p=r['wave_price_plan']
                self.assertEqual(p['status'],'available')
                self.assertEqual(p['thesis_invalidation'],100 if direction=='long' else 120)
                self.assertEqual(p['local_setup_failure'],104 if direction=='long' else 116)
                self.assertEqual(p['extension_zone']['kind'],'standard_fibonacci_conditional_projection')
                self.assertNotEqual(p['extension_zone']['near'],r['reference_levels']['structural_target'])
                self.assertEqual(r['grade'],'A');self.assertEqual(t,original)

    def test_a_thesis_does_not_require_a_local_price_action_pattern(self):
        r=assess();self.assertNotEqual(r['scenario_conditions']['status'],'conditions_observed')
        self.assertEqual(r['grade'],'A');self.assertEqual(report_records({'strategy_assessments':[r]}),[r])
        self.assertNotIn('swing_wave',r)

    def test_local_breakout_does_not_promote_counterpressure_to_a(self):
        t=track();n=t['indicator_context']['frames']['base']['observations']
        n[2]['macd_histogram_relation']='opposed'
        t['condition_inputs']['bars'][-1].update(open=105,high=108,close=107)
        r=assess(t)
        self.assertEqual(r['scenario_conditions']['status'],'conditions_observed')
        self.assertEqual(r['technical_outlook']['status'],'retracement_then_continuation')
        self.assertEqual(r['grade'],'B')

    def test_rci_short_counter_move_is_not_direction_vote_or_all_indicator_and(self):
        t=track();t['rci_observation']['frames']['base']['periods']['9']['movement']='falling'
        r=assess(t);self.assertEqual(r['grade'],'A')  # Stoch describes recovery; no RCI9 agreement requirement.
        t['rci_observation']['frames']['base']['periods']['26']['movement']='falling'
        r=assess(t);self.assertEqual(r['grade'],'B');self.assertEqual(r['direction'],'long')

    def test_projection_never_hides_near_obstacle_or_local_narrow_stop(self):
        t=track();i=t['technical_plan_inputs'];i['highs'].append({'price':107,'timestamp':i['bar']['timestamp']-4*14400})
        r=assess(t)
        self.assertEqual(r['wave_price_plan']['local_setup_failure'],104)
        self.assertEqual(r['trigger_price_review']['risk_distance'],5)
        self.assertEqual(r['trigger_price_review']['first_obstacle_reward'],2)
        self.assertEqual(r['practical_review']['status'],'price_plan_recheck')
        self.assertEqual(report_records({'strategy_assessments':[r]}),[])

    def test_local_failure_does_not_withdraw_base_wave(self):
        t=track();t['trigger_price_reference']['close']=103
        r=assess(t)
        self.assertEqual(r['wave_price_plan']['status'],'available')
        self.assertNotEqual(r['expiry']['status'],'withdrawn')
        self.assertEqual(r['invalidation']['scope'],'base_wave_thesis')
        self.assertEqual(r['practical_review']['status'],'entry_recheck')
        self.assertEqual(report_records({'strategy_assessments':[r]}),[])

    def test_followthrough_distinguishes_local_entry_and_base_thesis(self):
        from fx_system.scenario_followthrough import observe_frozen_condition
        t=track('daytrade');r=assess(t,'daytrade')
        bars=[{'timestamp':CLOCK+i*300,'open':105,'high':106,'low':102,'close':103} for i in range(12)]
        hourly=[{'timestamp':CLOCK,'open':105,'high':106,'low':102,'close':103}]
        pair={'decision_data':{'raw':{'m5':bars,'h1':hourly},'provenance':{
            **{'m5:'+str(b['timestamp']):'Twelve Data' for b in bars},
            **{'h1:'+str(b['timestamp']):'Twelve Data' for b in hourly}}}}
        f=observe_frozen_condition(r,pair,CLOCK+3600)
        self.assertIsNone(f['base_close_withdrawal'])
        self.assertEqual(f['trigger_close_withdrawal']['condition'],'local_setup_failure_crossed')
        self.assertEqual(f['trigger_withdrawal_scope'],'local_entry_only')

    def test_followthrough_retest_objective_is_not_base_thesis_withdrawal(self):
        from fx_system.scenario_followthrough import observe_frozen_condition
        r=assess(track('daytrade'),'daytrade')
        bars=[{'timestamp':CLOCK+i*300,'open':121,'high':122,'low':120,'close':121} for i in range(12)]
        hourly=[{'timestamp':CLOCK,'open':121,'high':122,'low':120,'close':121}]
        pair={'decision_data':{'raw':{'m5':bars,'h1':hourly},'provenance':{
            **{'m5:'+str(b['timestamp']):'Twelve Data' for b in bars},
            **{'h1:'+str(b['timestamp']):'Twelve Data' for b in hourly}}}}
        f=observe_frozen_condition(r,pair,CLOCK+3600)
        self.assertIsNone(f['base_close_withdrawal'])
        self.assertIsNotNone(f['base_objective_observation'])
        self.assertEqual(f['trigger_close_withdrawal']['condition'],'path_objective_reached')

    def test_base_origin_break_withdraws_thesis_not_trigger_pattern(self):
        t=track();t['technical_plan_inputs']['bar'].update(open=100,close=99,low=98)
        r=assess(t);self.assertEqual(r['assessment'],'skip')
        self.assertEqual(r['skip_reason'],'base_wave_invalidated')
        self.assertEqual(r['expiry']['status'],'withdrawn')

    def test_future_stale_missing_and_unconfirmed_anchors_stay_unknown(self):
        for mode in ('future','stale','missing','unconfirmed','bad_ohlc','quality'):
            t=track();i=t['technical_plan_inputs'];b=i['bar']
            if mode=='future':b['timestamp']+=14400
            if mode=='stale':b['timestamp']-=14400
            if mode=='missing':i['projection']={}
            if mode=='unconfirmed':i['projection']['end_pivot']['timestamp']=b['timestamp']
            if mode=='bad_ohlc':b['low']=110
            if mode=='quality':i['quality_verified']=False
            r=assess(t);self.assertEqual(r['assessment'],'evaluation_pending',mode)
            self.assertIsNone(r['grade']);self.assertEqual(report_records({'strategy_assessments':[r]}),[])

    def test_reaching_extension_does_not_move_goal_farther(self):
        t=track();t['technical_plan_inputs']['bar'].update(open=134,high=135,low=133,close=134)
        r=assess(t);self.assertEqual(r['skip_reason'],'base_wave_objective_reached')
        self.assertAlmostEqual(r['wave_price_plan']['extension_zone']['far'],132.36)

    def test_calendar_enrichment_is_idempotent_and_preserves_wave(self):
        r=assess();s=with_record(r);before=deepcopy(r['wave_price_plan'])
        calendar={'observed_at_utc':CLOCK,'complete':True,'events':[{
            'id':'synthetic','currency':'USD','impact':'high','time_precision':'minute',
            'reference_only':True,'observed_at_utc':CLOCK,'scheduled_at_utc':CLOCK+60}]}
        o=enrich_outlook(s['scheduled_outlook'],calendar)
        r=next(r for r in o['strategy_assessments'] if r['pair']=='EURUSD' and r['strategy']=='swing')
        self.assertEqual(r['practical_review']['status'],'event_recheck');self.assertEqual(r['grade'],'B')
        self.assertEqual(r['wave_price_plan'],before);self.assertEqual(refresh(deepcopy(r)),r)

    def test_export_restore_32_and_derived_field_tampering(self):
        r=assess();s=with_record(r);self.assertEqual(validate_strategy_snapshot(s),[])
        b=build_strategy_report_export(json.dumps(s).encode(),SOURCE)
        self.assertEqual(b['status'],'saved')
        self.assertEqual(len(restore_strategy_report_export(b,SOURCE,b['snapshot_git_blob_sha'])['scheduled_outlook']['strategy_assessments']),32)
        text=render_strategy_report(s);self.assertIn('条件付き到達域',text);self.assertIn('仕掛け確認',text)
        for field in ('wave_price_plan','technical_outlook','reference_levels','grade','scenario_conditions'):
            broken=deepcopy(s);x=broken['scheduled_outlook']['strategy_assessments'][0]
            if isinstance(x.get(field),dict):x[field]['tampered']=True
            else:x[field]='C'
            self.assertTrue(validate_strategy_snapshot(broken),field)

    def test_production_default_is_new_method_even_when_no_data(self):
        from fx_system.technical_evolution import METHOD as CURRENT_METHOD
        o=build_scheduled_outlook({}, {}, evaluated_at=CLOCK)
        self.assertEqual(len(o['strategy_assessments']),32)
        self.assertEqual({r['method_version'] for r in o['strategy_assessments']},{CURRENT_METHOD})
        self.assertTrue(all(r['assessment']=='evaluation_pending' for r in o['strategy_assessments']))

    def test_scheduled_dispatch_calendar_export_and_restore_all32_new_assessments(self):
        from fx_system.technical_evolution import METHOD as CURRENT_METHOD
        from fx_system.scheduled_outlook import _one
        def row(pair, data, quality, clock):
            result=_one(pair,{}, {},clock)
            for strategy in ('swing','daytrade'):
                t=track(strategy);t.update(state='waiting_trigger',reference_timeframe=t['base_timeframe'],
                                           reference_plan={},reference_levels={},scenario_explanation={})
                result['strategy_tracks'][strategy]=t
            return result
        with patch('fx_system.scheduled_outlook._one',side_effect=row):
            o=build_scheduled_outlook({}, {}, evaluated_at=CLOCK,economic_calendar={
                'observed_at_utc':CLOCK,'complete':False,'events':[]})
        s={'evaluated_at':CLOCK,'scheduled_outlook':o}
        self.assertEqual(validate_strategy_snapshot(s),[])
        self.assertEqual(len(o['strategy_assessments']),32)
        self.assertEqual({r['method_version'] for r in o['strategy_assessments']},{CURRENT_METHOD})
        b=build_strategy_report_export(json.dumps(s).encode(),SOURCE)
        self.assertEqual(b['status'],'saved')
        v=restore_strategy_report_export(b,SOURCE,b['snapshot_git_blob_sha'])
        self.assertEqual(v['scheduled_outlook']['strategy_assessments'],o['strategy_assessments'])


if __name__=='__main__':unittest.main()
