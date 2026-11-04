"""Presentation changes must preserve saved judgments and legacy text."""
from copy import deepcopy
import json
import unittest

from fx_system.economic_calendar_report import calendar_lines
from fx_system.standard_technicals import render_lines
from fx_system.strategy_report import render_strategy_report
from fx_system.strategy_report_export import build_strategy_report_export, restore_strategy_report_export
from test_strategy_report_export import snapshot, SOURCE


class ReportPresentationTests(unittest.TestCase):
    def test_quality_covers_hidden_events_and_keeps_credit_without_mutation(self):
        event = {'currency':'USD', 'scheduled_at_utc':100, 'timing':'upcoming',
                 'source_license':{'notice':'Synthetic full credit'}}
        row = {'pair':'EURUSD', 'economic_calendar_context':{'status':'partial',
            'events':[deepcopy(event) for _ in range(3)]+[
                {'currency':'USD', 'timing':'uncertain', 'freshness':'stale',
                 'source_health':{'status':'failed'}}]}}
        before = deepcopy(row)
        old = calendar_lines(row, str)
        new = calendar_lines(row, str, presentation_version=2)
        self.assertEqual(new[-len(old):], old)
        text = '\n'.join(new)
        self.assertIn('情報品質 USD：古い出典1件', text)
        self.assertIn('出典の劣化・失敗・停止1件', text)
        self.assertIn('日時未確定1件', text)
        self.assertIn('最新日程・実績を裏付けられない', text)
        self.assertIn('Synthetic full credit', text)
        self.assertEqual(row, before)

    def test_missing_calendar_is_not_absence_of_events(self):
        lines = calendar_lines({'economic_calendar_context':{'status':'unavailable'}},
                               str, presentation_version=2)
        self.assertIn('予定なしとは判断できない', lines[0])

    def test_plan_puts_state_conditions_and_distinct_stops_before_reasons(self):
        row = {'pair':'EURUSD', 'strategy':'swing', 'direction':'long', 'grade':'B',
            'trigger_timeframe':'m15', 'reference_timeframe':'h4',
            'technical_outlook':{'forecast':{'primary_path':'Synthetic outlook'}},
            'wave_price_plan':{'thesis_invalidation':1, 'local_setup_failure':2},
            'scenario_conditions':{'status':'conditions_observed','summary':'Synthetic RCI timing'},
            'reference_levels':{'structural_target':3,'scenario_target':4},
            'reasons':['Synthetic reason'], 'opposing_evidence':['Synthetic concern'],
            'practical_review':{'entry_status':'paused'}}
        before = deepcopy(row)
        old = render_lines(row)
        new = render_lines(row, presentation_version=2)
        self.assertIn('局所停止・再評価', new[1])
        self.assertIn('確認足 M15', new[2])
        self.assertIn('M15確定終値 2以下', new[3])
        self.assertIn('H4確定終値 1以下', new[4])
        self.assertIn('途中障害：3／経路目標：4', new[5])
        for line in (old[2],old[3],old[4],old[8],old[9],old[-1]):
            self.assertIn(line,new)
        self.assertEqual(row,before)
        row['direction']='short'
        self.assertIn('2以上',render_lines(row,presentation_version=2)[3])
        row['expiry']={'status':'withdrawn'}
        self.assertIn('経路終了・再評価',render_lines(row,presentation_version=2)[1])

    def test_export_version_preserves_old_text_and_all32_assessments(self):
        saved=snapshot()
        outlook=saved['scheduled_outlook']
        for record in outlook['strategy_assessments']:
            record['economic_calendar_context']['status']='partial'
        for row in outlook['rows']:
            for record in row['strategy_assessments'].values():
                record['economic_calendar_context']['status']='partial'
        before=deepcopy(saved)
        new=build_strategy_report_export(json.dumps(saved).encode(),SOURCE)
        self.assertEqual(new['presentation_version'],2)
        old=deepcopy(new);old.pop('presentation_version')
        old['report_text']=render_strategy_report(saved,comparison_explanation_version=2)
        old['review_context_text']=render_strategy_report(saved,include_all_reviews=True,
            complete_evidence=True,comparison_explanation_version=2)
        for bundle in (old,new):
            restored=restore_strategy_report_export(bundle,SOURCE,bundle['snapshot_git_blob_sha'])
            self.assertEqual(restored['scheduled_outlook']['strategy_assessments'],
                             saved['scheduled_outlook']['strategy_assessments'])
        self.assertNotEqual(old['report_text'],new['report_text'])
        for version in (True,0,3,'2',1):
            with self.assertRaises(ValueError):
                restore_strategy_report_export({**new,'presentation_version':version},SOURCE,
                                               new['snapshot_git_blob_sha'])
        self.assertEqual(saved,before)
