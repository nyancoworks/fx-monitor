"""Synthetic, cross-save checks of frozen price plans and candle coverage."""
from copy import deepcopy
import unittest
from unittest.mock import patch

from fx_system.research_followup import build, build_top3_trace, compare_daytrade_top3

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
    def test_top3_listing_links_to_a_later_observed_plan_without_resetting_rank(self):
        waiting = record(START, observed=False)
        waiting['reference_levels'] = {'structural_target': 100.0004}
        rows = {'daytrade': [{'pair': 'EURUSD'}]}
        opening = outlook(START, waiting)
        trace = build_top3_trace(opening, rows, build(opening, DIGEST))
        listed = trace['entries'][0]
        self.assertEqual(listed['first_obstacle_pips_at_listing'], 4)
        self.assertEqual(listed['condition_at_listing'], 'waiting')
        self.assertNotIn('fixed_plan_key', listed)
        later = outlook(START + 3600, record(START + 3600))
        plans = build(later, DIGEST)
        linked = build_top3_trace(later, {}, plans, trace)['entries'][0]
        self.assertEqual(linked['listed_at'], START)
        self.assertEqual(linked['rank'], 1)
        self.assertEqual(linked['fixed_plan_key'], plans['anchors'][0]['key'])

    def test_top3_does_not_link_to_price_plan_observed_before_listing(self):
        past = build(outlook(START, record(START)), DIGEST)
        now = START + 3600
        rows = {'daytrade': [{'pair': 'EURUSD'}]}
        trace = build_top3_trace(outlook(now, record(now, observed=False)), rows, past)
        self.assertNotIn('fixed_plan_key', trace['entries'][0])

    def test_parallel_rankings_follow_observed_plans_and_separate_shared_candidates(self):
        rows = [record(START, observed=False) for _ in range(3)]
        for row, pair in zip(rows, ('EURUSD', 'GBPUSD', 'AUDUSD')):
            row['pair'] = pair
        opening = {'evaluated_at': START, 'strategy_assessments': rows}
        later = START + 3600
        observed = record(later)
        observed['pair'] = 'GBPUSD'
        following = {'evaluated_at': later, 'strategy_assessments': [observed]}
        plans = build(following, DIGEST)
        plan = plans['anchors'][0]
        plan.update(status='complete', events={'obstacle': later + 300, 'local_stop': later + 600})
        with patch('fx_system.strategy_report.report_records', side_effect=[
                rows[:2], [rows[0], rows[2]], [], []]):
            first = compare_daytrade_top3(opening, build(opening, DIGEST))
            result = compare_daytrade_top3(following, plans, first)
        old, new = result['rankings']['5'], result['rankings']['6']
        self.assertEqual(old['outcomes']['shared'], {'waiting_for_plan': 1})
        self.assertEqual(old['outcomes']['exclusive'], {'obstacle_first': 1})
        self.assertEqual(new['outcomes']['exclusive'], {'waiting_for_plan': 1})
        self.assertEqual(old['entries'][1]['listed_at'], START)

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
