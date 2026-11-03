"""Re-read confirmed obstacles against the retained completed trigger candles."""
from copy import deepcopy
from .scenario_conditions import condition_inputs, _price


def describe(record, plan):
    original=plan.get('first_obstacle')
    result={'status':'unverified','original_obstacle':deepcopy(original),
            'active_obstacle':deepcopy(original),'passed_level':None,
            'reaction':'unverified','role':'base_reference_obstacle',
            'summary':'確認足を再照合できず、基準足時点の障害を維持する'}
    if plan.get('status')!='available' or not original:return result
    tf=record['trigger_timeframe'];clock=record['evaluated_at']
    inp=record.get('entry_condition_inputs',{})
    if (inp.get('status')!='verified' or inp.get('timeframe')!=tf
            or inp.get('evaluated_at')!=clock or inp.get('direction')!=record['direction']):return result
    checked=condition_inputs({tf:{'candles':inp.get('bars')}},
        {'base_verified':record.get('base_quality_verified'), 'trigger_verified':True,
         'direction':record['direction'],'trigger_timeframe':tf},clock)
    recent=record.get('trigger_price_reference',{})
    if (checked.get('status')!='verified' or checked['closed_at']!=inp.get('closed_at')
            or recent.get('status')!='observed_reference' or recent.get('timeframe')!=tf
            or recent.get('evaluated_at')!=clock or recent.get('closed_at')!=checked['closed_at']
            or recent.get('close')!=checked['bars'][-1]['close']):return result
    sec={'h4':14400,'h1':3600}[record['reference_timeframe']]
    known_at=original['timestamp']+3*sec
    bars=[b for b in checked['bars'] if b['timestamp']>=known_at]
    if not bars:return result
    last=bars[-1];sign=1 if record['direction']=='long' else -1
    level=original['price'];sides=[sign*(b['close']-level) for b in bars]
    result.update(status='available',closed_at=checked['closed_at'],saved_close=last['close'])
    if sides[-1]<=0:
        failed=any(v>0 for v in sides[:-1])
        result.update(reaction='breakout_failed' if failed else 'not_crossed',
            summary=('途中障害の終値突破後に元の側へ戻った。突破失敗の反応として障害を維持する'
                     if failed else '途中障害は確認足終値で未突破。ヒゲの越境だけでは通過扱いにしない'))
        return result
    # A close beyond the old obstacle changes its role, not the trend thesis.
    # Retests are chronological observations; never infer one outside this window.
    last_return=max((i for i,v in enumerate(sides) if v<=0),default=-1)
    held=any(sides[i-1]>0 and sides[i]>0 and b['low']<=level<=b['high']
             for i,b in enumerate(bars) if i>max(0,last_return))
    reaction=('retest_held' if held else 'breakout_close_observed'
              if len(sides)>1 and sides[-2]<=0 else 'beyond_level_retest_unobserved')
    inputs=record.get('technical_plan_inputs',{})
    if record.get('forecast_wave_version')==1:
        from .forecast_wave import plan as parent_plan
        inputs,_=parent_plan(record)
    sec={'h4':14400,'h1':3600}[record['reference_timeframe']]
    stamp=plan['reference_close_timestamp']
    candidates=inputs.get('highs' if sign==1 else 'lows',[])
    candidates=[p for p in candidates if isinstance(p,dict) and type(p.get('timestamp')) is int
                and p['timestamp']>0
                and p['timestamp']%sec==0 and p['timestamp']+2*sec<=stamp
                and _price(p.get('price'))
                and sign*(p['price']-last['close'])>0]
    end=plan.get('retest_objective')
    if end and sign*(end['price']-last['close'])>0:candidates.append(end)
    active=min(candidates,key=lambda p:sign*(p['price']-last['close'])) if candidates else None
    words={'retest_held':'突破後の別の確認足で再試しを観測し、終値は方向側を保持',
           'breakout_close_observed':'今回の確認足終値で突破。再試し・持続は未確認',
           'beyond_level_retest_unobserved':'確認足終値は突破側。保有する直近足では再試し未観測'}
    result.update(active_obstacle=deepcopy(active),passed_level=level,reaction=reaction,
        role='potential_support' if sign==1 else 'potential_resistance',
        summary=words[reaction]+'。通過水準は支持抵抗への転換候補として残し、前方障害とは区別する。転換確定・大局再開の保証ではない')
    return result
