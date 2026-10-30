"""Contextual saved-scenario maturity and monitoring priority; never execution."""
import math


def _number(x):
    return type(x) in (int,float) and math.isfinite(x)


def review(record, *, monitor_wait=True):
    conditions=record.get('scenario_conditions',{})
    recent=record.get('trigger_price_review',{})
    clock=record['evaluated_at']; seconds={'m5':300,'m15':900}.get(record.get('trigger_timeframe'),0)
    closed=recent.get('closed_at')
    verified=(recent.get('status')=='observed_reference' and type(closed) is int
        and seconds>0 and 0<=clock-closed<seconds)
    risk=recent.get('risk_distance');reward=recent.get('reward_distance')
    defined=verified and _number(risk) and _number(reward) and risk>0 and reward>0
    margin=defined and reward>risk
    planned={'status':'unavailable','reason':'保存された待ち水準での価格計画は未確認'}
    planned_ok=False
    if monitor_wait:
        level=conditions.get('level'); levels=record.get('reference_levels',{})
        stop=levels.get('invalidation');target=levels.get('structural_target');price=recent.get('saved_close')
        sign=1 if record.get('direction')=='long' else -1 if record.get('direction')=='short' else 0
        eligible=(record.get('assessment')=='review' and record.get('grade') in ('A','B')
            and conditions.get('status') in ('waiting','awaiting_breakout','awaiting_retest')
            and conditions.get('evaluated_at')==clock and verified and sign
            and all(_number(v) and v>0 for v in (level,stop,target,price)))
        if eligible:
            planned_risk=sign*(level-stop);planned_reward=sign*(target-level)
            better=sign*(price-level)>0
            planned_ok=better and planned_risk>0 and planned_reward>planned_risk
            planned={'status':'indicative' if planned_ok else 'insufficient',
                'level':level,'risk_distance':planned_risk,'reward_distance':planned_reward,
                'reference_rr':planned_reward/planned_risk if planned_risk>0 and planned_reward>0 else None,
                'basis':'saved_condition_level_not_entry_or_formation_price',
                'actual_formation_price':None,'actual_formation_rr':None,'costs_included':False,
                'reason':'待ち水準での参考計画。足の反応・成立時価格・費用で再評価'}
    blockers=[]
    from .swing_wave import METHOD, build_wave
    swing_wave = record.get('strategy')=='swing' and record.get('method_version')==METHOD
    if swing_wave:
        record['swing_wave'] = build_wave(record)
        if record['swing_wave']['status'] != 'response_confirmed':
            blockers.append(record['swing_wave']['summary'])
    if not margin:blockers.append('現在の確認足では価格余地が不足、または未確認')
    if conditions.get('status')!='conditions_observed':blockers.append('具体的な成立条件は未観測')
    if record.get('market_phase')=='transition_context':blockers.append('価格構造とトレンド背景が競合')
    if record.get('currency_strength_context',{}).get('material_opposition'):
        blockers.append('通常幅以上の通貨強弱が逆行')
    if record.get('scenario_type')=='range_reversal':blockers.append('暫定レンジ解釈の優位性は未検証')
    # Only scheduled, precisely timed relevant high-impact releases before the
    # next hourly report, or since the last analysed base close, affect priority.
    events=[]; base=record.get('reference_plan',{}).get('reference_close_timestamp')
    base_seconds={'h1':3600,'h4':14400}.get(record.get('reference_timeframe'),0)
    start=base+base_seconds if type(base) is int else clock
    end=(clock//3600+1)*3600
    for event in record.get('economic_calendar_context',{}).get('events',[]):
        stamp=event.get('scheduled_at_utc')
        if (event.get('impact')=='high' and type(stamp) is int
            and event.get('time_precision')=='minute' and not event.get('timing_conflict')
            and event.get('status') not in ('cancelled','canceled')
            and start<=stamp<=end):
            events.append({'id':event.get('id'),'scheduled_at_utc':stamp,
                'reason':'発表予定前または発表後の基準足未更新。結果・市場反応は未確認'})
    status=('event_recheck' if events else 'price_plan_recheck' if not margin
        else 'reaction_confirmed' if conditions.get('status')=='conditions_observed' else 'confirmation_wait')
    if monitor_wait and not events and not margin and planned_ok: status='planned_price_wait'
    if (swing_wave and record.get('assessment')=='review' and record.get('grade') in ('A','B')
            and record['swing_wave']['status']!='response_confirmed' and not events):
        status='swing_wave_wait'
    descriptions={'planned_price_wait':'現在価格は追わず、保存された押し戻り・再試し水準での反応を監視。待ち水準の余地は参考で成立時に再評価', 'event_recheck':'発表をまたぐため再評価待ち。発表前の見方を現在判断へ流用しない',
        'price_plan_recheck':'今から追わず価格計画の組み直し待ち。成立条件の観測と機会の有無は別',
        'reaction_confirmed':'保存足で成立条件と価格余地を確認。執行価格・費用・継続性は別確認',
        'confirmation_wait':'価格計画を維持し、具体的な反応を待つ'}
    descriptions['swing_wave_wait']='H4の波の反応待ち。大局の方向監視にとどめ、M15の一時反応だけでは優先候補にしない'
    record['practical_review']={'schema':'saved_practical_review_v1','status':status,
        'summary':descriptions[status],'a_blockers':blockers,'events':events,
        'margin_basis':'fresh_saved_trigger_reward_exceeds_risk_before_costs',
        'reference_margin_sufficient':margin,'not_order_or_profitability':True}
    if monitor_wait:
        record['practical_review'].update(schema='saved_practical_review_v2',planned_price_review=planned)
    if record.get('assessment')=='review' and record.get('grade') in ('A','B'):
        record['grade']='B' if blockers else 'A'
        record['grade_reason']=('具体的な価格反応と現在の参考価格計画が整合。補助指標の遅れは独立した否定票にせず、記載した懸念を監視' if not blockers
            else '監視を継続。A未到達の理由：'+'／'.join(blockers))
    if monitor_wait:
        from .decision_brief import build_brief
        record['decision_brief']=build_brief(record)
    from .swing_horizon import build_swing_context
    context = build_swing_context(record)
    if context is not None:
        record['swing_context'] = context
    return record
