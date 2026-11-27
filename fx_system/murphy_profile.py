"""Issue #124 profile. Saved indicator observations fully reproduce the assessment."""
from copy import deepcopy
import math

from .span_special import observe
from .standard_technicals import bollinger_regime
from .strategy_strength import interpret

METHOD = 'murphy_sb_span_v1'
TIMEFRAMES = {
    'swing': ('w1', 'd1', 'h4', 'h1', 'm15'),
    'daytrade': ('d1', 'h4', 'h1', 'm15', 'm5'),
}
TREND = {'gradual_trend', 'trend', 'expanding_trend'}


def observation(frame, tf, clock, quality):
    closed = frame.get('closed_at')
    if (quality.get('ok') is not True or frame.get('verified') is not True
            or frame.get('status') != 'available' or frame.get('timeframe') != tf
            or frame.get('evaluated_at') != clock or type(closed) is not int
            or not 0 < closed <= clock):
        return {'status': 'unverified'}
    bars = frame['bars']
    sb = frame['super_bollinger']
    direction, phase = bollinger_regime(sb, [bar['close'] for bar in bars])
    span = observe(bars, tf, transitions=True)
    if phase == 'unverified' or span['status'] != 'available':
        return {'status': 'insufficient', 'closed_at': closed, 'close': bars[-1]['close']}
    pos = span['last']['blue_position']
    side = {'above': 'long', 'below': 'short'}.get(pos)
    return {
        'status': 'available', 'closed_at': closed, 'close': bars[-1]['close'],
        'direction': direction if phase in TREND and direction == side else None,
        'sb_direction': direction, 'sb_phase': phase,
        'center': sb['centerline'], 'bands': deepcopy(sb['bands']),
        'span': span, 'macd': deepcopy(frame['macd']['observations'][-2:]),
        'rci': deepcopy(frame['rci']),
    }


def capture(data, quality, clock):
    frames = data.get('standard_technical_frames', {})
    return {tf: observation(frames.get(tf, {}), tf, clock,
                            quality.get('timeframes', {}).get(tf, {}))
            for tf in ('w1', 'd1', 'h4', 'h1', 'm15', 'm5')}


def assess(pair, strategy, clock, inputs, strength):
    context = {tf: deepcopy(inputs[tf]) for tf in TIMEFRAMES[strategy]}
    # M5 is a price observation only for swing, whose timing remains H1/M15.
    if strategy == 'swing':
        context['m5'] = {key: value for key, value in inputs['m5'].items()
                         if key in ('closed_at', 'close', 'status')}
    return refresh({
        'method_version': METHOD, 'pair': pair, 'strategy': strategy, 'evaluated_at': clock,
        'murphy_inputs': context, 'currency_strength_context': deepcopy(strength) or {},
        'execution_authority': 'none', 'advisory_only': True,
    })


def refresh(record):
    strategy, clock = record['strategy'], record['evaluated_at']
    higher, background, base_tf, setup_tf, timing_tf = TIMEFRAMES[strategy]
    frames = record['murphy_inputs']
    if set(frames) != set(TIMEFRAMES[strategy]) | {'m5'}:
        raise ValueError('Murphy timeframe inputs mismatch')
    for frame in frames.values():
        if frame['status'] not in ('available', 'unverified', 'insufficient'):
            raise ValueError('Murphy timeframe quality invalid')
        if frame['status'] != 'unverified':
            if (type(frame['closed_at']) is not int or not 0 < frame['closed_at'] <= clock
                    or type(frame['close']) not in (int, float)
                    or not math.isfinite(frame['close']) or frame['close'] <= 0):
                raise ValueError('Murphy timeframe observation invalid')

    base = frames[base_tf]
    direction = base.get('direction')
    price_tf = next((tf for tf in ('m5', timing_tf, setup_tf, base_tf)
                     if frames[tf].get('close') is not None), None)
    price_frame = frames[price_tf] if price_tf else {}
    price = price_frame.get('close')
    state = ('evaluation_pending' if base['status'] != 'available'
             else 'review' if direction else 'skip')
    ready = False
    grade = None
    reason = '主軸の確定足・SB・スパン未確認' if state == 'evaluation_pending' else '主軸の方向未確定'
    plan = {'current': price, 'price_timeframe': price_tf, 'price_closed_at': price_frame.get('closed_at'),
            'entry': None, 'stop': None, 'target': None, 'risk_pips': None,
            'reward_pips': None, 'rr': None, 'status': 'unavailable'}
    condition = '主軸のSBと青色スパンの方向を確認'
    if direction:
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

    record.update(reference_timeframe=base_tf, trigger_timeframe=timing_tf,
                  assessment=state, grade=grade, direction=direction, grade_reason=reason,
                  price_plan=plan, entry_condition=condition, ready_to_consider=ready,
                  reference_levels={'scenario_target': plan['target']},
                  reasons=[reason], formation_conditions=[condition] if direction else [],
                  currency_strength_context=interpret(record.get('currency_strength_context'),
                                                      record['pair'], strategy, direction, clock))
    return record


def selected(outlook):
    records = [row for row in outlook['strategy_assessments']
               if row['assessment'] == 'review' and row['price_plan']['status'] in ('ready', 'waiting')]
    ranked = sorted(records, key=lambda row: (
        'ABC'.index(row['grade']), not row['ready_to_consider'],
        row['currency_strength_context']['comparison_priority'],
        -(row['price_plan']['rr'] or 0), row['pair']))
    return [row for strategy in TIMEFRAMES for row in
            [candidate for candidate in ranked if candidate['strategy'] == strategy][:3]]
