"""Indicator-only NY17 continuity; never changes retained or formal inputs.

Recursive calculations restart after the latest missing session. Finite windows
can use the same suffix when it contains their complete lookback. This does not
infer holidays, attest source quality, or authorize a trade.
"""
from .indicator_calendar import NY17, ny17_sequence_valid


def contiguous_indicator_frames(frames, quality):
    result = dict(frames)
    diagnostics = {}
    timeframes = quality.get('timeframes', {})
    for tf in ('d1', 'w1'):
        rows = frames.get(tf, [])
        evidence = timeframes.get(tf, {})
        diagnostic = {'retained_count': len(rows), 'calendar': evidence.get('calendar'),
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
            while first > 0 and ny17_sequence_valid(rows[first-1:first+1], tf):
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
