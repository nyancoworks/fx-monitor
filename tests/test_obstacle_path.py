from copy import deepcopy
import json
import unittest
from fx_system.technical_scenario import refresh, render_lines
from fx_system.strategy_report_export import build_strategy_report_export, restore_strategy_report_export
from test_technical_interpretation import contextual
from test_technical_forecast import assess
from test_swing_horizon import with_record
from test_strategy_report_export import SOURCE


def scenario(strategy='swing', direction='long', closes=(105,105,105,105,107), hist=(.1,.2,.3)):
    t=contextual(strategy,direction,hist=hist);t['obstacle_path_version']=1
    inp=t['technical_plan_inputs'];sec=14400 if strategy=='swing' else 3600
    sign=1 if direction=='long' else -1
    mirror=lambda p:p if sign==1 else 220-p
    anchors=inp['highs' if sign==1 else 'lows']
    for price in (105.5,108):anchors.append({'price':mirror(price),'timestamp':inp['bar']['timestamp']-4*sec})
    for bar,close in zip(t['condition_inputs']['bars'],closes):
        lo,hi=close-.4,close+.4
        bar.update(open=mirror(close-.1),close=mirror(close),
                   low=mirror(lo if sign==1 else hi),high=mirror(hi if sign==1 else lo))
    t['trigger_price_reference']['close']=mirror(closes[-1])
    return t


class ObstaclePathTests(unittest.TestCase):
    def test_close_cross_changes_obstacle_role_both_directions_and_strategies(self):
        for strategy in ('swing','daytrade'):
            for direction in ('long','short'):
                r=assess(scenario(strategy,direction),strategy);p=r['obstacle_path_review']
                self.assertEqual(p['reaction'],'breakout_close_observed')
                self.assertEqual(p['active_obstacle']['price'],108 if direction=='long' else 112)
                self.assertEqual(r['wave_price_plan']['first_obstacle']['price'],105.5 if direction=='long' else 114.5)
                self.assertEqual(r['reference_levels']['structural_target'],p['active_obstacle']['price'])
                self.assertGreater(r['trigger_price_review']['first_obstacle_reward'],0)
                self.assertNotEqual(r['grade'],'A')
                self.assertIn('通過水準', '\n'.join(render_lines(r)))
                old=deepcopy(r);old.pop('obstacle_path_version');old.pop('obstacle_path_review');refresh(old)
                self.assertEqual(old['wave_price_plan'],r['wave_price_plan'])
                self.assertEqual(old['reference_levels']['scenario_target'],r['reference_levels']['scenario_target'])
                self.assertEqual(old['direction'],r['direction'])

    def test_wick_and_equal_close_cannot_clear_obstacle(self):
        for final in (105,105.5):
            t=scenario(closes=(105,105,105,105,final));t['condition_inputs']['bars'][-1]['high']=107
            r=assess(t);p=r['obstacle_path_review']
            self.assertEqual(p['reaction'],'not_crossed');self.assertIsNone(p['passed_level'])
            self.assertEqual(p['active_obstacle']['price'],105.5)

    def test_retest_hold_requires_later_candle_after_break(self):
        r=assess(scenario(closes=(105,106,105.7,106,107)))
        self.assertEqual(r['obstacle_path_review']['reaction'],'retest_held')
        r=assess(scenario(closes=(106,106,106,106,107)))
        self.assertEqual(r['obstacle_path_review']['reaction'],'beyond_level_retest_unobserved')

    def test_failed_break_restores_front_obstacle_and_resets_old_retest(self):
        r=assess(scenario(closes=(105,106,105.7,106,105)))
        self.assertEqual(r['obstacle_path_review']['reaction'],'breakout_failed')
        self.assertEqual(r['obstacle_path_review']['active_obstacle']['price'],105.5)
        r=assess(scenario(closes=(106,105.7,106,105,107)))
        self.assertEqual(r['obstacle_path_review']['reaction'],'breakout_close_observed')

    def test_bad_or_stale_candles_do_not_clear_base_obstacle(self):
        for mode in ('gap','price','clock','source'):
            t=scenario();i=t['condition_inputs']
            if mode=='gap':i['bars'][2]['timestamp']-=900
            if mode=='price':i['bars'][-1]['low']=109
            if mode=='clock':i['evaluated_at']-=900
            if mode=='source':t['trigger_price_reference']['close']+=.1
            r=assess(t);self.assertEqual(r['obstacle_path_review']['status'],'unverified',mode)
            self.assertEqual(r['obstacle_path_review']['active_obstacle']['price'],105.5)

    def test_no_next_pivot_is_not_an_invented_target_and_deepening_stays_deferred(self):
        t=scenario(closes=(105,105,105,105,121),hist=(-.1,-.2,-.3))
        t['technical_plan_inputs']['highs']=[p for p in t['technical_plan_inputs']['highs'] if p['price']<125]
        r=assess(t);self.assertIsNone(r['obstacle_path_review']['active_obstacle'])
        self.assertIsNone(r['reference_levels']['structural_target'])
        self.assertEqual(r['reference_levels']['scenario_target'],120)
        self.assertNotEqual(r['practical_review']['status'],'technical_watch')
        r=assess(scenario(hist=(-.1,-.2,-.3)))
        self.assertEqual(r['practical_review']['status'],'technical_recheck')

    def test_reactions_before_pivot_confirmation_are_not_claimed(self):
        from fx_system.obstacle_path import describe
        r=assess(scenario());p=deepcopy(r['wave_price_plan'])
        sec=14400
        # Confirmation arrives at the last candle's close, not its open.
        p['first_obstacle']['timestamp']=r['trigger_price_reference']['closed_at']-3*sec
        result=describe(r,p)
        self.assertEqual(result['status'],'unverified')
        self.assertIsNone(result['passed_level'])

    def test_new_and_legacy_original_reports_restore_and_bad_version_rejected(self):
        r=assess(scenario())
        for current in (r,assess(contextual())):
            b=build_strategy_report_export(json.dumps(with_record(current)).encode(),SOURCE)
            self.assertEqual(b['status'],'saved');restore_strategy_report_export(b,SOURCE,b['snapshot_git_blob_sha'])
        for version in (True,2,'1'):
            bad=deepcopy(r);bad['obstacle_path_version']=version
            with self.assertRaises(ValueError):refresh(bad)


if __name__=='__main__':unittest.main()
