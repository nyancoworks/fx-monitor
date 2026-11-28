"""Indicator-only NY17 continuity; never changes retained or formal inputs.

Recursive calculations restart after the latest missing session. Finite windows
can use the same suffix when it contains their complete lookback. This does not
infer holidays, attest source quality, or authorize a trade.
"""
from .core import ny17_frames
from .indicator_calendar import NY17, ny17_sequence_valid

MACRO_TARGETS = {'d1': 250, 'w1': 200}


def contiguous_indicator_frames(frames, quality, *, ny_study=None):
    result = dict(frames)
    diagnostics = {}
    timeframes = quality.get('timeframes', {})
    for tf in ('d1', 'w1'):
        rows = frames.get(tf, [])
        evidence = timeframes.get(tf, {})
        retained = rows
        if ny_study and evidence.get('ok') is True and evidence.get('calendar') == NY17:
            try:
                candidates = ny17_frames({key: ny_study.get('indicator_' + tf, []) if key == tf else []
                                          for key in MACRO_TARGETS}, quality['evaluated_at'])[tf]
            except (ValueError, TypeError, KeyError, OverflowError):
                candidates = []
            if candidates and retained and candidates[-1] == retained[-1]:
                original = {row['timestamp']: row for row in retained}
                if all(original.get(row['timestamp'], row) == row for row in candidates):
                    rows = candidates
        diagnostic = {'retained_count': len(retained), 'archive_candidates': len(rows),
                      'target_count': MACRO_TARGETS[tf], 'calendar': evidence.get('calendar'),
                      'source_quality_ok': evidence.get('ok') is True,
                      'source_attested_by_this_check': False, 'entry_permission': False}
        if evidence.get('calendar') != NY17:
            diagnostics[tf] = {**diagnostic, 'status': 'calendar_unverified',
                               'input_count': len(rows), 'prefix_excluded': 0}
            continue
        if not rows or not ny17_sequence_valid(rows[-1:], tf):
            selected = []
            status = 'empty' if not rows else 'invalid_latest_session'
        else:
            first = len(rows) - 1
            lower = max(0, len(rows) - MACRO_TARGETS[tf])
            while first > lower and ny17_sequence_valid(rows[first-1:first+1], tf):
                first -= 1
            selected = rows[first:]
            status = 'contiguous' if first == 0 else 'latest_contiguous_segment'
        result[tf] = selected
        diagnostics[tf] = {**diagnostic, 'status': status, 'input_count': len(selected),
                           'prefix_excluded': len(rows)-len(selected),
                           'first_input_timestamp': selected[0]['timestamp'] if selected else None,
                           'last_input_timestamp': selected[-1]['timestamp'] if selected else None,
                           'recursive_seed_policy': 'restart_with_existing_sma_seed_in_contiguous_segment'}
    return result, diagnostics
