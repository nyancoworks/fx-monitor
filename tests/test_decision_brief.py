import unittest
from copy import deepcopy
from test_practical_review import record
from fx_system.practical_review import review
from fx_system.decision_brief import build_brief

class BriefTests(unittest.TestCase):
    def test_long_short_boundary_algebra_and_no_fill_invention(self):
        for direction,stop,target in [('long',90,110),('short',110,90)]:
            r=record();r['direction']=direction;r['reference_levels']={'invalidation':stop,'structural_target':target}
            b=build_brief(review(r));self.assertEqual(b['before_cost_reward_equals_risk_boundary'],100)
            self.assertEqual(b['indicative_margin_interval']['lower'],90 if direction=='long' else 100)
            self.assertEqual(b['indicative_margin_interval']['upper'],100 if direction=='long' else 110)
            self.assertTrue(b['indicative_margin_interval']['not_entry_range'])
            self.assertTrue(any('費用' in x for x in b['limits']))
    def test_missing_or_wrong_direction_targets_never_fabricate_ranges(self):
        r=record();self.assertIsNone(build_brief(r)['indicative_margin_interval'])
        r['reference_levels']={'invalidation':110,'structural_target':90}
        self.assertIsNone(build_brief(r)['before_cost_reward_equals_risk_boundary'])
    def test_stale_saved_close_cannot_be_treated_as_current(self):
        r=record();r['trigger_price_review'].update(saved_close=100,closed_at=r['evaluated_at']-300)
        self.assertIsNone(build_brief(r)['saved_close_reference'])
    def test_calendar_enrichment_refreshes_brief_with_identical_grade(self):
        import json
        from test_strategy_report_export import snapshot,SOURCE
        from fx_system.economic_calendar_context import enrich_outlook
        from fx_system.strategy_report_export import build_strategy_report_export,restore_strategy_report_export
        s=snapshot();clock=SOURCE['evaluated_at'];c={'observed_at_utc':clock,'complete':True,'events':[{'currency':'USD','impact':'high','time_precision':'minute','scheduled_at_utc':clock,'observed_at_utc':clock,'reference_only':True}]}
        s['scheduled_outlook']=enrich_outlook(s['scheduled_outlook'],c)
        b=build_strategy_report_export(json.dumps(s).encode(),SOURCE);self.assertEqual(b['status'],'saved')
        restored=restore_strategy_report_export(b,SOURCE,b['snapshot_git_blob_sha'])
        for r in restored['scheduled_outlook']['strategy_assessments']:
            self.assertEqual(r['decision_brief'],build_brief(r))
