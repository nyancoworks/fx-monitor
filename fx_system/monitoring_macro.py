"""Observed-H1 NY17 monitoring references, isolated from formal data quality.

Partial sessions retain real observations and disclose every absent hour. They
are not repaired/verified candles and never replace the canonical NY17 archive.
"""
from datetime import datetime, time, timedelta, timezone
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path
import zipfile
from zoneinfo import ZoneInfo
from .indicator_calendar import NY17
from .indicator_research import research_snapshot, super_bollinger_context
from .dinapoli_research import dma_snapshot
from .core import technical

UTC = timezone.utc
NY = ZoneInfo('America/New_York')
BUNDLE_SHA256 = 'e66dced2f2628047e9662a929378414d2f829e03b98612070f6023d76961c9fa'
BUNDLE = Path(__file__).resolve().parents[1]/'evidence/w1-monitoring-reference/captured-h1.zip'
PAIR_KEYS = ('USDJPY EURUSD GBPUSD AUDUSD NZDUSD USDCAD USDCHF EURJPY GBPJPY '
             'AUDJPY NZDJPY CADJPY CHFJPY EURGBP EURAUD AUDNZD').split()
FIELDS = ('open', 'high', 'low', 'close')


def clean_bar(row):
    t = row.get('timestamp')
    if type(t) is not int or t % 3600:
        raise ValueError('invalid_hourly_start')
    values = [row.get(k) for k in FIELDS]
    if not all(type(v) in (float, int) and math.isfinite(v) and v > 0 for v in values):
        raise ValueError('invalid_hourly_price')
    o, h, l, c = values
    if not l <= min(o, c) <= max(o, c) <= h:
        raise ValueError('invalid_hourly_geometry')
    return {'timestamp': t, **dict(zip(FIELDS, values))}


@lru_cache(maxsize=1)
def captured_history():
    raw = BUNDLE.read_bytes()
    if hashlib.sha256(raw).hexdigest() != BUNDLE_SHA256:
        raise ValueError('reference_bundle_identity_mismatch')
    result = {}
    with zipfile.ZipFile(BUNDLE) as bundle:
        for pair in PAIR_KEYS:
            body = bundle.read(pair+'/response.json')
            receipt = json.loads(bundle.read(pair+'/receipt.json'))
            digest = hashlib.sha256(body).hexdigest()
            if (digest != receipt['response_sha256'] or
                    digest != bundle.read(pair+'/response.sha256').decode().strip() or
                    receipt['pair'] != pair or receipt['interval'] != '1h' or
                    receipt['timezone'] != 'UTC' or receipt['http_status'] != 200):
                raise ValueError('reference_receipt_mismatch')
            payload = json.loads(body)
            if payload['meta']['symbol'].replace('/', '') != pair or payload['meta']['interval'] != '1h':
                raise ValueError('reference_response_identity_mismatch')
            rows = {}
            for item in payload['values']:
                date = datetime.fromisoformat(item['datetime'])
                if date.tzinfo is None:
                    date = date.replace(tzinfo=UTC)
                if date.utcoffset() != timedelta(0):
                    raise ValueError('reference_timezone_mismatch')
                bar = clean_bar({'timestamp': int(date.timestamp()), **{k: float(item[k]) for k in FIELDS}})
                t = bar['timestamp']
                if (t in rows or not receipt['start'] <= t < receipt['end_exclusive'] or
                        t+3600 > receipt['received_at']):
                    raise ValueError('reference_response_clock_invalid')
                rows[t] = bar
            result[pair] = {'rows': rows, 'received_at': receipt['received_at'], 'response_sha256': digest}
    return result


def merge_observations(current, extra, now):
    """No write-through, price revisions, future bars, or inferred observations."""
    result = {}
    for row in [*current, *extra]:
        bar = clean_bar(row)
        t = bar['timestamp']
        if t+3600 > now:
            continue
        if t in result and result[t] != bar:
            raise ValueError('reference_overlap_conflict')
        result[t] = bar
    return result


def day_end(day):
    return int(datetime.combine(day, time(17), NY).timestamp())


def latest_day(now):
    local = datetime.fromtimestamp(now, NY)
    day = local.date() if local.time() >= time(17) else local.date()-timedelta(days=1)
    while day.weekday() > 4:
        day -= timedelta(days=1)
    return day


def observed_day(rows, day, now):
    end = day_end(day)
    start = end-86400
    if end > now:
        return None
    picked = [rows[t] for t in range(start, end, 3600) if t in rows]
    if not picked:
        return None
    missing = [t for t in range(start, end, 3600) if t not in rows]
    return {'timestamp': start, 'session_end_utc': end,
            'open': picked[0]['open'], 'high': max(r['high'] for r in picked),
            'low': min(r['low'] for r in picked), 'close': picked[-1]['close'],
            'observed_h1': len(picked), 'expected_nominal_h1': 24,
            'missing_h1_timestamps': missing, 'complete': not missing,
            'reference_only': True, 'closure_verified': False}


def reference_frames(rows, now):
    """60 nominal D1 slots and 53 closed W1 slots; empty slots stay absent."""
    last = latest_day(now)
    dates = []
    day = last
    while len(dates) < 60:
        if day.weekday() < 5:
            dates.append(day)
        day -= timedelta(days=1)
    d1 = [bar for day in reversed(dates) if (bar := observed_day(rows, day, now))]
    friday = last-timedelta(days=(last.weekday()-4) % 7)
    w1 = []
    for i in range(52, -1, -1):
        close_day = friday-timedelta(weeks=i)
        monday = close_day-timedelta(days=4)
        items = [bar for d in range(5) if (bar := observed_day(rows, monday+timedelta(days=d), now))]
        if not items:
            continue
        missing = [t for d in range(5) for t in range(day_end(monday+timedelta(days=d))-86400,
                                                     day_end(monday+timedelta(days=d)), 3600) if t not in rows]
        w1.append({'timestamp': day_end(monday)-86400, 'session_end_utc': day_end(close_day),
                   'open': items[0]['open'], 'high': max(r['high'] for r in items),
                   'low': min(r['low'] for r in items), 'close': items[-1]['close'],
                   'observed_h1': sum(r['observed_h1'] for r in items),
                   'expected_nominal_h1': 120, 'observed_d1': len(items),
                   'missing_h1_timestamps': missing, 'complete': not missing,
                   'reference_only': True, 'closure_verified': False})
    return {'d1': d1, 'w1': w1}


def summary(frames, now):
    out = {}
    for tf, candles in frames.items():
        missing = sum(len(r['missing_h1_timestamps']) for r in candles)
        observed = sum(r['observed_h1'] for r in candles)
        expected = 60 if tf == 'd1' else 53
        out[tf] = {'status': 'observed_reference' if candles else 'unavailable',
                   'calendar': NY17, 'candles': candles, 'available_candles': len(candles),
                   'target_calendar_slots': expected, 'absent_calendar_slots': expected-len(candles),
                   'partial_candles': sum(not r['complete'] for r in candles),
                   'observed_h1': observed, 'missing_h1': expected*(24 if tf == 'd1' else 120)-observed,
                   'coverage_of_nominal_slots': observed/(expected*(24 if tf == 'd1' else 120)),
                   'last_session_end_utc': candles[-1]['session_end_utc'] if candles else None,
                   'technical': technical(candles),
                   'super_bollinger': super_bollinger_context(candles, timeframe=tf, calendar=NY17),
                   'indicator_research': research_snapshot(candles), 'dinapoli_dma': dma_snapshot(candles),
                   'reference_only': True, 'closure_verified': False}
        # Every computed value inherits the partial-observation basis.
        for name in ('technical', 'super_bollinger', 'indicator_research', 'dinapoli_dma'):
            out[tf][name].update(reference_only=True, input_basis='observed_h1_reference',
                                 partial_candles=out[tf]['partial_candles'],
                                 missing_h1=out[tf]['missing_h1'])
    return {'schema': 'monitoring_macro_reference_v1', 'status': 'available',
            'evaluated_at': now, 'timeframes': out, 'reference_only': True,
            'input_quality_unchanged': False, 'archive_adopted': False}


def unavailable(reason, now):
    return {'schema': 'monitoring_macro_reference_v1', 'status': 'unavailable',
            'reason': reason, 'evaluated_at': now, 'reference_only': True,
            'input_quality_unchanged': False, 'archive_adopted': False}


def _build_reference(checkpoint, pair, now, context):
    """Caller supplies archive already checked by NYIntegration at this clock."""
    if (context.get('evaluated_at') != now or not context.get('source_contract_verified') or
            context.get('observed_availability', {}).get('observed_available') is not True):
        return unavailable('source_or_receipt_unverified', now)
    if pair in checkpoint.get('blocked_pairs', {}):
        return unavailable('incoming_source_rejected', now)
    try:
        extra = None
        extra_status = 'unavailable'
        try:
            extra = captured_history()[pair]
            extra_status = 'included' if extra['received_at'] <= now else 'not_yet_received'
        except (ValueError, KeyError, TypeError, OSError, zipfile.BadZipFile):
            pass
        use_extra = extra_status == 'included'
        current = list(checkpoint['archive']['pairs'][pair].values())
        rows = merge_observations(current, [], now)
        if use_extra:
            try:
                rows = merge_observations(current, extra['rows'].values(), now)
            except ValueError:
                # Keep the trusted current archive usable; do not adopt a
                # conflicting historical price or disable the other pairs.
                use_extra = False
                extra_status = 'conflicting_capture_excluded'
        out = summary(reference_frames(rows, now), now)
        out['source_verified_for_reference'] = True
        out['source'] = {'provider': 'Twelve Data', 'requested_timezone': 'UTC',
                         'captured_history_included': use_extra,
                         'captured_history_status': extra_status,
                         'capture_received_at': extra['received_at'] if use_extra else None,
                         'capture_response_sha256': extra['response_sha256'] if use_extra else None,
                         'latest_observed_h1_timestamp': max(rows) if rows else None,
                         'mixed_provider': False}
        return out
    except (ValueError, KeyError, TypeError, OSError, zipfile.BadZipFile):
        return unavailable('reference_evidence_invalid', now)


def build_reference(checkpoint, pair, now, context):
    """Auxiliary reference failures must never stop acquisition/publication."""
    try:
        return _build_reference(checkpoint, pair, now, context)
    except Exception:
        return unavailable('reference_calculation_failed', now)
