import unittest
from fx_system.followthrough_summary import describe


class FollowthroughSummaryTests(unittest.TestCase):
    def row(self, **events):
        return {'previous':{'scenario_conditions':{'status':'waiting'}},
                'previous_condition_followthrough':events}

    def test_observation_then_failure_is_not_just_observed(self):
        text=describe(self.row(condition_observation={'closed_at':1794560400},
            trigger_close_withdrawal={'closed_at':1794560700,'condition':'local_setup_failure_crossed'}))
        self.assertIn('18:00 条件観測 → 11/13 18:05 局所停止',text)
        self.assertNotIn('目標到達',text)

    def test_failure_then_target_preserves_order_and_no_profit_claim(self):
        text=describe(self.row(trigger_close_withdrawal={'closed_at':1794560700,'condition':'local_setup_failure_crossed'},
            base_objective_observation={'closed_at':1794561000}))
        self.assertLess(text.index('局所停止'),text.index('経路目標到達'))
        self.assertNotIn('利益',text)

    def test_same_close_does_not_invent_intrabar_order(self):
        text=describe(self.row(condition_observation={'closed_at':1794560700},
            trigger_close_withdrawal={'closed_at':1794560700,'condition':'path_objective_reached'}))
        self.assertIn('同時刻・順序未確認',text)

    def test_intrabar_touch_and_no_event_are_not_close_success(self):
        self.assertEqual(describe(self.row(target_touch={'bar_closed_at':1794560700})), '')
        self.assertEqual(describe({}), '')

    def test_already_observed_keeps_original_status_and_target_label(self):
        row=self.row(trigger_close_withdrawal={'closed_at':1794560700,'condition':'path_objective_reached'})
        row['previous']['scenario_conditions']['status']='conditions_observed'
        text=describe(row)
        self.assertTrue(text.startswith('保存時点で条件観測済み'))
        self.assertIn('経路目標到達',text)
        self.assertNotIn('局所停止',text)
