"""Bounded private follow-up of frozen observed plans across natural saves.

Only already saved, verified candles are considered. Touches use trigger-bar
high/low; local and thesis withdrawals require their respective closes. This
research ledger cannot establish an order within one candle or a trade fill.
"""
from copy import deepcopy
import datetime as dt
import hashlib
import json
import math
from zoneinfo import ZoneInfo

SCHEMA = 'private_plan_followup_v1'
LIMIT = 1024
HORIZON = {'swing': 72 * 3600, 'daytrade': 24 * 3600}
TRIGGER = {'swing': ('m15', 900), 'daytrade': ('m5', 300)}
BASE = {'swing': ('h4', 14400), 'daytrade': ('h1', 3600)}
NY = ZoneInfo('America/New_York')


def _timeframes(record):
    if record.get('daily_swing_version') == 1 and record['strategy'] == 'swing':
        return ('h1', 3600), ('d1', 86400)
    return TRIGGER[record['strategy']], BASE[record['strategy']]


def _nominal_market_closed(stamp):
    """Conventional FX weekend, not evidence of a provider's actual session."""
    local = dt.datetime.fromtimestamp(stamp, NY)
    weekday = local.weekday()
    return (weekday == 5 or (weekday == 4 and local.hour >= 17)
            or (weekday == 6 and local.hour < 17))


def _advance_market_coverage(anchor, record, clock):
    """Separate observable candle duration from the frozen wall-clock ledger."""
    (tf, seconds), _ = _timeframes(anchor)
    initial = ((anchor['start_at'] + seconds - 1) // seconds) * seconds
    coverage = anchor.setdefault('market_coverage', {
        'version': 1, 'calendar': 'nominal_ny_fx_weekend_v1',
        'next_open': initial, 'open_observed': 0, 'open_missing': 0,
        'closed_empty': 0, 'closed_observed': 0,
        'first_observed_close': None, 'last_observed_close': None})
    if (coverage.get('version') != 1 or type(coverage.get('next_open')) is not int
            or not initial <= coverage['next_open'] <= anchor['until'] + seconds):
        coverage['status'] = 'invalid_prior_coverage'
        return
    trigger = record.get('standard_inputs', {}).get('trigger', {})
    if trigger.get('timeframe') != tf or trigger.get('verified') is not True:
        coverage['status'] = 'input_unverified'
        return
    bars = {bar['timestamp']: bar for bar in trigger.get('bars', [])
            if isinstance(bar, dict) and type(bar.get('timestamp')) is int}
    through = min(clock, anchor['until'])
    stamp = coverage['next_open']
    while stamp + seconds <= through:
        closed = _nominal_market_closed(stamp)
        present = stamp in bars
        name = ('closed_observed' if present else 'closed_empty') if closed else (
            'open_observed' if present else 'open_missing')
        coverage[name] += 1
        if present:
            coverage['first_observed_close'] = coverage['first_observed_close'] or stamp + seconds
            coverage['last_observed_close'] = stamp + seconds
        stamp += seconds
    coverage['next_open'] = stamp
    coverage['observed_trigger_hours'] = round(
        (coverage['open_observed'] + coverage['closed_observed']) * seconds / 3600, 3)
    coverage['evaluated_through'] = through
    if clock < anchor['until']:
        coverage['status'] = 'tracking'
    elif coverage['closed_observed']:
        coverage['status'] = 'nominal_calendar_conflict'
    elif coverage['open_missing'] and coverage['closed_empty']:
        coverage['status'] = 'closed_weekend_and_unverified_open_hours'
    elif coverage['open_missing']:
        coverage['status'] = 'unverified_open_hours'
    elif coverage['closed_empty']:
        coverage['status'] = 'calendar_window_interrupted_by_weekend'
    else:
        coverage['status'] = 'calendar_window_observed'


def _price(value):
    return type(value) in (int, float) and math.isfinite(value) and value > 0


def _scenario_key(record):
    plan = record['wave_price_plan']
    identity = [record['pair'], record['strategy'], record['direction'],
                plan.get('start_pivot'), plan.get('end_pivot')]
    if record.get('daily_swing_version') == 1:
        identity.append({'daily_swing_version': 1})
    if not isinstance(plan.get('start_pivot'), dict) or not isinstance(plan.get('end_pivot'), dict):
        identity.append(plan.get('reference_close_timestamp'))
    return hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


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
    timing_profile = {'daily_swing_version': 1} if record.get('daily_swing_version') == 1 else {}
    if timing_profile:
        identity.append(timing_profile)
    (_, seconds), _ = _timeframes(record)
    key = hashlib.sha256(json.dumps(identity, sort_keys=True,
                                    separators=(',', ':')).encode()).hexdigest()
    scenario_key = _scenario_key(record)
    daily = next((item for item in digest['observations']
                  if item['pair'] == record['pair'] and item['timeframe'] == 'd1'), None)
    return {**timing_profile, 'key': key, 'scenario_key': scenario_key,
            'pair': record['pair'], 'strategy': strategy,
            'direction': record['direction'], 'start_at': clock,
            'until': clock + HORIZON[strategy], 'levels': levels,
            'daily_bars_sha256': daily['bars_sha256'] if daily else None,
            'daily_candidate_present': bool(daily and any(daily[k] for k in
                ('basic_count', 'equal_time_count', 'cycle_count'))),
            'reference_margin_sufficient': record.get('practical_review', {}).get(
                'reference_margin_sufficient'),
            'events': {}, 'next_trigger_open': ((clock + seconds - 1) // seconds * seconds),
            'last_base_close': None, 'missing_trigger_bars': 0,
            'base_gap': False, 'status': 'tracking'}


def _advance(anchor, record, clock):
    if anchor['status'] != 'tracking':
        return
    direction = anchor['direction']
    (tf, seconds), (base_tf, base_seconds) = _timeframes(anchor)
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
        closed = bar.get('session_end_utc') if base_tf == 'd1' else bar['timestamp'] + base_seconds
        if type(closed) is not int:
            anchor['status'] = 'input_unverified'
            return
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
        _advance_market_coverage(anchor, records[anchor['pair'], anchor['strategy']], clock)
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


TOP3_SCHEMA = 'private_top3_followup_v1'
TOP3_MAX_GROUPS = 192
TOP3_RETENTION = 7 * 86400


def build_top3_trace(outlook, sections, plans, previous=None):
    """Freeze the first published listing and link a subsequent fixed plan."""
    clock = outlook['evaluated_at']
    records = {(row['pair'], row['strategy']): row for row in outlook['strategy_assessments']}
    entries = {}
    if (isinstance(previous, dict) and previous.get('schema') == TOP3_SCHEMA
            and type(previous.get('evaluated_at')) is int and previous['evaluated_at'] < clock):
        entries = {entry['scenario_key']: deepcopy(entry) for entry in previous['entries']
                   if 0 <= clock - entry['listed_at'] <= TOP3_RETENTION}
    capacity_reached = False
    for strategy in HORIZON:
        for rank, listed in enumerate(sections.get(strategy, [])[:3], 1):
            if listed.get('excluded_target_reached'):
                continue
            record = records.get((listed['pair'], strategy))
            if (record is None or record.get('assessment') != 'review'
                    or record.get('direction') not in ('long', 'short')
                    or record.get('wave_price_plan', {}).get('status') != 'available'):
                continue
            key = _scenario_key(record)
            if key in entries:
                continue
            if len(entries) >= TOP3_MAX_GROUPS:
                capacity_reached = True
                continue
            close = record.get('trigger_price_review', {}).get('saved_close')
            obstacle = record.get('reference_levels', {}).get('structural_target')
            distance = None
            if _price(close) and _price(obstacle):
                sign = 1 if record['direction'] == 'long' else -1
                ahead = sign * (obstacle - close)
                if ahead > 0:
                    pip = .01 if record['pair'].endswith('JPY') else .0001
                    distance = round(ahead / pip, 3)
            entries[key] = {'scenario_key': key, 'pair': record['pair'],
                            'strategy': strategy, 'listed_at': clock, 'rank': rank,
                            'condition_at_listing': record['scenario_conditions']['status'],
                            'first_obstacle_pips_at_listing': distance}
    if plans.get('status') == 'saved':
        for plan in sorted(plans['anchors'], key=lambda item: item['start_at']):
            entry = entries.get(plan['scenario_key'])
            if (entry is not None and 'fixed_plan_key' not in entry
                    and plan['start_at'] >= entry['listed_at']):
                entry.update(fixed_plan_key=plan['key'], fixed_plan_at=plan['start_at'])
    return {'schema': TOP3_SCHEMA, 'evaluated_at': clock,
            'capacity_reached': capacity_reached, 'entries': list(entries.values())}
