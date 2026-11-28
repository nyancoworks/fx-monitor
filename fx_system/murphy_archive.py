"""Frozen Issue #124 original price-plan projection for archived assessments."""

def project(record, frames, base, direction, price, plan, higher, background, setup_tf, timing_tf):
    ready = False
    sign = 1 if direction == 'long' else -1
    side, opposite = ('upper', 'lower') if sign == 1 else ('lower', 'upper')
    blue, red = (base['span']['last'][key] for key in ('blue', 'red'))
    entry = max(base['center'], blue) if sign == 1 else min(base['center'], blue)
    stop = min(base['bands']['1'][opposite], blue, red) if sign == 1 else max(
        base['bands']['1'][opposite], blue, red)
    target = base['bands']['3'][side]
    condition = f'{setup_tf.upper()}または{timing_tf.upper()}でSB・青色スパンが方向側、価格が基準水準の方向側'
    reaction = any(frames[tf].get('direction') == direction for tf in (setup_tf, timing_tf))
    # A stop breach immediately invalidates the saved plan at the latest
    # available observation. The reported stop itself is an intrabar level.
    if sign * (price - stop) <= 0:
        status = 'stopped'
    elif sign * (target - price) <= 0:
        status = 'target_reached'
    elif reaction and sign * (price - entry) >= 0:
        status = 'ready'
    else:
        status = 'waiting'
    if sign * (entry - stop) > 0 and sign * (target - entry) > 0 and stop > 0 and target > 0:
        ready = status == 'ready'
        formation = price if ready else entry
        pip = .01 if record['pair'].endswith('JPY') else .0001
        risk = sign * (formation - stop)
        reward = sign * (target - formation)
        plan.update(entry=formation, trigger_level=entry, stop=stop, target=target,
                    risk_pips=round(risk / pip, 2), reward_pips=round(reward / pip, 2),
                    rr=round(reward / risk, 2), status=status)
    if plan['status'] in ('stopped', 'target_reached', 'unavailable'):
        ready = False
    oppositions = [tf.upper() for tf in (higher, background)
                   if frames[tf].get('direction') not in (None, direction)]
    supported = any(frames[tf].get('direction') == direction for tf in (higher, background))
    grade = 'C' if oppositions else 'A' if ready and supported else 'B'
    reason = ('上位足に逆方向 '+ '・'.join(oppositions) if oppositions else
              '主軸のSBと青色スパンが方向側。上位足に同方向あり' if supported else
              '主軸のSBと青色スパンが方向側。上位足の支持は未確認')
    return ready, grade, reason, condition
