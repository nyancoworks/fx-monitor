"""Technical wave thesis and conditional price path, separate from local timing.

Uses existing indicator calculations and confirmed impulse anchors. No fetching,
fitted thresholds, teacher-method certification, orders or time-to-target model.
Legacy assessments retain their original interpreter and rendering.
"""
from copy import deepcopy
import math

METHOD = 'contextual_scenario_review_v10_technical_wave'


def positive(x):
    return type(x) in (int, float) and math.isfinite(x) and x > 0


def plan_inputs(data, track, clock):
    tf = track['base_timeframe']
    analysis = data.get('technical', {}).get(tf, {})
    return {'evaluated_at': clock, 'timeframe': tf,
            'quality_verified': track.get('base_verified') is True,
            'bar': {k: data.get(tf, {}).get('candles', [{}])[-1].get(k)
                    for k in ('timestamp', 'open', 'high', 'low', 'close')}
                   if data.get(tf, {}).get('candles') else {},
            'projection': deepcopy(track.get('reference_plan', {}).get('reference_projection', {})),
            'highs': deepcopy(analysis.get('confirmed_swing_highs', [])),
            'lows': deepcopy(analysis.get('confirmed_swing_lows', []))}


def _notes(r, role):
    context = r.get('indicator_context', {})
    tf = r.get('reference_timeframe' if role == 'base' else 'trigger_timeframe')
    seconds = {'h4':14400, 'h1':3600, 'm15':900, 'm5':300}.get(tf, 0)
    if (context.get('schema') != 'contextual_indicator_context_v2'
            or context.get('evaluated_at') != r.get('evaluated_at')):
        return {}
    f = context.get('frames', {}).get(role, {})
    if f.get('timeframe') != tf:
        return {}
    notes = {n.get('indicator'):n for n in f.get('observations', []) if isinstance(n, dict)}
    # All role observations are tied to the same freshly completed frame.
    closed = notes.get('super_bollinger', {}).get('application', {}).get('closed_at')
    if (not seconds or type(closed) is not int or closed % seconds
            or not 0 <= r['evaluated_at']-closed < seconds):
        return {}
    return notes


def _movement(r, period, role='base'):
    f = r.get('rci_observation', {}).get('frames', {}).get(role, {})
    seconds = {'h4':14400, 'h1':3600, 'm15':900, 'm5':300}.get(f.get('timeframe'), 0)
    stamp = f.get('last_timestamp')
    if (f.get('status') not in ('observed_reference', 'calculated') or not seconds
            or type(stamp) is not int or not 0 <= r['evaluated_at']-stamp-seconds < seconds
            or f.get('timeframe') != r.get('reference_timeframe' if role=='base' else 'trigger_timeframe')):
        return 'unverified'
    return f.get('periods', {}).get(str(period), {}).get('movement', 'unverified')


def build_outlook(r):
    """Role hierarchy, not summed votes or a simultaneous indicator checklist."""
    out = {'schema':'technical_wave_outlook_v1', 'evaluated_at':r['evaluated_at'],
           'timeframe':r['reference_timeframe'], 'status':'unverified',
           'setup':'unverified', 'path':'大局の材料が不足。方向・到達を補完せず評価保留',
           'cautions':[], 'holding_period':'not_estimated', 'time_exit':'not_defined',
           'intended_horizon':'multi_session_wave' if r['strategy']=='swing' else 'intraday_wave',
           'not_probability_or_order':True}
    sign = 1 if r.get('direction')=='long' else -1 if r.get('direction')=='short' else 0
    if (r.get('base_quality_verified') is not True or not sign
            or {'HH_HL':1, 'LH_LL':-1}.get(r.get('base_structure')) != sign):
        return out
    notes = _notes(r, 'base'); sb = notes.get('super_bollinger', {})
    if sb.get('status') != 'calculated':
        return out
    app = sb.get('application', {})
    center, lag = sb.get('centerline_relation'), app.get('lagging_relation')
    zone, width = app.get('price_zone'), app.get('bandwidth_state')
    if (zone not in ('above_upper_1sigma','below_lower_1sigma','inside_1sigma')
            or width not in ('expanding','contracting','flat')):
        return out
    dma = notes.get('standard_fibonacci_and_dma', {}).get('application', {}).get('positions', {})
    macd = notes.get('dinapoli_macd_preferred_stochastic', {})
    momentum = macd.get('macd_histogram_relation') if macd.get('status')=='provisional_reference' else None
    stoch = macd.get('preferred_stochastic', {}).get('k_movement')
    with_move, against_move = ('rising','falling') if sign==1 else ('falling','rising')
    own_zone = 'above_upper_1sigma' if sign==1 else 'below_lower_1sigma'
    counter_zone = 'below_lower_1sigma' if sign==1 else 'above_upper_1sigma'
    # SB describes the environment. Momentum describes travel within it;
    # RCI timing does not reverse the structural direction by itself.
    if center=='opposed' or lag=='opposed' or zone==counter_zone:
        status = 'transition'
    elif center!='aligned' or lag not in ('aligned','unconfirmed'):
        return out
    elif width=='expanding' and zone==own_zone:
        status = 'continuation'
    else:
        status = 'retracement_then_continuation'
    if momentum=='opposed' and status=='continuation':
        status = 'retracement_then_continuation'
    if momentum not in ('aligned','opposed'):
        out['cautions'].append('基準足MACDの勢い未確認。継続の強さを断定しない')
    if _movement(r, 26)==against_move:
        out['cautions'].append('基準足RCI26は逆行。押し戻りの長期化・転換に注意')
    if _movement(r, 52)==against_move:
        out['cautions'].append('基準足RCI52の持続性が逆行。到達候補は条件付き')
    fast = dma.get('3x3', {})
    if fast.get('status')=='observed_reference' and fast.get('price_relation')=='opposed':
        setup = 'pullback_active'
    elif fast.get('status')=='observed_reference' and fast.get('price_relation')=='aligned':
        setup = 'resumption_context' if (_movement(r, 9)==with_move or stoch==with_move) else 'timing_wait'
    else:
        setup = 'unverified'
    if momentum=='opposed':out['cautions'].append('基準足MACDは逆行。局所反応だけで再開としない')
    # Payload JSON sorts mapping keys. Caution lists must retain the producer's
    # published W1 -> D1 order regardless of dictionary insertion on restore.
    for tf in ('w1','d1'):
        context = r.get('macro_context', {}).get(tf, {})
        if isinstance(context,dict) and context.get('verified') is True and context.get('relation')=='countertrend':
            out['cautions'].append(tf+'上位足の構造は逆方向。波の伸びと転換を再評価')
    paths = {'continuation':'基準足のトレンド継続を主シナリオとし、途中の障害を越えた場合に波の拡張を見込む',
             'retracement_then_continuation':'まずDMA・通常Fib付近への押し戻りを想定。勢いの回復後に既存波の終点再試し、突破後に拡張を検討',
             'transition':'価格構造とSB背景が競合。押し戻り継続と転換を分岐として保持し、方向候補の優先掲載は保留'}
    out.update(status=status, setup=setup, path=paths[status],
               evidence={'sb_environment':{'center':center, 'lag':lag, 'zone':zone, 'width':width},
                         'dma_setup':{k:deepcopy(dma.get(k, {})) for k in ('3x3','7x5','25x5')},
                         'macd_relation':momentum, 'rci9_movement':_movement(r,9),
                         'rci26_movement':_movement(r,26), 'rci52_movement':_movement(r,52),
                         'stochastic_movement':stoch})
    return out


def build_plan(r):
    i = r.get('technical_plan_inputs', {}); tf = r['reference_timeframe']
    sec = {'h4':14400, 'h1':3600}[tf]; clock = r['evaluated_at']
    out = {'schema':'technical_wave_plan_v1', 'evaluated_at':clock, 'timeframe':tf,
           'status':'unverified', 'thesis_invalidation':None, 'local_setup_failure':None,
           'first_obstacle':None, 'retest_objective':None, 'extension_zone':None,
           'pullback_zone':None, 'reference_close':None, 'reference_close_timestamp':None,
           'anchor_basis':'confirmed_base_timeframe_impulse_not_local_trigger_extremes',
           'projection_is_conditional':True, 'time_to_target':'not_estimated',
           'reason':'確認済み基準足の波・アンカー不足。遠い目標を補完しない'}
    if not isinstance(i,dict):return out
    b = i.get('bar', {}); p = i.get('projection', {}); start=p.get('start_pivot', {}); end=p.get('end_pivot', {})
    sign = 1 if r.get('direction')=='long' else -1 if r.get('direction')=='short' else 0
    stamp=b.get('timestamp'); prices=[b.get(k) for k in ('open','high','low','close')]
    if (not sign or r.get('base_quality_verified') is not True or i.get('quality_verified') is not True
            or i.get('evaluated_at')!=clock or i.get('timeframe')!=tf
            or type(stamp) is not int or stamp%sec or not 0<=clock-stamp-sec<sec
            or not all(positive(x) for x in prices)):
        return out
    o,h,l,c=prices
    if not l<=min(o,c)<=max(o,c)<=h:return out
    out.update(reference_close=c, reference_close_timestamp=stamp)
    def pivot_ok(a):
        ts=a.get('timestamp') if isinstance(a,dict) else None
        return (type(ts) is int and 0<ts and ts%sec==0 and ts+2*sec<=stamp and positive(a.get('price')))
    if (p.get('status')!='reference_only' or not pivot_ok(start) or not pivot_ok(end)
            or start['timestamp']>=end['timestamp'] or sign*(end['price']-start['price'])<=0):
        return out
    width=abs(end['price']-start['price']); origin=start['price']; finish=end['price']
    anchors = i.get('highs' if sign==1 else 'lows', [])
    stops = i.get('lows' if sign==1 else 'highs', [])
    if not isinstance(anchors,list) or not isinstance(stops,list):return out
    if (not any(pivot_ok(a) and a['timestamp']==start['timestamp'] and a['price']==start['price'] for a in stops)
            or not any(pivot_ok(a) and a['timestamp']==end['timestamp'] and a['price']==end['price'] for a in anchors)):
        return out
    candidates = [a for a in anchors if pivot_ok(a) and sign*(a['price']-c)>0]
    if sign*(finish-c)>0:candidates.append(end)
    obstacle = min(candidates, key=lambda a:sign*(a['price']-c)) if candidates else None
    local = [a for a in stops if pivot_ok(a) and sign*(c-a['price'])>0]
    ext = [origin+sign*width*ratio for ratio in (1.272,1.618)]
    # Never roll the goal farther because price has reached the projection.
    status = 'invalidated' if sign*(c-origin)<=0 else 'objective_reached' if sign*(c-ext[1])>=0 else 'available'
    out.update(status=status, thesis_invalidation=origin,
               local_setup_failure=max(local,key=lambda a:a['timestamp'])['price'] if local else None,
               first_obstacle=deepcopy(obstacle), retest_objective=deepcopy(end),
               extension_zone={'near':ext[0], 'far':ext[1], 'kind':'standard_fibonacci_conditional_projection',
                               'requires':'基準足の勢い回復・波の終点突破と維持。到達保証ではない'},
               pullback_zone={'shallow':finish-sign*width*.382, 'deep':finish-sign*width*.618,
                              'kind':'standard_fibonacci_retracement_reference'},
               start_pivot=deepcopy(start), end_pivot=deepcopy(end), wave_width=width,
               reason='基準足の確定波を起点に押し戻り→終点再試し→突破後拡張を分離。最寄り障害を最終目標に固定しない')
    return out


def assess(pair, strategy, track, clock):
    """Build a new assessment; old PA grading is never used by this path."""
    from .strategy_strength import interpret
    from .technical_context import attach_technical_context
    from .swing_environment import build_environment
    r = {'pair':pair, 'strategy':strategy, 'direction':track.get('direction'),
         'evaluated_at':clock, 'reference_timeframe':track['base_timeframe'],
         'trigger_timeframe':track['trigger_timeframe'], 'base_structure':track.get('base_structure'),
         'base_quality_verified':track.get('base_verified') is True,
         'method_version':METHOD, 'assessment':'evaluation_pending', 'grade':None,
         'grade_scope':'provisional_scenario_quality_not_permission', 'method_validated_for_profitability':False,
         'execution_authority':'none', 'price_basis':'saved_completed_candles_not_current_quote',
         'reasons':[], 'opposing_evidence':[], 'uncertainties':[], 'waiting_conditions':[],
         'formation_conditions':[], 'scenario_explanation':{}, 'reference_levels':{},
         'reference_plan':deepcopy(track.get('reference_plan', {})),
         'indicator_context':deepcopy(track.get('indicator_context', {})),
         'rci_observation':deepcopy(track.get('rci_observation', {})),
         'macro_context':deepcopy(track.get('macro_context', {})),
         'intermediate_context':deepcopy(track.get('intermediate_context', {})),
         'price_reaction_observation':deepcopy(track.get('price_reaction_observation', {})),
         'trigger_price_reference':deepcopy(track.get('trigger_price_reference', {})),
         'technical_plan_inputs':deepcopy(track.get('technical_plan_inputs', {})),
         'entry_condition_inputs':deepcopy(track.get('condition_inputs', {}))}
    r['currency_strength_context']=interpret(track.get('currency_strength_context'),pair,strategy,r['direction'],clock)
    if strategy=='swing':r['swing_environment']=build_environment(r)
    attach_technical_context(r)
    r['technical_outlook']=build_outlook(r); r['wave_price_plan']=build_plan(r)
    refresh(r)
    return r


def refresh(r):
    """Recompute prices, priority and grade, including after calendar enrichment."""
    from .scenario_conditions import describe_conditions
    out=build_outlook(r); p=build_plan(r); r['technical_outlook']=out; r['wave_price_plan']=p
    sign=1 if r.get('direction')=='long' else -1 if r.get('direction')=='short' else 0
    r.pop('skip_reason',None)
    r['assessment']='review';r['grade']='C'
    if r.get('base_quality_verified') is not True:
        r['assessment']='evaluation_pending'
    elif not sign or {'HH_HL':1,'LH_LL':-1}.get(r.get('base_structure'))!=sign:
        r['assessment']='skip';r['skip_reason']='base_direction_unconfirmed'
    elif r.get('swing_environment',{}).get('exclude_from_monitoring'):
        r['assessment']='skip';r['skip_reason']='h4_consolidation_excluded'
    elif p['status']=='invalidated':
        r['assessment']='skip';r['skip_reason']='base_wave_invalidated'
    elif p['status']=='objective_reached':
        r['assessment']='skip';r['skip_reason']='base_wave_objective_reached'
    elif out['status']=='unverified' or p['status']=='unverified':
        r['assessment']='evaluation_pending'
    target = None
    if p.get('extension_zone'):
        c=p['reference_close'];end=p['retest_objective']['price'];ext=p['extension_zone']
        # The next path objective is not relabelled as observed structure.
        target=end if sign*(end-c)>0 else ext['near'] if sign*(ext['near']-c)>0 else ext['far']
    stop=p.get('thesis_invalidation');obstacle=p.get('first_obstacle')
    r['reference_levels']={'invalidation':stop,'structural_target':obstacle['price'] if obstacle else None,
                           'scenario_target':target, 'target_kind':'conditional_wave_path', 'executable_price':False}
    r['reference_plan']={'reference_close':p['reference_close'], 'reference_close_timestamp':p['reference_close_timestamp'],
                         'invalidation':stop, 'scenario_target':target, 'status':p['status'],
                         'basis':p['anchor_basis'], 'reference_timeframe':r['reference_timeframe']}
    sec={'h4':14400,'h1':3600}[r['reference_timeframe']]
    baseclosed=p['reference_close_timestamp']+sec if type(p['reference_close_timestamp']) is int else None
    withdrawn=p['status'] in ('invalidated','objective_reached')
    r['expiry']={'status':'withdrawn' if withdrawn else 'unverified' if r['assessment']=='evaluation_pending' else 'reference_recheck',
                 'scope':'base_wave_thesis_not_local_entry', 'time_expiry':{'status':'not_defined'},
                 'observed_condition':r.get('skip_reason') if withdrawn else None,
                 'withdrawal_conditions':[{'condition':'base_wave_invalidation', 'price':stop,
                                          'relation':'<=' if sign==1 else '>=', 'basis_timeframe':r['reference_timeframe'],
                                          'confirmation':'verified_saved_base_close'}] if positive(stop) else [],
                 'observation':{'closed_at':baseclosed,'saved_close':p['reference_close']} if withdrawn else None}
    r['invalidation']={'price':stop,'scope':'base_wave_thesis', 'observed':p['status']=='invalidated'}
    # PA supplies timing only. Its success/failure never defines the base thesis.
    r['market_phase']='pullback_wait' if out['status']=='retracement_then_continuation' else 'transition_context' if out['status']=='transition' else 'directional_structure_wait'
    r['scenario_conditions']=describe_conditions(r,r.get('entry_condition_inputs'))
    recent=r.get('trigger_price_reference',{}); tf=r['trigger_timeframe'];seconds={'m15':900,'m5':300}[tf]
    closed=recent.get('closed_at');price=recent.get('close')
    fresh=(recent.get('status')=='observed_reference' and recent.get('timeframe')==tf
           and recent.get('evaluated_at')==r['evaluated_at'] and type(closed) is int
           and closed%seconds==0 and 0<=r['evaluated_at']-closed<seconds and positive(price))
    risk=sign*(price-stop) if fresh and positive(stop) else None
    reward=sign*(target-price) if fresh and positive(target) else None
    front=obstacle['price'] if obstacle else target
    front_reward=sign*(front-price) if fresh and positive(front) else None
    margin=bool(risk and risk>0 and reward and reward>risk and front_reward and front_reward>risk)
    entry_paused=bool(fresh and positive(p.get('local_setup_failure'))
                      and sign*(price-p['local_setup_failure'])<=0)
    # Projected RR must never conceal a nearer structural obstacle.
    r['trigger_price_review']={'status':'observed_reference' if fresh else 'unverified',
        'saved_close':price if fresh else None, 'closed_at':closed if fresh else None,
        'reference_timeframe':tf, 'risk_distance':risk,'reward_distance':reward,
        'first_obstacle_reward':front_reward,
        'reference_rr':round(reward/risk,2) if risk and risk>0 and reward and reward>0 else None,
        'costs_included':False,'formation_price':None,'formation_rr':None,
        'basis':'base_wave_thesis_risk_not_local_trigger_stop'}
    events=[];clock=r['evaluated_at']
    for e in r.get('economic_calendar_context',{}).get('events',[]):
        ts=e.get('scheduled_at_utc')
        if (e.get('impact')=='high' and e.get('time_precision')=='minute' and not e.get('timing_conflict')
                and e.get('status') not in ('cancelled','canceled') and type(ts) is int
                and (baseclosed if baseclosed is not None else clock)<=ts<=(clock//3600+1)*3600):
            events.append({'id':e.get('id'),'scheduled_at_utc':ts,'reason':'発表をまたぐため基準足と見通しを再評価'})
    usable=r['assessment']=='review'
    status=('evaluation_pending' if r['assessment']=='evaluation_pending' else 'direction_watch' if not usable
            else 'event_recheck' if events else 'technical_recheck' if out['status']=='transition'
            else 'entry_recheck' if entry_paused
            else 'price_plan_recheck' if not margin else 'technical_watch')
    # A concerns the base technical thesis, not completion of a local candle pattern.
    mature=(out['status']=='continuation' and out['setup']=='resumption_context'
            and not out['cautions'] and not r['currency_strength_context'].get('material_opposition'))
    r['grade']=('A' if status=='technical_watch' and mature else 'B') if usable else None
    descriptions={'technical_watch':'基準足のテクニカル見通しと波の価格計画を監視。局所反応は仕掛け確認で、大局評価とは別',
                  'technical_recheck':'基準足の構造とテクニカル背景が競合。局所PAで上書きせず見通し再評価',
                  'entry_recheck':'局所セットアップ無効化で仕掛け停止。基準足の波の見通しは別に保持し、仕掛けを再評価',
                  'price_plan_recheck':'波の見通しは保持するが、最初の障害までの余地不足・仕掛け停止。遠い投影のRRだけでは追わない',
                  'event_recheck':'重要発表をまたぐため基準足と見通しを再評価',
                  'evaluation_pending':'基準足・テクニカル・確定波の材料不足で評価保留',
                  'direction_watch':'有効なトレンド方向シナリオなし。新しい基準足を待つ'}
    r['practical_review']={'schema':'saved_practical_review_v3','status':status,'summary':descriptions[status],
        'events':events,'a_blockers':out['cautions'],'reference_margin_sufficient':margin,
        'entry_status':'paused' if entry_paused else 'timing_reference' if fresh else 'unverified',
        'margin_basis':'base_wave_risk_and_nearest_obstacle_before_costs','not_order_or_profitability':True}
    r['grade_reason']=descriptions[status]
    r['reasons']=[out['path'],p['reason']]
    r['opposing_evidence']=list(out['cautions'])
    if r['currency_strength_context'].get('relation')=='opposed':r['opposing_evidence'].append(r['currency_strength_context']['summary'])
    r['uncertainties']=['到達時刻・保有期間・費用控除後の余地は未確認']
    r['waiting_conditions']=[out['path'],r['scenario_conditions']['summary']]
    r['formation_conditions']=[r['scenario_conditions']['summary']]
    r['scenario_explanation']={'waiting_condition':out['path'], 'invalidation':deepcopy(r['invalidation']),
        'expiry':deepcopy(r['expiry']), 'scenario_conditions':deepcopy(r['scenario_conditions']),
        'formation_conditions':deepcopy(r['formation_conditions'])}
    return r


def render_lines(r):
    """Compact saved report consumed by the existing reporting task."""
    p=r['wave_price_plan'];o=r['technical_outlook'];recent=r['trigger_price_review']
    name='スイング' if r['strategy']=='swing' else 'デイトレード'
    fmt=lambda x:f'{x:.8f}'.rstrip('0').rstrip('.') if positive(x) else '未確認'
    z=p.get('extension_zone') or {}; pull=p.get('pullback_zone') or {}
    obstacle=p.get('first_obstacle') or {}
    return ['', f"{r['pair'][:3]}/{r['pair'][3:]} {name}｜{'買い方向' if r['direction']=='long' else '売り方向'}｜{r['grade']}",
            '評価理由：'+r['grade_reason'], '見通し：'+o['path'],
            '主根拠：'+r.get('technical_context',{}).get('frames',{}).get('base',{}).get('summary','基準足の明細は未確認'),
            '重要な懸念：'+('／'.join(r['opposing_evidence']) or '追加の具体的な逆行は未観測。未確認事項は別'),
            f"押し戻り参考域：{fmt(pull.get('shallow'))}～{fmt(pull.get('deep'))}（通常Fib。DMA位置も併せて確認）",
            f"途中の構造障害：{fmt(obstacle.get('price'))}｜波の終点再試し：{fmt((p.get('retest_objective') or {}).get('price'))}",
            f"終点突破・勢い継続後の条件付き到達域：{fmt(z.get('near'))}～{fmt(z.get('far'))}（通常Fib投影、到達保証・確定支持抵抗ではない）",
            f"大局撤回：{r['reference_timeframe'].upper()}確定終値が{fmt(p.get('thesis_invalidation'))}を{'以下' if r['direction']=='long' else '以上'}。局所の仕掛け停止とは別",
            f"局所セットアップの参考無効化：{fmt(p.get('local_setup_failure'))}。大局撤回や固定SLに流用しない",
            '仕掛け確認：'+r['scenario_conditions']['summary'],
            '価格余地：最初の障害までと波の大局撤回までを比較。'+('余地を確認（費用前）' if r['practical_review']['reference_margin_sufficient'] else '不足または未確認、追わず再評価'),
            f"保存確認足：{fmt(recent.get('saved_close'))}。現在値・約定価格ではない",
            '時間軸：'+('H4の複数セッションの波、M15は仕掛け確認' if r['strategy']=='swing' else 'H1の日中の波、M5は仕掛け確認')+'。到達時間・保有日数は予測しない',
            '未確認：到達・成立価格・費用控除後の余地。A/B/Cは売買許可や利益確率ではない']
