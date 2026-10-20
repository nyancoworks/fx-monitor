"""H4-only saved structural references, never an executable trade plan."""
import math


def _price(value):
    return value if type(value) in (int,float) and math.isfinite(value) and value>0 else None


def h4_reference_plan(rows, analysis, direction, invalidation):
    result={'status':'unavailable','reference_timeframe':'h4',
            'reference_close':None,'reference_close_timestamp':None,
            'structural_target':None,'target_pivot':None,'risk_distance':None,
            'reference_rr':None,'executable_price':False,
            'basis':'caller_supplied_completed_h4_close_and_confirmed_2left_2right_pivots',
            'limitations':['H4保存終値基準でありM15反応時点や現在のEntry価格ではない',
                           'スプレッド・手数料・滑り・イベントを含まない参考RR']}
    if direction not in ('long','short') or not rows:
        return {**result,'reason':'H4 direction or history unavailable'}
    last=rows[-1]
    close=_price(last.get('close'))
    stamp=last.get('timestamp')
    if close is None or type(stamp) is not int:
        return {**result,'reason':'H4 reference close or timestamp unavailable'}
    result.update(reference_close=close,reference_close_timestamp=stamp)
    stop=_price(invalidation)
    if stop is None:
        return {**result,'reason':'H4 confirmed invalidation unavailable'}
    risk=close-stop if direction=='long' else stop-close
    if risk<=0:
        return {**result,'reason':'H4 reference close reached or crossed invalidation'}
    result['risk_distance']=risk
    key='confirmed_swing_highs' if direction=='long' else 'confirmed_swing_lows'
    candidates=[p for p in analysis.get(key,[]) if isinstance(p,dict) and
                _price(p.get('price')) is not None and type(p.get('timestamp')) is int and
                p['timestamp']+2*14400<=stamp and
                (p['price']>close if direction=='long' else p['price']<close)]
    if not candidates:
        return {**result,'reason':'No confirmed H4 pivot ahead of reference close'}
    target=(min if direction=='long' else max)(candidates,key=lambda p:p['price'])
    reward=target['price']-close if direction=='long' else close-target['price']
    return {**result,'status':'reference_only','reason':'Nearest confirmed H4 pivot ahead of saved H4 close',
            'structural_target':target['price'],'target_pivot':dict(target),
            'reference_rr':round(reward/risk,2)}
