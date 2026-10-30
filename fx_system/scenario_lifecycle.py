"""Explain existing saved-scenario withdrawal decisions; no new expiry policy."""
from copy import deepcopy
from math import isfinite


def describe_lifecycle(record):
    direction = record.get('direction')
    levels = record.get('reference_levels', {})
    conditions = []
    for kind, field, relation in (
            ('invalidation_crossed', 'invalidation', '<=' if direction == 'long' else '>='),
            ('structural_target_reached', 'structural_target', '>=' if direction == 'long' else '<=')):
        price = levels.get(field)
        if direction in ('long', 'short') and type(price) in (int, float) and isfinite(price) and price > 0:
            conditions.append({'condition': kind, 'price': price, 'relation': relation,
                               'basis_timeframe': record.get('reference_timeframe'),
                               'confirmation': 'verified_saved_closed_candle_not_live_quote'})
    reason = record.get('skip_reason')
    invalidation = reason in ('confirmed_trigger_invalidation', 'saved_base_invalidation_crossed',
                              'saved_trigger_invalidation_crossed', 'confirmed_range_break')
    withdrawn = invalidation or reason == 'saved_trigger_target_reached'
    recent = record.get('trigger_price_review', {})
    observation = None
    if withdrawn:
        if reason == 'confirmed_range_break':
            observation = deepcopy(record.get('range_context', {}).get('break_observation'))
        elif reason.startswith('saved_trigger_'):
            observation = {'timeframe': record.get('trigger_timeframe'),
                           'closed_at': recent.get('closed_at'), 'saved_close': recent.get('saved_close')}
        elif reason == 'confirmed_trigger_invalidation':
            observation = {'timeframe': record.get('trigger_timeframe'),
                           'closed_at': record.get('invalidation_observed_at'), 'saved_close': None}
        else:
            plan = record.get('reference_plan', {})
            stamp = plan.get('reference_close_timestamp')
            seconds = {'h4': 14400, 'h1': 3600}.get(record.get('reference_timeframe'))
            observation = {'timeframe': record.get('reference_timeframe'),
                           'closed_at': stamp + seconds if type(stamp) is int and seconds else None,
                           'saved_close': plan.get('reference_close')}
    old = record.get('expiry', {})
    expiry = {
        'status': 'withdrawn' if withdrawn else 'unverified' if record.get('assessment') == 'evaluation_pending'
                  else 'reference_recheck' if record.get('assessment') == 'review' else 'not_applicable',
        'time_expiry': {'status': 'not_defined', 'reason': '時間失効の合意済み規定なし。期限は推定しない'},
        'withdrawal_conditions': conditions,
        'observed_condition': reason if withdrawn else None,
        'observation': observation,
        'basis': 'existing_saved_scenario_decision_not_position_exit_or_new_gate',
        'recheck': old.get('recheck', '次の確定基準足で構造・品質・反応を再評価する'),
    }
    inv = deepcopy(record.get('invalidation', {}))
    from .swing_horizon import METHOD
    from .swing_wave import METHOD as WAVE_METHOD
    if record.get('strategy') == 'swing' and record.get('method_version') in (METHOD, WAVE_METHOD):
        expiry['scope'] = 'saved_price_plan_not_h4_direction'
        expiry['recheck'] = 'H4で方向構造、M15で仕掛け計画を別々に再評価する'
        for condition in conditions:
            condition['scope'] = 'price_plan'
            condition['confirmation_timeframes'] = ['h4', 'm15']
    diagnostic = inv.get('observed') is True
    inv.update(observed=invalidation,
               observation_status='observed_in_saved_evidence' if invalidation else
                                  'unverified_diagnostic' if diagnostic else 'not_observed_in_saved_checks')
    if invalidation:
        inv.update(observation=observation, basis='検証済み保存足の既存無効化判定。現在値・SL注文ではない')
    return expiry, inv
