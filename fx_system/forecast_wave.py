"""Observed H4 parent impulse tied to the existing DMA25x5 background cycle.

No fitted thresholds, target-distance optimization, acquisition or future data.
The current forecast selects the side; nested pivots do not reset the parent.
"""
from copy import deepcopy
import math


def positive(x):
    return type(x) in (int,float) and math.isfinite(x) and x>0


def inputs(rows, clock, verified):
    out={'schema':'forecast_wave_inputs_v1','timeframe':'h4','evaluated_at':clock,
         'quality_verified':verified is True,'status':'unverified','first_timestamp':None,'hlc':[]}
    if verified is not True or not isinstance(rows,list) or not 35<=len(rows)<=10000:return out
    selected=rows[-500:]
    for index,b in enumerate(selected):
        if not isinstance(b,dict):return out
        t=b.get('timestamp');v=[b.get(k) for k in ('open','high','low','close')]
        if (type(clock) is not int or type(t) is not int or t<=0 or t%14400
                or t+14400>clock or index and t-selected[index-1]['timestamp']!=14400
                or not all(positive(x) for x in v)):return out
        o,h,l,c=v
        if not l<=min(o,c)<=max(o,c)<=h:return out
    if not 0<=clock-selected[-1]['timestamp']-14400<14400:return out
    return {**out,'status':'available','first_timestamp':selected[0]['timestamp'],
            'hlc':[[b['high'],b['low'],b['close']] for b in selected]}


def select(inp,direction):
    out={'status':'unverified','reason':'H4親波の品質・方向・履歴が未確認',
         'highs':[],'lows':[],'projection':{'status':'unavailable'}}
    if not isinstance(inp,dict):return out
    rows=inp.get('hlc');clock=inp.get('evaluated_at');first=inp.get('first_timestamp')
    sign=1 if direction=='long' else -1 if direction=='short' else 0
    if (not sign or inp.get('schema')!='forecast_wave_inputs_v1' or inp.get('timeframe')!='h4'
            or inp.get('quality_verified') is not True or inp.get('status')!='available'
            or not isinstance(rows,list) or not 35<=len(rows)<=500
            or type(clock) is not int or type(first) is not int or first<=0 or first%14400
            or not 0<=clock-first-len(rows)*14400<14400):return out
    if any(not isinstance(b,list) or len(b)!=3 or not all(positive(x) for x in b)
           or not b[1]<=b[2]<=b[0] for b in rows):return out
    highs=[];lows=[]
    for i in range(2,len(rows)-2):
        if all(rows[i][0]>rows[j][0] for j in (i-2,i-1,i+1,i+2)):
            highs.append({'timestamp':first+i*14400,'price':rows[i][0]})
        if all(rows[i][1]<rows[j][1] for j in (i-2,i-1,i+1,i+2)):
            lows.append({'timestamp':first+i*14400,'price':rows[i][1]})
    out.update(highs=highs,lows=lows)
    # Exact slope sign of the existing 25-period SMA displaced five bars:
    # SMA[i-5] - SMA[i-6] = (close[i-5] - close[i-30]) / 25.
    runs=[];slopes=[]
    for i in range(30,len(rows)):
        delta=rows[i-5][2]-rows[i-30][2]
        slopes.append(delta)
        recent=slopes[-3:]
        side=(1 if len(recent)==3 and all(v>=0 for v in recent) and any(v>0 for v in recent)
              else -1 if len(recent)==3 and all(v<=0 for v in recent) and any(v<0 for v in recent) else 0)
        if side and (not runs or side!=runs[-1][1]):runs.append((i-2,side))
    matched=[j for j,(_,side) in enumerate(runs) if side==sign]
    if not matched:return {**out,'reason':'予測方向に対応するH4背景区間を履歴内で確認できない'}
    # A counter episode does not reverse the forecast or erase the preceding
    # parent impulse. Existing forecast cautions describe that conflict.
    run_index=matched[-1]
    boundary=runs[run_index][0];earliest=runs[run_index-1][0] if run_index else 0
    endings,starts=(highs,lows) if sign==1 else (lows,highs)
    origins=[p for p in starts if first+earliest*14400<=p['timestamp']<=first+boundary*14400]
    if not origins:return {**out,'reason':'背景転換に対応する確定起点が履歴内にない'}
    start=min(origins,key=lambda p:sign*p['price'])
    # Moving averages lag price: the confirmed impulse high/low can precede
    # the DMA turn. Do not demand that price waits for an indicator timestamp.
    candidates=[p for p in endings if p['timestamp']>start['timestamp']]
    if not candidates:return {**out,'reason':'親波の方向側終点が未確定'}
    end=max(candidates,key=lambda p:sign*p['price'])
    if sign*(end['price']-start['price'])<=0:return {**out,'reason':'背景方向の正の親波値幅を確認できない'}
    breaches=[first+i*14400 for i,b in enumerate(rows)
              if first+i*14400>=start['timestamp']+3*14400 and sign*(b[2]-start['price'])<=0]
    return {**out,'status':'available','reason':'テクニカル予測方向とDMA25x5背景区間に対応する確定H4親波',
            'projection':{'status':'reference_only','start_pivot':deepcopy(start),'end_pivot':deepcopy(end)},
            'selection':{'schema':'forecast_parent_wave_v1','direction':direction,
                'background_start':first+boundary*14400,'search_start':first+earliest*14400,
                'history_left_censored':run_index==0,'input_count':len(rows),
                'background_relation':'aligned' if run_index==len(runs)-1 else 'opposed',
                'thesis_breached_at':breaches[0]+14400 if breaches else None,
                'thesis_breach_close':rows[(breaches[0]-first)//14400][2] if breaches else None,
                'basis':'forecast_direction_existing_dma25x5_cycle_confirmed_2left_2right_extremes',
                'does_not_optimize_distance_or_rr':True}}


def plan(record):
    inp=record.get('forecast_wave_inputs',{})
    chosen=select(inp,record.get('direction'))
    old=record.get('technical_plan_inputs',{});bar=old.get('bar',{})
    rows=inp.get('hlc',[]) if isinstance(inp,dict) else []
    if (record.get('strategy')!='swing' or record.get('reference_timeframe')!='h4'
            or record.get('base_quality_verified') is not True or inp.get('evaluated_at')!=record['evaluated_at']
            or not rows or bar.get('timestamp')!=inp.get('first_timestamp',0)+(len(rows)-1)*14400
            or [bar.get(k) for k in ('high','low','close')]!=rows[-1]):
        chosen={'status':'unverified','reason':'親波と基準足の時計・価格・品質が不一致','projection':{'status':'unavailable'},'highs':[],'lows':[]}
    return {**deepcopy(old),'projection':chosen['projection'],'highs':chosen['highs'],'lows':chosen['lows']},chosen
