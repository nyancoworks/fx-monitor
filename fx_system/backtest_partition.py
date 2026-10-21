"""Validated monthly partition codec, promoted from the existing offline archive.

No collection, publication or deletion. UTC partitions preserve explicit source
and capture clocks. NY17 metadata requires explicit validated session clocks.
"""
from __future__ import annotations
import gzip
import hashlib
import json
import math
from pathlib import Path
import re
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

SCHEMA = 'fx_backtest_partition_v1'
TIMEFRAMES = {'m5': 300, 'h1': 3600, 'd1': 86400}
SAFE_NAME = re.compile(r'^[A-Za-z0-9_-]{1,40}$')

def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')

def sha256(data):
    return hashlib.sha256(data).hexdigest()

def validate_bar(row, tf, now):
    if not isinstance(row, dict):
        raise ValueError('bar must be object')
    timestamp = row.get('timestamp')
    if type(timestamp) is not int or timestamp < 0:
        raise ValueError('invalid timestamp')
    end = timestamp + TIMEFRAMES[tf]
    if tf == 'd1' and row.get('session_policy') == 'NY17_verified':
        start, end = row.get('session_start_utc'), row.get('session_end_utc')
        if (type(start) is not int or type(end) is not int or start < 0 or end <= start):
            raise ValueError('explicit NY17 session clocks required')
        ny = ZoneInfo('America/New_York')
        opening = datetime.fromtimestamp(start, ny)
        closing = datetime.fromtimestamp(end, ny)
        if (opening.hour, opening.minute, opening.second) != (17, 0, 0) or (closing.hour, closing.minute, closing.second) != (17, 0, 0) or closing.date() != opening.date() + timedelta(days=1):
            raise ValueError('invalid NY17 daily boundary')
        role = row.get('timestamp_role')
        expected = start if role == 'session_start' else end - 86400 if role == 'end_minus_86400' else None
        if timestamp != expected:
            raise ValueError('NY17 timestamp role mismatch')
    elif timestamp % TIMEFRAMES[tf]:
        raise ValueError('unaligned timestamp')
    if end > now:
        raise ValueError('forming or future candle')
    vals = [row.get(k) for k in ('open', 'high', 'low', 'close')]
    if any(type(x) not in (int, float) or not math.isfinite(x) or x <= 0 for x in vals):
        raise ValueError('invalid OHLC')
    o, h, l, c = vals
    if h < max(o, c, l) or l > min(o, c, h):
        raise ValueError('OHLC invariant violated')
    if not isinstance(row.get('source'), str) or not row['source'].strip():
        raise ValueError('source provenance missing')
    if type(row.get('captured_at')) is not int or not end <= row['captured_at'] <= now:
        raise ValueError('capture provenance missing')
    if tf == 'd1' and row.get('session_policy') not in ('provider_UTC', 'NY17_verified'):
        raise ValueError('D1 calendar must be explicit')
    return row

def partition_key(provider, pair, tf, month):
    if not SAFE_NAME.fullmatch(provider) or not SAFE_NAME.fullmatch(pair):
        raise ValueError('unsafe provider or pair')
    if tf not in TIMEFRAMES or not re.fullmatch(r'\d{4}-(0[1-9]|1[0-2])', month):
        raise ValueError('invalid timeframe/month')
    return Path(provider) / pair / tf / month

def month_for(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime('%Y-%m')

def pack(provider, pair, tf, month, rows, now):
    partition_key(provider, pair, tf, month)
    if type(now) is not int:
        raise ValueError('invalid evaluation clock')
    seen = {}
    for original in rows:
        row = dict(validate_bar(original, tf, now))
        if month_for(row['timestamp']) != month:
            raise ValueError('wrong monthly partition')
        old = seen.get(row['timestamp'])
        if old is not None and old != row:
            raise ValueError('conflicting revisions require explicit review')
        seen[row['timestamp']] = row
    ordered = [seen[ts] for ts in sorted(seen)]
    payload = {'schema': SCHEMA, 'provider': provider, 'pair': pair, 'timeframe': tf,
               'month': month, 'bars': ordered}
    plain = canonical(payload)
    compressed = gzip.compress(plain, compresslevel=6, mtime=0)
    return compressed, {'sha256': sha256(compressed), 'plain_sha256': sha256(plain),
                        'count': len(ordered), 'uncompressed_bytes': len(plain),
                        'compressed_bytes': len(compressed)}

def unpack(compressed, expected_digest, *, provider, pair, tf, month, now):
    if sha256(compressed) != expected_digest:
        raise ValueError('archive digest mismatch')
    import zlib
    limit = 32 * 1024 * 1024
    decoder = zlib.decompressobj(wbits=31)
    plain = decoder.decompress(compressed, limit + 1)
    if len(plain) > limit or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
        raise ValueError('invalid or oversized compressed partition')
    obj = json.loads(plain)
    if (obj.get('schema'), obj.get('provider'), obj.get('pair'), obj.get('timeframe'), obj.get('month')) != (SCHEMA, provider, pair, tf, month):
        raise ValueError('partition identity mismatch')
    rows = obj.get('bars')
    if not isinstance(rows, list):
        raise ValueError('invalid bars array')
    if [r['timestamp'] for r in rows] != sorted({r['timestamp'] for r in rows}):
        raise ValueError('out of order or duplicated')
    for row in rows:
        validate_bar(row, tf, now)
        if month_for(row['timestamp']) != month:
            raise ValueError('cross-month row')
    if canonical(obj) != plain:
        raise ValueError('noncanonical partition')
    return rows
