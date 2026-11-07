import unittest
from unittest.mock import patch

from fx_system.long_swing import build_long_swing


class LongSwingTests(unittest.TestCase):
    def test_d1_levels_and_h4_reaction_are_separate(self):
        rows = [{'timestamp':i*14400,'open':110,'high':112,'low':109,'close':110}
                for i in range(1,5)]
        frames = {'w1':{'verified':True,'super_bollinger':{'status':'calculated','centerline_direction':'down'}},
                  'd1':{'verified':True,'status':'available','closed_at':57600,'bars':rows},
                  'h4':{'verified':True,'closed_at':72000,'bars':rows}}
        pairs = {'USDJPY':{'standard_technical_frames':frames}}
        with patch('fx_system.long_swing.forecast', return_value={
            'status':'available','direction':'long','primary_path':'synthetic'}), patch(
            'fx_system.long_swing.wave', return_value={
            'status':'available','retest_objective':{'price':120},'thesis_invalidation':100}):
            result, = build_long_swing(pairs, 72001)
            self.assertEqual((result['status'], result['weekly_direction']), ('waiting','down'))
            self.assertEqual((result['target'], result['invalidation'],result['reaction_level']), (120,100,112))
            rows[-1].update(high=114,close=113)
            result, = build_long_swing(pairs, 72001)
            self.assertEqual((result['status'],result['reward_pips']), ('observed',700))
            frames['h4']['verified'] = False
            result, = build_long_swing(pairs, 72001)
            self.assertEqual(result['status'],'pending')
