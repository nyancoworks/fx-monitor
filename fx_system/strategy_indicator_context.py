"""Describe independent saved indicator evidence, without votes or gates."""
from copy import deepcopy
import math


def _dict(value):
    return value if isinstance(value, dict) else {}


def _number(value):
    return value if type(value) in (int, float) and math.isfinite(value) else None


def _relation(side, direction):
    if side not in ('long', 'short') or direction not in ('long', 'short'):
        return 'unconfirmed'
    return 'aligned' if side == direction else 'opposed'


def strategy_indicator_context(data, track):
    """Trust only caller-verified timeframe flags; never alter input or selection."""
    direction = track.get('direction')
    result = {}
    for role, flag in (('base', 'base_verified'), ('trigger', 'trigger_verified')):
        tf = track[role + '_timeframe']
        if track.get(flag) is not True:
            result[role] = {'timeframe': tf, 'status': 'unverified',
                            'reason': '当該時間足の品質未確認', 'observations': []}
            continue
        notes = []
        sb = _dict(_dict(data.get('super_bollinger_context')).get(tf))
        research = _dict(_dict(data.get('indicator_research')).get(tf))
        band = _dict(research.get('band_research'))
        calculated = sb.get('status') == 'calculated'
        side = {'up': 'long', 'down': 'short'}.get(sb.get('centerline_direction')) if calculated else None
        notes.append({'indicator': 'super_bollinger', 'status': sb.get('status', 'unverified'),
                      'centerline_direction': sb.get('centerline_direction') if calculated else None,
                      'centerline_relation': _relation(side, direction),
                      'lagging_span_location': _dict(sb.get('lagging_span')).get('location') if calculated else None,
                      'bandwidth_change': _number(band.get('bandwidth_change')),
                      'lagged_close_comparison': band.get('lagged_close_comparison'),
                      'chart_parity_verified': False,
                      'meaning': '中心線・帯域変化・遅行の別々の観測。過去終値比較と対ローソク足比較を混同しない'})
        notes.append({'indicator': 'sma_context', 'sma100': _number(research.get('sma100')),
                      'sma200': _number(research.get('sma200')),
                      'missing_reason': 'SMA100/200は各履歴不足なら未提供',
                      'meaning': '背景の参考値。短期足で重視しすぎず、方向・採否を決めない'})
        # Standard H4 Fibonacci was calculated with the H1 setup direction.
        # A swing must instead use its own H4 setup's diagnostic.
        dma = (_dict(_dict(data.get('h4_setup_shadow')).get('dinapoli'))
               if tf == 'h4' and role == 'base' else
               _dict(_dict(data.get('dinapoli_research')).get(tf)))
        fib = _dict(dma.get('confirmed_fibonacci'))
        fib_direction = _dict(fib.get('fibonacci')).get('direction')
        matched = fib.get('status') == 'calculated' and fib_direction == direction and direction in ('long', 'short')
        notes.append({'indicator': 'standard_fibonacci_and_dma', 'dma': deepcopy(_dict(dma.get('dma'))),
                      'fibonacci': deepcopy({k:v for k,v in fib.items() if k!='entry_permission'}) if matched else None,
                      'fibonacci_status': 'direction_matched_reference' if matched else 'unavailable',
                      'reason': '通常フィボナッチの参考押し戻り・値幅投影。構造目標とは別物。方向一致した確定ピボットだけを参照し、DMA描画シフトは将来価格ではない'})
        dinapoli_ref = _dict(_dict(data.get('dinapoli_indicator_reference')).get(tf))
        ref_ok = dinapoli_ref.get('status') == 'calculated'
        ref_macd = _dict(dinapoli_ref.get('macd')) if ref_ok else {}
        ref_stoch = _dict(dinapoli_ref.get('preferred_stochastic')) if ref_ok else {}
        ref_histogram = _number(ref_macd.get('histogram'))
        ref_side = ('long' if ref_histogram is not None and ref_histogram > 0 else
                    'short' if ref_histogram is not None and ref_histogram < 0 else None)
        notes.append({'indicator': 'dinapoli_macd_preferred_stochastic',
                      'status': 'provisional_reference' if ref_ok else dinapoli_ref.get('status', 'unavailable'),
                      'macd': deepcopy(ref_macd), 'preferred_stochastic': deepcopy(ref_stoch),
                      'calculation_assumptions': deepcopy(dinapoli_ref.get('assumptions', [])),
                      'preferred_stochastic_algorithm': ref_stoch.get('algorithm', 'legacy_saved_unverified_algorithm'),
                      'macd_histogram_relation': _relation(ref_side, direction),
                      'chart_parity_verified': False,
                      'meaning': 'ディナポリ係数MACDとPreferred Stochasticの参考計算。algorithmでCQG Original修正版と旧保存値を区別。外部チャート一致は未検証。勢い・転換の参考として保持'})
        result[role] = {'timeframe': tf, 'status': 'reference', 'observations': notes}
    return {'frames': result, 'affects_selection': False,
            'interpretation': '一致点と対立点を個別に示す。多数決・単純加点・新しいAND条件に使わない',
            'source_scope': 'saved_existing_diagnostics_not_verified_teacher_rules'}
