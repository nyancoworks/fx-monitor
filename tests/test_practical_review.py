from copy import deepcopy
import unittest
from fx_system.practical_review import review
from fx_system.strategy_report import report_records

CLOCK=1800000000

def record(pair='EURUSD'):
    return {'pair':pair,'strategy':'daytrade','evaluated_at':CLOCK,'assessment':'review','grade':'B',
        'direction':'long','trigger_timeframe':'m5','reference_timeframe':'h1',
        'reference_plan':{'reference_close_timestamp':CLOCK-3600},
        'reference_levels':{},'scenario_conditions':{'status':'conditions_observed'},
        'market_phase':'directional_structure_wait',
        'opposing_evidence':['lagging oscillator, same price input'],
        'trigger_price_review':{'status':'observed_reference','closed_at':CLOCK,'risk_distance':1,'reward_distance':2},
        'economic_calendar_context':{'events':[]}}

class PracticalTests(unittest.TestCase):
    def test_concrete_observation_not_old_pattern_and_not_indicator_unanimity(self):
        r=review(record());self.assertEqual(r['grade'],'A')
        self.assertTrue(r['opposing_evidence'])
        r=record();r['grade']='A';r['scenario_conditions']['status']='waiting'
        self.assertEqual(review(r)['grade'],'B')

    def test_margin_conflict_and_strength_preserve_watch_b_not_skip(self):
        for key,value in [('market_phase','transition_context'),('currency_strength_context',{'material_opposition':True})]:
            r=record();r[key]=value;review(r)
            self.assertEqual((r['assessment'],r['grade']),('review','B'))
        r=record();r['trigger_price_review']['reward_distance']=.1;review(r)
        self.assertEqual(r['practical_review']['status'],'price_plan_recheck')
        o={'strategy_assessments':[r],'strategy_candidates':[]}
        self.assertEqual(report_records(o,selection_version=3),[])
        self.assertEqual(len(report_records(o,selection_version=2)),1)

    def test_event_priority_uses_saved_precise_time_not_new_results(self):
        r=record();r['economic_calendar_context']['events']=[{'id':'synthetic','impact':'high','scheduled_at_utc':CLOCK,'time_precision':'minute'}]
        review(r);self.assertEqual(r['practical_review']['status'],'event_recheck')
        self.assertEqual(r['grade'],'A') # calendar is priority context, not grade manipulation
        r['economic_calendar_context']['events'][0]['time_precision']='date'
        self.assertEqual(review(r)['practical_review']['status'],'reaction_confirmed')

    def test_calendar_enrichment_then_full_snapshot_export_and_restore(self):
        import json
        from test_strategy_report_export import snapshot,SOURCE
        from fx_system.economic_calendar_context import enrich_outlook
        from fx_system.validate_strategy_snapshot import validate_strategy_snapshot
        from fx_system.strategy_report_export import build_strategy_report_export,restore_strategy_report_export
        s=snapshot();clock=SOURCE['evaluated_at']
        before={(r['pair'],r['strategy']):(r['grade'],r['direction']) for r in s['scheduled_outlook']['strategy_assessments']}
        calendar={'observed_at_utc':clock,'complete':True,'events':[{
            'currency':'USD','scheduled_at_utc':clock,'observed_at_utc':clock,
            'reference_only':True,'impact':'high','time_precision':'minute','id':'synthetic-policy'}]}
        s['scheduled_outlook']=enrich_outlook(s['scheduled_outlook'],calendar)
        self.assertEqual(validate_strategy_snapshot(s),[])
        self.assertTrue(any(r['practical_review']['status']=='event_recheck' for r in s['scheduled_outlook']['strategy_assessments']))
        self.assertEqual(before,{(r['pair'],r['strategy']):(r['grade'],r['direction']) for r in s['scheduled_outlook']['strategy_assessments']})
        bundle=build_strategy_report_export(json.dumps(s).encode(),SOURCE)
        self.assertEqual(bundle['status'],'saved')
        self.assertEqual(len(restore_strategy_report_export(bundle,SOURCE,bundle['snapshot_git_blob_sha'])['scheduled_outlook']['strategy_assessments']),32)
        self.assertEqual(enrich_outlook(s['scheduled_outlook'],calendar),s['scheduled_outlook'])

    def test_stale_close_does_not_reuse_attractive_price_plan(self):
        r=record();r['trigger_price_review']['closed_at']-=300
        self.assertEqual(review(r)['grade'],'B')
        self.assertEqual(r['practical_review']['status'],'price_plan_recheck')

    def test_no_regrading_skip_pending_or_incomplete_plan(self):
        for state,grade in [('skip',None),('evaluation_pending',None),('review','C')]:
            r=record();r.update(assessment=state,grade=grade);review(r)
            self.assertEqual((r['assessment'],r['grade']),(state,grade))
