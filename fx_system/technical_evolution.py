"""Bounded base-frame indicator evolution; no acquisition or new parameters."""
from copy import deepcopy
import math

METHOD = 'contextual_scenario_review_v11_technical_evolution'


def finite(value):
    return type(value) in (int,float) and math.isfinite(value)


def observe(rows, timeframe, clock, quality_ok):
    """Reuse the exact existing recursive seeds and finite-window formulas.

    Three prefixes end at three consecutive completed base candles. Never
    restart an EMA at a short arbitrary window or include a future candle.
    """
    from .dinapoli_indicator_reference import indicator_reference
    from .dinapoli_research import dma_snapshot
    from .indicator_research import rci_series
    sec = {'h4':14400,'h1':3600}.get(timeframe)
    out = {'schema':'base_evolution_inputs_v1','evaluated_at':clock,'timeframe':timeframe,
           'quality_verified':quality_ok is True,'status':'unverified','points':[],
           'basis':'existing_verified_indicator_frames_same_recursive_seed_no_fetch'}
    if (quality_ok is not True or not sec or type(clock) is not int
            or not isinstance(rows,list) or not 54<=len(rows)<=10000):
        return out
    for i,b in enumerate(rows):
        if not isinstance(b,dict):return out
        ts=b.get('timestamp');values=[b.get(k) for k in ('open','high','low','close')]
        if (type(ts) is not int or ts<=0 or ts%sec or ts+sec>clock
                or i and ts<=rows[i-1]['timestamp']
                or not all(finite(v) and v>0 for v in values)):
            return out
        o,h,l,c=values
        if not l<=min(o,c)<=max(o,c)<=h:return out
    if (not 0<=clock-rows[-1]['timestamp']-sec<sec
            or any(b['timestamp']-a['timestamp']!=sec for a,b in zip(rows[-3:],rows[-2:]))):
        return out
    points=[]
    for end in range(len(rows)-2,len(rows)+1):
        prefix=rows[:end];ref=indicator_reference(prefix);dma=dma_snapshot(prefix)['dma']['3x3']
        if ref.get('status')!='calculated':return out
        closes=[b['close'] for b in prefix]
        points.append({'closed_at':prefix[-1]['timestamp']+sec,'close':closes[-1],
            'macd_histogram':ref['macd']['histogram'],'dma3x3':dma['current_plot'],
            'stochastic_k':ref['preferred_stochastic']['slow_k'],
            'rci':{str(p):rci_series(closes[-p:],p)[-1] for p in (9,26,52)}})
    if any(not all(finite(p.get(k)) for k in ('close','macd_histogram','dma3x3','stochastic_k'))
           for p in points):
        return out
    return {**out,'status':'available','points':points,'input_count':len(rows),
            'recursive_seed':'existing_first_observation_full_verified_prefix',
            'scope':'three_observed_base_bars_not_time_to_target'}


def describe(record):
    """MACD measures momentum path; DMA position and RCI remain separate roles."""
    from .technical_scenario import _notes
    clock=record['evaluated_at'];tf=record['reference_timeframe'];sec={'h4':14400,'h1':3600}[tf]
    result={'schema':'base_technical_evolution_v1','evaluated_at':clock,'timeframe':tf,
            'status':'unverified','momentum':'unverified','setup_position':'unverified',
            'persistence':{'26':'unverified','52':'unverified'},'first_closed_at':None,
            'last_closed_at':None,'summary':tf.upper()+'の複数足の勢いの経過は未確認。回復を補完しない',
            'not_reversal_confirmation_or_probability':True}
    inp=record.get('base_evolution_inputs',{});direction=record.get('direction')
    sign=1 if direction=='long' else -1 if direction=='short' else 0
    if not isinstance(inp,dict) or not sign:return result
    points=inp.get('points',[])
    if (record.get('base_quality_verified') is not True or inp.get('quality_verified') is not True
            or inp.get('schema')!='base_evolution_inputs_v1' or inp.get('status')!='available'
            or inp.get('evaluated_at')!=clock or inp.get('timeframe')!=tf
            or not isinstance(points,list) or len(points)!=3):
        return result
    for p in points:
        if not isinstance(p,dict):return result
        ts=p.get('closed_at');rci=p.get('rci',{})
        if (type(ts) is not int or ts<=0 or ts%sec or ts>clock or not isinstance(rci,dict)
                or not all(finite(p.get(k)) for k in ('close','macd_histogram','dma3x3','stochastic_k'))
                or p['close']<=0 or p['dma3x3']<=0
                or not all(finite(rci.get(str(k))) for k in (9,26,52))):
            return result
    if (any(b['closed_at']-a['closed_at']!=sec for a,b in zip(points,points[1:]))
            or not 0<=clock-points[-1]['closed_at']<sec):
        return result
    # Bind the sequence endpoint to the same base candle AND existing indicator
    # observation. A separate/reseeded or stale trajectory cannot affect a grade.
    bar=record.get('technical_plan_inputs',{}).get('bar',{})
    note=_notes(record,'base').get('dinapoli_macd_preferred_stochastic',{})
    histogram=note.get('macd',{}).get('histogram')
    if (points[-1]['closed_at']!=bar.get('timestamp',-sec)+sec or points[-1]['close']!=bar.get('close')
            or note.get('status')!='provisional_reference' or not finite(histogram)
            or not math.isclose(points[-1]['macd_histogram'],histogram,rel_tol=1e-10,abs_tol=1e-12)):
        return result
    notes=_notes(record,'base')
    plot=notes.get('standard_fibonacci_and_dma',{}).get('application',{}).get('positions',{}).get('3x3',{}).get('plot')
    k=note.get('preferred_stochastic',{}).get('slow_k')
    periods=record.get('rci_observation',{}).get('frames',{}).get('base',{}).get('periods',{})
    endpoints=[(points[-1]['dma3x3'],plot),(points[-1]['stochastic_k'],k)]
    endpoints.extend((points[-1]['rci'][p],periods.get(p,{}).get('value')) for p in ('9','26','52'))
    if any(not finite(b) or not math.isclose(a,b,rel_tol=1e-10,abs_tol=1e-12) for a,b in endpoints):
        return result
    h=[sign*p['macd_histogram'] for p in points]
    changes=[b-a for a,b in zip(h,h[1:])]
    increasing=all(d>=0 for d in changes) and any(d>0 for d in changes)
    decreasing=all(d<=0 for d in changes) and any(d<0 for d in changes)
    if h[-1]<0:
        momentum='counterpressure_easing' if increasing else 'counterpressure_deepening' if decreasing else 'counterpressure_mixed'
    elif h[-1]>0:
        momentum='directional_building' if increasing else 'directional_fading' if decreasing else 'directional_stable' if all(d==0 for d in changes) else 'directional_mixed'
    else:
        momentum='neutral'
    gaps=[sign*(p['close']-p['dma3x3']) for p in points]
    if all(v>0 for v in gaps[-2:]):setup='directional_position_held'
    elif gaps[-1]>0:setup='first_directional_recovery'
    elif all(b<a for a,b in zip(gaps,gaps[1:])):setup='counter_position_deepening'
    elif all(b>a for a,b in zip(gaps,gaps[1:])):setup='counter_position_easing'
    else:setup='position_mixed'
    persistence={}
    for period in ('26','52'):
        changes=[sign*(b['rci'][period]-a['rci'][period]) for a,b in zip(points,points[1:])]
        persistence[period]=('recovering' if all(d>0 for d in changes) else
                             'weakening' if all(d<0 for d in changes) else
                             'flat' if all(d==0 for d in changes) else 'mixed')
    texts={'counterpressure_easing':'MACDは逆行側だが2区間で逆行が鈍化。押し戻り鈍化の参考で、再開確定ではない',
           'counterpressure_deepening':'MACDの逆行が2区間で拡大。押し戻り継続・転換リスクを優先し、仕掛けを待つ',
           'counterpressure_mixed':'MACDは逆行側で変化も混在。押し戻り終了は未確認',
           'directional_building':'MACDは方向側で2区間の勢いが改善。DMAに対する回復の持続は別確認',
           'directional_fading':'MACDは方向側だが2区間で減速。直進継続より押し戻りへの移行に注意',
           'directional_stable':'MACDは方向側で横ばい。加速・反転とは扱わない',
           'directional_mixed':'MACDは方向側だが変化が混在。再加速を断定しない',
           'neutral':'MACDは中立。次の基準足で勢いを再評価'}
    return {**result,'status':'available','momentum':momentum,'setup_position':setup,
            'persistence':persistence,'first_closed_at':points[0]['closed_at'],
            'last_closed_at':points[-1]['closed_at'],'summary':tf.upper()+'確定足3本：'+texts[momentum]}


def apply(record, outlook):
    out=deepcopy(outlook);e=describe(record);out['evolution']=e
    # Enrich the actual causal outlook, not just a detached diagnostic. Only
    # downgrade unwarranted maturity; no easing observation promotes a B to A.
    if out['status']=='unverified':return out
    out['path']=e['summary']+'。'+out['path']
    if e['momentum']=='directional_fading' and out['status']=='continuation':
        out['status']='retracement_then_continuation'
        out['path']=e['summary']+'。DMA・通常Fib付近への調整を想定し、勢い回復後の終点再試しを待つ'
    if e['momentum'] not in ('directional_building','directional_stable'):
        out['cautions'].append(e['summary'])
    if out['setup']=='resumption_context' and e['setup_position']!='directional_position_held':
        out['setup']='timing_wait'
        out['cautions'].append('DMA3x3の方向側への回復持続が未確認。一足だけの回復で完成度を上げない')
    return out


def defer_priority(outlook):
    e=outlook.get('evolution',{})
    return e.get('status')!='available' or e.get('momentum')=='counterpressure_deepening'
