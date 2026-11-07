"""Supplementary long swing plan from the existing verified candle frames."""
from .core import technical
from .monitor_pairs import PAIR_KEYS
from .standard_technicals import forecast, wave


def build_long_swing(pairs, clock):
    records = []
    for pair in PAIR_KEYS:
        frames = pairs.get(pair, {}).get('standard_technical_frames')
        if not frames:
            continue
        records.append(_evaluate(pair, frames, clock))
    return records


def _evaluate(pair, frames, clock):
    row = {'pair': pair, 'status': 'pending'}
    w1, d1, h4 = (frames[tf] for tf in ('w1', 'd1', 'h4'))
    weekly = w1.get('super_bollinger') or {}
    row['weekly_direction'] = (weekly.get('centerline_direction') if
        w1.get('verified') and weekly.get('status') == 'calculated' else None)
    daily = d1.get('bars', [])
    if not d1.get('verified') or d1.get('status') != 'available' or not daily or not 0 < d1.get('closed_at', 0) <= clock:
        return {**row, 'reason': '検証済みの日足が不足'}
    view = forecast(d1, technical(daily).get('structure', 'unconfirmed'))
    if view['status'] != 'available':
        return {**row, 'reason': 'D1の方向材料が不足または競合'}
    direction = view['direction']
    row.update(direction=direction, daily_reason=view['primary_path'])
    plan = wave(daily, direction)
    if plan['status'] != 'available':
        return {**row, 'status': 'recheck', 'reason': 'D1の波または新しい目標を確認待ち'}
    target = plan['retest_objective']['price']
    stop = plan['thesis_invalidation']
    row.update(target=target, invalidation=stop)
    recent = h4.get('bars', [])[-4:]
    closed = h4.get('closed_at', 0)
    if (not h4.get('verified') or len(recent) != 4 or not 0 <= clock-closed < 14400
            or closed < d1['closed_at']):
        return {**row, 'reason': '同時点のH4確定足が不足'}
    from .mt4_calendar import sequence_valid
    continuous = (sequence_valid(recent) if h4.get('calendar') == 'mt4_ny_close_h4_v1' else
                  all(b['timestamp']-a['timestamp'] == 14400 for a,b in zip(recent, recent[1:])))
    if not continuous:
        return {**row, 'reason': 'H4確定足の連続性を確認できない'}
    price = recent[-1]['close']
    row.update(saved_close=price, closed_at=closed)
    sign = 1 if direction == 'long' else -1
    if sign*(target-price) <= 0 or sign*(price-stop) <= 0:
        return {**row, 'status': 'recheck', 'reason': 'H4終値がD1の目標・撤回水準の範囲外'}
    field, edge = ('high', max) if direction == 'long' else ('low', min)
    observed = sign*(price-edge(b[field] for b in recent[:-1])) > 0
    window = recent[:-1] if observed else recent[1:]
    return {**row, 'status': 'observed' if observed else 'waiting',
            'reaction_level': edge(b[field] for b in window),
            'reward_pips': round(sign*(target-price)/(0.01 if pair.endswith('JPY') else 0.0001), 2)}
