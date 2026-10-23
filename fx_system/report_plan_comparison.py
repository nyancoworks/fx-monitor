"""Compare saved price headroom only within matching scenario contexts.

This is a presentation tie-break, not an assessment, indicator vote, entry
rule, or profitability estimate. No snapshot fields are changed.
"""
import math


def _price(value):
    return type(value) in (int, float) and math.isfinite(value) and value > 0


def _dict(value):
    return value if isinstance(value, dict) else {}


def _fresh(stamp, seconds, clock):
    return (type(stamp) is int and type(clock) is int and seconds is not None
            and stamp > 0 and 0 <= clock - stamp < seconds)


def saved_plan_comparison(record):
    """Return an optional comparison group, saved RR, and Japanese explanation.

    Match the assessment's base-plan RR tolerance. Prefer a verified newer
    trigger close; never fall back from a claimed but invalid trigger close.
    Only known price-margin warnings are removed from the comparison context:
    they describe the quantity being compared, not independent opposition.
    Any unfamiliar opposition/uncertainty remains part of the exact group key.
    """
    unavailable = (None, None, '保存価格の余地比較：未確認。比較順位を上げる根拠にしない')
    levels = _dict(record.get('reference_levels'))
    plan = _dict(record.get('reference_plan'))
    direction = record.get('direction')
    clock = record.get('evaluated_at')
    stop, target, close = (levels.get('invalidation'), levels.get('structural_target'),
                           plan.get('reference_close'))
    reported = levels.get('reference_rr')
    if direction not in ('long', 'short') or not all(_price(x) for x in (stop, target, close, reported)):
        return unavailable

    def distances(price):
        return ((price-stop, target-price) if direction == 'long'
                else (stop-price, price-target))

    risk, reward = distances(close)
    if risk <= 0 or reward <= 0:
        return unavailable
    ratio = reward/risk
    if not math.isfinite(ratio) or abs(ratio-reported) > .011:
        return unavailable
    base_seconds = {'h4': 14400, 'h1': 3600}.get(record.get('reference_timeframe'))
    stamp = plan.get('reference_close_timestamp')
    if type(stamp) is not int or not base_seconds or not _fresh(stamp+base_seconds, base_seconds, clock):
        return unavailable
    basis = 'base'
    recent = _dict(record.get('trigger_price_review'))
    trigger_seconds = {'m15': 900, 'm5': 300}.get(record.get('trigger_timeframe'))
    if recent.get('status') == 'observed_reference':
        trigger_close = recent.get('saved_close')
        if (not _price(trigger_close)
                or not _fresh(recent.get('closed_at'), trigger_seconds, clock)
                or recent['closed_at'] < stamp+base_seconds):
            return unavailable
        risk, reward = distances(trigger_close)
        if risk <= 0 or reward <= 0:
            return unavailable
        ratio = reward/risk
        if (not math.isfinite(ratio) or not _price(recent.get('reference_rr'))
                or abs(ratio-recent['reference_rr']) > .011):
            return unavailable
        basis = 'trigger'
    note = ('確認足' if basis == 'trigger' else '基準足') + f'保存終値の目標距離／無効化距離：{ratio:.2f}'
    if reward < risk:
        note += '。目標までの余地が無効化までの距離より小さい'
    if basis == 'base':
        note += '。後の確認足価格は未確認'
    note += '。成立後RR・現在の売買価格・優位性を示す値ではない'

    # Missing clocks/conditions/context do not become a favorable default.
    conditions = _dict(record.get('scenario_conditions'))
    phase = record.get('market_phase')
    opposition = record.get('opposing_evidence')
    uncertainty = record.get('uncertainties')
    if (phase not in ('range_edge_reversal', 'pullback_wait', 'transition_context',
                      'directional_structure_with_reaction', 'directional_structure_wait')
            or conditions.get('evaluated_at') != clock
            or conditions.get('timeframe') != record.get('trigger_timeframe')
            or conditions.get('direction') != direction
            or conditions.get('status') not in ('waiting', 'awaiting_breakout', 'awaiting_retest',
                                               'retest_failed', 'conditions_observed')
            or conditions.get('route') not in ('continuation_breakout', 'pullback_rejection',
                                                'breakout_retest', 'range_edge_rejection')
            or not isinstance(opposition, list) or not all(isinstance(x, str) for x in opposition)
            or not isinstance(uncertainty, list) or not all(isinstance(x, str) for x in uncertainty)
            or _dict(record.get('expiry')).get('status') == 'withdrawn'):
        return None, ratio, note + '。確認段階を比較できないため掲載順を維持'
    margin_notes = {'構造目標の参考RRが1.5未満。採算余地を再検討（執行RRではない）'}
    if basis == 'trigger' and reward < risk:
        margin_notes.add(f"{record.get('trigger_timeframe')}保存終値基準では目標までの余地{reward:g}が無効化距離{risk:g}より小さい。勝率・優位性は未検証")
    strength = _dict(record.get('currency_strength_context'))
    # Use a common unknown bucket only when neither record claims valid context.
    strength_key = (strength.get('status'), strength.get('relation'), strength.get('movement'))
    if any(value is not None and not isinstance(value, str) for value in strength_key):
        return None, ratio, note
    formation = _dict(record.get('formation_observation'))
    formation_status = formation.get('status', 'unverified')
    if (formation_status not in ('unverified', 'observed_reference')
            or (formation_status == 'observed_reference' and
                (formation.get('timeframe') != record.get('trigger_timeframe')
                 or not _fresh(formation.get('closed_at'), trigger_seconds, clock)
                 or formation.get('scenario_withdrawn') is not False))
            or record.get('scenario_type', 'trend') not in ('trend', 'range_reversal')):
        return None, ratio, note
    group = (record.get('grade'), record.get('strategy'), record.get('scenario_type', 'trend'),
             phase, conditions['route'], conditions['status'], basis,
             tuple(x for x in opposition if x not in margin_notes), tuple(uncertainty), strength_key,
             formation_status)
    return group, ratio, note
