"""Bounded private follow-up of frozen observed plans across natural saves.

Only already saved, verified candles are considered. Touches use trigger-bar
high/low; local and thesis withdrawals require their respective closes. This
research ledger cannot establish an order within one candle or a trade fill.
"""
from copy import deepcopy
import hashlib
import json
import math

SCHEMA = 'private_plan_followup_v1'
LIMIT = 1024
HORIZON = {'swing': 72 * 3600, 'daytrade': 24 * 3600}
TRIGGER = {'swing': ('m15', 900), 'daytrade': ('m5', 300)}
BASE = {'swing': ('h4', 14400), 'daytrade': ('h1', 3600)}


def _price(value):
    return type(value) in (int, float) and math.isfinite(value) and value > 0


def _anchor(record, digest):
    strategy = record.get('strategy')
    if (strategy not in HORIZON or record.get('assessment') != 'review'
            or record.get('scenario_conditions', {}).get('status') != 'conditions_observed'
            or record.get('wave_price_plan', {}).get('status') != 'available'
            or record.get('direction') not in ('long', 'short')):
        return None
    plan = record['wave_price_plan']
    recent = record.get('trigger_price_review', {})
    close, room = recent.get('saved_close'), recent.get('first_obstacle_reward')
    sign = 1 if record['direction'] == 'long' else -1
    try:
        levels = {'obstacle': close + sign * room,
                  'local_stop': plan['local_setup_failure'],
                  'wave_goal': plan['retest_objective']['price'],
                  'thesis_withdrawal': plan['thesis_invalidation']}
    except (KeyError, TypeError):
        return None
    if (not _price(close) or not _price(room) or
            not all(_price(value) for value in levels.values())):
        return None
    clock = record['evaluated_at']
    identity = [record['pair'], strategy, record['direction'],
                plan.get('reference_close_timestamp'), levels]
    key = hashlib.sha256(json.dumps(identity, sort_keys=True,
                                    separators=(',', ':')).encode()).hexdigest()
    scenario_identity = [record['pair'], strategy, record['direction'],
                         plan.get('start_pivot'), plan.get('end_pivot')]
    if not isinstance(plan.get('start_pivot'), dict) or not isinstance(plan.get('end_pivot'), dict):
        scenario_identity.append(plan.get('reference_close_timestamp'))
    scenario_key = hashlib.sha256(json.dumps(scenario_identity, sort_keys=True,
                                             separators=(',', ':')).encode()).hexdigest()
    daily = next((item for item in digest['observations']
                  if item['pair'] == record['pair'] and item['timeframe'] == 'd1'), None)
    return {'key': key, 'scenario_key': scenario_key,
            'pair': record['pair'], 'strategy': strategy,
            'direction': record['direction'], 'start_at': clock,
            'until': clock + HORIZON[strategy], 'levels': levels,
            'daily_bars_sha256': daily['bars_sha256'] if daily else None,
            'daily_candidate_present': bool(daily and any(daily[k] for k in
                ('basic_count', 'equal_time_count', 'cycle_count'))),
            'reference_margin_sufficient': record.get('practical_review', {}).get(
                'reference_margin_sufficient'),
            'events': {}, 'next_trigger_open': ((clock + TRIGGER[strategy][1] - 1)
                                                // TRIGGER[strategy][1] * TRIGGER[strategy][1]),
            'last_base_close': None, 'missing_trigger_bars': 0,
            'base_gap': False, 'status': 'tracking'}


def _advance(anchor, record, clock):
    if anchor['status'] != 'tracking':
        return
    strategy, direction = anchor['strategy'], anchor['direction']
    tf, seconds = TRIGGER[strategy]
    base_tf, base_seconds = BASE[strategy]
    inputs = record.get('standard_inputs', {})
    trigger, base = inputs.get('trigger', {}), inputs.get('base', {})
    if (trigger.get('timeframe') != tf or base.get('timeframe') != base_tf or
            trigger.get('verified') is not True or base.get('verified') is not True):
        anchor['status'] = 'input_unverified'
        return
    through = min(clock, anchor['until'])
    bars = {bar['timestamp']: bar for bar in trigger['bars']
            if isinstance(bar, dict) and type(bar.get('timestamp')) is int}
    stamp = anchor['next_trigger_open']
    sign = 1 if direction == 'long' else -1
    while stamp + seconds <= through:
        bar = bars.get(stamp)
        if bar is None:
            anchor['missing_trigger_bars'] += 1
        else:
            level = anchor['levels']
            for name, reached in (
                ('obstacle', sign * (bar['high' if sign == 1 else 'low'] - level['obstacle']) >= 0),
                ('wave_goal', sign * (bar['high' if sign == 1 else 'low'] - level['wave_goal']) >= 0),
                ('local_stop', sign * (bar['close'] - level['local_stop']) <= 0),
            ):
                if reached and name not in anchor['events']:
                    anchor['events'][name] = stamp + seconds
        stamp += seconds
    anchor['next_trigger_open'] = stamp
    for bar in base['bars']:
        if not isinstance(bar, dict) or type(bar.get('timestamp')) is not int:
            anchor['status'] = 'input_unverified'
            return
        closed = bar['timestamp'] + base_seconds
        if not anchor['start_at'] < closed <= through:
            continue
        last = anchor['last_base_close']
        if last is not None and closed <= last:
            continue
        if last is not None and closed - last > base_seconds:
            anchor['base_gap'] = True
        if sign * (bar['close'] - anchor['levels']['thesis_withdrawal']) <= 0:
            anchor['events'].setdefault('thesis_withdrawal', closed)
        anchor['last_base_close'] = closed
    if clock >= anchor['until']:
        anchor['status'] = ('complete' if anchor['missing_trigger_bars'] == 0
                            and not anchor['base_gap']
                            and anchor['next_trigger_open'] + seconds > anchor['until']
                            and anchor['last_base_close'] is not None
                            and anchor['last_base_close'] >= anchor['until'] - base_seconds
                            else 'censored_coverage')


def build(outlook, digest, previous=None):
    """Return a private ledger; failure never affects the canonical judgment."""
    clock = outlook['evaluated_at']
    prior = previous if isinstance(previous, dict) and previous.get('schema') == SCHEMA else None
    if prior and (prior.get('status') != 'saved'
                  or type(prior.get('evaluated_at')) is not int
                  or prior['evaluated_at'] >= clock
                  or not isinstance(prior.get('anchors'), list)):
        return {'schema': SCHEMA, 'evaluated_at': clock,
                'status': 'prior_invalid', 'anchors': []}
    anchors = deepcopy(prior['anchors']) if prior else []
    anchors = [a for a in anchors if type(a.get('start_at')) is int
               and 0 <= clock - a['start_at'] <= 7 * 86400]
    if len(anchors) > LIMIT or len({a.get('key') for a in anchors}) != len(anchors):
        return {'schema': SCHEMA, 'evaluated_at': clock, 'status': 'prior_invalid', 'anchors': []}
    records = {(r['pair'], r['strategy']): r for r in outlook['strategy_assessments']}
    known = {a['key'] for a in anchors}
    observed = 0
    missing_plan = 0
    added = 0
    for record in records.values():
        if (record.get('assessment') == 'review' and
                record.get('scenario_conditions', {}).get('status') == 'conditions_observed'):
            observed += 1
        anchor = _anchor(record, digest)
        if anchor is None and record.get('assessment') == 'review' and record.get(
                'scenario_conditions', {}).get('status') == 'conditions_observed':
            missing_plan += 1
        if anchor and anchor['key'] not in known:
            anchors.append(anchor)
            known.add(anchor['key'])
            added += 1
    if len(anchors) > LIMIT:
        return {'schema': SCHEMA, 'evaluated_at': clock, 'status': 'capacity_exceeded', 'anchors': []}
    for anchor in anchors:
        if anchor['status'] == 'tracking':
            _advance(anchor, records[anchor['pair'], anchor['strategy']], clock)
    result = {'schema': SCHEMA, 'evaluated_at': clock, 'status': 'saved',
              'scope': 'saved_candles_not_trade_or_profit',
              'lineage': 'continued' if prior else 'initialized_without_prior',
              'anchors': anchors,
              'current_observed_conditions': observed, 'current_missing_plan': missing_plan,
              'new_fixed_plans': added,
              'scenario_groups': len({a['scenario_key'] for a in anchors})}
    if len(json.dumps(result, allow_nan=False).encode()) > 800_000:
        return {'schema': SCHEMA, 'evaluated_at': clock,
                'status': 'capacity_exceeded', 'anchors': []}
    return result
