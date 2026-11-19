import unittest
from copy import deepcopy

from fx_system.activate_time import analyze, observe_pair, validate_pair, swing_line


def frame(highs, lows, *, clock=None):
    bars = [{'timestamp': i*86400, 'high': high, 'low': low,
             'close': (10.5 if i == len(highs)-1 and high >= 10.5 else 9)}
            for i,(high,low) in enumerate(zip(highs,lows))]
    end = len(bars)*86400
    return {'timeframe':'d1','evaluated_at':clock or end, 'verified':True,
            'status':'available', 'closed_at':end, 'bars':bars}


class PublicTimeAnalysisTests(unittest.TestCase):
    def test_confirmed_pivot_inclusive_nine_and_price_confirmation(self):
        highs=[10]*12;highs[3]=15;highs[-1]=11
        f=frame(highs,[8]*12)
        observation=analyze(f,'d1',f['evaluated_at'])
        self.assertEqual(observation['basic'][0]['elapsed_bars_inclusive'],9)
        self.assertIn(9,observation['basic'][0]['matching_counts'])
        self.assertEqual(observation['price_confirmation'],'above_previous_high')
        # The final candle cannot be a pivot until two later candles confirm it.
        self.assertEqual(observation['basic'][0]['pivot_at'],3*86400)
        self.assertEqual(analyze(f,'d1',f['evaluated_at']-1)['status'],'unavailable')

    def test_equal_time_and_cycle_are_separate_observations(self):
        highs=[10]*18;lows=[8]*18
        for i in (3,8,13):highs[i]=15
        f=frame(highs,lows)
        self.assertEqual(analyze(f,'d1',f['evaluated_at'])['cycles'][0]['interval_bars'],[5,5])
        highs=[10]*18;lows=[8]*18;highs[4]=15;lows[10]=5
        f=frame(highs,lows)
        self.assertEqual(analyze(f,'d1',f['evaluated_at'])['equal_time'][0]['duration_bars_inclusive'],7)

    def test_saved_context_recomputes_and_cannot_alter_evidence(self):
        highs=[10]*12;highs[3]=15;highs[-1]=11
        f=frame(highs,[8]*12)
        context=observe_pair({'d1':f},f['evaluated_at'])
        self.assertTrue(validate_pair(context,f['evaluated_at']))
        self.assertIn('方向・評価・売買許可には使わない',swing_line(context))
        bad=deepcopy(context)
        bad['timeframes']['d1']['observation']['basic']=[]
        self.assertFalse(validate_pair(bad,f['evaluated_at']))
        self.assertFalse(validate_pair(context,f['evaluated_at']+1))
