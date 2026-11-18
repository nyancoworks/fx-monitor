"""Joint SB/Span observations on the actual confirmation timeframe.

This is contextual evidence, not another indicator or an entry permission.
It deliberately does not turn oscillator events into a complete trade setup.
"""
from .span_special import observe


def describe(frame, direction):
    from .standard_technicals import bollinger_regime

    rows = frame.get('bars', [])
    sb = frame.get('super_bollinger', {})
    movement, regime = bollinger_regime(sb, [r['close'] for r in rows])
    span = observe(rows, frame['timeframe'], transitions=True)
    labels = {'trend':'トレンド', 'expanding_trend':'拡大トレンド',
              'gradual_trend':'緩やかなトレンド', 'correction':'調整',
              'range':'レンジ', 'transition':'移行中', 'unverified':'未確認'}
    sides = {'long':'上向き', 'short':'下向き', None:'方向未確定'}
    parts = ['SB '+labels.get(regime, '未確認')+'・'+sides[movement]]
    observations = {'sb_movement':movement, 'sb_regime':regime,
                    'span_model':span}
    opposing = []
    unavailable = []
    if regime == 'unverified':
        unavailable.append('super_bollinger')
    if direction in ('long', 'short') and movement and movement != direction:
        opposing.append('sb_movement')
    if span['status'] == 'available':
        last = span['last']
        if last['lag_zone'] == 'unavailable':
            unavailable.append('lag_zone')
        positions = {'above':'上', 'below':'下', 'inside':'絡み', 'unavailable':'未確認'}
        slope = {'up':'上向き', 'down':'下向き', 'flat':'横ばい'}
        parts += ['価格は青色の'+positions[last['blue_position']],
                  '赤色'+slope[span['red_slope']],
                  '遅行は過去足の'+positions[last['lag_candle']]+'・雲の'+positions[last['lag_zone']]]
        if direction in ('long', 'short'):
            opposite = 'below' if direction == 'long' else 'above'
            for key in ('blue_position', 'lag_candle', 'lag_zone'):
                if last[key] == opposite:
                    opposing.append(key)
            if span['red_slope'] == ('down' if direction == 'long' else 'up'):
                opposing.append('red_slope')
        event = span['signal_event']
        if event and event['within_grace']:
            parts.append('変化時間帯・'+{'long':'買い', 'short':'売り', None:'方向未確定'}[event['sign']]+'サイン')
            if direction and event['sign'] and event['sign'] != direction:
                opposing.append('change_window_sign')
    else:
        unavailable.append('span_model')
        parts.append('スパン未確認（履歴不足または入力不正）')
    # No count, majority, grade adjustment or mandatory all-indicator gate.
    names = {'sb_movement':'SBの動き', 'blue_position':'青色と価格',
             'red_slope':'赤色の向き', 'lag_candle':'遅行と過去足',
             'lag_zone':'遅行と雲', 'change_window_sign':'変化時間帯サイン'}
    concise = parts[0]+'。'+('反対材料：'+'・'.join(names[k] for k in opposing)
                            if opposing else 'スパンの反対材料は未観測' if span['status']=='available'
                            else 'スパンは履歴不足または入力不正で未確認')
    if 'lag_zone' in unavailable:
        concise += '（遅行と雲は未確認）'
    return {'schema':'murphy_timing_context_v1', 'timeframe':frame['timeframe'],
            'closed_at':frame.get('closed_at'), 'direction':direction,
            'observations':observations, 'opposing_components':opposing,
            'unavailable_components':unavailable,
            'summary':'／'.join(parts), 'concise_summary':concise,
            'scope':'context_not_setup_confirmation'}
