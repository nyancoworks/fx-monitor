"""Offline review of frozen private scenarios; no collection or trading results.

Callers pin private inputs before calling. Returned content belongs in private
research storage, never a public workflow log. Nothing is written or mutated.
"""
from collections import Counter
from copy import deepcopy
import re

from .monitoring_result_history import restore_generation
from .candidate_followup_archive import canonical_records
from fx_system.candidate_followup import observe, positive
from fx_system.report_plan_comparison import saved_plan_comparison
from fx_system.strategy_report import report_records
from fx_system.strategy_report_export import restore_strategy_report_export


def _identity(record):
    return record['pair'], record['strategy']


def review_saved_followup(bundle, source, snapshot_blob_sha, followup):
    """Recheck all reviews before selecting observed-condition case studies.

    A level touch is an OHLC observation, not a fill or close-based withdrawal.
    Counts expose coverage and missing levels; they are not success rates.
    Different windows are never pooled into a return or excursion average.
    """
    view = restore_strategy_report_export(bundle, source, snapshot_blob_sha)
    records = view['scheduled_outlook']['strategy_assessments']
    prior_source = {k: source[k] for k in ('source_repository', 'source_commit', 'run_id')}
    try:
        through = followup['evaluated_at']
        window = followup['observation_window']
        next_source = followup['source']
        if (followup['schema'] != 'candidate_followup_save_v1'
                or followup['previous_source'] != prior_source
                or followup['previous_status'] != 'canonical32'
                or next_source.get('source_repository') != source['source_repository']
                or type(next_source.get('run_id')) is not int or next_source['run_id'] <= 0
                or not isinstance(next_source.get('source_commit'), str)
                or re.fullmatch('[0-9a-f]{40}', next_source['source_commit']) is None
                or type(through) is not int or through <= source['evaluated_at']
                or window['after_publication'] != source['evaluated_at']
                or window['through_saved_evaluation'] != through
                or window['clock_basis'] != 'saved_evaluation_not_notification_delivery'
                or window['is_scenario_expiry'] is not False
                or window['equal_horizon_comparison'] is not False
                or window['publication_time_verified'] is not False):
            raise ValueError
        previous = restore_generation(followup['previous_saved_evaluation'])
        previous_records = canonical_records(previous)
        if (previous_records is None or previous['evaluated_at'] != source['evaluated_at']
                or {_identity(r): r for r in previous_records} != {_identity(r): r for r in records}):
            raise ValueError
        current = restore_generation(followup['saved_evaluation'])
        current_records = canonical_records(current)
        if current['evaluated_at'] != through or current_records is None:
            raise ValueError
        next_by_identity = {_identity(r): r for r in current_records}
        saved_observations = followup['candidate_observations']
        by_identity = {_identity(r): r for r in saved_observations}
        reviews = [r for r in records if r['assessment'] == 'review']
        if (len(by_identity) != len(saved_observations)
                or set(by_identity) != {_identity(r) for r in reviews}):
            raise ValueError
        cases = []
        for record in reviews:
            feed = followup['m5_observations'][record['pair']]
            unknown = feed['unverified_source_count']
            if type(unknown) is not int or unknown < 0:
                raise ValueError
            observation = observe(record, feed['candles'], through)
            observation.update(followup_data_status=feed['status'], unverified_source_count=unknown)
            if observation != by_identity[_identity(record)]:
                raise ValueError
            complete = (feed['status'] == 'saved_reference' and feed.get('provider') == 'Twelve Data'
                        and unknown == 0 and observation['status'] == 'descriptive_observation_only'
                        and observation['missing_start'] is False and observation['missing_end'] is False
                        and not observation['internal_gaps'])
            since = source['evaluated_at']
            expected_seconds = max(0, through//300*300 - (since+299)//300*300)
            coverage = {
                'basis': 'whole_m5_intervals_after_saved_evaluation',
                'saved_evaluation_window_seconds': through-since,
                'expected_whole_m5_seconds': expected_seconds,
                'excluded_clock_boundary_seconds': through-since-expected_seconds,
                'observed_whole_m5_seconds': observation['observed_bar_count']*300
                    if observation['status'] == 'descriptive_observation_only' else None,
                'whole_m5_grid_complete': complete,
                'continuous_saved_evaluation_window': complete and expected_seconds == through-since,
                'notification_to_notification_coverage': 'unverified',
            }
            levels = record.get('reference_levels', {})
            next_record = next_by_identity[_identity(record)]
            cases.append({'pair': record['pair'], 'strategy': record['strategy'],
                'saved_grade': record['grade'], 'saved_direction': record['direction'],
                'condition_status_at_save': record.get('scenario_conditions', {}).get('status', 'unknown'),
                'market_phase_at_save': record.get('market_phase'),
                'scenario_type': record.get('scenario_type', 'trend'),
                'complete_saved_m5_window': complete,
                'saved_m5_coverage': coverage,
                'target_touch_observable': complete and positive(levels.get('structural_target')),
                'invalidation_touch_observable': complete and positive(levels.get('invalidation')),
                'next_saved_evaluation': {
                    'evaluated_at': through, 'assessment': next_record['assessment'],
                    'grade': next_record['grade'], 'direction': next_record['direction'],
                    'condition_status': next_record.get('scenario_conditions', {}).get('status', 'unknown'),
                    'expiry_status': next_record.get('expiry', {}).get('status'),
                    'observed_withdrawal': next_record.get('expiry', {}).get('observed_condition'),
                    'reference_levels': deepcopy(next_record.get('reference_levels', {})),
                    'scope': 'new_saved_evaluation_not_continuous_scenario_or_position'},
                'observation': observation})
    except (KeyError, TypeError, AttributeError, ValueError):
        raise ValueError('saved followup does not match frozen scenarios and observations') from None

    outlook = view['scheduled_outlook']
    shown = {_identity(r) for r in report_records(
        outlook, selection_version=bundle.get('selection_version', 1))}
    groups = { _identity(r): saved_plan_comparison(r)[0] for r in reviews }
    selection = []
    for record in reviews:
        key = _identity(record)
        group, ratio, note = saved_plan_comparison(record)
        peers = [other for other, other_group in groups.items() if group is not None and other_group == group]
        selection.append({'pair': key[0], 'strategy': key[1], 'default_displayed': key in shown,
            'comparable_peers': [{'pair': p, 'strategy': s} for p, s in peers if (p, s) != key],
            'headroom_ratio': ratio, 'comparison_note': note,
            'ordering_basis': ('matching_context_headroom' if len(peers) > 1 else
                               'saved_order_no_matching_peer' if group is not None else
                               'saved_order_comparison_unavailable')})
    return {'schema': 'saved_scenario_quality_review_v1', 'source': deepcopy(source),
        'snapshot_git_blob_sha': snapshot_blob_sha,
        'followup_source': deepcopy(followup.get('source')),
        'window': deepcopy(window), 'private_research_only': True,
        'interpretation': 'saved_scenario_and_candle_observations_not_trade_performance',
        'selection_scope': 'saved_default_only_not_task_selection_or_optimality',
        'canonical_count': len(records), 'review_count': len(cases),
        'condition_status_counts': dict(Counter(c['condition_status_at_save'] for c in cases)),
        'complete_saved_window_count': sum(c['complete_saved_m5_window'] for c in cases),
        'continuous_saved_evaluation_window_count': sum(
            c['saved_m5_coverage']['continuous_saved_evaluation_window'] for c in cases),
        'target_touch_observable_count': sum(c['target_touch_observable'] for c in cases),
        'invalidation_touch_observable_count': sum(c['invalidation_touch_observable'] for c in cases),
        'cases': cases, 'selection_review': selection,
        'limitations': ['No verified notification publication clock or execution price.',
            'Complete whole-M5 grids can exclude partial intervals at saved evaluation boundaries.',
            'Wick touches do not prove scenario formation, withdrawal, fills or profit.',
            'No pooled unequal-horizon returns, win rates or hindsight ranking changes.',
            'Input identity and agreement are not independent market-source verification.']}
