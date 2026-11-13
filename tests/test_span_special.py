import unittest
from copy import deepcopy
from fx_system.span_special import observe, timing, apply
from fx_system.standard_technicals import refresh
from test_technical_entry import record


def rows(values):
    return [dict(timestamp=3600*(i+1),open=c,high=c+.1,low=c-.1,close=c) for i,c in enumerate(values)]


class SpanSpecialTests(unittest.TestCase):
    def test_confirmed_changes_are_directional_and_not_missing_history(self):
        for sign,side,slope in ((1,'above','up'),(-1,'below','down')):
            data=rows([100.]*80+[100+sign*10])
            changes=observe(data,'h1',transitions=True)['confirmed_changes']
            by={x['component']:x for x in changes}
            for component in ('blue_position','lag_candle','lag_zone'):
                self.assertEqual(by[component]['before'],'inside')
                self.assertEqual(by[component]['after'],side)
                self.assertEqual(by[component]['timestamp'],data[-1]['timestamp'])
            self.assertEqual(by['red_slope']['before'],'flat')
            self.assertEqual(by['red_slope']['after'],slope)
            # One more unchanged bar flattens the red span; it does not reverse it.
            later=observe(rows([100.]*80+[100+sign*10]*2),'h1',transitions=True)
            red=next(x for x in later['confirmed_changes'] if x['component']=='red_slope')
            self.assertEqual(red['after'],'flat')
        partial=observe(rows([100.]*77+[110.]),'h1',transitions=True)
        self.assertNotIn('lag_zone',[x['component'] for x in partial['confirmed_changes']])
        self.assertNotIn('confirmed_changes',observe(rows([100.]*90),'h1'))

    def test_transition_evidence_preserves_grades_and_old_restoration(self):
        r=record('swing');self.assertEqual(refresh(deepcopy(r)),r)
        old=deepcopy(r);old.pop('span_transition_version');refresh(old)
        self.assertEqual(refresh(deepcopy(old)),old)
        self.assertNotIn('confirmed_changes',old['technical_outlook']['forecast']['span_special'])
        for key in ('direction','grade','assessment','scenario_conditions','reference_levels'):
            self.assertEqual(r[key],old[key])
        r['span_transition_version']=True
        with self.assertRaises(ValueError):refresh(r)

    def test_flat_and_midpoint_formula(self):
        result=observe(rows([100.]*90),'h1')
        self.assertEqual(result['last']['blue'],100)
        self.assertEqual(result['last']['red'],100)
        self.assertEqual(result['red_slope'],'flat')
        self.assertEqual(result['last']['lag_zone'],'inside')
        self.assertIsNone(result['signal_event'])
        self.assertEqual(observe(rows([100.]*52),'h1')['status'],'unavailable')
        self.assertEqual(observe(rows([100.]*53),'h1')['last']['lag_zone'],'unavailable')

    def test_trend_mirror_and_no_future_lag(self):
        for sign,loc in ((1,'above'),(-1,'below')):
            data=rows([100+sign*i*.1 for i in range(100)])
            result=observe(data,'h1')
            self.assertEqual(result['last']['blue_position'],loc)
            self.assertEqual(result['last']['lag_candle'],loc)
            self.assertEqual(result['last']['lag_zone'],loc)
            expected=(max(b['high'] for b in data[-9:])+min(b['low'] for b in data[-9:])+max(b['high'] for b in data[-26:])+min(b['low'] for b in data[-26:]))/4
            self.assertAlmostEqual(result['last']['blue'],expected)

    def test_cloud_buy_signal_can_be_sell_sign_and_window_expires(self):
        data=rows([100.]*80+[110.]*9)
        result=observe(data,'h1')['signal_event']
        self.assertEqual(result['signal'],'long')
        self.assertEqual(result['sign'],'short')
        self.assertEqual(result['pattern'],'reverse')
        self.assertTrue(result['within_grace'])
        later=observe(rows([100.]*80+[110.]*14),'h1')['signal_event']
        self.assertFalse(later['within_grace'])
        mirror=observe(rows([100.]*80+[90.]*9),'h1')['signal_event']
        self.assertEqual(mirror['sign'],'long')

    def test_recovery_is_not_cloud_colour_and_old_records_restore(self):
        for sign,direction in ((1,'long'),(-1,'short')):
            self.assertEqual(timing(rows([100.]*80+[100+sign*10]),'m15',direction),['span_blue_recovery'])
        r=record('swing')
        self.assertEqual(r['span_special_version'],1)
        self.assertIn('span_special',r['technical_outlook']['forecast'])
        self.assertEqual(refresh(deepcopy(r)),r)
        old=deepcopy(r);old.pop('span_special_version');refresh(old)
        self.assertNotIn('span_special',old['technical_outlook']['forecast'])
        self.assertNotIn('span_model',old['technical_profile'])
        self.assertEqual(refresh(deepcopy(old)),old)
        bad=deepcopy(r);bad['span_special_version']=True
        with self.assertRaises(ValueError):refresh(bad)

    def test_span_alone_is_not_a_downgrade_gate(self):
        frame={'status':'available','timeframe':'h1','bars':rows([110-i*.1 for i in range(100)])}
        base={'direction':'long','support':[],'cautions':[],'material_cautions':[],
              'evolution':{'momentum':'directional_building'},'conviction':'developing','phase':'continuation','primary_path':'trend'}
        f=apply(frame,deepcopy(base))
        self.assertEqual(f['conviction'],'developing')
        base['evolution']['momentum']='counterpressure_deepening'
        self.assertEqual(apply(frame,base)['conviction'],'weak')

    def test_frozen_blue_recovery_uses_high_low_history(self):
        from unittest.mock import patch
        from fx_system.scenario_followthrough import observe_frozen_condition
        r=record();clock=r['evaluated_at'];start=(clock//300)*300
        prefix=[dict(timestamp=start-(80-i)*300,open=200.,high=200.1,low=199.9,close=200.) for i in range(80)]
        r['standard_inputs']['trigger']['bars']=prefix
        r['direction']='long';r['assessment']='review'
        r['wave_price_plan']['local_setup_failure']=190.
        r['reference_levels'].update(invalidation=190.,scenario_target=210.)
        r['scenario_conditions'].update(status='waiting',conditions=[{'kind':'span_blue_recovery'}])
        future=[dict(timestamp=start,open=200.,high=201.1,low=199.9,close=201.)]
        pair={'decision_data':{'raw':{'m5':future},'provenance':{f'm5:{start}':'Twelve Data'}}}
        with patch('fx_system.scenario_followthrough.validate_conditions',return_value=[]), patch('fx_system.technical_entry.timing_signals',return_value=[]):
            out=observe_frozen_condition(r,pair,start+300)
        self.assertEqual(out['status'],'frozen_condition_observed')
        self.assertEqual(out['condition_observation']['closed_at'],start+300)
