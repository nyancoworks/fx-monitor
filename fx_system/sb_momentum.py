"""Observed SB band dynamics, not an independent vote or forecast."""
from .advisory_indicators import stddev_bands


def describe(closes, direction, macd_momentum):
    if direction not in ('long', 'short') or len(closes) < 23:
        return {'status':'unavailable'}
    bands = stddev_bands(closes)
    sign = 1 if direction == 'long' else -1
    edge = 'upper' if sign == 1 else 'lower'
    sigma = '＋' if sign == 1 else '−'
    current, previous, earlier = bands[-1], bands[-2], bands[-3]
    delta = sign * (current['bands']['3'][edge] - previous['bands']['3'][edge])
    prior_delta = sign * (previous['bands']['3'][edge] - earlier['bands']['3'][edge])
    movement = 'aligned' if delta > 0 else 'opposed' if delta < 0 else 'flat'
    pace = ('accelerating' if delta > prior_delta else
            'decelerating' if delta < prior_delta else 'unchanged')
    runs = {}
    for n in ('1','2'):
        count = 0
        for close, band in reversed(list(zip(closes, bands))):
            if band is None or sign * (close-band['bands'][n][edge]) <= 0:
                break
            count += 1
        runs[n] = count
    prev_two = sign * (closes[-2]-previous['bands']['2'][edge]) > 0
    event = ('breakout' if runs['2'] == 1 else 'running' if runs['2'] > 1
             else 'slowing_inside_two' if prev_two and runs['1'] else
             'one_sigma_trend' if runs['1'] else 'inside_one')
    labels = {'breakout':sigma+'2σを終値で突破',
              'running':sigma+'2σ外を'+str(runs['2'])+'本継続',
              'slowing_inside_two':sigma+'2σ内へ戻るが'+sigma+'1σ外は維持',
              'one_sigma_trend':sigma+'1σ外を'+str(runs['1'])+'本継続',
              'inside_one':sigma+'1σ外の継続は未確認'}
    slope = ('方向側へ伸長' if movement == 'aligned' else
             '方向と逆へ動く' if movement == 'opposed' else '横ばい')
    if movement == 'aligned':
        slope += '・伸び加速' if pace == 'accelerating' else '・伸び鈍化' if pace == 'decelerating' else ''
    macd_aligned = macd_momentum == 'directional_building'
    conflict = (movement == 'opposed' and macd_aligned or
                movement == 'aligned' and macd_momentum in ('counterpressure_deepening','counterpressure_mixed'))
    # Both derive from price. Agreement is not two independent votes.
    return {'status':'observed','band_event':event,'outside_close_runs':runs,
            'directional_3sigma_delta':delta,'previous_directional_3sigma_delta':prior_delta,
            'movement':movement,'pace':pace,'macd_conflict':conflict,
            'summary':labels[event]+'。'+sigma+'3σは'+slope,
            'caution':('SBの帯の勢いとMACDが競合。再加速を断定しない' if conflict else
                       sigma+'3σの伸びが鈍化。帯外継続と勢い低下を区別' if movement=='aligned' and pace=='decelerating' else
                       sigma+'3σが方向と逆へ動く。継続の勢いに注意' if movement=='opposed' else None)}
