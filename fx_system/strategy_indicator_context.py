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


def strategy_indicator_context(data, track, *, evaluated_at=None):
    """Trust only caller-verified timeframe flags; never alter input or selection."""
    direction = track.get('direction')
    application = data.get('indicator_context_version') == 2
    def fresh(stamp, tf):
        seconds = {'m5':300,'m15':900,'h1':3600,'h4':14400}.get(tf)
        return (type(stamp) is int and type(evaluated_at) is int and seconds
                and stamp % seconds == 0 and 0 <= evaluated_at-stamp-seconds < seconds)
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
        calculated = sb.get('status') == 'calculated' and (not application or fresh(sb.get('last_timestamp'),tf))
        side = {'up': 'long', 'down': 'short'}.get(sb.get('centerline_direction')) if calculated else None
        notes.append({'indicator': 'super_bollinger', 'status': sb.get('status', 'unverified'),
                      'centerline_direction': sb.get('centerline_direction') if calculated else None,
                      'centerline_relation': _relation(side, direction),
                      'lagging_span_location': _dict(sb.get('lagging_span')).get('location') if calculated else None,
                      'bandwidth_change': _number(band.get('bandwidth_change')),
                      'lagged_close_comparison': band.get('lagged_close_comparison'),
                      'chart_parity_verified': False,
                      'meaning': '中心線・帯域変化・遅行の別々の観測。過去終値比較と対ローソク足比較を混同しない'})
        if application:
            note = notes[-1]
            if not calculated:
                note['status']='unverified'
            price = _number(sb.get('last_close')) if calculated else None
            band1 = _dict(_dict(sb.get('bands')).get('1'))
            lower,upper = _number(band1.get('lower')),_number(band1.get('upper'))
            width = (_number(band.get('bandwidth_change')) if calculated
                     and _dict(research.get('rci_observation')).get('last_timestamp')==sb.get('last_timestamp') else None)
            note['application'] = {'closed_at':sb['last_timestamp']+{'m5':300,'m15':900,'h1':3600,'h4':14400}[tf] if calculated else None,
                'lagging_relation': _relation({'above':'long','below':'short'}.get(note['lagging_span_location']),direction) if calculated else 'unconfirmed',
                'bandwidth_state':'expanding' if width is not None and width>0 else 'contracting' if width is not None and width<0 else 'flat' if width==0 else 'unverified',
                'price_zone':('above_upper_1sigma' if price>upper else 'below_lower_1sigma' if price<lower else 'inside_1sigma')
                    if price is not None and lower is not None and upper is not None else 'unverified',
                'not_original_method_certification':True}
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
        if application:
            price = _number(dma.get('saved_close'))
            checked = fresh(dma.get('last_timestamp'),tf) and price is not None and price>0
            positions = {}
            for name, value in _dict(dma.get('dma')).items():
                value = _dict(value); plot = _number(value.get('current_plot')); slope = _number(value.get('plot_slope'))
                spec = {'3x3':(3,3),'7x5':(7,5),'25x5':(25,5)}.get(name)
                seconds = {'m5':300,'m15':900,'h1':3600,'h4':14400}[tf]
                valid = (checked and plot is not None and plot>0 and value.get('plot_timestamp')==dma.get('last_timestamp')
                    and spec is not None and (value.get('period'),value.get('display_shift'))==spec
                    and value.get('source_timestamp')==dma['last_timestamp']-spec[1]*seconds
                    and value.get('basis')=='historical_sma_displaced_to_current_bar_not_latest_future_plot')
                positions[name] = {'status':'observed_reference' if valid else 'unverified',
                    'plot':plot if valid else None,'saved_close':price if valid else None,
                    'price_side':('above' if price>plot else 'below' if price<plot else 'at') if valid else 'unverified',
                    'slope_movement':('rising' if slope>0 else 'falling' if slope<0 else 'flat') if valid and slope is not None else 'unverified',
                    'price_relation':_relation('long' if price>plot else 'short' if price<plot else None,direction) if valid else 'unconfirmed',
                    'slope_relation':_relation('long' if slope>0 else 'short' if slope<0 else None,direction) if valid and slope is not None else 'unconfirmed',
                    'source_timestamp':value.get('source_timestamp') if valid else None}
            notes[-1]['application'] = {'closed_at':dma['last_timestamp']+{'m5':300,'m15':900,'h1':3600,'h4':14400}[tf] if checked else None,
                                       'positions':positions}
        dinapoli_ref = _dict(_dict(data.get('dinapoli_indicator_reference')).get(tf))
        ref_ok = dinapoli_ref.get('status') == 'calculated' and (not application or fresh(dinapoli_ref.get('last_timestamp'),tf))
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
        if application:
            notes[-1]['status']='provisional_reference' if ref_ok else 'unverified'
        result[role] = {'timeframe': tf, 'status': 'reference', 'observations': notes}
    context = {'frames': result, 'affects_selection': False,
            'interpretation': '一致点と対立点を個別に示す。多数決・単純加点・新しいAND条件に使わない',
            'source_scope': 'saved_existing_diagnostics_not_verified_teacher_rules'}
    if application:
        context.update(schema='contextual_indicator_context_v2',evaluated_at=evaluated_at)
    return context
