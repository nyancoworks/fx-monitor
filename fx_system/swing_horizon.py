"""Separate H4 directional context from the lifetime of an M15 price plan."""
import math

METHOD = 'contextual_scenario_review_v8_swing_horizon'


def build_swing_context(record):
    if record.get('strategy') != 'swing' or record.get('method_version') != METHOD:
        return None
    clock = record.get('evaluated_at')
    plan = record.get('reference_plan', {})
    stamp = plan.get('reference_close_timestamp')
    close = plan.get('reference_close')
    levels = record.get('reference_levels', {})
    stop = levels.get('invalidation')
    direction = {'HH_HL': 'long', 'LH_LL': 'short'}.get(record.get('base_structure'))
    fresh = (record.get('base_quality_verified') is True and type(clock) is int
             and type(stamp) is int and stamp > 0 and stamp % 14400 == 0
             and 0 <= clock - (stamp + 14400) < 14400)
    positive = lambda v: type(v) in (int, float) and math.isfinite(v) and v > 0
    state, summary = 'unverified', 'H4の方向・確定時計・構造水準は未確認'
    if fresh and direction is None:
        state, summary = 'direction_unconfirmed', 'H4の方向構造は未確認。M15から方向を補完しない'
    elif fresh and direction == record.get('direction') and positive(close) and positive(stop):
        crossed = close <= stop if direction == 'long' else close >= stop
        if crossed:
            state, summary = 'structure_invalidated', 'H4確定終値が構造無効化水準を越境。大局の再形成待ち'
        elif record.get('swing_environment', {}).get('exclude_from_monitoring'):
            state, summary = 'environment_excluded', 'H4のもみ合い背景でスイング監視対象外'
        else:
            state, summary = 'direction_watch', 'H4の方向構造を監視。M15の仕掛け停止とは区別する'
    reason = record.get('skip_reason')
    trigger_stop = reason in ('confirmed_trigger_invalidation', 'saved_trigger_invalidation_crossed',
                              'saved_trigger_target_reached')
    entry = ('paused' if trigger_stop else 'unavailable' if record.get('assessment') != 'review'
             else record.get('practical_review', {}).get('status', 'unverified'))
    return {'schema': 'saved_swing_context_v1', 'evaluated_at': clock,
            'structure_timeframe': 'h4', 'entry_timeframe': 'm15',
            'structure_closed_at': stamp + 14400 if fresh else None,
            'direction': direction if fresh else None, 'structure_status': state,
            'structure_invalidation': stop if positive(stop) else None,
            'entry_status': entry, 'entry_pause_reason': reason if trigger_stop else None,
            'summary': summary,
            'holding_period': 'not_estimated', 'time_exit': 'not_defined',
            'target_scope': 'nearest_confirmed_h4_obstacle_not_multi_day_forecast',
            'recheck': 'H4確定ごとに方向構造を再評価。M15は仕掛け条件と価格余地を再評価',
            'not_position_management': True}
