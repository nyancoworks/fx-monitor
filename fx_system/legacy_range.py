"""Read-only validation of frozen legacy range assessments; no generation."""
import math

SECONDS = {'h1': 3600, 'h4': 14400}


def _valid(bar, seconds):
    if not isinstance(bar, dict):
        return False
    stamp = bar.get('timestamp')
    values = [bar.get(k) for k in ('open', 'high', 'low', 'close')]
    return (type(stamp) is int and stamp > 0 and stamp % seconds == 0
            and all(type(v) in (int, float) and math.isfinite(v) and v > 0 for v in values)
            and values[2] <= min(values[0], values[3]) <= max(values[0], values[3]) <= values[1])


def validate_range(record):
    """Validate optional compact range evidence; legacy records remain valid."""
    rc = record.get('range_context')
    if rc is None:
        return ['range evidence missing'] if record.get('scenario_type') == 'range_reversal' else []
    if (not isinstance(rc, dict) or rc.get('schema') != 'horizontal_range_v1'
            or rc.get('evaluated_at') != record.get('evaluated_at')
            or rc.get('timeframe') != record.get('reference_timeframe')
            or rc.get('status') not in ('unavailable', 'bounded', 'broken')
            or rc.get('advisory_only') is not True or rc.get('profitability_validated') is not False):
        return ['range evidence contract invalid']
    if rc['status'] == 'unavailable':
        return ['unavailable range selected'] if record.get('scenario_type') == 'range_reversal' else []
    seconds = SECONDS.get(rc.get('timeframe')); anchors = rc.get('anchors')
    if (not seconds or not isinstance(anchors, list) or len(anchors) != 4
            or any(not _valid(a, seconds) or a.get('kind') not in ('high', 'low')
                   or a.get('confirmed_at') != a['timestamp']+3*seconds for a in anchors)
            or any(b['timestamp'] <= a['timestamp'] or a['kind'] == b['kind'] for a, b in zip(anchors, anchors[1:]))
            or rc.get('formed_at') != anchors[-1]['confirmed_at']
            or rc['formed_at'] > record['evaluated_at']):
        return ['range anchor chronology invalid']
    highs = [a for a in anchors if a['kind'] == 'high']; lows = [a for a in anchors if a['kind'] == 'low']
    expected = {'lower_outer': min(a['low'] for a in lows), 'upper_outer': max(a['high'] for a in highs),
                'lower_zone': [max(a['low'] for a in lows), min(min(a['open'], a['close']) for a in lows)],
                'upper_zone': [max(max(a['open'], a['close']) for a in highs), min(a['high'] for a in highs)]}
    lo, hi = expected['lower_zone'], expected['upper_zone']
    if (any(rc.get(k) != v for k, v in expected.items())
            or not expected['lower_outer'] <= lo[0] < lo[1] < hi[0] < hi[1] <= expected['upper_outer']):
        return ['range zones differ from confirmed anchors']
    if record.get('scenario_type') == 'range_reversal':
        long = record.get('direction') == 'long'; levels = record.get('reference_levels', {})
        if (record.get('direction') not in ('long', 'short') or rc['status'] != 'bounded'
                or rc.get('direction') != record['direction']
                or rc.get('selection') != ('lower_edge' if long else 'upper_edge')
                or rc.get('reaction_level') != (lo[1] if long else hi[0])
                or levels.get('invalidation') != (expected['lower_outer'] if long else expected['upper_outer'])
                or levels.get('structural_target') != (hi[1] if long else lo[0])
                or record.get('grade') == 'A'):
            return ['range selection or price plan invalid']
    if rc['status'] == 'broken':
        obs = rc.get('break_observation', {})
        close = obs.get('saved_close'); closed = obs.get('closed_at')
        sec = {**SECONDS, 'm5': 300, 'm15': 900}.get(obs.get('timeframe'))
        if (type(close) not in (int, float) or not math.isfinite(close) or close <= 0
                or not (close <= expected['lower_outer'] or close >= expected['upper_outer'])
                or not sec or obs.get('timeframe') not in (record.get('reference_timeframe'),record.get('trigger_timeframe'))
                or type(closed) is not int or closed % sec or not rc['formed_at'] <= closed <= record['evaluated_at']
                or record.get('assessment') != 'skip' or record.get('expiry',{}).get('status') != 'withdrawn'):
            return ['range withdrawal evidence invalid']
    return []
