import unittest
from copy import deepcopy
from unittest.mock import patch
from fx_system.standard_technicals import forecast, refresh, wave
from test_technical_entry import record


class DirectionContextTests(unittest.TestCase):
    def test_band_reentry_is_not_automatic_scenario_reversal(self):
        for trend,move,lag,position,sgn in (('short','long','below','below',1),('long','short','above','above',-1)):
            f=record()['standard_inputs']['base']
            f['super_bollinger']['lagging_span']['location']=lag
            for m in f['macd']['observations']:m.update(histogram=sgn*.1,line=sgn*.2)
            with patch('fx_system.standard_technicals.bollinger_regime',return_value=(move,'correction')), patch('fx_system.span_special.observe',return_value={'status':'available','last':{'blue_position':position}}):
                out=forecast(f,'unconfirmed',bollinger_regimes=True,regime_transitions=True,direction_context=True)
                old=forecast(f,'unconfirmed',bollinger_regimes=True,regime_transitions=True)
            self.assertEqual(old['direction'],move)
            self.assertEqual(out['direction'],trend)
            self.assertEqual(out['direction_context']['movement_direction'],move)
            self.assertEqual(out['phase'],'recovery_wait')
            with patch('fx_system.standard_technicals.bollinger_regime',return_value=(move,'correction')), patch('fx_system.span_special.observe',return_value={'status':'available','last':{'blue_position':'above' if move=='long' else 'below'}}):
                developed=forecast(f,'unconfirmed',bollinger_regimes=True,regime_transitions=True,direction_context=True)
            self.assertEqual(developed['direction'],move)
            self.assertEqual(developed['direction_context']['scenario_kind'],'countertrend_hypothesis')
            self.assertEqual(developed['conviction'],'weak')

    def test_price_plan_absence_is_not_missing_candles(self):
        r=record();empty=wave([],r['direction'])
        with patch('fx_system.standard_technicals.wave',return_value=deepcopy(empty)):
            new=refresh(deepcopy(r))
            old=deepcopy(r);old.pop('scenario_state_version');refresh(old)
        self.assertEqual(new['assessment'],'skip')
        self.assertEqual(new['skip_reason'],'price_plan_unformed')
        self.assertIn('確定足は取得済み',new['grade_reason'])
        self.assertEqual(old['assessment'],'evaluation_pending')

    def test_old_records_and_new_context_restore(self):
        r=record('swing');self.assertEqual(refresh(deepcopy(r)),r)
        old=deepcopy(r);old.pop('scenario_state_version');refresh(old)
        self.assertNotIn('direction_context',old['technical_outlook']['forecast'])
        self.assertEqual(refresh(deepcopy(old)),old)
        bad=deepcopy(r);bad['scenario_state_version']=True
        with self.assertRaises(ValueError):refresh(bad)
