"""Synthetic, cross-save checks of frozen price plans and candle coverage."""
from copy import deepcopy
import unittest
from unittest.mock import patch

from fx_system.research_followup import build

START = 360001


def record(clock, *, observed=True, missing=False):
    bars = []
    for stamp in range(360300, 363600, 300):
        if missing and stamp == 360900:
            continue
        high = 103 if stamp == 360300 else 100
        close = 98 if stamp == 360600 else 100
        bars.append({'timestamp':stamp, 'open':100, 'high':high,
                     'low':min(98,close), 'close':close})
    return {'pair':'EURUSD', 'strategy':'daytrade', 'direction':'long',
            'assessment':'review', 'evaluated_at':clock,
            'scenario_conditions':{'status':'conditions_observed' if observed else 'waiting'},
            'wave_price_plan':{'status':'available', 'reference_close_timestamp':360000,
                               'local_setup_failure':99,
                               'retest_objective':{'price':102}, 'thesis_invalidation':95},
            'trigger_price_review':{'saved_close':100,'first_obstacle_reward':1},
            'practical_review':{'reference_margin_sufficient':False},
            'standard_inputs':{
                'trigger':{'timeframe':'m5','verified':True,'bars':bars},
                'base':{'timeframe':'h1','verified':True,'bars':[
                    {'timestamp':360000,'open':100,'high':103,'low':94,'close':94}]}}}


def outlook(clock, value):
    return {'evaluated_at':clock, 'strategy_assessments':[value]}


DIGEST = {'observations':[{'pair':'EURUSD','timeframe':'d1',
                            'bars_sha256':'a'*64,'basic_count':1,
                            'equal_time_count':0,'cycle_count':0}]}


class ResearchFollowupTests(unittest.TestCase):
    def test_complete_candle_path_and_same_bar_order_unknown(self):
        with patch.dict('fx_system.research_followup.HORIZON', daytrade=3600):
            initial=build(outlook(START,record(START)),DIGEST)
            self.assertEqual(len(initial['anchors']),1)
            later=build(outlook(START+3600,record(START+3600)),DIGEST,initial)
        anchor=later['anchors'][0]
        self.assertEqual(anchor['status'],'complete')
        self.assertEqual(len(later['anchors']),1)
        self.assertEqual(anchor['events']['obstacle'],anchor['events']['wave_goal'])
        self.assertLess(anchor['events']['obstacle'],anchor['events']['local_stop'])
        self.assertEqual(anchor['events']['thesis_withdrawal'],363600)
        self.assertFalse(anchor['reference_margin_sufficient'])
        self.assertTrue(anchor['daily_candidate_present'])
        self.assertEqual(initial['anchors'][0]['events'],{})

    def test_missing_trigger_bar_censors_instead_of_inventing_order(self):
        with patch.dict('fx_system.research_followup.HORIZON', daytrade=3600):
            initial=build(outlook(START,record(START)),DIGEST)
            later=build(outlook(START+3600,record(START+3600,missing=True)),DIGEST,initial)
        self.assertEqual(later['anchors'][0]['status'],'censored_coverage')
        self.assertEqual(later['anchors'][0]['missing_trigger_bars'],1)
        self.assertEqual(initial['anchors'][0]['status'],'tracking')
