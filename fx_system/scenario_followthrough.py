"""Frozen prior conditions in already saved candles; never fills or new grades."""
from .candidate_followup import positive
from .scenario_conditions import validate_conditions


def _aggregate(rows, seconds, start, end, input_seconds=300):
    """Only complete UTC-aligned candles, never partial bars or gap filling."""
    result = []
    for stamp in range((start + seconds - 1) // seconds * seconds,
                       end // seconds * seconds, seconds):
        block = [rows.get(t) for t in range(stamp, stamp + seconds, input_seconds)]
        if any(b is None for b in block):
            continue
        result.append({'timestamp': stamp, 'closed_at': stamp + seconds,
                       'open': block[0]['open'], 'close': block[-1]['close'],
                       'high': max(b['high'] for b in block),
                       'low': min(b['low'] for b in block)})
    return result


def observe_frozen_condition(record, pair, through):
    """Observe an original plan without replacing it with the current local level.

    The caller binds both assessments and the supplied candles to immutable
    snapshots. Positive observations need complete preceding whole M5 coverage;
    partial boundary intervals remain explicitly excluded. Base-timeframe close
    withdrawal is separate from intrabar level touches.
    """
    clock = record['evaluated_at']
    out = {'schema': 'frozen_condition_followthrough_v1',
           'status': 'not_monitorable_at_save', 'saved_evaluated_at': clock,
           'through': through, 'condition_observation': None,
           'base_close_withdrawal': None, 'trigger_close_withdrawal': None, 'target_touch': None,
           'invalidation_touch': None, 'trade_performance': 'not_measured',
           'is_current_scenario_validity': False, 'is_entry_or_fill': False}
    plan = record.get('scenario_conditions', {})
    supported = ('waiting', 'awaiting_breakout', 'awaiting_retest', 'conditions_observed')
    if (record.get('assessment') != 'review' or plan.get('status') not in supported
            or record.get('expiry', {}).get('status') == 'withdrawn'):
        return out
    if validate_conditions(record):
        return {**out, 'status': 'saved_condition_unverified'}
    seconds = {'m5': 300, 'm15': 900}.get(record.get('trigger_timeframe'))
    base_seconds = {'h1': 3600, 'h4': 14400}.get(record.get('reference_timeframe'))
    levels = record.get('reference_levels', {})
    stop, target, level = levels.get('invalidation'), levels.get('structural_target'), plan.get('level')
    sign = 1 if record.get('direction') == 'long' else -1 if record.get('direction') == 'short' else 0
    if (not seconds or not base_seconds or not sign or type(through) is not int
            or not 0 < through-clock <= 31*86400 or not all(positive(v) for v in (stop, target, level))
            or not sign * (target - level) > 0 or not sign * (level - stop) > 0):
        return {**out, 'status': 'saved_price_plan_unavailable'}
    out.update(original_level=level, original_target=target, original_invalidation=stop,
               confirmation_timeframe=record['trigger_timeframe'],
               withdrawal_timeframes=[record['reference_timeframe'],record['trigger_timeframe']],
               condition_route=plan['route'])
    decision = pair.get('decision_data', {}) if isinstance(pair, dict) else {}
    if not isinstance(decision, dict) or not isinstance(decision.get('raw', {}), dict):
        return {**out, 'status': 'followup_input_invalid'}
    raw = decision.get('raw', {}).get('m5', [])
    provenance = decision.get('provenance', {})
    if not isinstance(raw, list) or len(raw) > 10000 or not isinstance(provenance, dict):
        return {**out, 'status': 'followup_input_invalid'}
    rows = {}; stamps = []; unknown = 0
    for bar in raw:
        if not isinstance(bar, dict) or type(bar.get('timestamp')) is not int:
            return {**out, 'status': 'followup_input_invalid'}
        ts = bar['timestamp']
        if ts < clock // base_seconds * base_seconds or ts + 300 > through:
            continue
        if (ts <= 0 or ts % 300 or any(not positive(bar.get(k)) for k in ('open', 'high', 'low', 'close'))
                or not bar['low'] <= min(bar['open'], bar['close']) <= max(bar['open'], bar['close']) <= bar['high']):
            return {**out, 'status': 'followup_input_invalid'}
        stamps.append(ts)
        if provenance.get('m5:' + str(ts)) == 'Twelve Data':
            rows[ts] = bar
        elif ts >= clock:
            unknown += 1
    if stamps != sorted(set(stamps)):
        return {**out, 'status': 'followup_input_invalid'}
    start = (clock + 299) // 300 * 300
    expected = list(range(start, through // 300 * 300, 300))
    missing = sum(t not in rows for t in expected)
    out.update(whole_m5_count=len(expected) - missing, missing_or_unverified_m5_count=missing,
               unverified_future_source_count=unknown,
               excluded_initial_m5_seconds=start-clock,
               excluded_initial_confirmation_seconds=(clock+seconds-1)//seconds*seconds-clock,
               excluded_final_m5_seconds=through % 300,
               boundary_candles_are_not_fully_observed=True)
    if not expected:
        return {**out, 'status': 'awaiting_whole_future_candles'}
    if missing:
        return {**out, 'status': 'incomplete_saved_candles'}
    future = [rows[t] for t in expected]
    for bar in future:
        for name, price in (('target_touch', target), ('invalidation_touch', stop)):
            reached = (sign*(bar['high' if sign == 1 else 'low']-price) >= 0 if name == 'target_touch'
                       else sign*(bar['low' if sign == 1 else 'high']-price) <= 0)
            if reached and out[name] is None:
                out[name] = {'bar_opened_at': bar['timestamp'], 'bar_closed_at': bar['timestamp']+300,
                             'level': price, 'is_close_based_withdrawal': False}
    # Production H4 is derived from verified H1, not from potentially different
    # M5 closes. Retain that distinction when checking the original base plan.
    hourly = {}; hourly_stamps = []
    raw_hourly = decision.get('raw', {}).get('h1', [])
    if not isinstance(raw_hourly, list) or len(raw_hourly) > 10000:
        return {**out, 'status': 'followup_input_invalid'}
    for bar in raw_hourly:
        if not isinstance(bar, dict) or type(bar.get('timestamp')) is not int:
            return {**out, 'status': 'followup_input_invalid'}
        ts = bar['timestamp']
        if ts < clock // base_seconds * base_seconds or ts + 3600 > through:
            continue
        if (ts <= 0 or ts % 3600 or any(not positive(bar.get(k)) for k in ('open', 'high', 'low', 'close'))
                or not bar['low'] <= min(bar['open'], bar['close']) <= max(bar['open'], bar['close']) <= bar['high']):
            return {**out, 'status': 'followup_input_invalid'}
        hourly_stamps.append(ts)
        if provenance.get('h1:' + str(ts)) == 'Twelve Data':
            hourly[ts] = bar
    if hourly_stamps != sorted(set(hourly_stamps)):
        return {**out, 'status': 'followup_input_invalid'}
    # A base candle may open before publication. Its later close can be checked
    # only with all constituent verified H1 candles, including the earlier ones.
    base = _aggregate(hourly, base_seconds, clock // base_seconds * base_seconds, through, 3600)
    for bar in base:
        if bar['closed_at'] <= clock:
            continue
        reason = ('invalidation_crossed' if sign*(bar['close']-stop) <= 0 else
                  'structural_target_reached' if sign*(bar['close']-target) >= 0 else None)
        if reason:
            out['base_close_withdrawal'] = {'condition': reason, 'closed_at': bar['closed_at'],
                                             'saved_close': bar['close']}
            break
    out['base_close_coverage_complete'] = len(base) == through//base_seconds-clock//base_seconds
    confirmation = _aggregate(rows, seconds, clock, through)
    out['whole_confirmation_candle_count'] = len(confirmation)
    for bar in confirmation:
        reason = ('invalidation_crossed' if sign*(bar['close']-stop) <= 0 else
                  'structural_target_reached' if sign*(bar['close']-target) >= 0 else None)
        if reason:
            out['trigger_close_withdrawal'] = {'condition': reason, 'closed_at': bar['closed_at'],
                                                'saved_close': bar['close']}
            break
    if plan['status'] == 'conditions_observed':
        return {**out, 'status': 'already_observed_at_save'}
    breakout = plan.get('breakout_observed_at') if plan['status'] == 'awaiting_retest' else None
    for bar in confirmation:
        withdrawals = [out[k] for k in ('base_close_withdrawal','trigger_close_withdrawal') if out[k]]
        if any(w['closed_at'] <= bar['closed_at'] for w in withdrawals):
            break
        close, opened = bar['close'], bar['open']
        touched = bar['low'] <= level if sign == 1 else bar['high'] >= level
        reclaimed = sign * (close-level) > 0
        route = plan['route']
        if route in ('pullback_rejection', 'range_edge_rejection'):
            observed = touched and reclaimed and sign*(close-opened) > 0
        elif route == 'continuation_breakout':
            observed = reclaimed
        elif route == 'breakout_retest':
            if breakout is None:
                if reclaimed:
                    breakout = bar['closed_at']
                continue
            if not reclaimed:
                return {**out, 'status': 'frozen_retest_failed', 'retest_failed_at': bar['closed_at']}
            observed = touched and breakout < bar['closed_at']
        else:
            return {**out, 'status': 'saved_condition_unverified'}
        if observed:
            risk, reward = sign*(close-stop), sign*(target-close)
            out['condition_observation'] = {'closed_at': bar['closed_at'], 'saved_close': close,
                'risk_distance': risk, 'reward_distance': reward,
                'reference_rr': reward/risk if risk > 0 and reward > 0 else None,
                'margin_sufficient_before_costs': risk > 0 and reward > risk,
                'costs_included': False, 'is_entry_or_fill': False,
                'base_close_coverage_complete': out['base_close_coverage_complete']}
            return {**out, 'status': 'frozen_condition_observed'}
    return {**out, 'status': 'close_based_withdrawal_observed' if out['base_close_withdrawal'] or out['trigger_close_withdrawal'] else
            'frozen_condition_not_seen_in_whole_candles' if confirmation else 'awaiting_whole_future_candles'}
