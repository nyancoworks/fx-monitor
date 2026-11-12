import unittest
from copy import deepcopy
from fx_system.sb_momentum import describe
from fx_system.standard_technicals import refresh
from test_technical_entry import record


class BandMomentumTests(unittest.TestCase):
    def test_breakout_and_continuation_are_separate_and_symmetric(self):
        for sign,direction in ((1,'long'),(-1,'short')):
            prices=[200.0]*25+[200+sign*10]
            first=describe(prices,direction,'directional_building')
            second=describe(prices+[200+sign*12],direction,'directional_building')
            self.assertEqual(first['band_event'],'breakout')
            self.assertEqual(first['outside_close_runs']['2'],1)
            self.assertEqual(second['band_event'],'running')
            self.assertEqual(second['outside_close_runs']['2'],2)
            slowed=describe(prices+[200+sign*12,200+sign*8],direction,'directional_fading')
            self.assertEqual(slowed['band_event'],'slowing_inside_two')
            self.assertEqual(first['movement'],'aligned')
            self.assertFalse(first['macd_conflict'])
            self.assertTrue(describe(prices,direction,'counterpressure_deepening')['macd_conflict'])

    def test_flat_and_insufficient_do_not_claim_trend(self):
        self.assertEqual(describe([200]*22,'long','neutral')['status'],'unavailable')
        result=describe([200]*30,'long','neutral')
        self.assertEqual(result['band_event'],'inside_one')
        self.assertEqual(result['movement'],'flat')
        self.assertEqual(result['outside_close_runs'],{'1':0,'2':0})

    def test_context_is_not_a_vote_or_new_gate_and_restores(self):
        new=record('swing')
        old=deepcopy(new);old.pop('sb_detail_version');refresh(old)
        for key in ('direction','grade','assessment','reference_levels','scenario_conditions','practical_review'):
            self.assertEqual(new[key],old[key],key)
        self.assertEqual(refresh(deepcopy(new)),new)
        self.assertEqual(refresh(deepcopy(old)),old)
        self.assertTrue(any('3σ' in x for x in new['reasons']+new['opposing_evidence']))
