"""Span Model + SB contextual interpretation; not the proprietary auto-signal."""
import math

GRACE = {'w1':5, 'd1':5, 'h4':5, 'h1':5, 'm15':7, 'm5':8}


def observe(rows, timeframe, *, transitions=False):
    out = {'status':'unavailable', 'reason':'スパン計算に必要な確定足が不足',
           'parameters':[9,26,52], 'lag_intervals':26, 'cloud_shift':0}
    if timeframe not in GRACE or not isinstance(rows, list) or len(rows) < 53:
        return out
    if any(not isinstance(b,dict) or not all(type(b.get(k)) in (int,float) and math.isfinite(b[k]) and b[k]>0 for k in ('high','low','close'))
           or not b['low'] <= b['close'] <= b['high'] for b in rows):
        return {**out, 'reason':'スパン入力の高安・終値が不正'}
    def mid(i,n):
        window=rows[i-n+1:i+1]
        return (max(b['high'] for b in window)+min(b['low'] for b in window))/2
    def location(c,lo,hi):
        return 'above' if c>hi else 'below' if c<lo else 'inside'
    points=[]
    for i in range(51,len(rows)):
        blue=(mid(i,9)+mid(i,26))/2;red=mid(i,52);c=rows[i]['close']
        past=i-26
        past_blue=(mid(past,9)+mid(past,26))/2 if past>=51 else None
        past_red=mid(past,52) if past>=51 else None
        points.append({'timestamp':rows[i].get('timestamp'), 'close':c,'blue':blue,'red':red,
            'signal':'long' if blue>red else 'short' if blue<red else None,
            'zone':location(c,min(blue,red),max(blue,red)),
            'blue_position':location(c,blue,blue),
            'lag_candle':location(c,rows[past]['low'],rows[past]['high']),
            'lag_zone':location(c,min(past_blue,past_red),max(past_blue,past_red)) if past_blue is not None else 'unavailable'})
    previous,last=points[-2:]
    event=None
    for j in range(len(points)-1,0,-1):
        p,prior=points[j],points[j-1]
        if p['signal'] and p['signal'] != prior['signal']:
            age=len(points)-1-j
            side={'above':'short','below':'long'}.get(p['zone'])
            event={'timestamp':p['timestamp'],'signal':p['signal'],'sign':side,
                   'pattern':'undetermined' if side is None else 'forward' if side==p['signal'] else 'reverse',
                   'age_bars':age,'grace_bars':GRACE[timeframe],
                   'within_grace':age<GRACE[timeframe]}
            break
    change=last['red']-previous['red']
    changes = []
    if transitions:
        for field in ('blue_position', 'lag_candle', 'lag_zone'):
            before, after = previous[field], last[field]
            if 'unavailable' not in (before, after) and before != after:
                changes.append({'component':field, 'before':before, 'after':after,
                                'timestamp':last['timestamp']})
        if len(points) >= 3:
            old_change = previous['red']-points[-3]['red']
            before = 'up' if old_change>0 else 'down' if old_change<0 else 'flat'
            after = 'up' if change>0 else 'down' if change<0 else 'flat'
            if before != after:
                changes.append({'component':'red_slope', 'before':before, 'after':after,
                                'timestamp':last['timestamp']})
    return {**out,'status':'available','reason':None,'last':last,'previous':previous,
            **({'confirmed_changes':changes} if transitions else {}),
            'red_slope':'up' if change>0 else 'down' if change<0 else 'flat',
            'signal_event':event}


def timing(rows, timeframe, direction):
    obs=observe(rows,timeframe)
    if obs['status']!='available' or direction not in ('long','short'):return []
    own='above' if direction=='long' else 'below'
    last,prior=obs['last'],obs['previous']
    # A crossing of the blue span is a price reaction, not a cloud-colour vote.
    return ['span_blue_recovery'] if last['blue_position']==own and prior['blue_position']!=own else []


def apply(frame, forecast, *, transitions=False):
    obs=observe(frame.get('bars',[]), frame['timeframe'], transitions=transitions) if frame.get('status')=='available' else {'status':'unavailable','reason':'確定足未確認'}
    forecast['span_special']=obs
    if obs['status']!='available':
        forecast['cautions'].append(frame['timeframe'].upper()+'スパン：'+obs['reason'])
        return forecast
    last=obs['last'];direction=forecast['direction']
    words={'above':'上','below':'下','inside':'絡み','unavailable':'未確認'}
    text=(frame['timeframe'].upper()+'スパン：価格は青色の'+words[last['blue_position']]+
          '、赤色'+{'up':'上向き','down':'下向き','flat':'横ばい'}[obs['red_slope']]+
          '、遅行は過去足の'+words[last['lag_candle']]+'／雲の'+words[last['lag_zone']])
    if transitions and obs['confirmed_changes']:
        names = {'blue_position':'価格と青色', 'lag_candle':'遅行と過去足',
                 'lag_zone':'遅行と雲', 'red_slope':'赤色の向き'}
        slope_words = {'up':'上向き','down':'下向き','flat':'横ばい'}
        descriptions = []
        for item in obs['confirmed_changes']:
            labels = slope_words if item['component']=='red_slope' else words
            descriptions.append(names[item['component']]+'：'+labels[item['before']]+'→'+labels[item['after']])
        text+='。確定足の変化：'+'、'.join(descriptions)
    event=obs['signal_event']
    if event and event['within_grace']:
        side={'long':'買い','short':'売り',None:'未確定'}[event['sign']]
        text+='。変化時間帯：'+{'forward':'順行','reverse':'逆行','undetermined':'雲内で未判定'}[event['pattern']]+'・'+side+'サイン'
    own='above' if direction=='long' else 'below'
    opposed='below' if direction=='long' else 'above'
    conflict=direction in ('long','short') and last['blue_position']==opposed
    background_conflict = direction in ('long','short') and (
        obs['red_slope']==('down' if direction=='long' else 'up') or last['lag_candle']==opposed or last['lag_zone']==opposed)
    forecast['cautions' if conflict or background_conflict else 'support'].append(text)
    # Span positioning alone never downgrades. Adverse price reaction and
    # independently calculated momentum together challenge continuation.
    momentum=forecast['evolution']['momentum']
    if conflict and momentum in ('counterpressure_deepening','counterpressure_mixed'):
        forecast.update(conviction='weak',phase='transition')
        forecast['primary_path']='青色スパンの反対側へ推移し、MACDも逆行。継続シナリオを再評価'
        forecast['material_cautions'].append('span_momentum_conflict')
    elif direction and last['blue_position']==own and event and event['within_grace'] and event['sign'] not in (None,direction):
        forecast['cautions'].append('スパンの変化時間帯は逆方向サイン。現行トレンドの失速・転換を監視')
        forecast['material_cautions'].append('span_change_window_opposed')
    return forecast
