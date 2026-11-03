"""Synthetic finite-window/alignment and contextual integration regressions."""
from copy import deepcopy
import json
import math
import unittest
from unittest.mock import patch

from fx_system.span_model import inputs, calculate, note, describe
from fx_system.technical_scenario import refresh
from fx_system.strategy_report_export import build_strategy_report_export, restore_strategy_report_export
from fx_system.validate_strategy_snapshot import validate_strategy_snapshot
from fx_system.strategy_report import report_records
from fx_system.scheduled_outlook import _one, build_scheduled_outlook
from fx_system.scenario_continuity import compare_views, _brief
from test_technical_forecast import track, assess
from test_strategy_strength import CLOCK
from test_strategy_report_export import SOURCE
from test_swing_horizon import with_record


def bars(tf='h4', direction='long', state='held'):
    sec={'h4':14400,'h1':3600,'m15':900,'m5':300}[tf]
    last=(CLOCK//sec-1)*sec
    rows=[{'timestamp':last-(79-i)*sec,'open':105,'high':106,'low':100,'close':105} for i in range(80)]
    if state=='failed':
        for b in rows:b.update(open=115,high=120,low=110,close=115)
        for b in rows[-3:]:b.update(open=105,low=100,close=105)
    elif state=='inside':
        for b in rows[-3:]:b.update(open=103,close=103)
    elif state=='first':
        for b in rows[-3:-1]:b.update(open=102,close=102)
    elif state=='red_opposed':
        for i,b in enumerate(rows):b['high']=107-i*.01
    if direction=='short':
        rows=[{**b,'open':220-b['open'],'close':220-b['close'],
               'high':220-b['low'],'low':220-b['high']} for b in rows]
    return rows


def span_track(strategy='swing',direction='long',base='held',trigger='held',**kwargs):
    t=track(strategy,direction,**kwargs);t['span_model_version']=1
    for role,state in (('base',base),('trigger',trigger)):
        tf=t[role+'_timeframe'];rows=bars(tf,direction,state)
        if role=='base':
            # Keep the real directional price plan and evolution endpoint.
            close=t['technical_plan_inputs']['bar']['close']
            if state=='inside':
                delta=close-rows[-1]['close']
                for b in rows:
                    for k in ('open','high','low','close'):b[k]+=delta
        else:close=t['trigger_price_reference']['close']
        rows[-1]['close']=close
        rows[-1]['high']=max(rows[-1]['high'],close)
        rows[-1]['low']=min(rows[-1]['low'],close)
        frame=t['indicator_context']['frames'][role]
        if not frame['observations']:
            frame['observations']=[{'indicator':'super_bollinger','status':'calculated',
                'application':{'closed_at':rows[-1]['timestamp']+{'m5':300,'m15':900}[tf]}}]
        frame['observations'].append(note(inputs(rows,tf,CLOCK,True)))
    return t


class SpanModelTests(unittest.TestCase):
    def test_independent_extrema_oracle_includes_current_bar_without_cloud_projection(self):
        rows=bars()
        for i,b in enumerate(rows):
            c=100+math.sin(i)*3+i*.1
            b.update(open=c-.1,high=c+1.2,low=c-.8,close=c)
        inp=inputs(rows,'h4',CLOCK,True);before=deepcopy(inp);obs=calculate(inp)
        for point,end in zip(obs['points'],(78,79,80)):
            def mid(period):
                selected=rows[end-period:end]
                return (max(b['high'] for b in selected)+min(b['low'] for b in selected))/2
            self.assertEqual(point['blue'],(mid(9)+mid(26))/2)
            self.assertEqual(point['red'],mid(52))
            self.assertEqual(point['closed_at'],rows[end-1]['timestamp']+14400)
            self.assertEqual(point['lagging_reference_timestamp'],rows[end-27]['timestamp'])
        self.assertEqual(obs['cloud_display_shift'],0)
        self.assertEqual(inp,before)

    def test_price_scaling_and_constant_price_catch_double_price_formula(self):
        rows=bars()
        for b in rows:b.update(open=100,high=100,low=100,close=100)
        o=calculate(inputs(rows,'h4',CLOCK,True))
        self.assertTrue(all(p['blue']==p['red']==100 for p in o['points']))
        for b in rows:
            for k in ('open','high','low','close'):b[k]*=1.5
        o=calculate(inputs(rows,'h4',CLOCK,True))
        self.assertTrue(all(p['blue']==p['red']==150 for p in o['points']))

    def test_lagging_cloud_is_historical_not_current_or_past_close(self):
        rows=bars()
        for b in rows[:54]:b.update(open=90,high=91,low=89,close=90)
        for b in rows[54:]:b.update(open=110,high=111,low=109,close=110)
        o=calculate(inputs(rows,'h4',CLOCK,True));last=o['points'][-1]
        self.assertEqual(last['lagging_candle_location'],'above')
        self.assertEqual(last['lagging_cloud_location'],'above')
        self.assertEqual(last['lagging_reference_timestamp'],rows[-27]['timestamp'])

    def test_missing_gap_invalid_stale_future_and_unverified_are_not_filled(self):
        for mode in ('short','gap','bad','nan','future','stale','quality'):
            rows=bars();clock=CLOCK;quality=True
            if mode=='short':rows.pop(0)
            if mode=='gap':rows[5]['timestamp']+=14400
            if mode=='bad':rows[5]['low']=rows[5]['high']+1
            if mode=='nan':rows[5]['high']=float('nan')
            if mode=='future':clock-=14400
            if mode=='stale':clock+=14400
            if mode=='quality':quality=False
            self.assertIsNone(calculate(inputs(rows,'h4',clock,quality)),mode)

    def test_bounded_input_and_sorted_json_are_deterministic(self):
        rows=bars();prefix=[{**rows[0],'timestamp':rows[0]['timestamp']-14400}]
        a=inputs(rows,'h4',CLOCK,True);b=inputs(prefix+rows,'h4',CLOCK,True)
        self.assertEqual(a,b)
        self.assertEqual(calculate(a),calculate(json.loads(json.dumps(b,sort_keys=True))))

    def test_production_no_longer_generates_span_inputs(self):
        from fx_system.indicator_refresh import refresh_strategy_indicators
        from fx_system.strategy_indicator_context import strategy_indicator_context
        from fx_system.technical_forecast import prepare_track
        from fx_system.dinapoli_research import dma_snapshot,confirmed_fibonacci
        frames={tf:bars(tf) if tf in ('h4','h1','m15','m5') else []
                for tf in ('w1','d1','h4','h1','m15','m5')}
        q={'evaluated_at':CLOCK,'timeframes':{tf:{'ok':bool(rows)} for tf,rows in frames.items()}}
        data={tf:{'candles':rows} for tf,rows in frames.items()}
        data['h4_setup_shadow']={'dinapoli':{**dma_snapshot(frames['h4']),
             'confirmed_fibonacci':confirmed_fibonacci(frames['h4'],'long')}}
        refresh_strategy_indicators(data,frames,frames,q,{})
        self.assertNotIn('span_model_version',data)
        self.assertNotIn('span_model_inputs',data)
        self.assertEqual(data['standard_technical_version'],1)

    def test_comparison_drops_duplicate_wording_but_keeps_role_states_and_original(self):
        r=assess(span_track());original=deepcopy(r)
        projection=_brief(r)['technical_outlook']['forecast']['span_model']
        for role in ('base','trigger'):
            self.assertNotIn('summary',projection[role])
            self.assertEqual(projection[role]['state'],'directional_position_held')
            self.assertIn('lagging_cloud_location',r['technical_outlook']['forecast']['span_model'][role])
        self.assertEqual(r,original)

    def test_both_strategies_directions_held_cloud_does_not_change_prices_or_add_votes(self):
        for strategy in ('swing','daytrade'):
            for direction in ('long','short'):
                legacy=assess(track(strategy,direction),strategy)
                r=assess(span_track(strategy,direction),strategy)
                self.assertEqual(r['direction'],legacy['direction'])
                self.assertEqual(r['wave_price_plan'],legacy['wave_price_plan'])
                self.assertEqual(r['reference_levels'],legacy['reference_levels'])
                self.assertEqual(r['technical_outlook']['forecast']['span_model']['base']['state'],'directional_position_held')
                self.assertEqual(r['grade'],legacy['grade'])

    def test_inside_and_first_recovery_do_not_become_a_or_reverse_direction(self):
        for state in ('inside','first'):
            r=assess(span_track(base=state))
            self.assertEqual(r['direction'],'long');self.assertEqual(r['grade'],'B')
            self.assertEqual(r['technical_outlook']['forecast']['phase'],'recovery_wait')

    def test_cloud_failure_and_red_background_conflict_are_explained_not_forced_reversals(self):
        for state in ('failed','red_opposed'):
            for direction in ('long','short'):
                r=assess(span_track(direction=direction,base=state))
                self.assertEqual(r['direction'],direction);self.assertEqual(r['grade'],'C')
                self.assertEqual(r['practical_review']['status'],'technical_recheck')
                self.assertEqual(report_records({'strategy_assessments':[r]}),[])

    def test_trigger_cloud_failure_waits_for_entry_without_reversing_base(self):
        for strategy in ('swing','daytrade'):
            r=assess(span_track(strategy,trigger='failed'),strategy)
            self.assertEqual(r['direction'],'long');self.assertEqual(r['grade'],'B')
            self.assertEqual(r['technical_outlook']['forecast']['phase'],'continuation')
            self.assertEqual(r['practical_review']['status'],'entry_recheck')
            self.assertIn('雲の反対側',r['grade_reason'])

    def test_cloud_recovery_cannot_rescue_deepening_momentum(self):
        r=assess(span_track(base='first',hist=(-.1,-.2,-.3)))
        self.assertEqual(r['technical_outlook']['forecast']['phase'],'pullback_deepening')
        self.assertEqual(r['grade'],'C')

    def test_wrong_frame_clock_endpoint_or_observation_is_not_trusted(self):
        r=assess(span_track())
        for mode in ('clock','timeframe','close','blue','quality','missing'):
            broken=deepcopy(r);n=broken['indicator_context']['frames']['base']['observations'][-1]
            if mode=='clock':n['inputs']['evaluated_at']+=1
            if mode=='timeframe':n['inputs']['timeframe']='h1'
            if mode=='close':n['inputs']['closes'][-1]-=.1;n['observation']=calculate(n['inputs'])
            if mode=='blue':n['observation']['points'][-1]['blue']+=1
            if mode=='quality':n['inputs']['quality_verified']=False
            if mode=='missing':broken['indicator_context']['frames']['base']['observations'].pop()
            self.assertEqual(describe(broken)['status'],'unverified',mode)

    def test_old_v12_records_keep_exact_original_interpretation(self):
        r=assess(track());before=deepcopy(r)
        self.assertNotIn('span_model_version',r)
        self.assertEqual(refresh(json.loads(json.dumps(r,sort_keys=True))),before)
        self.assertNotIn('span_model',r['technical_outlook']['forecast'])

    def test_all32_export_restore_adjacent_comparison_and_tamper_rejection(self):
        def row(pair,data,quality,clock,method=None):
            out=_one(pair,{}, {},clock)
            for strategy in ('swing','daytrade'):
                t=span_track(strategy);t.update(state='watch',reference_timeframe=t['base_timeframe'],
                    reference_plan={},reference_levels={},scenario_explanation={})
                out['strategy_tracks'][strategy]=t
            return out
        with patch('fx_system.scheduled_outlook._one',side_effect=row):
            o=build_scheduled_outlook({}, {},evaluated_at=CLOCK)
        s={'evaluated_at':CLOCK,'scheduled_outlook':o}
        self.assertEqual(validate_strategy_snapshot(s),[])
        b=build_strategy_report_export(json.dumps(s).encode(),SOURCE)
        self.assertEqual(b['status'],'saved')
        v=restore_strategy_report_export(b,SOURCE,b['snapshot_git_blob_sha'])
        self.assertEqual(v['scheduled_outlook']['strategy_assessments'],o['strategy_assessments'])
        comparison=compare_views(v,v)
        self.assertEqual(len(comparison),32)
        self.assertLess(len(json.dumps(comparison,ensure_ascii=False).encode()),512*1024)
        for version in (True,2,'1'):
            broken=deepcopy(v);broken['scheduled_outlook']['strategy_assessments'][0]['span_model_version']=version
            self.assertTrue(validate_strategy_snapshot(broken))
        broken=deepcopy(v)
        broken['scheduled_outlook']['strategy_assessments'][0]['indicator_context']['frames']['base']['observations'][-1]['observation']['points'][-1]['red']+=1
        self.assertTrue(validate_strategy_snapshot(broken))


if __name__=='__main__':unittest.main()
