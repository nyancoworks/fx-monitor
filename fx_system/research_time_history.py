"""Export a bounded research copy of already archived NY-close candles privately.

The archive is restored by the existing scheduled workflow. No provider call is
made here; the copy is never an entry signal or a provider-native D1/W1 feed.
"""
import datetime as dt
import hashlib
import json
from pathlib import Path

from diagnostics.issue43_ny_runtime import MAX_CHECKPOINT_BYTES, validate_checkpoint
from diagnostics.issue43_ny_shadow import build_shadow
from .core import ny17_frames
from .monitor_pairs import PAIR_KEYS

MAX_WEEKDAYS = 260
MAX_EXPORT_BYTES = 1_500_000


def build(checkpoint_path, clock):
    path = Path(checkpoint_path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_CHECKPOINT_BYTES:
        raise ValueError('private archive unavailable')
    raw = path.read_bytes()
    checkpoint = json.loads(raw)
    validate_checkpoint(checkpoint)
    as_of = dt.datetime.fromtimestamp(clock, dt.timezone.utc)
    received = {}
    for event in checkpoint['archive']['events']:
        received.setdefault(event['pair'], []).append(event['received_as_of_utc'])
    pairs = {}
    for pair in PAIR_KEYS:
        rows = list(checkpoint['archive']['pairs'].get(pair, {}).values())
        study = build_shadow(rows, as_of, minimum=MAX_WEEKDAYS)
        frames = ny17_frames(study, clock)
        pairs[pair] = {
            'h1_archived': len(rows),
            'first_h1_timestamp': min((r['timestamp'] for r in rows), default=None),
            'first_received_at_utc': min(received.get(pair, []), default=None),
            'missing_or_invalid_ny_days': len(study['errors']),
            'd1': frames['d1'], 'w1': frames['w1'],
        }
    result = {'schema': 'private_time_history_v1', 'scope': 'historical_research_not_entry',
              'as_of': clock, 'archive_generation': checkpoint['generation'],
              'checkpoint_sha256': hashlib.sha256(raw).hexdigest(), 'pairs': pairs,
              'timeframe_limit_weekdays': MAX_WEEKDAYS,
              'provider_native_daily_verified': False}
    if len(json.dumps(result, ensure_ascii=False, allow_nan=False).encode()) > MAX_EXPORT_BYTES:
        raise ValueError('private research export exceeds bounded size')
    return result
