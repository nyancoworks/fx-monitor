"""Descriptive saved-candidate observations, never trade performance or new decisions."""
import math


def positive(v):
    return type(v) in (int, float) and math.isfinite(v) and v > 0


def observe(record, bars, through):
    clock = record['evaluated_at']
    out = {'pair': record['pair'], 'strategy': record['strategy'],
           'saved_grade': record['grade'], 'saved_direction': record['direction'],
           'saved_evaluated_at': clock, 'status': 'awaiting_future_saved_candles',
           'trade_performance': 'not_measured', 'window_is_scenario_expiry': False}
    if record.get('direction') not in ('long', 'short'):
        return {**out, 'status': 'saved_direction_unavailable'}
    ref = record.get('trigger_price_review', {})
    seconds = {'m5': 300, 'm15': 900}.get(record.get('trigger_timeframe'))
    if (ref.get('status') != 'observed_reference' or not positive(ref.get('saved_close'))
            or not seconds or ref.get('reference_timeframe') != record['trigger_timeframe']
            or type(ref.get('closed_at')) is not int or ref['closed_at'] % seconds
            or not 0 < ref['closed_at'] <= clock or clock-ref['closed_at'] >= seconds):
        return {**out, 'status': 'saved_reference_unavailable'}
    out.update(reference_close=ref['saved_close'], reference_closed_at=ref['closed_at'],
               reference_is_entry_price=False)
    if type(through) is not int or through < clock or not isinstance(bars, list):
        return {**out, 'status': 'followup_input_invalid'}
    # Only full M5 intervals starting after publication can describe future movement.
    rows = []
    for b in bars:
        if not isinstance(b, dict) or type(b.get('timestamp')) is not int:
            return {**out, 'status': 'followup_input_invalid'}
        ts = b['timestamp']
        if ts < clock or ts + 300 > through:
            continue
        if (ts % 300 or any(not positive(b.get(k)) for k in ('open', 'high', 'low', 'close'))
                or not b['low'] <= min(b['open'], b['close']) <= max(b['open'], b['close']) <= b['high']):
            return {**out, 'status': 'followup_input_invalid'}
        rows.append(b)
    if not rows:
        return out
    stamps = [b['timestamp'] for b in rows]
    if stamps != sorted(set(stamps)):
        return {**out, 'status': 'followup_input_invalid'}
    gaps = [{'after': a, 'before': b} for a, b in zip(stamps, stamps[1:]) if b-a != 300]
    start_expected = ((clock+299)//300)*300
    price, sign = ref['saved_close'], 1 if record['direction'] == 'long' else -1
    pip = .01 if record['pair'].endswith('JPY') else .0001
    favorable = max(0, max((b['high']-price if sign == 1 else price-b['low']) for b in rows))/pip
    adverse = max(0, max((price-b['low'] if sign == 1 else b['high']-price) for b in rows))/pip
    levels = record.get('reference_levels', {})
    def first_touch(key):
        level = levels.get(key)
        if not positive(level):
            return {'status': 'saved_level_unavailable'}
        for b in rows:
            reached = (b['high'] >= level if sign == 1 else b['low'] <= level) if key == 'structural_target' else (b['low'] <= level if sign == 1 else b['high'] >= level)
            if reached:
                return {'status': 'touched_in_observed_bar', 'level': level, 'bar_opened_at': b['timestamp'], 'bar_closed_at': b['timestamp']+300}
        return {'status': 'not_seen_in_observed_bars', 'level': level}
    target, stop = first_touch('structural_target'), first_touch('invalidation')
    return {**out, 'status': 'descriptive_observation_only', 'observed_bar_count': len(rows),
            'first_bar_opened_at': stamps[0], 'last_bar_closed_at': stamps[-1]+300,
            'missing_start': stamps[0] != start_expected, 'missing_end': through-(stamps[-1]+300) >= 300,
            'internal_gaps': gaps, 'favorable_excursion_pips': favorable,
            'adverse_excursion_pips': adverse, 'last_close_directional_change_pips': sign*(rows[-1]['close']-price)/pip,
            'target_touch': target, 'invalidation_level_touch': stop,
            'same_bar_touch_order_unknown': target.get('bar_opened_at') is not None and target.get('bar_opened_at') == stop.get('bar_opened_at'),
            'touch_is_not_scenario_formation_or_close_based_withdrawal': True}

