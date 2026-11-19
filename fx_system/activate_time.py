"""Public-rule time/price observations, not the proprietary Murphy report.

The saved, closed daily/weekly candles are the only inputs. Candidate windows
are descriptive; they do not grant an entry, change a grade or predict a turn.
"""
import math

BASIC_COUNTS = (9, 17, 21, 26, 33, 42, 52)
MAX_BARS = {'d1': 120, 'w1': 80}


def _within(age, count):
    return abs(age-count) <= max(1, int(count*.1+.5))


def _pivots(bars):
    points = []
    for i in range(2, len(bars)-2):
        for kind, field, predicate in (
                ('high', 'high', lambda a, b: a > b),
                ('low', 'low', lambda a, b: a < b)):
            if all(predicate(bars[i][field], bars[j][field]) for j in (i-2, i-1, i+1, i+2)):
                points.append({'kind': kind, 'index': i,
                               'timestamp': bars[i]['timestamp'], 'price': bars[i][field]})
    return points


def analyze(frame, timeframe, clock):
    """Count completed bars with both endpoints included; never use future bars."""
    result = {'schema': 'public_time_price_observation_v1', 'timeframe': timeframe,
              'evaluated_at': clock, 'status': 'unavailable', 'basic': [],
              'equal_time': [], 'cycles': [], 'price_confirmation': 'unverified',
              'scope': 'research_reference_not_entry_or_grade'}
    if timeframe not in MAX_BARS or type(clock) is not int or not isinstance(frame, dict):
        return result
    bars = frame.get('bars')
    if (frame.get('verified') is not True or frame.get('timeframe') != timeframe
            or frame.get('evaluated_at') != clock or frame.get('status') != 'available'
            or not isinstance(bars, list) or not 5 <= len(bars) <= MAX_BARS[timeframe]):
        return result
    seconds = 86400 if timeframe == 'd1' else 604800
    for bar in bars:
        if (not isinstance(bar, dict) or type(bar.get('timestamp')) is not int
                or any(type(bar.get(k)) not in (int, float) or not math.isfinite(bar[k]) or bar[k] <= 0
                       for k in ('high', 'low', 'close'))
                or not bar['low'] <= bar['close'] <= bar['high']
                or bar.get('session_end_utc', bar['timestamp']+seconds) > clock):
            return result
    if any(a['timestamp'] >= b['timestamp'] for a, b in zip(bars, bars[1:])):
        return result
    if (type(frame.get('closed_at')) is not int
            or frame['closed_at'] != bars[-1].get('session_end_utc', bars[-1]['timestamp']+seconds)
            or frame['closed_at'] > clock):
        return result
    pivots = _pivots(bars)
    last = {kind: next((p for p in reversed(pivots) if p['kind'] == kind), None)
            for kind in ('high', 'low')}
    basic = []
    for kind, pivot in last.items():
        if pivot is None:
            continue
        age = len(bars)-pivot['index']  # Both the pivot and final closed bar count.
        matches = [n for n in BASIC_COUNTS if _within(age, n)]
        if matches:
            basic.append({'kind': kind, 'pivot_at': pivot['timestamp'],
                          'elapsed_bars_inclusive': age, 'matching_counts': matches})
    equal = []
    latest = sorted((p for p in last.values() if p), key=lambda p:p['index'])
    if len(latest) == 2 and latest[0]['kind'] != latest[1]['kind']:
        duration = latest[1]['index']-latest[0]['index']+1
        age = len(bars)-latest[1]['index']
        if duration >= 3 and _within(age, duration):
            equal.append({'from_at': latest[0]['timestamp'], 'pivot_at': latest[1]['timestamp'],
                          'duration_bars_inclusive': duration, 'elapsed_bars_inclusive': age})
    cycles = []
    for kind in ('high','low'):
        points = [p for p in pivots if p['kind'] == kind][-3:]
        if len(points) != 3:
            continue
        first = points[1]['index']-points[0]['index']
        second = points[2]['index']-points[1]['index']
        age = len(bars)-points[2]['index']
        if first >= 3 and second >= 3 and _within(first, second) and _within(age, second):
            cycles.append({'kind': kind, 'pivots_at': [p['timestamp'] for p in points],
                           'interval_bars': [first,second], 'elapsed_bars_inclusive': age})
    previous, current = bars[-2:]
    confirmation = ('above_previous_high' if current['close'] > previous['high'] else
                    'below_previous_low' if current['close'] < previous['low'] else 'none')
    return {**result, 'status':'observed', 'closed_at':frame.get('closed_at'),
            'pivot_count':len(pivots), 'basic':basic, 'equal_time':equal,
            'cycles':cycles, 'price_confirmation':confirmation}


def observe_pair(frames, clock):
    """Retain a bounded input so saved observations can be reproduced exactly."""
    result = {'schema':'public_time_analysis_context_v1', 'evaluated_at':clock,
              'scope':'supplemental_not_grade_or_ranking', 'timeframes':{}}
    for tf, limit in MAX_BARS.items():
        source = frames.get(tf, {}) if isinstance(frames, dict) else {}
        if not isinstance(source, dict):
            source = {}
        bars = source.get('bars')
        if not isinstance(bars, list) or any(not isinstance(b,dict) for b in bars):
            bars = []
        compact = {'timeframe':tf, 'evaluated_at':clock,
                   'verified':source.get('verified') is True,
                   'status':source.get('status'), 'closed_at':source.get('closed_at'),
                   'bars':[{k:b[k] for k in ('timestamp','high','low','close','session_end_utc') if k in b}
                           for b in bars[-limit:]]}
        result['timeframes'][tf] = {'source':compact, 'observation':analyze(compact,tf,clock)}
    return result


def validate_pair(value, clock):
    if (not isinstance(value, dict) or value.get('schema') != 'public_time_analysis_context_v1'
            or value.get('evaluated_at') != clock or value.get('scope') != 'supplemental_not_grade_or_ranking'
            or not isinstance(value.get('timeframes'),dict)
            or set(value['timeframes']) != set(MAX_BARS)):
        return False
    return all(isinstance(item,dict) and item.get('observation') == analyze(item.get('source'),tf,clock)
               for tf,item in value['timeframes'].items())


def swing_line(value):
    """A restrained supplement to a saved swing report, never a trade signal."""
    if not isinstance(value,dict):
        return '日足の時間参考：未確認'
    daily = value.get('timeframes',{}).get('d1',{}).get('observation',{})
    if daily.get('status') != 'observed':
        return '日足の時間参考：保存足不足または未確認'
    kinds = [f"{item['kind']}から{item['elapsed_bars_inclusive']}本目（基本数値の近似）"
             for item in daily['basic']]
    if daily['equal_time']:
        kinds.append('直近の対等時間候補')
    if daily['cycles']:
        kinds.append('同種高安の反復周期候補')
    confirmation = {'above_previous_high':'前日高値の上を日足終値で確認',
                    'below_previous_low':'前日安値の下を日足終値で確認',
                    'none':'前日高安の終値突破なし'}[daily['price_confirmation']]
    return '日足の時間参考（公開規則の探索）：'+('／'.join(kinds) if kinds else '節目候補は未観測')+'。'+confirmation+'。方向・評価・売買許可には使わない'
