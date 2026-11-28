"""Immutable, compressed Twelve Data UTC H1 segments for NY17 analysis."""
import datetime as dt
import gzip
import hashlib
import json
import math
import re
import zlib

from diagnostics.issue43_ny_incremental import PAIRS
from diagnostics.issue43_ny_shadow import build_shadow

MAX_SEGMENT_BYTES = 2 * 1024 * 1024
WEEKDAY_WINDOW = 1005
FIELDS = ('timestamp', 'open', 'high', 'low', 'close')
SOURCE = 'Twelve Data UTC H1'


def validate_rows(rows, year, received_at):
    if not isinstance(rows, list) or not 0 < len(rows) <= 8784:
        raise ValueError('invalid history segment length')
    start = int(dt.datetime(year, 1, 1, tzinfo=dt.timezone.utc).timestamp())
    end = int(dt.datetime(year + 1, 1, 1, tzinfo=dt.timezone.utc).timestamp())
    previous = start - 3600
    for row in rows:
        if not isinstance(row, dict) or set(row) != set(FIELDS):
            raise ValueError('invalid history row')
        stamp, o, h, l, c = (row[key] for key in FIELDS)
        if (type(stamp) is not int or stamp % 3600 or not previous < stamp < end
                or stamp + 3600 > received_at
                or not all(type(p) in (int, float) and math.isfinite(p) and p > 0
                           for p in (o, h, l, c))
                or not l <= min(o, c) <= max(o, c) <= h):
            raise ValueError('invalid history candle')
        previous = stamp


def encode_segment(pair, year, received_at, rows):
    if pair not in PAIRS or type(year) is not int or not 2000 <= year <= 2099:
        raise ValueError('invalid segment identity')
    if type(received_at) is not int:
        raise ValueError('invalid segment receipt')
    validate_rows(rows, year, received_at)
    payload = json.dumps(rows, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    sha = hashlib.sha256(payload).hexdigest()
    return {'year': year, 'received_at': received_at, 'sha256': sha, 'source': SOURCE}, gzip.compress(
        payload, mtime=0)


def read_segment(directory, pair, item, now):
    year, sha, received_at = (item[key] for key in ('year', 'sha256', 'received_at'))
    if (pair not in PAIRS or type(year) is not int or not 2000 <= year <= 2099
            or type(received_at) is not int or not 0 < received_at <= now
            or not isinstance(sha, str) or not re.fullmatch('[0-9a-f]{64}', sha)
            or item.get('source') != SOURCE):
        raise ValueError('invalid history receipt')
    path = directory / f'{pair}-{year}-{sha}.json.gz'
    if path.is_symlink() or path.stat().st_size > MAX_SEGMENT_BYTES:
        raise ValueError('unsafe history segment')
    decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
    raw = decoder.decompress(path.read_bytes(), MAX_SEGMENT_BYTES + 1)
    if (len(raw) > MAX_SEGMENT_BYTES or not decoder.eof or decoder.unused_data
            or hashlib.sha256(raw).hexdigest() != sha):
        raise ValueError('history segment digest or size mismatch')
    rows = json.loads(raw)
    validate_rows(rows, year, received_at)
    return rows


def extend_study(directory, pair, archived, study, clock):
    """Extend analysis only; require exact agreement on existing NY17 candles."""
    if directory.is_symlink():
        raise ValueError('unsafe history directory')
    path = directory / 'manifest.json'
    if path.is_symlink():
        raise ValueError('unsafe history manifest')
    if not path.exists():
        return study
    if path.stat().st_size > 65536:
        raise ValueError('history manifest too large')
    manifest = json.loads(path.read_bytes())
    if manifest.get('schema') != 1 or not isinstance(manifest.get('pairs'), dict):
        raise ValueError('invalid history manifest')
    entries = manifest['pairs'].get(pair, [])
    if not entries:
        return study
    if not isinstance(entries, list) or len(entries) > 16:
        raise ValueError('invalid history segment inventory')
    joined = dict(archived)
    for item in entries:
        for row in read_segment(directory, pair, item, int(clock.timestamp())):
            key = str(row['timestamp'])
            if joined.setdefault(key, row) != row:
                raise ValueError('history conflicts with retained observation')
    combined = build_shadow(joined.values(), clock, minimum=WEEKDAY_WINDOW)
    extended = dict(study)
    for tf, key, limit in (('d1', 'indicator_d1', 250), ('w1', 'indicator_w1', 200)):
        existing = study[tf][-limit:]
        candidate = combined[tf][-limit:]
        by_session = {row['trading_date_ny' if tf == 'd1' else 'week_start_ny']: row
                      for row in candidate}
        session = 'trading_date_ny' if tf == 'd1' else 'week_start_ny'
        if (existing and candidate and candidate[-1] == existing[-1]
                and all(by_session.get(row[session], row) == row for row in existing)):
            extended[key] = candidate
    return extended
