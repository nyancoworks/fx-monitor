"""Contextual saved-scenario maturity and monitoring priority; never execution."""
import math


def _number(x):
    return type(x) in (int,float) and math.isfinite(x)


def review(record):
    conditions=record.get('scenario_conditions',{})
    recent=record.get('trigger_price_review',{})
    clock=record['evaluated_at']; seconds={'m5':300,'m15':900}.get(record.get('trigger_timeframe'),0)
    closed=recent.get('closed_at')
    verified=(recent.get('status')=='observed_reference' and type(closed) is int
        and seconds>0 and 0<=clock-closed<seconds)
    risk=recent.get('risk_distance');reward=recent.get('reward_distance')
    defined=verified and _number(risk) and _number(reward) and risk>0 and reward>0
    margin=defined and reward>risk
    blockers=[]
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
    descriptions={'event_recheck':'発表をまたぐため再評価待ち。発表前の見方を現在判断へ流用しない',
        'price_plan_recheck':'今から追わず価格計画の組み直し待ち。成立条件の観測と機会の有無は別',
        'reaction_confirmed':'保存足で成立条件と価格余地を確認。執行価格・費用・継続性は別確認',
        'confirmation_wait':'価格計画を維持し、具体的な反応を待つ'}
    record['practical_review']={'schema':'saved_practical_review_v1','status':status,
        'summary':descriptions[status],'a_blockers':blockers,'events':events,
        'margin_basis':'fresh_saved_trigger_reward_exceeds_risk_before_costs',
        'reference_margin_sufficient':margin,'not_order_or_profitability':True}
    if record.get('assessment')=='review' and record.get('grade') in ('A','B'):
        record['grade']='B' if blockers else 'A'
        record['grade_reason']=('具体的な価格反応と現在の参考価格計画が整合。補助指標の遅れは独立した否定票にせず、記載した懸念を監視' if not blockers
            else '監視を継続。A未到達の理由：'+'／'.join(blockers))
    return record
