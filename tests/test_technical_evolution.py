"""Temporal interpretations and production integration; synthetic data only."""
from copy import deepcopy
import json
import math
import unittest
from unittest.mock import patch

from fx_system.technical_evolution import METHOD, observe, describe
from fx_system.technical_scenario import refresh
from fx_system.strategy_scenario_assessment import assess_strategy
from fx_system.strategy_report import report_records, render_strategy_report
from fx_system.strategy_report_export import build_strategy_report_export, restore_strategy_report_export
from fx_system.validate_strategy_snapshot import validate_strategy_snapshot
from fx_system.scheduled_outlook import build_scheduled_outlook, _one
from fx_system.economic_calendar_context import enrich_outlook
from fx_system.dinapoli_indicator_reference import indicator_reference
from fx_system.dinapoli_research import dma_snapshot
from fx_system.indicator_research import rci_series
from test_technical_scenario import track
from test_swing_horizon import with_record
from test_strategy_report_export import SOURCE
from test_strategy_strength import CLOCK


def temporal_track(strategy='swing',direction='long',hist=(.1,.2,.3),gaps=(1,1,1)):
    t=track(strategy,direction);t['assessment_method']=METHOD
    sec=14400 if strategy=='swing' else 3600
    end=t['technical_plan_inputs']['bar']['timestamp']+sec
    sign=1 if direction=='long' else -1
    close=t['technical_plan_inputs']['bar']['close']
    points=[{'closed_at':end-(2-i)*sec,'close':close,'macd_histogram':sign*h,
             'dma3x3':close-sign*g,'stochastic_k':50,
             'rci':{'9':10+i,'26':20+i,'52':30+i}} for i,(h,g) in enumerate(zip(hist,gaps))]
    t['base_evolution_inputs']={'schema':'base_evolution_inputs_v1','evaluated_at':CLOCK,
          'timeframe':t['base_timeframe'],'quality_verified':True,'status':'available','points':points}
    notes=t['indicator_context']['frames']['base']['observations']
    notes[1]['application']['positions']['3x3']['plot']=points[-1]['dma3x3']
    notes[2]['macd']={'histogram':points[-1]['macd_histogram']}
    notes[2]['macd_histogram_relation']='aligned' if hist[-1]>0 else 'opposed'
    notes[2]['preferred_stochastic']['slow_k']=50
    for p,value in points[-1]['rci'].items():t['rci_observation']['frames']['base']['periods'][p]['value']=value
    return t


def assess(t,strategy='swing',direction='long'):
    return assess_strategy('EURUSD',strategy,t,CLOCK)


class EvolutionTests(unittest.TestCase):
    def test_same_latest_macd_sign_can_be_deepening_or_easing(self):
        for strategy in ('swing','daytrade'):
            for direction in ('long','short'):
                a=assess(temporal_track(strategy,direction,(-.1,-.2,-.3)),strategy,direction)
                b=assess(temporal_track(strategy,direction,(-.5,-.4,-.3)),strategy,direction)
                self.assertEqual(a['technical_outlook']['evolution']['momentum'],'counterpressure_deepening')
                self.assertEqual(b['technical_outlook']['evolution']['momentum'],'counterpressure_easing')
                self.assertEqual(a['technical_outlook']['status'],b['technical_outlook']['status'])
                self.assertEqual(a['practical_review']['status'],'technical_recheck')
                self.assertEqual(report_records({'strategy_assessments':[a]}),[])
                self.assertEqual(b['practical_review']['status'],'technical_watch')
                self.assertEqual((a['grade'],b['grade']),('B','B'))
                self.assertEqual(a['wave_price_plan'],b['wave_price_plan'])

    def test_directional_but_fading_is_not_straight_continuation(self):
        r=assess(temporal_track(hist=(.5,.4,.3)))
        self.assertEqual(r['technical_outlook']['status'],'retracement_then_continuation')
        self.assertEqual(r['grade'],'B')
        self.assertIn('減速',r['technical_outlook']['path'])

    def test_one_rebound_or_dma_recovery_cannot_supply_mature_a(self):
        for hist,gaps in [((-.3,-.4,.3),(1,1,1)),((.1,.2,.3),(-1,-1,1))]:
            r=assess(temporal_track(hist=hist,gaps=gaps))
            self.assertEqual(r['grade'],'B')
            self.assertEqual(r['direction'],'long')

    def test_persistent_positive_momentum_preserves_existing_a_not_new_vote(self):
        for hist in ((.1,.2,.3),(.3,.3,.3)):
            t=temporal_track(hist=hist);original=deepcopy(t);r=assess(t)
            self.assertEqual(r['grade'],'A');self.assertEqual(t,original)
            self.assertNotEqual(r['scenario_conditions']['status'],'conditions_observed')
            self.assertNotIn('swing_wave',r)

    def test_missing_stale_future_gapped_wrong_endpoint_and_quality_not_inferred(self):
        base=temporal_track()
        for mode in ('missing','stale','future','gap','clock','timeframe','close','histogram','rci','dma','stoch','quality','nan'):
            t=deepcopy(base);i=t['base_evolution_inputs'];p=i['points'];sec=14400
            if mode=='missing':i['points']=[]
            if mode=='stale':
                for v in p:v['closed_at']-=sec
            if mode=='future':
                for v in p:v['closed_at']+=sec
            if mode=='gap':p[0]['closed_at']-=sec
            if mode=='clock':i['evaluated_at']-=1
            if mode=='timeframe':i['timeframe']='h1'
            if mode=='close':p[-1]['close']+=1
            if mode=='histogram':p[-1]['macd_histogram']+=1
            if mode=='rci':p[-1]['rci']['26']+=1
            if mode=='dma':p[-1]['dma3x3']+=1
            if mode=='stoch':p[-1]['stochastic_k']+=1
            if mode=='quality':i['quality_verified']=False
            if mode=='nan':p[0]['macd_histogram']=float('nan')
            r=assess(t)
            self.assertEqual(r['technical_outlook']['evolution']['status'],'unverified',mode)
            self.assertEqual(r['grade'],'B',mode)
            self.assertEqual(r['practical_review']['status'],'technical_recheck',mode)
            self.assertEqual(report_records({'strategy_assessments':[r]}),[],mode)

    def test_producer_uses_original_seed_and_exact_existing_formulas(self):
        rows=[{'timestamp':CLOCK-(100-i)*3600,'open':100+i*.03,'close':100+i*.03,
               'high':101+i*.03,'low':99+i*.03} for i in range(100)]
        obs=observe(rows,'h1',CLOCK,True)
        self.assertEqual(obs['status'],'available')
        for offset,p in zip((2,1,0),obs['points']):
            prefix=rows[:-offset] if offset else rows
            self.assertEqual(p['macd_histogram'],indicator_reference(prefix)['macd']['histogram'])
            self.assertEqual(p['stochastic_k'],indicator_reference(prefix)['preferred_stochastic']['slow_k'])
            self.assertEqual(p['dma3x3'],dma_snapshot(prefix)['dma']['3x3']['current_plot'])
            for period in (9,26,52):self.assertEqual(p['rci'][str(period)],rci_series([x['close'] for x in prefix],period)[-1])
        self.assertEqual(observe(rows,'h1',CLOCK,False)['status'],'unverified')
        self.assertEqual(observe(rows[:-1],'h1',CLOCK,True)['status'],'unverified')
        self.assertEqual(observe(rows[:50],'h1',CLOCK,True)['status'],'unverified')
        gap=deepcopy(rows);gap[-2]['timestamp']-=3600
        self.assertEqual(observe(gap,'h1',CLOCK,True)['status'],'unverified')

    def test_sorted_json_macro_order_export_and_tamper_detection(self):
        t=temporal_track();t['macro_context']={tf:{'verified':True,'relation':'countertrend'} for tf in ('w1','d1')}
        r=assess(t);self.assertEqual(refresh(json.loads(json.dumps(r,sort_keys=True))),r)
        s=with_record(r);self.assertEqual(validate_strategy_snapshot(s),[])
        b=build_strategy_report_export(json.dumps(s).encode(),SOURCE)
        self.assertEqual(b['status'],'saved');restore_strategy_report_export(b,SOURCE,b['snapshot_git_blob_sha'])
        self.assertIn('確定足3本',render_strategy_report(s,include_all_reviews=True))
        broken=deepcopy(s);x=broken['scheduled_outlook']['strategy_assessments'][0]
        x['technical_outlook']['evolution']['momentum']='counterpressure_deepening'
        self.assertTrue(validate_strategy_snapshot(broken))

    def test_default32_dispatch_and_calendar_cannot_promote_deepening(self):
        def row(pair,data,quality,clock):
            out=_one(pair,{}, {},clock)
            for strategy in ('swing','daytrade'):
                t=temporal_track(strategy,hist=(-.1,-.2,-.3))
                t.update(state='waiting_trigger',reference_timeframe=t['base_timeframe'],
                         reference_plan={},reference_levels={},scenario_explanation={})
                out['strategy_tracks'][strategy]=t
            return out
        with patch('fx_system.scheduled_outlook._one',side_effect=row):o=build_scheduled_outlook({}, {},evaluated_at=CLOCK)
        self.assertEqual(len(o['strategy_assessments']),32)
        self.assertEqual({r['method_version'] for r in o['strategy_assessments']},{METHOD})
        before=deepcopy(o);o=enrich_outlook(o,{'observed_at_utc':CLOCK,'complete':True,'events':[]})
        self.assertEqual(o['assessment_counts'],before['assessment_counts'])
        self.assertTrue(all(r['grade']=='B' and r['practical_review']['status']=='technical_recheck' for r in o['strategy_assessments']))
        s={'evaluated_at':CLOCK,'scheduled_outlook':o};self.assertEqual(validate_strategy_snapshot(s),[])
        b=build_strategy_report_export(json.dumps(s).encode(),SOURCE)
        self.assertEqual(b['status'],'saved');restore_strategy_report_export(b,SOURCE,b['snapshot_git_blob_sha'])
        self.assertEqual(report_records(o),[])

    def test_local_price_breakout_does_not_override_deepening(self):
        t=temporal_track(hist=(-.1,-.2,-.3))
        t['condition_inputs']['bars'][-1].update(open=105,high=108,close=107)
        r=assess(t)
        self.assertEqual(r['scenario_conditions']['status'],'conditions_observed')
        self.assertEqual(r['grade'],'B');self.assertEqual(r['practical_review']['status'],'technical_recheck')


if __name__=='__main__':unittest.main()
