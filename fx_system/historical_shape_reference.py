"""Descriptive past shapes from saved candles; no grade, direction or trade rule.

Promotes the unchanged search/business core from private research 081265cf.
The full original research and prices stay private. No network calls are used.
"""
import datetime as dt
import math
from zoneinfo import ZoneInfo

from .core import aggregate, technical
from .monitor_pairs import PAIR_KEYS

SCHEMA = 'historical_shape_reference_v1'
ALGORITHM = 'business_shape20_atr14_same_structure_v1'
WINDOW = 20
HORIZONS = (4, 12)
NY = ZoneInfo('America/New_York')


def nominal_open(timestamp):
    local = dt.datetime.fromtimestamp(timestamp, NY)
    day = local.weekday()
    return day < 4 or day == 4 and local.hour < 17 or day == 6 and local.hour >= 17


def allowed_start(stamp, seconds):
    return all(nominal_open(t) for t in range(stamp, stamp + seconds, 3600))


def next_start(stamp, seconds):
    candidate = stamp + seconds
    while candidate <= stamp + 8 * 86400:
        if allowed_start(candidate, seconds):
            return candidate
        candidate += seconds
    raise ValueError('nominal calendar unavailable')


def validate_prefix(rows, clock, seconds):
    result = []
    if not isinstance(rows, list) or len(rows) > 500:
        raise ValueError('saved H1 limit')
    for row in rows:
        if not isinstance(row, dict) or type(row.get('timestamp')) is not int:
            raise ValueError('saved candle time')
        if row['timestamp'] + seconds > clock:
            continue
        vals = [row.get(k) for k in ('open', 'high', 'low', 'close')]
        if (row['timestamp'] % seconds or
                any(type(v) not in (int, float) or not math.isfinite(v) or v <= 0 for v in vals) or
                row['low'] > min(row['open'], row['close']) or row['high'] < max(row['open'], row['close'])):
            raise ValueError('saved candle OHLC')
        if result and row['timestamp'] <= result[-1]['timestamp']:
            raise ValueError('saved candle order')
        result.append(dict(row))
    return result


def view(h1, clock, seconds):
    prefix = validate_prefix(h1, clock, 3600)
    rows = prefix if seconds == 3600 else aggregate(prefix, 3600, seconds)
    return [r for r in rows if allowed_start(r['timestamp'], seconds)]


def describe(rows, seconds):
    if len(rows) != WINDOW or any(next_start(a['timestamp'], seconds) != b['timestamp']
                                  for a, b in zip(rows, rows[1:])):
        return None
    tr = [max(rows[i]['high'] - rows[i]['low'],
              abs(rows[i]['high'] - rows[i-1]['close']),
              abs(rows[i]['low'] - rows[i-1]['close'])) for i in range(1, len(rows))]
    scale = sum(tr[-14:]) / 14
    if scale <= 0:
        return None
    origin = rows[0]['close']
    return {'vector': [(r[k] - origin) / scale for r in rows for k in ('open', 'high', 'low', 'close')],
            'structure': technical(rows)['structure'], 'origin': origin, 'scale': scale}


def rank(rows, clock, seconds, limit=3):
    rows = validate_prefix(rows, clock, seconds)
    query_rows = rows[-WINDOW:]
    query = describe(query_rows, seconds)
    if query is None:
        return {'status': 'unavailable', 'reason': 'query_needs_20_business_bars', 'matches': []}
    first_query = len(rows) - WINDOW
    candidates = []
    for end in range(WINDOW - 1, first_query):
        last_observation = end + max(HORIZONS)
        if last_observation >= first_query:
            continue
        window = rows[end-WINDOW+1:end+1]
        shape = describe(window, seconds)
        if shape is None or shape['structure'] != query['structure']:
            continue
        observation_end = rows[last_observation]['timestamp'] + seconds
        if observation_end > query_rows[0]['timestamp']:
            continue
        distance = math.sqrt(sum((x-y)**2 for x, y in zip(query['vector'], shape['vector'])) / len(query['vector']))
        candidates.append({'start': window[0]['timestamp'], 'end_close': window[-1]['timestamp'] + seconds,
                           'reference_close': window[-1]['close'], 'distance': distance,
                           'embargo_end': observation_end})
    candidates.sort(key=lambda e: (e['distance'], e['end_close']))
    selected = []
    for candidate in candidates:
        if any(candidate['start'] < old['embargo_end'] and old['start'] < candidate['embargo_end']
               for old in selected):
            continue
        selected.append(candidate)
        if len(selected) == limit:
            break
    return {'status': 'nearest_examples_only', 'query_start': query_rows[0]['timestamp'],
            'query_closed_at': query_rows[-1]['timestamp'] + seconds,
            'query_structure': query['structure'], 'eligible_shape_windows': len(candidates),
            'query_chart': [(r['close'] - query['origin']) / query['scale'] for r in query_rows],
            'matches': selected}


def observations(rows, end_close, reference_close, seconds, pip):
    by_time = {r['timestamp']: r for r in rows}
    result = {}
    for horizon in HORIZONS:
        stamps = []; previous = end_close - seconds
        for _ in range(horizon):
            previous = next_start(previous, seconds); stamps.append(previous)
        missing = [t for t in stamps if t not in by_time]
        if missing:
            result[str(horizon)] = {'status': 'unavailable', 'reason': 'missing_expected_business_bars'}
            continue
        selected = [by_time[t] for t in stamps]
        result[str(horizon)] = {'status': 'observed', 'closed_at': stamps[-1] + seconds,
            'elapsed_hours': (stamps[-1] + seconds - end_close) / 3600,
            'close_change_pips': round((selected[-1]['close'] - reference_close) / pip, 3),
            'highest_above_reference_pips': round(max(0, max(r['high'] for r in selected) - reference_close) / pip, 3),
            'lowest_below_reference_pips': round(max(0, reference_close - min(r['low'] for r in selected)) / pip, 3)}
    return result


def stream(h1, clock, seconds, pip):
    rows = view(h1, clock, seconds)
    expected = clock // seconds * seconds - seconds
    while not allowed_start(expected, seconds):
        expected -= seconds
    if not rows or rows[-1]['timestamp'] != expected:
        return {'status': 'unavailable', 'reason': 'saved_base_candle_stale', 'matches': []}
    result = rank(rows, clock, seconds)
    if result['status'] != 'nearest_examples_only':
        return result
    # Selection is already fixed. Only now attach later prices and chart points.
    for example in result['matches']:
        example['observations'] = observations(rows, example['end_close'], example['reference_close'], seconds, pip)
        shape_rows = [r for r in rows if example['start'] <= r['timestamp'] < example['end_close']]
        shape = describe(shape_rows, seconds)
        chart_rows = [r for r in rows if example['start'] <= r['timestamp'] < example['embargo_end']]
        # Missing business candles may shorten charts; never bridge an unknown gap.
        complete = all(example['observations'][str(n)]['status'] == 'observed' for n in HORIZONS)
        example['chart'] = ([(r['close'] - shape['origin']) / shape['scale'] for r in chart_rows]
                            if complete and len(chart_rows) == 32 else [])
    return result


def build_references(cache, outlook, clock):
    if type(clock) is not int or clock <= 0 or outlook.get('evaluated_at') != clock:
        raise ValueError('shape evaluation clock')
    assessments = outlook.get('strategy_assessments', [])
    expected = {(p, s) for p in PAIR_KEYS for s in ('swing', 'daytrade')}
    if (len(assessments) != 32 or {(r.get('pair'), r.get('strategy')) for r in assessments} != expected
            or any(r.get('evaluated_at') != clock or r.get('execution_authority') != 'none' for r in assessments)):
        raise ValueError('canonical32 shape input')
    records = []
    for saved in assessments:
        pair, strategy = saved['pair'], saved['strategy']
        record = {'pair': pair, 'strategy': strategy, 'direction': saved.get('direction'),
                  'timeframe': 'h4' if strategy == 'swing' else 'h1', 'matches': []}
        if saved.get('assessment') != 'review':
            record.update(status='not_candidate')
        else:
            source = cache.get(pair, {})
            rows = source.get('h1', [])
            provenance = source.get('bar_provenance', {})
            if (not rows or not isinstance(provenance, dict) or
                    any(not isinstance(r, dict) or provenance.get('h1:' + str(r.get('timestamp'))) != 'Twelve Data' for r in rows)):
                record.update(status='unavailable', reason='unverified_saved_H1_source')
            else:
                try:
                    record.update(stream(rows, clock, 14400 if strategy == 'swing' else 3600,
                                         .01 if pair.endswith('JPY') else .0001))
                except (ValueError, TypeError, KeyError, OverflowError):
                    record.update(status='unavailable', reason='invalid_saved_H1')
        records.append(record)
    return {'schema': SCHEMA, 'algorithm': ALGORITHM, 'evaluated_at': clock,
            'advisory_only': True, 'similarity_acceptance_threshold': None,
            'profitability_validated': False, 'historical_arrivals_verified': False,
            'calendar': 'nominal_NY_Sunday17_Friday17_complete_UTC_H1_H4',
            'shape_window': 20, 'horizons': [4, 12], 'records': records}


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
