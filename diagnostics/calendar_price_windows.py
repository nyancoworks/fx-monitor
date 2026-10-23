"""Private offline price observations around saved scheduled event times.

No fetch, save, decision change, causal attribution or trading performance.
"""
from collections import Counter
from copy import deepcopy

from .scenario_quality_review import review_saved_followup
from fx_system.candidate_followup import positive
from fx_system.strategy_report_export import restore_strategy_report_export


def _measure(event, feed, since, through, seconds):
    when = event.get('scheduled_at_utc')
    if type(when) is not int:
        return {'status': 'unavailable', 'reason': 'scheduled_instant_unconfirmed'}
    if type(event.get('observed_at_utc')) is not int or not 0 < event['observed_at_utc'] <= since:
        return {'status': 'unavailable', 'reason': 'event_observation_clock_invalid'}
    if event.get('provider_status') in ('cancelled', 'estimated') or event.get('freshness') == 'stale':
        return {'status': 'unavailable', 'reason': 'cancelled_estimated_or_stale_event'}
    if event.get('time_role') not in (None, 'release'):
        return {'status': 'unavailable', 'reason': 'non_release_or_unknown_time_role'}
    if when % 300:
        return {'status': 'unavailable', 'reason': 'event_not_aligned_to_saved_m5_boundary'}
    if when+seconds > through:
        return {'status': 'unavailable', 'reason': 'horizon_not_yet_saved'}
    if (not isinstance(feed, dict) or feed.get('status') != 'saved_reference'
            or feed.get('provider') != 'Twelve Data'
            or type(feed.get('unverified_source_count')) is not int
            or feed['unverified_source_count'] != 0 or not isinstance(feed.get('candles'), list)):
        return {'status': 'unavailable', 'reason': 'saved_source_unverified_or_unavailable'}
    bars = feed['candles']
    stamps = []
    for bar in bars:
        if (not isinstance(bar, dict) or type(bar.get('timestamp')) is not int
                or bar['timestamp'] % 300 or bar['timestamp'] < since
                or bar['timestamp']+300 > through
                or any(not positive(bar.get(k)) for k in ('open', 'high', 'low', 'close'))
                or not bar['low'] <= min(bar['open'], bar['close'])
                    <= max(bar['open'], bar['close']) <= bar['high']):
            return {'status': 'unavailable', 'reason': 'saved_candles_invalid'}
        stamps.append(bar['timestamp'])
    if stamps != sorted(set(stamps)):
        return {'status': 'unavailable', 'reason': 'saved_candles_invalid'}
    by_time = {bar['timestamp']: bar for bar in bars}
    required = list(range(when-300, when+seconds, 300))
    if any(stamp not in by_time for stamp in required):
        return {'status': 'unavailable', 'reason': 'missing_baseline_endpoint_or_internal_bar'}
    before, after = by_time[when-300], by_time[when+seconds-300]
    after_bars = [by_time[t] for t in required[1:]]
    return {'status': 'saved_price_observation', 'baseline_closed_at': when,
            'endpoint_closed_at': when+seconds, 'baseline_close': before['close'],
            'endpoint_close': after['close'], 'pair_quote_change': after['close']-before['close'],
            'post_window_high': max(b['high'] for b in after_bars),
            'post_window_low': min(b['low'] for b in after_bars),
            'post_bar_count': len(after_bars)}


def review_calendar_price_windows(bundle, source, snapshot_blob_sha, followup,
                                 *, horizons=(300, 900, 3600)):
    """Observe all related events inside one pinned saved-followup window.

    Exact endpoints are required. These durations are observation windows only,
    not entry/exit horizons or a grading rule. Output belongs in private storage.
    """
    if (not isinstance(horizons, tuple) or not horizons or len(horizons) > 12
            or any(type(h) is not int or h <= 0 or h > 86400 or h % 300 for h in horizons)
            or len(set(horizons)) != len(horizons)):
        raise ValueError('invalid calendar observation horizons')
    # Reuse the established identity/history/observation verification, not just
    # a matching source label on an unrelated next generation.
    bound = review_saved_followup(bundle, source, snapshot_blob_sha, followup)
    view = restore_strategy_report_export(bundle, source, snapshot_blob_sha)
    since, through = source['evaluated_at'], followup['evaluated_at']
    events = {}; conflicts = set(); unidentified = 0
    for record in view['scheduled_outlook']['strategy_assessments']:
        context = record.get('economic_calendar_context', {})
        for event in context.get('events', []):
            if not isinstance(event, dict):
                continue
            event_id = event.get('id')
            if not isinstance(event_id, str) or not event_id:
                unidentified += 1
                continue
            if (event.get('reference_only') is not True
                    or event.get('currency') not in (record['pair'][:3], record['pair'][3:])):
                continue
            key = record['pair'], event_id
            if key in events and events[key] != event:
                conflicts.add(key)
            events[key] = event
    cases = []; outside = 0
    for (pair, event_id), event in sorted(events.items()):
        when = event.get('scheduled_at_utc')
        if type(when) is int and not since < when <= through:
            outside += 1
            continue
        for seconds in horizons:
            observation = ({'status': 'unavailable', 'reason': 'conflicting_saved_event_identity'}
                           if (pair, event_id) in conflicts else
                           _measure(event, followup.get('m5_observations', {}).get(pair), since, through, seconds))
            overlap = [other_id for (other_pair, other_id), other in events.items()
                       if other_pair == pair and other_id != event_id and type(when) is int
                       and type(other.get('scheduled_at_utc')) is int
                       and when-300 <= other['scheduled_at_utc'] <= when+seconds]
            unknown = sum(other_pair == pair and other_id != event_id
                          and type(other.get('scheduled_at_utc')) is not int
                          for (other_pair, other_id), other in events.items())
            cases.append({'pair': pair, 'event_id': event_id, 'currency': event['currency'],
                'scheduled_at_utc': when, 'horizon_seconds': seconds,
                'event_observed_at_utc': event.get('observed_at_utc'),
                'known_before_scheduled_time': (type(when) is int
                    and type(event.get('observed_at_utc')) is int
                    and 0 < event['observed_at_utc'] <= min(when, since)),
                'release_time_verified': False, 'causal_attribution': 'unassessed',
                'overlapping_scheduled_event_ids': sorted(overlap),
                'other_uncertain_time_event_count': unknown, 'observation': observation})
    return {'schema': 'saved_calendar_price_windows_v1', 'source': deepcopy(source),
            'snapshot_git_blob_sha': snapshot_blob_sha,
            'followup_source': deepcopy(bound['followup_source']),
            'through_saved_evaluation': through, 'horizons_seconds': list(horizons),
            'private_research_only': True, 'cases': cases,
            'measurable_window_count': sum(c['observation']['status'] == 'saved_price_observation' for c in cases),
            'unavailable_reason_counts': dict(Counter(c['observation']['reason'] for c in cases
                                                     if c['observation']['status'] == 'unavailable')),
            'outside_observation_window_event_count': outside,
            'unidentified_event_record_count': unidentified,
            'limitations': ['Scheduled times do not prove actual publication or causal market response.',
                'Pair quote changes are not event-currency strength, surprises, fills or returns.',
                'Missing bars, provider uncertainty and simultaneous events cannot be imputed away.',
                'No pooled unequal horizons, hindsight ranking, grade or direction changes.',
                'Saved identities and source labels are not independent market-source verification.']}
