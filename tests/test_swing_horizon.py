"""Synthetic separation of H4 direction and M15 opportunity, including restores."""
from copy import deepcopy
import json
import unittest

from fx_system.strategy_scenario_assessment import assess_strategy
from fx_system.swing_horizon import build_swing_context, METHOD
from fx_system.strategy_report import render_strategy_report
from fx_system.validate_strategy_snapshot import validate_strategy_snapshot
from fx_system.strategy_report_export import build_strategy_report_export, restore_strategy_report_export
from fx_system.scenario_continuity import compare_views, render
from test_strategy_strength import mature_track, CLOCK
from test_strategy_report_export import snapshot, SOURCE


def track(direction='long'):
    t = mature_track()
    t.update(base_timeframe='h4', trigger_timeframe='m15', direction=direction,
             base_structure='HH_HL' if direction == 'long' else 'LH_LL',
             reaction_timestamp=CLOCK-900, trigger_status='waiting')
    t['reference_plan']['reference_close_timestamp']=(CLOCK//14400-1)*14400
    t['trigger_price_reference'].update(timeframe='m15')
    if direction == 'short':
        t['reference_levels'].update(invalidation=110,structural_target=70)
    return t


def with_record(r):
    s=snapshot();o=s['scheduled_outlook']
    old=next(x for x in o['strategy_assessments'] if x['pair']=='EURUSD' and x['strategy']=='swing')
    o['assessment_counts'][old['assessment']]-=1
    o['assessment_counts'][r['assessment']]+=1
    o['strategy_assessments'][o['strategy_assessments'].index(old)]=r
    next(x for x in o['rows'] if x['pair']=='EURUSD')['strategy_assessments']['swing']=deepcopy(r)
    return s


class SwingHorizonTests(unittest.TestCase):
    def test_m15_invalidation_pauses_entry_without_claiming_h4_break(self):
        for direction, price in [('long',89),('short',111)]:
            t=track(direction);t['trigger_price_reference']['close']=price
            before=deepcopy(t);r=assess_strategy('EURUSD','swing',t,CLOCK)
            self.assertEqual((r['assessment'],r['grade']),('skip',None))
            self.assertEqual(r['expiry']['status'],'withdrawn')
            self.assertEqual(r['expiry']['scope'],'saved_price_plan_not_h4_direction')
            self.assertEqual(r['swing_context']['structure_status'],'direction_watch')
            self.assertEqual(r['swing_context']['entry_status'],'paused')
            self.assertEqual(r['swing_context']['entry_pause_reason'],'saved_trigger_invalidation_crossed')
            self.assertEqual(t,before)

    def test_m15_target_does_not_extend_target_or_claim_fill(self):
        t=track();t['trigger_price_reference']['close']=131
        r=assess_strategy('EURUSD','swing',t,CLOCK)
        self.assertEqual(r['skip_reason'],'saved_trigger_target_reached')
        self.assertEqual(r['reference_levels']['structural_target'],130)
        self.assertEqual(r['swing_context']['entry_status'],'paused')
        self.assertEqual(r['swing_context']['structure_status'],'direction_watch')

    def test_trigger_diagnostic_alone_is_not_h4_invalidation(self):
        t=track();t['trigger_status']='invalidated'
        r=assess_strategy('EURUSD','swing',t,CLOCK)
        self.assertEqual(r['skip_reason'],'confirmed_trigger_invalidation')
        self.assertEqual(r['swing_context']['structure_status'],'direction_watch')
        self.assertEqual(r['swing_context']['entry_status'],'paused')

    def test_h4_close_break_remains_structural_withdrawal(self):
        for direction, price in [('long',89),('short',111)]:
            t=track(direction);t['reference_plan']['reference_close']=price
            r=assess_strategy('EURUSD','swing',t,CLOCK)
            self.assertEqual(r['skip_reason'],'saved_base_invalidation_crossed')
            self.assertEqual(r['swing_context']['structure_status'],'structure_invalidated')
            self.assertEqual(r['expiry']['status'],'withdrawn')

    def test_missing_stale_future_base_not_claimed_valid(self):
        r=assess_strategy('EURUSD','swing',track(),CLOCK)
        for stamp in (None, CLOCK//14400*14400, (CLOCK//14400-2)*14400):
            x=deepcopy(r);x['reference_plan']['reference_close_timestamp']=stamp
            self.assertEqual(build_swing_context(x)['structure_status'],'unverified')
        x=deepcopy(r);x['base_quality_verified']=False
        self.assertEqual(build_swing_context(x)['structure_status'],'unverified')
        self.assertEqual(r['swing_context']['holding_period'],'not_estimated')
        self.assertEqual(r['swing_context']['time_exit'],'not_defined')

    def test_daytrade_and_old_method_do_not_gain_new_semantics(self):
        r=assess_strategy('EURUSD','daytrade',mature_track(),CLOCK)
        self.assertNotIn('swing_context',r)
        self.assertNotIn('scope',r['expiry'])
        old=assess_strategy('EURUSD','swing',track(),CLOCK)
        old['method_version']='contextual_scenario_review_v7_trend_swing'
        self.assertIsNone(build_swing_context(old))

    def test_export_validation_and_report_distinguish_paused_entry(self):
        t=track();t['trigger_price_reference']['close']=89
        r=assess_strategy('EURUSD','swing',t,CLOCK);s=with_record(r)
        self.assertEqual(validate_strategy_snapshot(s),[])
        b=build_strategy_report_export(json.dumps(s).encode(),SOURCE)
        v=restore_strategy_report_export(b,SOURCE,b['snapshot_git_blob_sha'])
        self.assertEqual(len(v['scheduled_outlook']['strategy_assessments']),32)
        text=render_strategy_report(s)
        self.assertIn('仕掛け計画停止：EUR/USD スイング',text)
        self.assertIn('H4の方向構造を監視',text)
        missing=deepcopy(s)
        next(x for x in missing['scheduled_outlook']['strategy_assessments']
             if x['pair']=='EURUSD' and x['strategy']=='swing').pop('swing_environment')
        self.assertIn('scheduled swing environment mismatch',validate_strategy_snapshot(missing))
        r['swing_context']['structure_status']='structure_invalidated'
        self.assertIn('scheduled swing context mismatch',validate_strategy_snapshot(s))

    def test_continuity_reports_entry_stop_without_h4_withdrawal(self):
        old=with_record(assess_strategy('EURUSD','swing',track(),CLOCK))
        t=track();t['trigger_price_reference']['close']=89
        new=with_record(assess_strategy('EURUSD','swing',t,CLOCK))
        rows=compare_views(new,old)
        text=render(rows,CLOCK-3600,CLOCK)
        self.assertIn('仕掛け計画停止',text)
        self.assertIn('大局：H4の方向構造を監視',text)


if __name__ == '__main__':
    unittest.main()
