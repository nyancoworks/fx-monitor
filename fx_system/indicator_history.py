"""Bounded indicator history, reusing existing verified observations only."""
from copy import deepcopy
import math
from .activate_time import MAX_BARS, observe_pair
from .mt4_calendar import aggregate_h4
from .span_special import observe

# Enough for 201 complete H4/M15 candles, with aggregation alignment margin.
# Request sizes and request planning remain unchanged.
RETAINED_BARS = {'h1': 840, 'm5': 660}
FIELDS = ('timestamp', 'open', 'high', 'low', 'close')


def extend_from_archive(frames, checkpoint, pair, context, quality, now):
    """Prepend only an adjacent, matching H1 prefix; never bridge a gap.

    This is an indicator-only view. Formal decision inputs, cache, immutable
    archive and readiness are untouched. The existing observed-source policy
    must have verified the archive and its receipts at this evaluation clock.
    """
    result = dict(frames)
    current = frames.get('h1', [])
    diagnostic = {'retained_h1': len(current), 'input_h1': len(current),
                  'added_h1': 0, 'status': 'archive_unverified'}
    if (not checkpoint or context.get('mode') != 'adopt'
            or context.get('evaluated_at') != now
            or context.get('source_contract_verified') is not True
            or (context.get('observed_availability') or {}).get('observed_available') is not True
            or pair in checkpoint.get('blocked_pairs', {})
            or quality.get('timeframes', {}).get('h1', {}).get('ok') is not True
            or not current):
        return result, diagnostic
    try:
        archived = checkpoint['archive']['pairs'][pair]
        # Compare overlapping observations exactly; never revise a retained bar.
        overlap = False
        for bar in current:
            old = archived.get(str(bar['timestamp']))
            if old is not None:
                overlap = True
                if any(old.get(k) != bar.get(k) for k in FIELDS):
                    diagnostic['status'] = 'archive_overlap_conflict'
                    return result, diagnostic
        if not overlap:
            diagnostic['status'] = 'archive_overlap_missing'
            return result, diagnostic
        prefix = []
        stamp = current[0]['timestamp'] - 3600
        while len(prefix) + len(current) < RETAINED_BARS['h1']:
            old = archived.get(str(stamp))
            if old is None:
                break
            if (type(old.get('timestamp')) is not int or old['timestamp'] != stamp
                    or stamp % 3600 or stamp + 3600 > now
                    or any(type(old.get(k)) not in (int, float) or
                           not math.isfinite(old[k]) or old[k] <= 0 for k in FIELDS[1:])
                    or not old['low'] <= min(old['open'], old['close']) <=
                           max(old['open'], old['close']) <= old['high']):
                diagnostic['status'] = 'archive_invalid_bar'
                return result, diagnostic
            prefix.append({k: old[k] for k in FIELDS})
            stamp -= 3600
        result['h1'] = list(reversed(prefix)) + deepcopy(current)
        result['h4'] = aggregate_h4(result['h1'])
        diagnostic.update(status='archive_prefix_reused' if prefix else 'no_adjacent_prefix',
                          added_h1=len(prefix), input_h1=len(result['h1']))
    except (KeyError, TypeError, ValueError, AttributeError):
        return dict(frames), {**diagnostic, 'status': 'archive_invalid'}
    return result, diagnostic


def indicator_health(frames, quality=None):
    """Counts and availability only; missing auxiliaries never veto a scenario."""
    result = {}
    for tf in ('w1', 'd1', 'h4', 'm15', 'h1', 'm5'):
        if tf not in frames:
            continue
        value = frames[tf]
        count = len(value.get('bars', []))
        if value.get('calculation_version') == 4:
            bars = value.get('bars', [])
            verified = value.get('verified') is True
            span = observe(bars, tf) if verified else {}
            macd = value.get('macd', {}).get('observations', [])[-2:]
            rci = value.get('rci', {})
            evidence = (quality or {}).get('timeframes', {}).get(tf, {})
            result[tf] = {'input_count': count, 'verified': verified,
                          'fresh': evidence.get('fresh') is True,
                          'sb_available': verified and value.get('super_bollinger', {}).get('status') == 'calculated',
                          'span_available': span.get('status') == 'available',
                          'span_lag_zone_available': span.get('last', {}).get('lag_zone') in ('above', 'inside', 'below'),
                          'macd_available': verified and len(macd) == 2 and all(
                              point.get('histogram') is not None for point in macd),
                          **{f'rci{period}_available': verified and rci.get(str(period), {}).get('value') is not None
                             for period in (9, 26, 52)}}
            if tf in MAX_BARS:
                observed = observe_pair({tf: value}, value['evaluated_at'])['timeframes'][tf]
                result[tf]['time_input_count'] = len(observed['source']['bars'])
                result[tf]['time_available'] = observed['observation'].get('status') == 'observed'
            continue
        sma = value.get('sma', {}).get('200', {})
        result[tf] = {'input_count': count, 'sma200_required': 200,
                      'slope_required': 201, 'shortfall': max(0, 201-count),
                      'sma200_available': sma.get('value') is not None,
                      'slope_available': sma.get('previous') is not None,
                      'verified': value.get('verified') is True}
    return result
