"""Finite-window Span Model observations from existing verified closed candles.

Clouds stay at their calculation time. The lagging close is placed 26 intervals
back. This explicit convention is not a claim of external chart parity.
"""
from copy import deepcopy
import math

SECONDS = {'h4':14400, 'h1':3600, 'm15':900, 'm5':300}
WINDOW = 80  # 52-period historical cloud + 26-interval lag + 2 prior points.


def _positive(value):
    return type(value) in (int, float) and math.isfinite(value) and value > 0


def inputs(rows, timeframe, clock, quality_ok):
    result = {'schema':'span_model_inputs_v1', 'timeframe':timeframe,
              'evaluated_at':clock, 'quality_verified':quality_ok is True,
              'status':'unverified', 'first_timestamp':None, 'high_low':[], 'closes':[]}
    sec = SECONDS.get(timeframe)
    if (not sec or type(clock) is not int or quality_ok is not True
            or not isinstance(rows, list) or len(rows) < WINDOW):
        return result
    selected = rows[-WINDOW:]
    previous = None
    for bar in selected:
        if not isinstance(bar, dict):return result
        stamp = bar.get('timestamp')
        values = [bar.get(k) for k in ('open','high','low','close')]
        if (type(stamp) is not int or stamp <= 0 or stamp % sec or stamp+sec > clock
                or previous is not None and stamp-previous != sec
                or not all(_positive(v) for v in values)):
            return result
        o,h,l,c = values
        if not l <= min(o,c) <= max(o,c) <= h:return result
        previous = stamp
    if not 0 <= clock-selected[-1]['timestamp']-sec < sec:return result
    return {**result, 'status':'available', 'first_timestamp':selected[0]['timestamp'],
            'high_low':[[b['high'],b['low']] for b in selected],
            'closes':[b['close'] for b in selected[-3:]]}


def calculate(inp):
    """Recompute bounded evidence on restore; never extrapolate missing history."""
    if not isinstance(inp,dict):return None
    tf = inp.get('timeframe');sec = SECONDS.get(tf);clock = inp.get('evaluated_at')
    first = inp.get('first_timestamp');hl = inp.get('high_low');closes = inp.get('closes')
    if (inp.get('schema')!='span_model_inputs_v1' or inp.get('status')!='available'
            or inp.get('quality_verified') is not True or not sec or type(clock) is not int
            or type(first) is not int or first<=0 or first%sec
            or not isinstance(hl,list) or len(hl)!=WINDOW
            or not isinstance(closes,list) or len(closes)!=3
            or not all(_positive(c) for c in closes)
            or not 0<=clock-first-WINDOW*sec<sec):return None
    if any(not isinstance(p,list) or len(p)!=2 or not all(_positive(v) for v in p)
           or p[1]>p[0] for p in hl):return None
    if any(not p[1]<=c<=p[0] for p,c in zip(hl[-3:],closes)):return None

    def midpoint(index, period):
        rows=hl[index-period+1:index+1]
        return (max(p[0] for p in rows)+min(p[1] for p in rows))/2

    def cloud(index):
        return (midpoint(index,9)+midpoint(index,26))/2, midpoint(index,52)

    def location(price, lower, upper):
        return 'above' if price>upper else 'below' if price<lower else 'inside'

    points=[]
    for index,close in zip(range(WINDOW-3,WINDOW),closes):
        blue,red=cloud(index);past=index-26;old_blue,old_red=cloud(past)
        points.append({'closed_at':first+(index+1)*sec, 'close':close,
            'blue':blue,'red':red,'cloud_side':'long' if blue>red else 'short' if blue<red else 'neutral',
            'price_location':location(close,min(blue,red),max(blue,red)),
            'lagging_candle_location':location(close,hl[past][1],hl[past][0]),
            'lagging_cloud_location':location(close,min(old_blue,old_red),max(old_blue,old_red)),
            'lagging_reference_timestamp':first+past*sec})
    red_changes=[b['red']-a['red'] for a,b in zip(points,points[1:])]
    red_trend=('rising' if all(v>=0 for v in red_changes) and any(v>0 for v in red_changes) else
               'falling' if all(v<=0 for v in red_changes) and any(v<0 for v in red_changes) else
               'flat' if all(v==0 for v in red_changes) else 'mixed')
    return {'schema':'span_model_observation_v1','timeframe':tf,'evaluated_at':clock,
            'status':'available','points':points,'red_trend':red_trend,
            'cloud_display_shift':0,'lagging_display_shift':-26,
            'parameters':{'short':9,'medium':26,'long':52},'chart_parity_verified':False}


def note(inp):
    return {'indicator':'span_model','inputs':deepcopy(inp), 'observation':calculate(inp),
            'meaning':'雲は現在位置、遅行は26区間前。価格由来の環境・押し戻りの補足で独立票にしない'}


def describe(record, role='base'):
    from .technical_scenario import _notes
    tf=record['reference_timeframe' if role=='base' else 'trigger_timeframe']
    result={'status':'unverified','timeframe':tf,'state':'unverified',
            'summary':tf.upper()+'スパンモデルは未確認。雲や回復を補完しない'}
    n=_notes(record,role).get('span_model',{});inp=n.get('inputs',{})
    obs=calculate(inp)
    if (obs is None or obs!=n.get('observation') or obs['timeframe']!=tf
            or obs['evaluated_at']!=record['evaluated_at']):return result
    if role=='base':
        bar=record.get('technical_plan_inputs',{}).get('bar',{})
        close=bar.get('close');stamp=bar.get('timestamp')
        closed=stamp+SECONDS[tf] if type(stamp) is int else None
        verified=record.get('base_quality_verified') is True
    else:
        ref=record.get('trigger_price_reference',{})
        close=ref.get('close');closed=ref.get('closed_at')
        verified=(ref.get('status')=='observed_reference' and ref.get('timeframe')==tf
                  and ref.get('evaluated_at')==record['evaluated_at'])
    points=obs['points'];last=points[-1]
    if not verified or last['close']!=close or last['closed_at']!=closed:return result
    direction=record.get('direction');own='above' if direction=='long' else 'below'
    opposite='below' if direction=='long' else 'above'
    if direction not in ('long','short'):return result
    locations=[p['price_location'] for p in points]
    red_opposed=obs['red_trend']==('falling' if direction=='long' else 'rising')
    if all(p==opposite for p in locations[-2:]):
        state='cloud_failure';text='終値が2本続けて雲の反対側。正常な押し戻りと決めつけず、方向背景の競合を再評価'
    elif red_opposed:
        state='background_conflict';text='赤色スパンの傾きが方向仮説と逆。短期回復と背景転換を区別'
    elif locations[-1]==opposite:
        state='cloud_break_unconfirmed';text='終値が雲の反対側へ。単発の越境で方向を反転せず、回復か背景悪化かを確認'
    elif locations[-1]=='inside':
        state='pullback_in_cloud';text='終値は雲の中。押し戻りの進行として扱い、方向側への回復を待つ'
    elif locations[-2]!=own:
        state='first_recovery';text='終値が方向側へ雲を抜けた初足。回復持続・再加速は未確認'
    else:
        state='directional_position_held';text='終値は2本続けて雲の方向側。押し戻り後の継続を検討する背景で、成立保証ではない'
    label={'above':'上','below':'下','inside':'内側'}
    summary=(tf.upper()+'スパンモデル：'+text+'。赤色='+obs['red_trend']+
             '、遅行は過去足の'+label[last['lagging_candle_location']]+
             '・過去雲の'+label[last['lagging_cloud_location']])
    return {**result,'status':'available','state':state,'summary':summary,
            'red_trend':obs['red_trend'],'price_location':last['price_location'],
            'cloud_side':last['cloud_side'],'lagging_candle_location':last['lagging_candle_location'],
            'lagging_cloud_location':last['lagging_cloud_location'],
            'cross_observed':any(a['cloud_side']!=b['cloud_side'] for a,b in zip(points,points[1:])),
            'cross_meaning':'交差は変化の観測。単独の方向転換・売買サインにはしない'}


def apply(record, forecast):
    """Refine an existing directional thesis; no new vote or forced reversal."""
    base=describe(record);trigger=describe(record,'trigger')
    forecast['span_model']={'base':base,'trigger':trigger}
    state=base['state']
    if state=='directional_position_held':forecast['support'].append(base['summary'])
    else:forecast['cautions'].append(base['summary'])
    if state in ('cloud_failure','background_conflict'):
        forecast.update(phase='transition',conviction='weak',primary_path=base['summary'])
    elif state in ('pullback_in_cloud','cloud_break_unconfirmed','first_recovery'):
        # Preserve an already weak/deepening/reversal forecast. Cloud position
        # cannot turn adverse momentum into an optimistic recovery forecast.
        if forecast['phase'] in ('continuation','recovery_wait'):
            forecast.update(phase='recovery_wait',primary_path=base['summary'])
        if forecast['conviction']=='established':forecast['conviction']='developing'
    elif state=='unverified' and forecast['conviction']=='established':
        forecast['conviction']='developing'
    if trigger['state']!='directional_position_held':
        forecast['cautions'].append(trigger['summary']+'。確認足の情報だけで大局予測を反転しない')
    return forecast
