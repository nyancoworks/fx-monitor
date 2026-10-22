"""Provisional horizontal range interpretation of existing verified candles.

No tolerance is fitted: two upper/lower pivot wick zones must overlap. These
strict definitions deliberately miss some visual ranges. No acquisition occurs.
"""
from copy import deepcopy
import math
from .scenario_conditions import condition_inputs
from .scenario_price_plan import trigger_price_reference

SECONDS = {'h1': 3600, 'h4': 14400}


def _valid(bar, seconds):
    if not isinstance(bar, dict):
        return False
    stamp = bar.get('timestamp')
    values = [bar.get(k) for k in ('open', 'high', 'low', 'close')]
    return (type(stamp) is int and stamp > 0 and stamp % seconds == 0
            and all(type(v) in (int, float) and math.isfinite(v) and v > 0 for v in values)
            and values[2] <= min(values[0], values[3]) <= max(values[0], values[3]) <= values[1])


def apply_range(data, track, clock):
    """Fill an otherwise directionless slot; never replace a directional track."""
    if track.get('direction') in ('long', 'short') or track.get('base_verified') is not True:
        return
    base = track.get('base_timeframe'); seconds = SECONDS.get(base)
    bars = data.get(base, {}).get('candles', [])
    context = {'schema': 'horizontal_range_v1', 'status': 'unavailable',
               'evaluated_at': clock, 'timeframe': base, 'advisory_only': True,
               'profitability_validated': False,
               'reason': '反復する上限・下限の確認済み水平帯が不足'}
    track['range_context'] = context
    if not seconds or not isinstance(bars, list) or any(not _valid(b, seconds) for b in bars):
        return
    # Never bridge a weekend or missing base bar when constructing a range.
    for i in range(len(bars)-1, 0, -1):
        if bars[i]['timestamp'] - bars[i-1]['timestamp'] != seconds:
            bars = bars[i:]
            break
    if (type(clock) is not int or len(bars) < 9
            or not 0 <= clock - (bars[-1]['timestamp'] + seconds) < seconds):
        return
    pivots = {}
    for kind, compare in (('high', max), ('low', min)):
        pivots[kind] = [i for i in range(2, len(bars)-2)
                        if all((bars[i][kind] > bars[j][kind] if kind == 'high' else
                                bars[i][kind] < bars[j][kind])
                               for j in (i-2, i-1, i+1, i+2))][-2:]
    if any(len(v) != 2 for v in pivots.values()):
        return
    ordered = sorted((i, kind) for kind, indexes in pivots.items() for i in indexes)
    if len({i for i, _ in ordered}) != 4 or any(a[1] == b[1] for a, b in zip(ordered, ordered[1:])):
        return
    highs = [bars[i] for i in pivots['high']]; lows = [bars[i] for i in pivots['low']]
    lower_outer = min(b['low'] for b in lows)
    lower_low = max(b['low'] for b in lows)
    lower_inner = min(min(b['open'], b['close']) for b in lows)
    upper_inner = max(max(b['open'], b['close']) for b in highs)
    upper_high = min(b['high'] for b in highs)
    upper_outer = max(b['high'] for b in highs)
    if not lower_outer <= lower_low < lower_inner < upper_inner < upper_high <= upper_outer:
        return
    formed = bars[ordered[-1][0]+2]['timestamp'] + seconds
    anchors = [{**{k: bars[i][k] for k in ('timestamp', 'open', 'high', 'low', 'close')},
                'kind': kind, 'confirmed_at': bars[i+2]['timestamp'] + seconds}
               for i, kind in ordered]
    context.update(status='bounded', reason='交互の確認済み高安と上下のヒゲ帯の重なりを確認',
                   formed_at=formed, anchors=anchors,
                   lower_zone=[lower_low, lower_inner], upper_zone=[upper_inner, upper_high],
                   lower_outer=lower_outer, upper_outer=upper_outer,
                   selection='waiting_edge',
                   limitations=['水平帯の定義は暫定。視覚的な全レンジを網羅しない',
                                '勝率・収益性・閾値最適化は未検証'])
    # Closed breaches since formation withdraw this interpretation, including
    # an excursion followed by a return. Wicks alone do not withdraw it.
    trigger = track.get('trigger_timeframe'); trigger_seconds = {'m5': 300, 'm15': 900}.get(trigger)
    trigger_bars = data.get(trigger, {}).get('candles', [])
    check = [(b, base, seconds) for b in bars if b['timestamp'] + seconds >= formed]
    if track.get('trigger_verified') is True and trigger_seconds:
        check += [(b, trigger, trigger_seconds) for b in trigger_bars if _valid(b, trigger_seconds)
                  and formed <= b['timestamp'] + trigger_seconds <= clock]
    breaches = [(b, tf, sec) for b, tf, sec in check if b['close'] <= lower_outer or b['close'] >= upper_outer]
    if breaches:
        bar, tf, sec = min(breaches, key=lambda x: x[0]['timestamp']+x[2])
        context.update(status='broken', selection='withdrawn', reason='形成後の保存確定終値がレンジ外縁へ到達・越境。再形成待ち')
        context['break_observation'] = {'timeframe': tf, 'closed_at': bar['timestamp']+sec, 'saved_close': bar['close']}
        return
    candidate_inputs = condition_inputs(data, {**track, 'direction': 'long'}, clock)
    if candidate_inputs.get('status') != 'verified':
        context['reason'] = candidate_inputs.get('reason', '確認足が未確認')
        return
    last = candidate_inputs['bars'][-1]
    if last['timestamp'] < formed:
        context['reason'] = '水平帯の確定後に始まる確認足を待つ'
        return
    lower_touch = last['low'] <= lower_inner and last['high'] >= lower_low
    upper_touch = last['high'] >= upper_inner and last['low'] <= upper_high
    # A candle spanning both edges is ambiguous; never emit two directions.
    if lower_touch == upper_touch:
        context['reason'] = '両端接触で方向が曖昧' if lower_touch else '端への接触なし。中央で方向を作らず待機'
        return
    long = lower_touch
    stop = lower_outer if long else upper_outer
    target = upper_high if long else lower_low
    reference = bars[-1]
    if not (stop < last['close'] < target and stop < reference['close'] < target if long else
            target < last['close'] < stop and target < reference['close'] < stop):
        context['reason'] = '保存終値とレンジ価格計画の位置関係を確認できない'
        return
    direction = 'long' if long else 'short'
    risk = abs(reference['close']-stop); reward = abs(target-reference['close'])
    plan = {'status': 'reference_only', 'reference_timeframe': base,
            'reference_close': reference['close'], 'reference_close_timestamp': reference['timestamp'],
            'invalidation': stop, 'structural_target': target,
            'target_pivot': {'timestamp': (min(highs, key=lambda b: b['high']) if long else max(lows, key=lambda b: b['low']))['timestamp'], 'price': target},
            'risk_distance': risk, 'reference_rr': round(reward/risk, 2),
            'basis': 'confirmed_range_outer_invalidation_opposite_pivot_target_v1',
            'executable_price': False, 'formation_price': None, 'formation_rr': None}
    context.update(selection='lower_edge' if long else 'upper_edge', direction=direction,
                   reaction_level=lower_inner if long else upper_inner,
                   reason='下側水平帯の反発を確認する買いシナリオ' if long else '上側水平帯の反落を確認する売りシナリオ')
    track.update(scenario_type='range_reversal', direction=direction,
                 state='watch', trigger_status='range_edge_wait', invalidation_observed=False,
                 reaction_timestamp=last['timestamp'], price_action={'status': 'unverified', 'observation_only': True},
                 timing_assessment='timing_unverified', reference_plan=plan,
                 reference_levels={k: plan[k] for k in ('invalidation', 'structural_target', 'reference_rr')},
                 saved_reference_close=reference['close'])
    track['reference_levels']['executable_price'] = False
    track['trigger_price_reference'] = trigger_price_reference(data, track, clock)


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
