"""Small, reproducible research index for the private saved report.

This describes saved observations and presentation margins. It does not score
time candidates, alter assessments, or infer a trade from a monitoring slot.
"""
import hashlib
import json

from .monitor_pairs import PAIR_KEYS
from .strategy_report import CURRENT_SELECTION_VERSION, report_records


def build(outlook, *, selection_version=CURRENT_SELECTION_VERSION):
    if outlook.get('activate_time_version') != 1:
        return None
    context = outlook['activate_time_context']
    if set(context) != set(PAIR_KEYS):
        raise ValueError('time research universe invalid')
    observations = []
    for pair in PAIR_KEYS:
        for timeframe in ('d1', 'w1'):
            item = context[pair]['timeframes'][timeframe]
            source, observation = item['source'], item['observation']
            raw = json.dumps(source['bars'], sort_keys=True, separators=(',', ':'),
                             allow_nan=False).encode()
            observations.append({
                'pair': pair, 'timeframe': timeframe,
                'closed_at': source['closed_at'],
                'bars_sha256': hashlib.sha256(raw).hexdigest(),
                'status': observation['status'],
                'basic_count': len(observation['basic']),
                'equal_time_count': len(observation['equal_time']),
                'cycle_count': len(observation['cycles']),
                'price_confirmation': observation['price_confirmation'],
            })
    selected = []
    for record in report_records(outlook, selection_version=selection_version):
        recent = record.get('trigger_price_review', {})
        room = recent.get('first_obstacle_reward')
        pip = .01 if 'JPY' in record['pair'] else .0001
        selected.append({
            'pair': record['pair'], 'strategy': record['strategy'],
            'reference_margin_sufficient': record.get('practical_review', {}).get(
                'reference_margin_sufficient'),
            'first_obstacle_pips': round(room / pip, 2)
                if type(room) in (int, float) and room > 0 else None,
        })
    return {'schema': 'private_research_digest_v1', 'evaluated_at': outlook['evaluated_at'],
            'scope': 'saved_observations_not_prediction_or_trade',
            'observations': observations, 'report_selection_before_continuity': selected}
