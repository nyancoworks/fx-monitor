from copy import deepcopy
import json
import unittest
from fx_system.pair_market_context import build,attach
from fx_system.strategy_report import report_records
from fx_system.strategy_report_export import build_strategy_report_export,restore_strategy_report_export
from fx_system.validate_strategy_snapshot import validate_strategy_snapshot
from test_technical_interpretation import contextual
from test_technical_forecast import assess
from test_swing_horizon import with_record
from test_strategy_report_export import SOURCE
from test_strategy_strength import CLOCK


def records():
    s=assess(contextual())
    t=contextual('daytrade','short',hist=(-.3,-.2,-.1))
    positions=t['indicator_context']['frames']['base']['observations'][1]['application']['positions']
    positions['25x5']['slope_movement']='rising'
    d=assess(t,'daytrade')
    return [s,d]


class PairMarketContextTests(unittest.TestCase):
    def test_concrete_branches_use_saved_conditions_and_distinct_withdrawals(self):
        rows=records();c=build(rows,CLOCK,version=2)[0]
        self.assertEqual(len(c['decision_branches']),3)
        text=c['resolution']
        for r in rows:
            self.assertIn(r['scenario_conditions']['summary'],text)
            self.assertIn(str(r['invalidation']['price']).rstrip('0').rstrip('.'),text)
        self.assertIn('H1確定終値',text);self.assertIn('H4確定終値',text)
        self.assertIn('H1撤回だけでH4再開とはせず',text)
        self.assertNotIn('decision_branches',build(rows,CLOCK)[0])
        rows[0]['invalidation']['price']=None
        self.assertIn('撤回水準未確認',build(rows,CLOCK,version=2)[0]['resolution'])

    def test_upper_background_and_lower_recovery_choose_primary_not_two_equal_calls(self):
        rows=records();before=deepcopy(rows);c=build(rows,CLOCK)[0]
        self.assertEqual(c['preferred_strategy'],'swing')
        self.assertEqual(c['range_assessment'],'range_not_established')
        self.assertIn('回復失敗時の対案',c['summary'])
        o=attach({'evaluated_at':CLOCK,'strategy_assessments':rows})
        self.assertEqual([r['strategy'] for r in report_records(o)],['swing'])
        self.assertEqual(rows,before)
        self.assertIn('daytrade',c['plans']);self.assertEqual(c['plans']['daytrade']['direction'],'short')

    def test_strong_opposite_horizons_are_not_automatically_range_or_removed(self):
        rows=[assess(contextual()),assess(contextual('daytrade','short'),'daytrade')]
        c=build(rows,CLOCK)[0];self.assertIsNone(c['preferred_strategy'])
        self.assertEqual(c['phase'],'opposing_hypotheses_unresolved')
        self.assertEqual(len(report_records(attach({'evaluated_at':CLOCK,'strategy_assessments':rows}))),2)

    def test_no_forced_h4_precedence_and_withdrawn_plan_cannot_be_primary(self):
        rows=records();rows[0]['assessment']='skip'
        self.assertIsNone(build(rows,CLOCK)[0]['preferred_strategy'])
        rows=records();f=rows[0]['technical_outlook']['forecast'];f['conviction']='weak'
        fd=rows[1]['technical_outlook']['forecast'];fd['phase']='continuation'
        fd['background']['dma']['25x5']['slope_relation']='aligned'
        fd['background']['dma']['25x5']['slope_movement']='falling'
        self.assertEqual(build(rows,CLOCK)[0]['preferred_strategy'],'daytrade')

    def test_deepening_or_unusable_primary_does_not_override_other_horizon(self):
        rows=records();rows[0]['technical_outlook']['forecast']['evolution']['momentum']='counterpressure_deepening'
        self.assertIsNone(build(rows,CLOCK)[0]['preferred_strategy'])
        rows=records();rows[0]['practical_review']['status']='price_plan_recheck'
        self.assertIsNone(build(rows,CLOCK)[0]['preferred_strategy'])

    def test_missing_different_generation_and_aligned_forecasts_are_not_guessed(self):
        rows=records();rows[1]['evaluated_at']-=3600;self.assertEqual(build(rows,CLOCK),[])
        rows=records();rows[1]['technical_outlook']['forecast']['status']='unverified'
        self.assertEqual(build(rows,CLOCK),[])
        rows=records();rows[1]['technical_outlook']['forecast']['direction']='long'
        self.assertEqual(build(rows,CLOCK),[])

    def test_range_context_requires_existing_consolidation_evidence(self):
        rows=records();rows[0]['swing_environment']['state']='h4_consolidation'
        self.assertEqual(build(rows,CLOCK)[0]['range_assessment'],'h4_consolidation_observed')

    def test_legacy_selection_unchanged_and_all32_originals_restore(self):
        s,d=records();snapshot=with_record(s);o=snapshot['scheduled_outlook']
        old=next(r for r in o['strategy_assessments'] if r['pair']=='EURUSD' and r['strategy']=='daytrade')
        o['assessment_counts'][old['assessment']]-=1;o['assessment_counts'][d['assessment']]+=1
        o['strategy_assessments'][o['strategy_assessments'].index(old)]=d
        next(row for row in o['rows'] if row['pair']=='EURUSD')['strategy_assessments']['daytrade']=deepcopy(d)
        legacy=deepcopy(snapshot)
        legacy['scheduled_outlook'].pop('pair_context_version',None)
        legacy['scheduled_outlook'].pop('pair_market_context',None)
        self.assertIn(d,report_records(o))
        attach(o);self.assertEqual(validate_strategy_snapshot(snapshot),[])
        for x in (snapshot,legacy):
            bundle=build_strategy_report_export(json.dumps(x,sort_keys=True).encode(),SOURCE)
            self.assertEqual(bundle['status'],'saved')
            restored=restore_strategy_report_export(bundle,SOURCE,bundle['snapshot_git_blob_sha'])
            self.assertEqual(restored['scheduled_outlook']['strategy_assessments'],x['scheduled_outlook']['strategy_assessments'])
        bad=deepcopy(snapshot);bad['scheduled_outlook']['pair_market_context'][0]['preferred_strategy']='daytrade'
        self.assertIn('scheduled pair market context mismatch',validate_strategy_snapshot(bad))
        bad=deepcopy(snapshot);bad['scheduled_outlook']['pair_context_version']=True
        self.assertIn('scheduled pair market context mismatch',validate_strategy_snapshot(bad))


if __name__=='__main__':unittest.main()
