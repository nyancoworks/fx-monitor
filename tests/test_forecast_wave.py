from copy import deepcopy
import json
import math
import unittest
from unittest.mock import patch
from fx_system.forecast_wave import inputs,select
from fx_system.technical_scenario import refresh,build_plan
from fx_system.strategy_report_export import build_strategy_report_export,restore_strategy_report_export
from fx_system.scheduled_outlook import _one,build_scheduled_outlook
from test_technical_forecast import track,assess
from test_strategy_strength import CLOCK
from test_strategy_report_export import SOURCE


def candles(direction='long'):
    last=(CLOCK//14400-1)*14400
    rows=[]
    for i in range(120):
        c=(140-.5*i if i<40 else 120+.5*(i-40) if i<80 else 140-.1*(i-80))+math.sin(i*.8)
        rows.append({'timestamp':last-(119-i)*14400,'open':c-.1,'high':c+.4,'low':c-.4,'close':c})
    if direction=='short':
        rows=[{**b,'open':280-b['open'],'high':280-b['low'],'low':280-b['high'],'close':280-b['close']} for b in rows]
    return rows


def parent_track(direction='long'):
    t=track('swing',direction);rows=candles(direction);bar=t['technical_plan_inputs']['bar']
    shift=bar['close']-rows[-1]['close']
    for b in rows:
        for k in ('open','high','low','close'):b[k]+=shift
    rows[-1]=deepcopy(bar)
    t.update(forecast_wave_version=1,forecast_wave_inputs=inputs(rows,CLOCK,True))
    return t


class ForecastWaveTests(unittest.TestCase):
    def test_parent_keeps_nested_pivots_separate_without_rr_selection(self):
        for direction in ('long','short'):
            rows=candles(direction);a=select(inputs(rows,CLOCK,True),direction)
            self.assertEqual(a['status'],'available')
            # There are many nested pivots after the parent endpoint. Merely
            # making those local pivots more recent must not shrink the wave.
            self.assertGreater(len(a['highs']),2);self.assertGreater(len(a['lows']),2)
            self.assertLess(a['projection']['end_pivot']['timestamp'],a['highs' if direction=='long' else 'lows'][-1]['timestamp'])
            self.assertTrue(a['selection']['does_not_optimize_distance_or_rr'])
            changed=deepcopy(rows)
            for b in changed[-8:-3]:
                b['high']+=.05;b['low']-=.05
            b=select(inputs(changed,CLOCK,True),direction)
            self.assertEqual(a['projection'],b['projection'])

    def test_dma_cycle_uses_existing_displaced_sma_slope_and_preserves_conflict(self):
        from fx_system.dinapoli_research import dma_snapshot
        rows=candles();selected=select(inputs(rows,CLOCK,True),'long')
        self.assertEqual(selected['status'],'available')
        for i in range(31,len(rows)+1):
            slope=dma_snapshot(rows[:i])['dma']['25x5']['plot_slope']
            expected=(rows[i-6]['close']-rows[i-31]['close'])/25
            self.assertAlmostEqual(slope,expected)
        self.assertEqual(selected['selection']['background_relation'],'opposed')

    def test_all_pivots_remain_strictly_confirmed_and_parent_precedes_endpoint(self):
        rows=candles();s=select(inputs(rows,CLOCK,True),'long')
        index={b['timestamp']:i for i,b in enumerate(rows)}
        for key,field,compare in [('highs','high',lambda x,y:x>y),('lows','low',lambda x,y:x<y)]:
            for p in s[key]:
                i=index[p['timestamp']]
                self.assertTrue(all(compare(p['price'],rows[j][field]) for j in (i-2,i-1,i+1,i+2)))
                self.assertLessEqual(i+2,len(rows)-1)
        self.assertLess(s['projection']['start_pivot']['timestamp'],s['projection']['end_pivot']['timestamp'])

    def test_historical_origin_breach_is_not_resurrected_by_a_bounce(self):
        t=parent_track();s=select(t['forecast_wave_inputs'],'long');origin=s['projection']['start_pivot']['price']
        raw=t['forecast_wave_inputs']['hlc'];raw[-5]=[origin+1,origin-2,origin-1]
        r=assess(t)
        self.assertEqual(r['wave_price_plan']['status'],'invalidated')
        self.assertGreater(r['wave_price_plan']['reference_close'],origin)
        self.assertLess(r['expiry']['observation']['saved_close'],origin)
        self.assertIsNone(r['reference_levels']['scenario_target'])

    def test_future_gap_quality_insufficient_and_wrong_endpoint_are_not_inferred(self):
        for mode in ('future','gap','quality','short','endpoint'):
            rows=candles();quality=True;clock=CLOCK
            if mode=='future':clock-=14400
            if mode=='gap':rows[50]['timestamp']+=14400
            if mode=='quality':quality=False
            if mode=='short':rows=rows[-30:]
            self.assertEqual(inputs(rows,clock,quality)['status'],'available' if mode=='endpoint' else 'unverified')
            if mode=='endpoint':
                t=parent_track();t['forecast_wave_inputs']['hlc'][-1][2]-=.01
                r=assess(t);self.assertEqual(r['assessment'],'evaluation_pending')

    def test_new_parent_does_not_change_forecast_direction_or_daytrade(self):
        for direction in ('long','short'):
            t=parent_track(direction);r=assess(t)
            self.assertEqual(r['direction'],direction)
            self.assertEqual(r['wave_price_plan']['anchor_basis'],'forecast_direction_dma25x5_cycle_confirmed_h4_parent_wave')
            self.assertEqual(refresh(json.loads(json.dumps(r,sort_keys=True))),r)
            for version in (True,2,'1'):
                broken=deepcopy(r);broken['forecast_wave_version']=version
                with self.assertRaises(ValueError):refresh(broken)
        old=assess(track('daytrade'),'daytrade');self.assertEqual(refresh(deepcopy(old)),old)
        self.assertNotIn('forecast_wave_inputs',old)

    def test_rr_or_local_trigger_changes_cannot_select_a_different_parent(self):
        r=assess(parent_track());before=build_plan(r)
        r['trigger_price_reference']['close']*=1.01
        r['reference_plan']={'reference_rr':1000,'scenario_target':99999}
        self.assertEqual(build_plan(r),before)

    def test_exact_export_32_and_original_record_survive_sorted_json(self):
        def row(pair,data,quality,clock,method=None):
            out=_one(pair,{}, {},clock)
            for strategy in ('swing','daytrade'):
                t=parent_track() if strategy=='swing' else track('daytrade')
                t.update(state='watch',reference_timeframe=t['base_timeframe'],reference_plan={},reference_levels={},scenario_explanation={})
                out['strategy_tracks'][strategy]=t
            return out
        with patch('fx_system.scheduled_outlook._one',side_effect=row):o=build_scheduled_outlook({}, {},evaluated_at=CLOCK)
        snapshot={'evaluated_at':CLOCK,'scheduled_outlook':o};original=deepcopy(snapshot)
        bundle=build_strategy_report_export(json.dumps(snapshot).encode(),SOURCE)
        self.assertEqual(bundle['status'],'saved')
        restored=restore_strategy_report_export(bundle,SOURCE,bundle['snapshot_git_blob_sha'])
        self.assertEqual(snapshot,original)
        self.assertEqual(restored['scheduled_outlook']['strategy_assessments'],o['strategy_assessments'])
