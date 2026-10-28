"""A traceable saved-price decision brief, never a quote or order."""
import math


def _price(v):
    return type(v) in (int,float) and math.isfinite(v) and v>0


def build_brief(r):
    level=r.get('reference_levels',{}); stop=level.get('invalidation');target=level.get('structural_target')
    recent=r.get('trigger_price_review',{}); conditions=r.get('scenario_conditions',{})
    practical=r.get('practical_review',{})
    sign=1 if r.get('direction')=='long' else -1 if r.get('direction')=='short' else 0
    clock=r.get('evaluated_at'); seconds={'m5':300,'m15':900}.get(r.get('trigger_timeframe'),0)
    close=recent.get('saved_close');stamp=recent.get('closed_at')
    fresh=(recent.get('status')=='observed_reference' and type(clock) is int and type(stamp) is int
        and seconds and 0<=clock-stamp<seconds and _price(close))
    coherent=sign and _price(stop) and _price(target) and sign*(target-stop)>0
    boundary=(target+stop)/2 if coherent else None
    waiting=conditions.get('level') if conditions.get('status') in ('waiting','awaiting_breakout','awaiting_retest') else None
    status=practical.get('status','unverified')
    return {'schema':'saved_decision_brief_v1','evaluated_at':clock,
        'basis':'saved_assessment_not_live_or_fill','direction':r.get('direction'),
        'practical_status':status,'decision':practical.get('summary','判断材料未確認'),
        'base_timeframe':r.get('reference_timeframe'),'confirmation_timeframe':r.get('trigger_timeframe'),
        'confirmation_status':conditions.get('status'),
        'confirmation_field':'scenario_conditions.summary',
        'waiting_level':waiting,'waiting_plan_field':'practical_review.planned_price_review',
        'saved_close_reference':{'price':close,'closed_at':stamp} if fresh else None,
        'current_margin_field':'trigger_price_review',
        'structural_target':target,'invalidation':stop,
        'before_cost_reward_equals_risk_boundary':boundary,
        'indicative_margin_interval':{'lower':stop if sign==1 else boundary,'upper':boundary if sign==1 else stop,'endpoints':'exclusive','not_entry_range':True} if coherent else None,
        'boundary_relation':'<' if sign==1 else '>' if sign==-1 else None,
        'boundary_meaning':'既存の余地判定（目標距離が無効化距離を上回る）の境界。推奨エントリーや損益分岐ではない',
        'recheck':'待った反応の終了足で価格余地を再計算。境界到達・目標到達・無効化なら旧計画をそのまま追わない',
        'strength_context_field':'currency_strength_context',
        'cautions_field':'opposing_evidence','event_rechecks_field':'practical_review.events',
        'limits':['保存価格であり現在値ではない','スプレッド・滑り・手数料は未取得。費用控除後の余地は未確認',
            '実際の成立価格・約定・利益は未確認','予定の欠落を発表リスクなしと解釈しない']}
