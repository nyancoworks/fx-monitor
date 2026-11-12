"""RCI timing, with one optional bullish candle observation; no PA strategy."""
from copy import deepcopy
from statistics import median
import math

BASIS='rci9_turn_v1'
MULTI_BASIS = 'multi_technical_turn_v1'
SIGNAL_LABELS = {
    'rci9_extreme_recovery': 'RCI9の極端域からの反転',
    'macd_signal_cross': 'MACDのシグナル交差',
    'sb_one_sigma_cross': '終値の方向側1σ通過',
}


def timing_signals(closes, direction, *, continuation=False):
    from .advisory_indicators import stddev_bands
    from .indicator_research import rci_series
    from .standard_technicals import macd

    sign = 1 if direction == 'long' else -1
    signals = []
    if len(closes) >= 10:
        rci = rci_series(closes[-10:], 9)
        if turn_observed(rci[-1], rci[-2], direction):
            signals.append('rci9_extreme_recovery')
    if len(closes) >= 35:
        previous, current = (v['histogram'] for v in macd(closes)[-2:])
        if sign * previous <= 0 < sign * current:
            signals.append('macd_signal_cross')
    if len(closes) >= 22:
        previous, current = stddev_bands(closes[-22:])[-2:]
        edge = 'upper' if sign == 1 else 'lower'
        if sign * (closes[-2] - previous['bands']['1'][edge]) <= 0 < sign * (closes[-1] - current['bands']['1'][edge]):
            signals.append('sb_one_sigma_cross')
        elif continuation and sign * (closes[-2] - previous['bands']['1'][edge]) > 0 and sign * (closes[-1] - current['bands']['1'][edge]) > 0:
            signals.append('sb_one_sigma_hold')
    return signals


def turn_observed(value,previous,direction):
    if direction not in ('long','short') or not all(type(x) in (int,float) and math.isfinite(x) and -100<=x<=100 for x in (value,previous)):return None
    return min(value,previous)<=-80 and value>previous if direction=='long' else max(value,previous)>=80 and value<previous


def describe(record):
    clock=record['evaluated_at'];tf=record['trigger_timeframe'];direction=record.get('direction')
    result={'schema':'scenario_conditions_v1','evaluated_at':clock,'timeframe':tf,'direction':direction,
        'status':'unavailable','route':'technical_rci_recovery','conditions':[],
        'observed_at':None,'observed_close':None,'formation_price':None,'formation_rr':None,
        'advisory_only':True,'profitability_validated':False,'basis':BASIS,
        'scope':'technical_timing_not_candle_pattern_or_fill','level':None}
    def unavailable(text,status='unavailable'):
        return {**result,'status':status,'reason':text,'summary':text}
    multi = record.get('multi_timing_version') in (1, 2, 3)
    if multi:
        result.update(basis=MULTI_BASIS, route='multi_technical_recovery', scope='alternative_technical_timing')
    if tf == 'h1':
        result.update(basis='h1_price_reaction_v1', route='continuation_breakout',
                      scope='h1_price_reaction_with_rci_context')
    if record.get('expiry',{}).get('status')=='withdrawn':return unavailable('旧経路は終了。新しい価格計画を待つ','withdrawn')
    if record.get('assessment')!='review':return unavailable('主要材料の不足または方向未確定で条件を具体化できない','not_applicable')
    f=record['standard_inputs']['trigger'];sec={'m5':300,'m15':900,'h1':3600}[tf];rci=f.get('rci',{}).get('9',{})
    rows=f.get('bars',[]);closed=f.get('closed_at');value,previous=rci.get('value'),rci.get('previous')
    observed=turn_observed(value,previous,direction)
    if (f.get('verified') is not True or f.get('evaluated_at')!=clock or f.get('timeframe')!=tf
            or type(closed) is not int or not 0<=clock-closed<sec or not rows or (tf != 'h1' and not multi and observed is None)):
        return unavailable('同時刻の確定確認足・RCI9の位置と傾きを確認できない')
    price=rows[-1]['close'];levels=record['reference_levels'];stop,target=levels.get('invalidation'),levels.get('scenario_target')
    if (type(stop) not in (int,float) or type(target) not in (int,float)
            or not (stop<price<target if direction=='long' else target<price<stop)):
        return unavailable('方向仮説は保持するが、経路目標・撤回と確認足価格の関係を再評価する')
    if tf == 'h1':
        if len(rows) < 4 or any(b['timestamp']-a['timestamp'] != sec
                                for a,b in zip(rows[-4:], rows[-3:])):
            return unavailable('連続するH1確定足が不足')
        long = direction == 'long'
        edge, extreme = ('high', max) if long else ('low', min)
        previous_level = extreme(b[edge] for b in rows[-4:-1])
        confirmed = price > previous_level if long else price < previous_level
        level = previous_level if confirmed else extreme(b[edge] for b in rows[-3:])
        move = '上抜け' if long else '下抜け'
        timing = ('H1確定終値で直前3本の水準を'+move+'観測' if confirmed else
                  f'H1確定終値で直近3本の水準 {level} の{move}待ち')
        rci_context = ('RCI9反転を観測' if observed else
                       'RCI9反転は未観測' if observed is False else 'RCI9は未確認')
        text = timing+'。'+rci_context+'（勢いの補足）'
        return {**result, 'status':'conditions_observed' if confirmed else 'waiting',
                'summary':text, 'reason':text, 'level':level,
                'conditions':[{'kind':'h1_close_breakout', 'lookback':3, 'price':level}],
                'observed_at':closed if confirmed else None,
                'observed_close':price if confirmed else None,
                'evidence':{'closed_at':closed,'rci9':value,'previous_rci9':previous},
                'withdrawal_conditions':deepcopy(record.get('expiry',{}).get('withdrawal_conditions',[]))}
    if multi:
        pullback = record.get('multi_timing_version') == 2 and record.get('timing_context') == 'pullback'
        kinds = ('sb_one_sigma_cross',) if pullback else tuple(SIGNAL_LABELS)
        current = record.get('multi_timing_version') == 3
        if current:
            kinds = (*kinds, 'sb_one_sigma_hold')
        options = {'continuation': True} if current else {}
        signals = [kind for kind in timing_signals([bar['close'] for bar in rows], direction, **options) if kind in kinds]
        if record.get('span_special_version') == 1 and current:
            from .span_special import timing
            kinds = (*kinds, 'span_blue_recovery')
            signals.extend(timing(rows, tf, direction))
        band_cross = '＋1σを上抜け' if direction == 'long' else '−1σを下抜け'
        labels = {**SIGNAL_LABELS, 'sb_one_sigma_cross': '終値が'+band_cross+'る動き'}
        labels['sb_one_sigma_hold'] = '終値が'+('＋1σより上' if direction == 'long' else '−1σより下')+'を維持する動き'
        labels['span_blue_recovery'] = '終値が青色スパンの'+('上' if direction == 'long' else '下')+'へ回復する動き'
        frame = {'m15':'15分足', 'm5':'5分足'}[tf]
        wait = ('1時間足の調整後、終値が'+band_cross+'るのを待つ' if pullback else
                'RCI9反転・MACD交差・終値が'+band_cross+'る動きのいずれかを待つ')
        if current:
            wait = 'RCI9反転、MACD交差、終値が'+band_cross+'る動き、または'+('＋1σより上' if direction == 'long' else '−1σより下')+'の維持を確認待ち'
        if record.get('span_special_version') == 1 and current:
            wait += '（青色スパン回復も確認）'
        summary = (frame+'の確定足で'+'・'.join(labels[s] for s in signals)+'を観測'
                   if signals else frame+'の確定足で'+wait)
        return {**result, 'status':'conditions_observed' if signals else 'waiting',
                'summary':summary, 'reason':summary,
                'conditions':[{'kind':kind} for kind in kinds],
                'observed_at':closed if signals else None,
                'observed_close':price if signals else None,
                'evidence':{'closed_at':closed,'signals':signals},
                'withdrawal_conditions':deepcopy(record.get('expiry',{}).get('withdrawal_conditions',[]))}
    text=tf.upper()+'のRCI9が'+('−80以下から上向く押し目回復' if direction=='long' else '＋80以上から下向く戻りの収束')+'を確定足で確認する。ローソク足パターンは必須にしない'
    return {**result,'status':'conditions_observed' if observed else 'waiting',
        'reason':('RCI9反転のタイミングを観測' if observed else 'RCI9の極端域からの反転待ち')+'。方向背景・価格経路・局所停止は別途評価',
        'summary':text,'conditions':[{'kind':'rci9_extreme_recovery','period':9,
            'extreme':-80 if direction=='long' else 80,'movement':'rising' if direction=='long' else 'falling'}],
        'observed_at':closed if observed else None,'observed_close':price if observed else None,
        'evidence':{'rci9':value,'previous_rci9':previous,'closed_at':closed},
        'withdrawal_conditions':deepcopy(record.get('expiry',{}).get('withdrawal_conditions',[]))}


def candle_reference(record):
    f=record['standard_inputs']['trigger'];rows=f.get('bars',[]);rci=f.get('rci',{}).get('9',{})
    out={'status':'not_applicable','required_for_timing':False,'guarantee':False,
         'summary':'ローソク足は独立した仕掛け条件に使用しない'}
    if (record.get('direction')!='long' or record.get('assessment')!='review' or not rows
            or f.get('verified') is not True or f.get('evaluated_at')!=record['evaluated_at']
            or type(f.get('closed_at')) is not int or not 0<=record['evaluated_at']-f['closed_at']<{'m5':300,'m15':900,'h1':3600}[record['trigger_timeframe']]):return out
    value,previous=rci.get('value'),rci.get('previous')
    if turn_observed(value,previous,'long') is not True:return out
    b=rows[-1];body=abs(b['close']-b['open']);lower=min(b['open'],b['close'])-b['low'];upper=b['high']-max(b['open'],b['close'])
    previous_bodies=[abs(p['close']-p['open']) for p in rows[-5:-1]]
    long_wick=lower>max(body,upper)
    strong_bull=bool(previous_bodies and b['close']>b['open'] and body>median(previous_bodies) and body>lower+upper)
    return {**out,'status':'observed' if long_wick or strong_bull else 'not_observed',
        'body':body,'lower_wick':lower,'upper_wick':upper,'long_lower_wick':long_wick,'strong_bullish_body':strong_bull,
        'definition':'参考分類：下ヒゲが実体/上ヒゲより長い、または陽線実体が前4本中央値とヒゲ合計を上回る。優位性未検証',
        'summary':'RCI9の極端域からの上向きに、'+('下ヒゲまたは強い陽線の補足反応を観測' if long_wick or strong_bull else '補足の下ヒゲ/強い陽線は未観測')+'。必須条件・満点評価・約定・利益保証ではない'}
