import unittest

from fx_system.strategy_report import report_records


def candidate(pair, phase, condition, room, *, profile=1):
    return {
        'pair': pair, 'strategy': 'daytrade', 'direction': 'long',
        'assessment': 'review', 'grade': 'B',
        'technical_order_version': 1, 'three_indicator_version': profile,
        'practical_review': {'status': 'technical_watch'},
        'technical_outlook': {'forecast': {'phase': phase}},
        'scenario_conditions': {'status': condition},
        'wave_price_plan': {'status': 'available', 'local_setup_failure': 1.0},
        'trigger_price_review': {'status': 'observed_reference',
                                 'saved_close': 1.001, 'first_obstacle_reward': room},
    }


class MurphyPriorityTests(unittest.TestCase):
    def test_daytrade_can_promote_recovery_with_room_in_both_measures(self):
        rows = [candidate('EURUSD', 'continuation', 'conditions_observed', .0002),
                candidate('GBPUSD', 'continuation', 'waiting', .0001),
                candidate('AUDUSD', 'recovery_wait', 'waiting', .003)]
        for row in rows:
            row['reference_levels'] = {
                'structural_target': 1.001 + row['trigger_price_review']['first_obstacle_reward']}
        outlook = {'strategy_assessments': rows}
        self.assertEqual([r['pair'] for r in report_records(outlook, selection_version=5)],
                         ['EURUSD', 'GBPUSD', 'AUDUSD'])
        self.assertEqual([r['pair'] for r in report_records(outlook)],
                         ['EURUSD', 'AUDUSD', 'GBPUSD'])
        rows[2]['wave_price_plan']['local_setup_failure'] = .9
        self.assertEqual([r['pair'] for r in report_records(outlook)],
                         ['EURUSD', 'GBPUSD', 'AUDUSD'])

    def test_core_phase_then_path_room_without_fixed_distance_gate(self):
        rows = [candidate('EURUSD', 'recovery_wait', 'conditions_observed', .003),
                candidate('GBPUSD', 'continuation', 'waiting', .0001),
                candidate('AUDUSD', 'continuation', 'conditions_observed', .0002),
                candidate('NZDUSD', 'continuation', 'waiting', .0007)]
        outlook = {'strategy_assessments': rows}
        self.assertEqual([r['pair'] for r in report_records(outlook, selection_version=4)],
                         ['EURUSD', 'GBPUSD', 'AUDUSD'])
        self.assertEqual([r['pair'] for r in report_records(outlook)],
                         ['NZDUSD', 'AUDUSD', 'GBPUSD'])

    def test_missing_geometry_follows_comparable_candidate(self):
        rows = [candidate('EURUSD', 'continuation', 'waiting', None),
                candidate('GBPUSD', 'continuation', 'waiting', .0004)]
        self.assertEqual([r['pair'] for r in report_records({'strategy_assessments': rows})],
                         ['GBPUSD', 'EURUSD'])

    def test_old_profile_keeps_original_order(self):
        rows = [candidate('EURUSD', 'recovery_wait', 'waiting', .0001, profile=None),
                candidate('GBPUSD', 'continuation', 'conditions_observed', .001, profile=None)]
        self.assertEqual([r['pair'] for r in report_records({'strategy_assessments': rows})],
                         ['EURUSD', 'GBPUSD'])


if __name__ == '__main__':
    unittest.main()
