"""Synthetic price-phase regression cases; no market observations."""
import unittest
from copy import deepcopy
from unittest.mock import patch
from fx_system.advisory_indicators import stddev_bands
from fx_system.standard_technicals import bollinger_regime, refresh
from fx_system.technical_entry import timing_signals, describe
from fx_system.scenario_conditions import validate_conditions
from test_technical_entry import record


class PhaseTests(unittest.TestCase):
    def test_correction_starts_inside_one_before_middle_and_mirrors(self):
        for sign, lag, expected in ((1,'above','short'),(-1,'below','long')):
            closes = [200+sign*i for i in range(30)]+[200+sign*24]
            band = stddev_bands(closes)[-1]
            sb = {'status':'calculated','lagging_span':{'location':lag},
                  'last_close':closes[-1], 'centerline':band['middle'],
                  'bands':band['bands'],'bandwidth_state':'flat'}
            self.assertEqual(bollinger_regime(sb)[1], 'gradual_trend')
            self.assertEqual(bollinger_regime(sb, closes), (expected,'correction'))
            renewed = closes[:-1]+[200+sign*31]
            b = stddev_bands(renewed)[-1]
            sb.update(last_close=renewed[-1], centerline=b['middle'],bands=b['bands'])
            self.assertEqual(bollinger_regime(sb, renewed)[0], 'long' if sign==1 else 'short')

    def test_sustained_band_does_not_require_a_new_cross(self):
        for sign, direction in ((1,'long'),(-1,'short')):
            closes = [200+sign*i for i in range(30)]
            self.assertNotIn('sb_one_sigma_cross', timing_signals(closes,direction))
            self.assertNotIn('sb_one_sigma_hold', timing_signals(closes,direction))
            self.assertIn('sb_one_sigma_hold',timing_signals(closes,direction,continuation=True))
        self.assertNotIn('sb_one_sigma_hold',timing_signals([200]*30,'long',continuation=True))

    def test_new_timing_does_not_force_only_sigma_during_adjustment(self):
        r=record('swing')
        self.assertEqual(r['multi_timing_version'],3)
        r['timing_context']='pullback'
        with patch('fx_system.technical_entry.timing_signals',return_value=['macd_signal_cross']):
            self.assertEqual(describe(r)['status'],'conditions_observed')
        with patch('fx_system.technical_entry.timing_signals',return_value=['sb_one_sigma_hold']):
            self.assertIn('維持',describe(r)['summary'])
        self.assertEqual(validate_conditions(r),[])
        for v in (1,2,3):
            old=deepcopy(r);old['multi_timing_version']=v
            old['bollinger_regime_version']=1 if v<3 else 2
            restored=refresh(old)
            self.assertEqual(refresh(deepcopy(restored)),restored)
