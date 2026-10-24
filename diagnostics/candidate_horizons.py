"""Read-only frozen candidate horizons. Returned observations are private research."""
from copy import deepcopy
import hashlib
import json
import re

from .candidate_followup_archive import observed_bars
from fx_system.candidate_followup import observe, positive
from fx_system.strategy_report_export import restore_strategy_report_export


def review_candidate_horizons(bundle, source, snapshot_blob_sha,
                              price_bundle, price_source, price_snapshot_blob_sha,
                              cache_bytes, cache_blob_sha, *, private_commit,
                              horizons=(3600, 14400, 28800, 86400)):
    """Caller pins price bundle and exact cache bytes to one immutable commit.

    Preserve every original review for every horizon, including unavailable ones.
    Cache identity is checked here; remote commit membership is caller evidence.
    """
    if (not isinstance(horizons, (list, tuple)) or not 1 <= len(horizons) <= 16
            or any(type(h) is not int or not 300 <= h <= 31*86400 or h % 300 for h in horizons)
            or len(set(horizons)) != len(horizons)):
        raise ValueError('invalid candidate horizons')
    view = restore_strategy_report_export(bundle, source, snapshot_blob_sha)
    restore_strategy_report_export(price_bundle, price_source, price_snapshot_blob_sha)
    through = price_source['evaluated_at']
    if (not isinstance(cache_bytes, bytes) or len(cache_bytes) > 4*1024*1024
            or not isinstance(private_commit, str) or re.fullmatch('[0-9a-f]{40}', private_commit) is None
            or price_source['source_repository'] != source['source_repository']
            or through <= source['evaluated_at']
            or hashlib.sha1(b'blob '+str(len(cache_bytes)).encode()+b'\0'+cache_bytes).hexdigest() != cache_blob_sha):
        raise ValueError('invalid saved cache identity or clock')
    try:
        cache = json.loads(cache_bytes)
        if not isinstance(cache, dict):
            raise ValueError
        cases = []
        for record in view['scheduled_outlook']['strategy_assessments']:
            if record['assessment'] != 'review':
                continue
            saved = cache.get(record['pair'], {})
            if not isinstance(saved, dict):
                raise ValueError
            for horizon in horizons:
                end = source['evaluated_at']+horizon
                case = {'pair': record['pair'], 'strategy': record['strategy'],
                        'saved_grade': record['grade'], 'saved_direction': record['direction'],
                        'condition_status_at_save': record.get('scenario_conditions', {}).get('status'),
                        'horizon_seconds': horizon, 'through': end,
                        'status': 'beyond_saved_cache_evaluation', 'observation': None,
                        'whole_m5_grid_complete': False, 'continuous_evaluation_window': False,
                        'target_touch_observable': False, 'invalidation_touch_observable': False}
                if end <= through:
                    feed = observed_bars({'decision_data': {'raw': {'m5': saved.get('m5', [])},
                        'provenance': saved.get('bar_provenance', {})}}, source['evaluated_at'], end)
                    observation = observe(record, feed['candles'], end)
                    complete = (feed['status'] == 'saved_reference' and feed['unverified_source_count'] == 0
                        and observation['status'] == 'descriptive_observation_only'
                        and not observation['missing_start'] and not observation['missing_end']
                        and not observation['internal_gaps'])
                    expected = end//300*300 - (source['evaluated_at']+299)//300*300
                    levels = record.get('reference_levels', {})
                    case.update(status='saved_cache_observation', observation=observation,
                        feed_status=feed['status'], unverified_source_count=feed['unverified_source_count'],
                        expected_whole_m5_seconds=expected, excluded_boundary_seconds=horizon-expected,
                        whole_m5_grid_complete=complete,
                        continuous_evaluation_window=complete and expected == horizon,
                        target_touch_observable=complete and positive(levels.get('structural_target')),
                        invalidation_touch_observable=complete and positive(levels.get('invalidation')))
                cases.append(case)
    except (ValueError, KeyError, TypeError, AttributeError, RecursionError):
        raise ValueError('invalid saved candidate cache') from None
    return {'schema': 'frozen_candidate_horizons_v1', 'private_research_only': True,
            'source': deepcopy(source), 'snapshot_git_blob_sha': snapshot_blob_sha,
            'price_source': deepcopy(price_source), 'price_snapshot_git_blob_sha': price_snapshot_blob_sha,
            'cache_git_blob_sha': cache_blob_sha, 'cache_private_commit': private_commit,
            'remote_commit_membership': 'caller_pinned_not_independently_verified',
            'cases': cases, 'summary': [{'horizon_seconds': h,
                'candidate_records': sum(c['horizon_seconds'] == h for c in cases),
                'complete_whole_m5_records': sum(c['horizon_seconds'] == h and c['whole_m5_grid_complete'] for c in cases),
                'beyond_saved_clock_records': sum(c['horizon_seconds'] == h and c['status'] == 'beyond_saved_cache_evaluation' for c in cases)} for h in horizons],
            'limitations': ['Frozen levels may cease to be valid after a later re-evaluation.',
                'Whole M5 grids exclude partial evaluation boundaries; no gap interpolation.',
                'Nested horizons and repeated candidates are not independent samples.',
                'No entry/fills, trading returns, win rates or strategy superiority measured.',
                'Saved source labels are not independent market-price verification.']}
