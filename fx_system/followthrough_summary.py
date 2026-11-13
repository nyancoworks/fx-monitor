"""Chronological facts about a frozen scenario, never a trade outcome."""
from datetime import datetime
from zoneinfo import ZoneInfo


def describe(row):
    follow = row.get('previous_condition_followthrough') or {}
    events = []
    labels = {'local_setup_failure_crossed':'局所停止',
              'invalidation_crossed':'見立て撤回',
              'path_objective_reached':'経路目標到達',
              'structural_target_reached':'構造目標到達'}
    for key in ('base_close_withdrawal', 'trigger_close_withdrawal'):
        event = follow.get(key) or {}
        label = labels.get(event.get('condition'))
        if label and type(event.get('closed_at')) is int:
            events.append((event['closed_at'], label))
    objective = follow.get('base_objective_observation') or {}
    if type(objective.get('closed_at')) is int:
        events.append((objective['closed_at'], '経路目標到達'))
    if not events:
        return ''  # No event is not evidence of success or failure.
    observation = follow.get('condition_observation') or {}
    prefix = ''
    if type(observation.get('closed_at')) is int:
        events.append((observation['closed_at'], '条件観測'))
    elif (row.get('previous', {}).get('scenario_conditions') or {}).get('status') == 'conditions_observed':
        prefix = '保存時点で条件観測済み → '
    grouped = {}
    for stamp, label in sorted(set(events)):
        grouped.setdefault(stamp, []).append(label)
    parts = []
    for stamp, values in grouped.items():
        clock = datetime.fromtimestamp(stamp, ZoneInfo('Asia/Tokyo')).strftime('%m/%d %H:%M')
        parts.append(clock+' '+ '・'.join(values)+('（同時刻・順序未確認）' if len(values)>1 else ''))
    return prefix+' → '.join(parts)+'。前回の固定条件の経過で、今回の条件とは別'
