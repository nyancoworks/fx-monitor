from copy import deepcopy
import datetime as dt
import math
import unittest

from fx_system import historical_shape_reference as m
from fx_system.monitor_pairs import PAIR_KEYS


def fixture():
    start = int(dt.datetime(2026, 10, 1, tzinfo=dt.timezone.utc).timestamp())
    rows = []
    for i in range(480):
        v = 100 + math.sin(i / 8) + i * .002
        rows.append(dict(timestamp=start+i*3600, open=v, high=v+.4, low=v-.4, close=v+.1))
    clock = start + 480*3600
    records = [dict(pair=p, strategy=s, evaluated_at=clock, execution_authority='none',
                    assessment='review' if p == 'USDJPY' else 'skip',
                    direction='long' if p == 'USDJPY' else None)
               for p in PAIR_KEYS for s in ('swing', 'daytrade')]
    return {'USDJPY': {'h1': rows, 'bar_provenance': {'h1:'+str(r['timestamp']): 'Twelve Data' for r in rows}}}, {'evaluated_at': clock, 'strategy_assessments': records}, clock


class HistoricalReferences(unittest.TestCase):
    def test_saved_inputs_unchanged_and_projection_contract(self):
        cache, outlook, clock = fixture(); old = deepcopy((cache, outlook))
        value = m.build_references(cache, outlook, clock)
        self.assertEqual((cache, outlook), old)
        self.assertEqual(m.reference_errors(value, clock), [])
        self.assertEqual(len(value['records']), 32)
        self.assertTrue(any(r['matches'] for r in value['records']))
        self.assertTrue(all(e['embargo_end'] <= r['query_start'] for r in value['records'] for e in r['matches']))

    def test_unknown_provider_and_missing_prices_stay_unavailable(self):
        cache, outlook, clock = fixture()
        cache['USDJPY']['bar_provenance'] = {}
        value = m.build_references(cache, outlook, clock)
        self.assertEqual(m.reference_errors(value, clock), [])
        self.assertEqual([r['status'] for r in value['records'] if r['pair'] == 'USDJPY'], ['unavailable']*2)

    def test_future_candles_never_affect_reference(self):
        cache, outlook, clock = fixture()
        before = m.build_references(cache, outlook, clock)
        for i in range(5):
            r = dict(timestamp=clock+i*3600, open=1e6, high=1e6+1, low=1, close=2)
            cache['USDJPY']['h1'].append(r)
            cache['USDJPY']['bar_provenance']['h1:'+str(r['timestamp'])] = 'Twelve Data'
        self.assertEqual(m.build_references(cache, outlook, clock), before)

    def test_nominal_week_keeps_timestamps_and_excludes_partial_h4(self):
        friday = int(dt.datetime(2026, 10, 16, 20, tzinfo=dt.timezone.utc).timestamp())
        rows = [dict(timestamp=friday+i*3600, open=100, high=102, low=99, close=101) for i in range(4)]
        self.assertEqual(m.view(rows, friday+14400, 14400), [])
        self.assertEqual(rows[0]['timestamp'], friday)

    def test_bad_candle_and_stale_query_do_not_create_examples(self):
        cache, outlook, clock = fixture()
        cache['USDJPY']['h1'][-1]['high'] = 1
        value = m.build_references(cache, outlook, clock)
        self.assertTrue(all(r['status'] == 'unavailable' for r in value['records'] if r['pair'] == 'USDJPY'))
        cache, outlook, clock = fixture()
        cache['USDJPY']['h1'] = cache['USDJPY']['h1'][:-8]
        value = m.build_references(cache, outlook, clock)
        self.assertTrue(all(r['status'] == 'unavailable' for r in value['records'] if r['pair'] == 'USDJPY'))

    def test_projection_tampering_rejected(self):
        cache, outlook, clock = fixture()
        good = m.build_references(cache, outlook, clock)
        for key, bad_value in [('evaluated_at', clock+1), ('profitability_validated', True)]:
            bad = deepcopy(good); bad[key] = bad_value
            self.assertTrue(m.reference_errors(bad, clock))
        bad = deepcopy(good)
        record = next(r for r in bad['records'] if r['matches'])
        record['matches'][0]['observations']['12']['closed_at'] = clock + 1
        self.assertTrue(m.reference_errors(bad, clock))

    def test_invalid_canonical_input_is_not_a_different_universe(self):
        cache, outlook, clock = fixture(); outlook['strategy_assessments'].pop()
        with self.assertRaises(ValueError): m.build_references(cache, outlook, clock)

    def test_compact_export_copies_only_valid_optional_references(self):
        import json
        from fx_system.strength_export import build_strength_export
        cache, outlook, clock = fixture()
        value = m.build_references(cache, outlook, clock)
        source = dict(source_repository='nyancoworks/fx-monitor', source_commit='a'*40,
                      run_id=1, evaluated_at=clock)
        snapshot = dict(evaluated_at=clock, historical_shape_references=value)
        bundle = build_strength_export(json.dumps(snapshot).encode(), source)
        self.assertEqual(bundle['historical_shape_references'], value)
        value['records'][0]['matches'] = [{'observations': None}]
        bundle = build_strength_export(json.dumps(snapshot).encode(), source)
        self.assertNotIn('historical_shape_references', bundle)

    def test_scale_and_price_level_do_not_change_shape_selection(self):
        cache, _, clock = fixture(); rows = cache['USDJPY']['h1']
        original = m.rank(m.view(rows, clock, 3600), clock, 3600)
        scaled = [{k: v if k == 'timestamp' else v*3+700 for k, v in r.items()} for r in rows]
        changed = m.rank(m.view(scaled, clock, 3600), clock, 3600)
        self.assertEqual([(e['start'], e['end_close']) for e in original['matches']],
                         [(e['start'], e['end_close']) for e in changed['matches']])
        for a, b in zip(original['matches'], changed['matches']):
            self.assertAlmostEqual(a['distance'], b['distance'], places=9)


if __name__ == '__main__': unittest.main()
