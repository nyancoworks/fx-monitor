"""Build an immutable per-save follow-up record using already-collected candles only."""
from copy import deepcopy
from .monitoring_result_history import restore_generation, pack_generation
from fx_system.candidate_followup import observe, positive
from fx_system.monitor_pairs import PAIR_KEYS
from fx_system.validate_strategy_snapshot import validate_strategy_snapshot


def canonical_records(payload):
    rows = payload['rows']
    if any(not isinstance(row.get('strategy_assessments'), dict) for row in rows):
        return None
    records = [row['strategy_assessments'].get(s) for row in rows for s in ('swing', 'daytrade')]
    if any(not isinstance(r, dict) for r in records):
        return None
    counts = {s: sum(r.get('assessment') == s for r in records) for s in ('review', 'skip', 'evaluation_pending')}
    clock = payload['evaluated_at']
    candidate = {'evaluated_at': clock, 'scheduled_outlook': {
        'evaluated_at': clock, 'advisory_only': True,
        'canonical_assessment_field': 'strategy_assessments', 'strategy_assessment_count': 32,
        'strategy_assessments': records, 'assessment_counts': counts, 'rows': rows}}
    if validate_strategy_snapshot(candidate):
        return None
    return records


def observed_bars(pair, since, through):
    """Whitelist closed OHLC with its existing provider identity; never infer a missing bar."""
    decision = pair.get('decision_data', {}) if isinstance(pair, dict) else {}
    if not isinstance(decision, dict):
        return {'status': 'invalid_input', 'candles': [], 'unverified_source_count': 0}
    raw = decision.get('raw', {})
    bars = raw.get('m5', []) if isinstance(raw, dict) else []
    provenance = decision.get('provenance', {})
    if not isinstance(bars, list) or not isinstance(provenance, dict):
        return {'status': 'invalid_input', 'candles': [], 'unverified_source_count': 0}
    output = []; unknown = 0; stamps = []
    for b in bars:
        if not isinstance(b, dict) or type(b.get('timestamp')) is not int:
            return {'status': 'invalid_input', 'candles': [], 'unverified_source_count': unknown}
        ts = b['timestamp']
        if ts < since or ts+300 > through:
            continue
        if (ts <= 0 or ts % 300 or any(not positive(b.get(k)) for k in ('open', 'high', 'low', 'close'))
                or not b['low'] <= min(b['open'], b['close']) <= max(b['open'], b['close']) <= b['high']):
            return {'status': 'invalid_input', 'candles': [], 'unverified_source_count': unknown}
        stamps.append(ts)
        # A known source is an observation label, not a guarantee of price accuracy.
        source = provenance.get(f'm5:{ts}')
        if source != 'Twelve Data':
            unknown += 1
            continue
        output.append({k: b[k] for k in ('timestamp', 'open', 'high', 'low', 'close')})
    if stamps != sorted(set(stamps)):
        return {'status': 'invalid_input', 'candles': [], 'unverified_source_count': unknown}
    return {'status': 'saved_reference' if output else 'no_verified_future_bars',
            'provider': 'Twelve Data', 'unverified_source_count': unknown, 'candles': output}


def build_followup(previous, snapshot, source, *, input_identity=None):
    """Archive all32 now and describe prior candidates through this saved observation clock."""
    if validate_strategy_snapshot(snapshot):
        raise ValueError('followup requires canonical saved32')
    clock = snapshot['evaluated_at']
    last = previous['history'][-1] if previous['history'] else None
    payload = restore_generation(last) if last else None
    since = payload['evaluated_at'] if payload else clock
    prior_records = canonical_records(payload) if payload else None
    bars = {pair: observed_bars(snapshot.get('pairs', {}).get(pair, {}), since, clock) for pair in PAIR_KEYS}
    observations = []
    for record in prior_records or []:
        if record['assessment'] != 'review':
            continue
        feed = bars[record['pair']]
        observation = observe(record, feed['candles'], clock)
        observation['followup_data_status'] = feed['status']
        observation['unverified_source_count'] = feed['unverified_source_count']
        observations.append(observation)
    return {'schema': 'candidate_followup_save_v1', 'evaluated_at': clock,
        'source': deepcopy(source), 'input_identity': deepcopy(input_identity),
        'replay_status': 'code_and_input_identity_recorded_not_full_strategy_backtest',
        'advisory_only': True, 'trade_performance': 'not_measured',
        'saved_evaluation': pack_generation(snapshot['scheduled_outlook']['rows'], evaluated_at=clock),
        'previous_saved_evaluation': deepcopy(last),
        'previous_source': deepcopy(previous['provenance'].get(str(since))) if payload else None,
        'previous_status': 'canonical32' if prior_records else 'legacy_or_absent_not_reinterpreted',
        'observation_window': {'after_publication': since, 'through_saved_evaluation': clock,
            'clock_basis': 'saved_evaluation_not_notification_delivery',
            'publication_time_verified': False,
            'is_scenario_expiry': False, 'equal_horizon_comparison': False},
        'm5_observations': bars, 'candidate_observations': observations,
        'formation_or_fill_defined': False, 'win_rate': None, 'profit': None}
