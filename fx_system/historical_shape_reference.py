"""Validate historical shape projections retained in older snapshots."""
import math

from .monitor_pairs import PAIR_KEYS

SCHEMA = 'historical_shape_reference_v1'
ALGORITHM = 'business_shape20_atr14_same_structure_v1'


def _reference_errors(value, clock):
    """Reject malformed optional projections without changing strength or grades."""
    if (not isinstance(value, dict) or value.get('schema') != SCHEMA or value.get('algorithm') != ALGORITHM
            or value.get('evaluated_at') != clock or value.get('advisory_only') is not True
            or value.get('similarity_acceptance_threshold') is not None
            or value.get('profitability_validated') is not False or value.get('historical_arrivals_verified') is not False
            or value.get('shape_window') != 20 or value.get('horizons') != [4, 12]):
        return ['shape reference contract']
    records = value.get('records')
    expected = {(p, s) for p in PAIR_KEYS for s in ('swing', 'daytrade')}
    if not isinstance(records, list) or len(records) != 32 or any(not isinstance(r, dict) for r in records):
        return ['shape reference records']
    if {(r.get('pair'), r.get('strategy')) for r in records} != expected:
        return ['shape reference identities']
    finite = lambda n: type(n) in (int, float) and math.isfinite(n)
    stamp = lambda n: type(n) is int and 0 < n <= clock
    for r in records:
        if r.get('timeframe') != ('h4' if r['strategy'] == 'swing' else 'h1'):
            return ['shape reference timeframe']
        matches = r.get('matches')
        if not isinstance(matches, list) or len(matches) > 3:
            return ['shape reference match limit']
        if r.get('status') in ('not_candidate', 'unavailable'):
            if matches:
                return ['unavailable shape has matches']
            continue
        if (r.get('status') != 'nearest_examples_only' or not stamp(r.get('query_start'))
                or not stamp(r.get('query_closed_at')) or r['query_start'] >= r['query_closed_at']
                or r.get('query_structure') not in ('HH_HL', 'LH_LL', 'mixed', 'unconfirmed')
                or not isinstance(r.get('query_chart'), list) or len(r['query_chart']) != 20
                or not all(finite(n) for n in r['query_chart'])):
            return ['shape query contract']
        intervals = []
        for e in matches:
            if (not isinstance(e, dict) or not all(stamp(e.get(k)) for k in ('start', 'end_close', 'embargo_end'))
                    or not e['start'] < e['end_close'] < e['embargo_end'] <= r['query_start']
                    or not finite(e.get('distance')) or e['distance'] < 0
                    or not isinstance(e.get('chart'), list) or len(e['chart']) not in (0, 32)
                    or not all(finite(n) for n in e['chart'])):
                return ['shape match contract']
            intervals.append((e['start'], e['embargo_end']))
            for horizon in ('4', '12'):
                obs = e.get('observations', {}).get(horizon, {})
                if obs.get('status') == 'unavailable':
                    continue
                if (obs.get('status') != 'observed' or not stamp(obs.get('closed_at'))
                        or not e['end_close'] < obs['closed_at'] <= r['query_start']
                        or not all(finite(obs.get(k)) for k in ('close_change_pips', 'highest_above_reference_pips', 'lowest_below_reference_pips'))
                        or obs['highest_above_reference_pips'] < 0 or obs['lowest_below_reference_pips'] < 0):
                    return ['shape outcome contract']
        ordered = sorted(intervals)
        if any(a[1] > b[0] for a, b in zip(ordered, ordered[1:])):
            return ['shape examples overlap']
    return []


def reference_errors(value, clock):
    try:
        return _reference_errors(value, clock)
    except (TypeError, ValueError, KeyError, OverflowError):
        return ['shape reference malformed']
