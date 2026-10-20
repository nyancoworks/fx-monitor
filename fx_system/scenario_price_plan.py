"""Independent saved-candle price plans; structural targets and projections stay separate."""
import math
from .dinapoli_research import confirmed_fibonacci


def _price(value):
    return value if type(value) in (int,float) and math.isfinite(value) and value>0 else None


def saved_price_plan(data, track, evaluated_at):
    tf=track['base_timeframe'];seconds={'h4':14400,'h1':3600}[tf]
    rows=data.get(tf,{}).get('candles',[])
    if not track.get('base_verified') or track.get('direction') not in ('long','short') or not rows:
        return None
    last=rows[-1];stamp=last.get('timestamp');close=_price(last.get('close'))
    if close is None or type(stamp) is not int or type(evaluated_at) is not int or stamp+seconds>evaluated_at:
        return None
    analysis=data.get('technical',{}).get(tf,{})
    direction=track['direction'];long=direction=='long'
    def pivots(key):
        return [p for p in analysis.get(key,[]) if isinstance(p,dict) and _price(p.get('price')) is not None
                and type(p.get('timestamp')) is int and p['timestamp']+2*seconds<=stamp]
    stops=pivots('confirmed_swing_lows' if long else 'confirmed_swing_highs')
    stop=stops[-1]['price'] if stops else None
    risk=(close-stop if long else stop-close) if stop else None
    targets=[p for p in pivots('confirmed_swing_highs' if long else 'confirmed_swing_lows')
             if p['price']>close] if long else [p for p in pivots('confirmed_swing_lows') if p['price']<close]
    target=(min if long else max)(targets,key=lambda p:p['price']) if targets else None
    rr=round(abs(target['price']-close)/risk,2) if target and risk and risk>0 else None
    plan={'status':'reference_only' if rr is not None else 'unavailable','reference_timeframe':tf,
          'reference_close':close,'reference_close_timestamp':stamp,'invalidation':stop,
          'structural_target':target['price'] if target else None,'target_pivot':target,
          'risk_distance':risk,'reference_rr':rr,'executable_price':False,
          'basis':'own_timeframe_confirmed_2left_2right_pivots_and_saved_close',
          'reason':'Nearest confirmed pivot ahead of saved close' if target else 'No confirmed pivot ahead of saved close',
          'formation_price':None,'formation_rr':None,
          'formation_rr_reason':'成立価格未確定。成立後の価格・無効化・目標で再計算が必要',
          'limitations':['保存基準終値の参考RR。スプレッド・手数料・滑りを含まない']}
    fib=confirmed_fibonacci(rows,direction)
    projection={'status':'unavailable','method':'standard_fibonacci','reason':fib.get('reason'),
                'structural_target':False,'targets':[]}
    if fib.get('status')=='calculated':
        projection.update(status='reference_only',reason='Confirmed impulse range projection, not observed resistance/support',
                          start_pivot=fib['start_pivot'],end_pivot=fib['end_pivot'])
        for ratio,price in fib['fibonacci']['extension_levels'].items():
            ahead=price>close if long else price<close
            projection['targets'].append({'ratio':ratio,'price':price,'ahead_of_saved_close':ahead,
                'reference_rr':round(abs(price-close)/risk,2) if ahead and risk and risk>0 else None})
    plan['reference_projection']=projection
    return plan


def trigger_price_reference(data, track, evaluated_at):
    """Latest saved closed trigger price, separate from base plan and formation price."""
    tf=track['trigger_timeframe'];seconds={'m15':900,'m5':300}[tf]
    result={'status':'unverified','timeframe':tf,'evaluated_at':evaluated_at,
            'basis':'saved_completed_trigger_candle_not_live_quote_or_formation_price'}
    if track.get('trigger_verified') is not True:
        return {**result,'reason':'Trigger candle quality is unverified'}
    rows=data.get(tf,{}).get('candles',[])
    if not rows:return {**result,'reason':'Saved trigger candle unavailable'}
    last=rows[-1];stamp=last.get('timestamp');close=_price(last.get('close'))
    if (close is None or type(stamp) is not int or type(evaluated_at) is not int or
            stamp%seconds or not 0<=evaluated_at-(stamp+seconds)<seconds):
        return {**result,'reason':'Trigger close or completed-candle clock is invalid/stale'}
    base_stamp=track.get('reference_plan',{}).get('reference_close_timestamp')
    if type(base_stamp) is int and stamp+seconds<base_stamp+{'h4':14400,'h1':3600}[track['base_timeframe']]:
        return {**result,'reason':'Trigger reference predates the base reference close'}
    return {**result,'status':'observed_reference','close':close,'candle_timestamp':stamp,
            'closed_at':stamp+seconds,'reason':'Verified saved trigger close at the evaluation clock'}
