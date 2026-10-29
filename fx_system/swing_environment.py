"""H4 context for trend-only swing monitoring; not an original-method signal."""

METHOD = 'contextual_scenario_review_v7_trend_swing'


def build_environment(record):
    """One SB family's consolidation context, never an indicator vote.

    Structure remains primary. Missing auxiliary observations do not erase a
    verified structural direction; missing primary quality is evaluation pending.
    Only H4 is examined: M15 pullbacks must remain independently monitorable.
    """
    if record.get('strategy') != 'swing':
        return None
    clock = record.get('evaluated_at')
    structure = record.get('base_structure')
    direction = {'HH_HL': 'long', 'LH_LL': 'short'}.get(structure)
    out = {'schema': 'saved_swing_environment_v1', 'evaluated_at': clock,
           'timeframe': 'h4', 'structure': structure, 'direction': direction,
           'state': 'primary_unverified', 'exclude_from_monitoring': False,
           'sb_status': 'unverified', 'sb_observation': None,
           'basis': 'structure_primary_sb_consolidation_context_not_votes',
           'original_method_replication': False,
           'summary': 'H4構造の品質未確認。レンジと断定せず評価保留'}
    if record.get('base_quality_verified') is not True:
        return out
    if direction is None or direction != record.get('direction'):
        out.update(state='direction_unconfirmed',
                   summary='H4の方向構造が不明確。トレンド方向を補完せず再形成待ち')
        return out
    out.update(state='structure_only', summary='H4構造の方向を保持。SB局面は未確認')
    context = record.get('indicator_context', {})
    if not isinstance(context, dict) or context.get('schema') != 'contextual_indicator_context_v2' or context.get('evaluated_at') != clock:
        return out
    frame = context.get('frames', {}).get('base', {})
    if frame.get('timeframe') != 'h4':
        return out
    notes = [n for n in frame.get('observations', []) if n.get('indicator') == 'super_bollinger']
    if len(notes) != 1:
        return out
    note = notes[0]; app = note.get('application', {}); closed = app.get('closed_at')
    if (note.get('status') != 'calculated' or type(clock) is not int or type(closed) is not int
            or closed % 14400 or not 0 <= clock - closed < 14400):
        return out
    lag, zone, width = note.get('lagging_span_location'), app.get('price_zone'), app.get('bandwidth_state')
    if lag not in ('above', 'below', 'inside') or zone not in ('above_upper_1sigma', 'below_lower_1sigma', 'inside_1sigma') or width not in ('expanding', 'contracting', 'flat'):
        return out
    out.update(sb_status='observed', sb_observation={'closed_at': closed,
               'lagging_location': lag, 'price_zone': zone, 'bandwidth_state': width})
    if (lag, zone, width) == ('inside', 'inside_1sigma', 'contracting'):
        out.update(state='h4_consolidation', exclude_from_monitoring=True,
                   summary='H4遅行が過去足内・終値が±1σ内・帯縮小のもみ合い背景。スイング監視対象外、構造と拡がりの再評価待ち')
    elif lag == ('below' if direction == 'long' else 'above') or zone == ('below_lower_1sigma' if direction == 'long' else 'above_upper_1sigma'):
        out.update(state='trend_with_counterpressure',
                   summary='H4構造方向は保持。SBの逆行背景を懸念として残し、価格反応を待つ')
    else:
        out.update(state='structural_trend_context',
                   summary='H4構造方向の押し目・戻りを監視。M15の調整だけでは除外しない')
    return out
