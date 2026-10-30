"""Provisional discretionary scenario review, not a strategy/permission verifier.

Evidence is interpreted by causal role: structure anchors the scenario, price
reaction describes its stage, overlapping trend indicators are one contextual
family, and RCI timing is not an independent vote for direction.
"""
from copy import deepcopy
import math
from .scenario_lifecycle import describe_lifecycle
from .scenario_conditions import describe_conditions
from .strategy_strength import interpret as interpret_strength


def _dict(value):return value if isinstance(value,dict) else {}
def _number(value):return value if type(value) in (int,float) and math.isfinite(value) else None


def assess_strategy(pair,strategy,track,evaluated_at):
    from .technical_scenario import METHOD, assess
    if isinstance(track,dict) and track.get('assessment_method')==METHOD:
        return assess(pair,strategy,track,evaluated_at)
    t=_dict(track);direction=t.get('direction');explain=_dict(t.get('scenario_explanation'))
    levels=_dict(t.get('reference_levels'));plan=_dict(t.get('reference_plan'))
    reasons=[];opposition=[];uncertainties=[]
    base=t.get('base_timeframe');trigger=t.get('trigger_timeframe')
    record={'pair':pair,'strategy':strategy,'direction':direction,'state':t.get('state'),
        'assessment':'evaluation_pending','grade':None,'grade_reason':None,
        'grade_scope':'provisional_scenario_quality_not_permission',
        'method_version':('contextual_scenario_review_v9_swing_wave' if strategy=='swing' else 'contextual_scenario_review_v7_trend_swing'),'method_validated_for_profitability':False,
        'base_structure':t.get('base_structure'),'base_quality_verified':t.get('base_verified') is True,
        'evaluated_at':evaluated_at,'price_basis':'saved_completed_candles_not_current_quote',
        'reference_timeframe':base,'trigger_timeframe':trigger,
        'execution_authority':'none','reasons':reasons,'opposing_evidence':opposition,
        'uncertainties':uncertainties,'reference_levels':deepcopy(levels),'reference_plan':deepcopy(plan),
        'scenario_explanation':deepcopy(explain),'indicator_context':deepcopy(t.get('indicator_context',{})),
        'macro_context':deepcopy(t.get('macro_context',{})),
        'intermediate_context':deepcopy(t.get('intermediate_context',{})),
        'rci_observation':deepcopy(t.get('rci_observation',{})),
        'waiting_conditions':[explain.get('waiting_condition')] if explain.get('waiting_condition') else [],
        'formation_conditions':[],
        'price_reaction_observation':deepcopy(t.get('price_reaction_observation', {})),
        'reference_projection':deepcopy(plan.get('reference_projection',{'status':'unavailable','reason':'投影の確定アンカー未提供'})),
        'invalidation':deepcopy(explain.get('invalidation',{})),
        'expiry':deepcopy(explain.get('expiry',{'status':'not_defined'}))}
    strength=interpret_strength(t.get('currency_strength_context'),pair,strategy,direction,evaluated_at)
    if strategy == 'swing':
        record['swing_wave_inputs'] = deepcopy(t.get('swing_wave_inputs', {}))
        from .swing_environment import build_environment
        record['swing_environment'] = build_environment(record)
    record['currency_strength_context']=strength
    strength_only_opposition=[]
    def finish(state,grade,reason):
        record.update(assessment=state,grade=grade,grade_reason=reason)
        record['expiry'],record['invalidation']=describe_lifecycle(record)
        record['scenario_explanation']['expiry']=deepcopy(record['expiry'])
        record['scenario_explanation']['invalidation']=deepcopy(record['invalidation'])
        reaction_stamp=t.get('reaction_timestamp')
        reaction_seconds={'m15':900,'m5':300}.get(trigger,0)
        pattern=(t.get('trigger_status')=='watch_pattern' if trigger=='m15'
                 else _dict(t.get('price_action')).get('status')=='watch_pattern')
        verified_pattern=(t.get('base_verified') is True and t.get('trigger_verified') is True
            and direction in ('long','short') and pattern and type(reaction_stamp) is int
            and type(evaluated_at) is int and reaction_seconds>0
            and 0<=evaluated_at-(reaction_stamp+reaction_seconds)<=reaction_seconds)
        record['formation_observation']={
            'status':'observed_reference' if verified_pattern else 'unverified',
            'timeframe':trigger,'closed_at':reaction_stamp+reaction_seconds if verified_pattern else None,
            'scenario_withdrawn':record['expiry']['status']=='withdrawn',
            'formation_price':None,'basis':'reference_pattern_not_scenario_formation_or_fill'}
        record['scenario_explanation']['formation_evidence']=(
            '旧参考パターンは撤回済みシナリオの継続条件に転用しない' if verified_pattern and record['expiry']['status']=='withdrawn'
            else '参考パターン観測済み' if verified_pattern else '参考パターン成立は未確認')
        wait=None
        if record['expiry']['status']=='withdrawn':
            wait=f'{base.upper()}で新たな構造・無効化水準・構造目標を再評価し、{trigger.upper()}確定足の反応を確認する'
        elif pattern and not verified_pattern:
            wait=f'{trigger.upper()}参考パターンの品質・確定時刻・鮮度を再確認。保存状態だけで成立としない'
        if wait:
            old_wait=record['scenario_explanation'].get('waiting_condition')
            record['scenario_explanation']['waiting_condition']=wait
            record['waiting_conditions']=[wait]+[x for x in record['waiting_conditions'] if x!=old_wait]
        # Concrete advisory conditions never change grade, authority or the
        # raw reference-pattern observation above.
        condition_plan = describe_conditions(record, t.get('condition_inputs'))
        record['scenario_conditions'] = condition_plan
        if record['expiry']['status']=='withdrawn':
            record['formation_conditions']=[f'旧シナリオは撤回済み。{base.upper()}の新しい構造・無効化・目標を再評価する。旧条件の維持を成立条件にしない']
        elif state=='evaluation_pending':
            record['formation_conditions']=[f'{base.upper()}の品質・出所・評価時刻が未確認のため、成立条件を評価できない']
        elif direction not in ('long','short'):
            record['formation_conditions']=[f'{base.upper()}の方向構造が未確認。維持すべき方向・成立価格を推定しない']
        else:
            record['formation_conditions']=[condition_plan['summary']]
            if condition_plan['status'] in ('waiting','awaiting_breakout','awaiting_retest','retest_failed','conditions_observed'):
                pending = list(record['waiting_conditions'])
                old_wait = record['scenario_explanation'].get('waiting_condition')
                # Preserve price-margin warnings appended by the assessment.
                pending = [x for x in pending if x != old_wait]
                observed = condition_plan['status']=='conditions_observed'
                wait = ('条件を保存確定足で観測。反対根拠と目標までの余地を確認する' if observed else
                        '突破は観測済み。同水準の再試しと終値の維持を待つ' if condition_plan['status']=='awaiting_retest' else
                        condition_plan['summary'])
                record['waiting_conditions']=[wait]+pending
                record['scenario_explanation']['waiting_condition']=wait
                record['scenario_explanation']['formation_evidence']=(
                    '具体的な確認条件を保存足で観測（約定・売買指示ではない）' if observed else
                    '再試しで終値を維持できず、反応の再評価が必要' if condition_plan['status']=='retest_failed' else
                    '具体的な確認条件の観測待ち')
            else:
                record['uncertainties'].append(condition_plan['reason'])
                if pattern and not verified_pattern:
                    record['waiting_conditions'].append(condition_plan['summary'])
                else:
                    record['waiting_conditions']=[condition_plan['summary']]+record['waiting_conditions']
                    record['scenario_explanation']['waiting_condition']=condition_plan['summary']
        record['scenario_explanation']['formation_conditions']=deepcopy(record['formation_conditions'])
        record['scenario_explanation']['scenario_conditions']=deepcopy(condition_plan)
        from .technical_context import attach_technical_context
        attach_technical_context(record)
        from .practical_review import review
        review(record)
        return record
    if t.get('base_verified') is not True:
        uncertainties.append(f'{base}確定足の品質・出所・評価時刻が未確認')
        return finish('evaluation_pending',None,'当該戦略の基準足を評価できない。相場の見送りとは別')
    seconds={'m15':900,'m5':300}.get(trigger,0)
    stamp=t.get('reaction_timestamp')
    reaction_clock=(type(stamp) is int and type(evaluated_at) is int and seconds>0
                    and 0<=evaluated_at-(stamp+seconds)<=seconds)
    invalidated=t.get('trigger_status')=='invalidated' or t.get('invalidation_observed') is True
    invalidation_confirmed=bool(invalidated and reaction_clock and t.get('trigger_verified') is True)
    record['invalidation_time_verified']=invalidation_confirmed
    if invalidated and not invalidation_confirmed:
        uncertainties.append('無効化診断の確認足品質・確定時刻・鮮度が未確認。保存された状態だけで見送りと断定しない')
    if invalidation_confirmed:
        record['skip_reason']='confirmed_trigger_invalidation'
        record['invalidation_observed_at']=stamp+seconds
        opposition.append('当該戦略の確認足で無効化を観測')
        return finish('skip',None,'保存時点でシナリオが無効化。再形成待ち')
    if direction not in ('long','short'):
        return finish('skip',None,'基準足の方向構造を確認できず、再形成待ち')
    reasons.append(f'{base}の確認済み高値安値構造={t.get("base_structure")}が{direction}を示す')
    if strength.get('relation') == 'aligned':
        reasons.append(strength['summary'])
        if strength.get('movement') == 'weakening':
            note='通貨強弱差は方向と整合するが前の同期間より支持が弱まる。価格の押し戻り・転換と併せて確認'
            opposition.append(note);strength_only_opposition.append(note)
    elif strength.get('relation') == 'opposed':
        opposition.append(strength['summary'])
        if not strength.get('material_opposition'):
            strength_only_opposition.append(strength['summary'])
        record['waiting_conditions'].append('通貨強弱の逆行を押し戻り・転換の価格反応と併せて確認。逆行だけで一律除外しない')
    elif strength.get('status') != 'available':
        uncertainties.append(strength['summary'])
    macro=_dict(t.get('macro_context'))
    for tf,item in macro.items():
        item=_dict(item)
        if item.get('verified') is True and item.get('relation')=='countertrend':
            opposition.append(f'{tf}環境認識は逆方向。反転確定とはせず逆行局面として扱う')
        elif item.get('verified') is not True:uncertainties.append(f'{tf}上位足環境は未確認')
    for tf,item in _dict(t.get('intermediate_context')).items():
        item=_dict(item)
        if item.get('verified') is True and item.get('relation')=='countertrend':
            opposition.append(f'{tf}構造は戦略方向と逆。押し戻り/逆行局面として保持し一律除外しない')
    frames=_dict(_dict(t.get('indicator_context')).get('frames'))
    base_notes=_dict(frames.get('base')).get('observations',[])
    base_notes=base_notes if isinstance(base_notes,list) else []
    contextual_conflict=False
    for note in base_notes:
        n=_dict(note)
        if n.get('indicator') not in ('super_bollinger',):continue
        relation=n.get('centerline_relation')
        if n.get('status') not in ('calculated','observed_reference','ok'):
            continue
        if relation=='opposed':
            contextual_conflict=True
            opposition.append(f'{base} {n["indicator"]}は構造と逆。帯・遅行を含む移行局面の確認が必要')
        elif relation=='aligned':reasons.append(f'{base} {n["indicator"]}はトレンド背景と整合（独立票には数えない）')
    # A verified trigger-timeframe disagreement matters for reaction timing,
    # but does not automatically negate the base-timeframe structure.
    trigger_notes=_dict(frames.get('trigger')).get('observations',[])
    # Reject stale or externally supplied trigger observations when candle quality is unverified.
    if t.get('trigger_verified') is not True:
        trigger_notes=[]
    for item in trigger_notes if isinstance(trigger_notes,list) else []:
        n=_dict(item)
        kind=n.get('indicator')
        if kind not in ('super_bollinger',):
            continue
        if n.get('status') not in ('calculated','observed_reference','ok'):
            continue
        relation=n.get('centerline_relation')
        if relation=='opposed':
            opposition.append(f'{trigger} {kind}は戦略方向と逆。確認足の反応・転換を見極める（基準足の一律否定ではない）')
        elif relation=='aligned':
            reasons.append(f'{trigger} {kind}は確認足の背景と整合（独立票には数えない）')
    # DiNapoli observations are already saved; surface their actual relation
    # to the scenario instead of leaving them buried in raw indicator JSON.
    # No standalone votes, trade gates, or claims of chart/original parity.
    record['dinapoli_synthesis']=[]
    for role in ('base','trigger'):
        if role=='trigger' and t.get('trigger_verified') is not True:
            continue
        frame=_dict(frames.get(role))
        timeframe=frame.get('timeframe')
        notes=frame.get('observations',[])
        for item in notes if isinstance(notes,list) else []:
            note=_dict(item)
            kind=note.get('indicator')
            if kind=='standard_fibonacci_and_dma':
                fib_relation=note.get('fibonacci_status')
                record['dinapoli_synthesis'].append({
                    'timeframe':timeframe,'indicator':'dma_fibonacci',
                    'fibonacci_status':fib_relation,
                    'dma':deepcopy(_dict(note.get('dma'))),
                    'interpretation':'DMAは価格位置の参考。確認済みanchorのないフィボナッチ目標は捏造しない'})
                if fib_relation=='direction_matched_reference':
                    reasons.append(f'{timeframe} 通常方式の確認済みフィボナッチ方向が戦略方向と整合（独立票ではない）')
            elif kind=='dinapoli_macd_preferred_stochastic':
                relation=note.get('macd_histogram_relation')
                record['dinapoli_synthesis'].append({
                    'timeframe':timeframe,'indicator':'macd_preferred_stochastic',
                    'status':note.get('status'),'macd_histogram_relation':relation,
                    'macd':deepcopy(_dict(note.get('macd'))),
                    'preferred_stochastic':deepcopy(_dict(note.get('preferred_stochastic'))),
                    'preferred_stochastic_algorithm':note.get('preferred_stochastic_algorithm','legacy_saved_unverified_algorithm'),
                    'chart_parity_verified':note.get('chart_parity_verified') is True,
                    'interpretation':'MACDヒストグラム符号は勢いの参考。ストキャスの計算版・位置・変化と外部チャート一致は別途確認'})
                if note.get('status')=='provisional_reference' and relation=='opposed':
                    opposition.append(f'{timeframe} ディナポリMACDの勢いは構造方向と逆（参考値、単独で除外しない）')
                elif note.get('status')=='provisional_reference' and relation=='aligned':
                    reasons.append(f'{timeframe} ディナポリMACDの勢いは構造方向と整合（参考値、独立票ではない）')
                stoch=_dict(note.get('preferred_stochastic'))
                if note.get('status')=='provisional_reference':
                    movement=stoch.get('k_movement')
                    if movement in ('rising','falling'):
                        against=(movement=='falling' and direction=='long') or (movement=='rising' and direction=='short')
                        detail=f'{timeframe} Preferred Stochastic K={stoch.get("slow_k")} D={stoch.get("slow_d")}、変化={movement}、クロス={stoch.get("cross","unverified")}。MACDと同じ価格由来の勢い補足'
                        (opposition if against else reasons).append(detail)
    # RCI9/26/52 share price/time input; retain their separate timing meanings.
    counter=t.get('timing_assessment')=='counter_rebound_wait'
    rci=_dict(_dict(t.get('rci_observation')).get('frames'))
    record['rci_synthesis']=[]
    for role,r in rci.items():
        r=_dict(r)
        if r.get('status') in ('observed_reference','calculated'):
            reasons.append(f'{r.get("timeframe")} RCI9/26/52を短期反応・持続性の参考として保持。極端値だけで反転判定しない')
            for period in ('9','26','52'):
                p=_dict(_dict(r.get('periods')).get(period))
                movement=p.get('movement')
                against=(movement=='falling' and direction=='long') or (movement=='rising' and direction=='short')
                record['rci_synthesis'].append({'timeframe':r.get('timeframe'),'period':int(period),
                    'role':'short_reaction' if period=='9' else 'persistence_context',
                    'movement':movement if movement in ('rising','falling','flat') else 'unverified',
                    'against_structure_movement':against,'value':_number(p.get('value')),
                    'previous':_number(p.get('previous')),'turn':p.get('turn'),
                    'cross_26':p.get('cross_26'),'cross_52':p.get('cross_52'),
                    'extreme_run':deepcopy(p.get('extreme_run')),
                    'interpretation':'一足の変化・極端値だけで反転確定や加点をしない'})
                if against:
                    if counter:
                        opposition.append(f'{r.get("timeframe")} RCI{period}の逆行傾斜は観測済み価格の押し戻りと整合。同じ価格由来の補足説明')
                    else:
                        opposition.append(f'{r.get("timeframe")} RCI{period}の傾斜は戦略方向と逆。短期反応と継続性を確認（単独の反転判定ではない）')

    if counter:opposition.append(f'{trigger}で逆行反応中。終了・再開を待つ')
    reaction=(reaction_clock and t.get('trigger_verified') is True and
              (t.get('trigger_status')=='watch_pattern' if strategy=='swing'
               else _dict(t.get('price_action')).get('status')=='watch_pattern'))
    if t.get('trigger_verified') is not True:
        uncertainties.append(f'{trigger}の品質・鮮度が未確認。基準足の方向シナリオは保持')
    if not reaction_clock:uncertainties.append('反応足の確定時刻・鮮度は未確認。過去のパターンを現在の反応にしない')
    record['reaction_timestamp']=stamp if type(stamp) is int and reaction_clock else None
    record['market_phase']=('pullback_wait' if counter else 'transition_context' if contextual_conflict else
                            'directional_structure_with_reaction' if reaction else 'directional_structure_wait')
    record['evidence_dependencies']={'structure':'confirmed_price_pivots',
        'trend_context':'Super Bollinger is price-derived trend context; no independent votes',
        'rci':'9 timing versus 26/52 persistence, same price input, not three votes',
        'price_action':'confirmed trigger reaction, not current executable quote',
        'currency_strength':'other configured pairs; assessed pair excluded, correlated price context, not independent votes'}
    stop=_number(levels.get('invalidation'));target=_number(levels.get('structural_target'))
    rr=_number(levels.get('reference_rr'))
    close=_number(plan.get('reference_close')) or _number(t.get('saved_reference_close'))
    if close is not None and stop is not None and stop>0 and ((direction=='long' and close<=stop) or (direction=='short' and close>=stop)):
        record['skip_reason']='saved_base_invalidation_crossed'
        opposition.append('保存基準終値が構造無効化水準へ到達/越境')
        return finish('skip',None,'当該戦略の保存価格計画が無効化。現在価格による判定ではない')
    # This is plan consistency, not a new trade-entry AND gate or RR threshold.
    risk_defined=stop is not None and stop>0
    plan_coherent=(close is not None and close>0 and risk_defined and target is not None and target>0 and rr is not None and rr>0 and
                   ((stop<target) if direction=='long' else (stop>target)))
    if close is not None and plan_coherent:
        plan_coherent=stop<close<target if direction=='long' else target<close<stop
    if close is None:uncertainties.append('基準となる保存終値が未提供。価格計画の整合性を検証できない')
    recomputed_rr=None
    rr_consistency='unavailable'
    if plan_coherent:
        risk=close-stop if direction=='long' else stop-close
        reward=target-close if direction=='long' else close-target
        recomputed_rr=reward/risk if risk>0 else None
        if recomputed_rr is None or not math.isfinite(recomputed_rr) or abs(recomputed_rr-rr)>.011:
            plan_coherent=False;rr_consistency='mismatch'
            uncertainties.append('保存終値・無効化・構造目標からの参考RRが報告値と不一致')
        else:rr_consistency='consistent'
    record['reference_plan_review']={'saved_close':close,'reported_reference_rr':rr,
        'recomputed_reference_rr':recomputed_rr if recomputed_rr is not None and math.isfinite(recomputed_rr) else None,
        'consistency':rr_consistency,'costs_included':False}
    if not risk_defined:uncertainties.append('構造無効化価格が未算出')
    if target is None:uncertainties.append('構造目標が未算出。参考投影を構造目標に代用しない')
    if rr is None:uncertainties.append('構造目標への参考RRが未算出')
    if rr is not None and rr<1.5:opposition.append('構造目標の参考RRが1.5未満。採算余地を再検討（執行RRではない）')
    # A later trigger close can invalidate the old opportunity even while the
    # base close/RR still looks attractive. Never relabel it as a formation fill.
    recent=_dict(t.get('trigger_price_reference'))
    recent_close=_number(recent.get('close'));closed_at=recent.get('closed_at')
    recent_ok=(t.get('trigger_verified') is True and recent.get('status')=='observed_reference'
        and recent.get('timeframe')==trigger and recent.get('evaluated_at')==evaluated_at
        and recent_close is not None and recent_close>0 and type(closed_at) is int
        and type(evaluated_at) is int and seconds>0 and 0<=evaluated_at-closed_at<seconds)
    record['trigger_price_reference']=deepcopy(recent)
    recent_review={'status':'unverified','reference_timeframe':trigger,
        'base_reference_rr':rr,'reference_rr':None,'costs_included':False,
        'formation_price':None,'formation_rr':None,
        'basis':'saved_trigger_close_not_live_quote_or_formation_fill'}
    record['trigger_price_review']=recent_review
    if recent_ok:
        recent_risk=(recent_close-stop if direction=='long' else stop-recent_close) if stop is not None and stop>0 else None
        recent_reward=(target-recent_close if direction=='long' else recent_close-target) if target is not None and target>0 else None
        recent_review.update(status='observed_reference',saved_close=recent_close,closed_at=closed_at,
            risk_distance=recent_risk,reward_distance=recent_reward,
            reference_rr=round(recent_reward/recent_risk,2) if recent_reward is not None and recent_risk is not None and recent_risk>0 and recent_reward>0 else None)
        if recent_risk is not None and recent_risk<=0:
            record['skip_reason']='saved_trigger_invalidation_crossed'
            opposition.append(f'{trigger}保存終値{recent_close}が構造無効化価格{stop}に到達/越境')
            return finish('skip',None,'後の確認足保存終値で無効化。旧基準足RRを継続候補に流用しない')
        if recent_reward is not None and recent_reward<=0:
            record['skip_reason']='saved_trigger_target_reached'
            opposition.append(f'{trigger}保存終値{recent_close}が構造目標{target}に到達/越境。旧目標への前方余地なし')
            record['waiting_conditions'].append('新たな構造目標または別の価格反応に基づくシナリオの再形成を待つ')
            return finish('skip',None,'確認足保存終値が旧構造目標に到達済み。実際の売買や利確の実績を意味しない')
        if recent_reward is not None and recent_risk is not None and 0<recent_reward<recent_risk:
            opposition.append(f'{trigger}保存終値基準では目標までの余地{recent_reward:g}が無効化距離{recent_risk:g}より小さい。勝率・優位性は未検証')
            record['waiting_conditions'].append('成立候補価格での余地・無効化距離・価格反応を再評価。保存終値のRRだけで売買判断を確定しない')
    else:
        uncertainties.append('後の確認足保存終値を検証できない。基準足価格の参考RRだけを保持')
    environment = record.get('swing_environment', {})
    if environment.get('exclude_from_monitoring'):
        record['skip_reason'] = 'h4_consolidation_excluded'
        opposition.append(environment['summary'])
        record['waiting_conditions'] = ['H4の方向構造とSB局面を再評価し、トレンド方向のM15価格反応を待つ']
        return finish('skip',None,environment['summary'])
    if not plan_coherent:
        return finish('review','C','方向は説明できるが価格計画が未完成または不整合。欠落値は補完しない')
    if counter:
        return finish('review','B','価格計画は説明可能だが短期逆行中。押し戻り終了待ち')
    if contextual_conflict:
        return finish('review','B','価格構造と帯の解釈が競合する移行局面。票数で決めず再確認')
    if reaction:
        reasons.append(f'{trigger}で方向に沿う参考プライスアクションを観測')
        # Correlated cross-pair context informs comparison/waits but must not
        # determine direction or skip. Material adverse context prevents claiming
        # a fully aligned A, while preserving the price-based scenario as B.
        if any(note not in strength_only_opposition for note in opposition):
            return finish('review','B','反応と価格計画はあるが逆行背景または採算上の反対根拠が残る')
        return finish('review','A','保存時点で構造・価格計画に沿う反応まで説明できる成熟シナリオ。優位性未実証')
    return finish('review','B','方向と価格計画の監視を継続。ただし反対根拠・確認足価格での余地を再確認' if opposition else '構造と参考価格計画は説明でき、確認足の反応待ち')
