from copy import deepcopy
import unittest

from fx_system import historical_shape_reference as m
from fx_system.monitor_pairs import PAIR_KEYS


def saved_reference(clock):
    records = [dict(pair=pair, strategy=strategy, timeframe=tf, status='unavailable', matches=[])
               for pair in PAIR_KEYS for strategy, tf in (('swing', 'h4'), ('daytrade', 'h1'))]
    records[0].update(status='nearest_examples_only', query_start=clock-100, query_closed_at=clock,
                      query_structure='mixed', query_chart=[0.] * 20,
                      matches=[dict(start=clock-400, end_close=clock-300, embargo_end=clock-200,
                                    distance=0., chart=[], observations={
                                        '4': {'status':'unavailable'}, '12': {'status':'observed',
                                        'closed_at':clock-250, 'close_change_pips':0.,
                                        'highest_above_reference_pips':1., 'lowest_below_reference_pips':1.}})])
    return dict(schema=m.SCHEMA, algorithm=m.ALGORITHM, evaluated_at=clock, advisory_only=True,
                similarity_acceptance_threshold=None, profitability_validated=False,
                historical_arrivals_verified=False, shape_window=20, horizons=[4, 12], records=records)


class HistoricalReferences(unittest.TestCase):
    def test_projection_tampering_rejected(self):
        clock = 100000
        good = saved_reference(clock)
        for key, bad_value in [('evaluated_at', clock+1), ('profitability_validated', True)]:
            bad = deepcopy(good); bad[key] = bad_value
            self.assertTrue(m.reference_errors(bad, clock))
        bad = deepcopy(good)
        record = next(r for r in bad['records'] if r['matches'])
        record['matches'][0]['observations']['12']['closed_at'] = clock + 1
        self.assertTrue(m.reference_errors(bad, clock))

    def test_compact_export_copies_only_valid_optional_references(self):
        import json
        from fx_system.strength_export import build_strength_export
        clock = 100000
        value = saved_reference(clock)
        source = dict(source_repository='nyancoworks/fx-monitor', source_commit='a'*40,
                      run_id=1, evaluated_at=clock)
        snapshot = dict(evaluated_at=clock, historical_shape_references=value)
        bundle = build_strength_export(json.dumps(snapshot).encode(), source)
        self.assertEqual(bundle['historical_shape_references'], value)
        value['records'][0]['matches'] = [{'observations': None}]
        bundle = build_strength_export(json.dumps(snapshot).encode(), source)
        self.assertNotIn('historical_shape_references', bundle)
