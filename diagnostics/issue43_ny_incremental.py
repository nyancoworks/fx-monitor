"""Offline, immutable-source NY17 archive. Never used by production decisions."""
import copy
import datetime as dt
import hashlib
import json
import math
import os
import tempfile
from pathlib import Path
from .issue43_ny_shadow import build_shadow, close_utc, latest_closed_date, UTC

from fx_system.monitor_pairs import PAIR_KEYS as PAIRS


def packed(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(packed(value)).hexdigest()


def empty_archive():
    return {'schema': 'issue43_ny17_incremental_v1', 'pairs': {}, 'events': [],
            'formal_decision_permission': False, 'entry_permission': False}


def aware(as_of):
    if not isinstance(as_of, dt.datetime) or as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError('aware evaluation clock required')
    return int(as_of.timestamp())


def ingest(state, pair, rows, *, as_of, source_digest, provider='Twelve Data',
           timezone='UTC', accept_revisions=False):
    """Copy-on-write transaction; failed batches leave caller state untouched.

    source_digest identifies an immutable retained response, never a price fix.
    Revisions need explicit caller acceptance and retain both versions in events.
    """
    now = aware(as_of)
    if pair not in PAIRS or provider != 'Twelve Data' or timezone != 'UTC':
        raise ValueError('unverified pair/provider/timezone contract')
    if (type(source_digest) is not str or len(source_digest) != 64 or
            any(c not in '0123456789abcdef' for c in source_digest)):
        raise ValueError('source SHA256 required')
    if type(accept_revisions) is not bool:
        raise ValueError('explicit revision decision required')
    validate_state(state)
    incoming = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError('invalid H1')
        t = row.get('timestamp')
        v = [row.get(k) for k in ('open','high','low','close')]
        if (type(t) is not int or t % 3600 or t + 3600 > now or
                not all(type(x) in (float,int) and math.isfinite(x) and x > 0 for x in v) or
                v[2] > min(v[0],v[3]) or v[1] < max(v[0],v[3])):
            raise ValueError('invalid or forming H1')
        clean = dict(timestamp=t, open=v[0], high=v[1], low=v[2], close=v[3])
        key = str(t)
        if key in incoming and incoming[key] != clean:
            raise ValueError('conflicting duplicate in source batch')
        incoming[key] = clean
    result = copy.deepcopy(state)
    current = result['pairs'].setdefault(pair, {})
    changes = []
    for key, row in sorted(incoming.items(), key=lambda kv:int(kv[0])):
        old = current.get(key)
        if old == row:
            continue
        if old is not None and not accept_revisions:
            raise ValueError('source revision requires explicit acceptance')
        changes.append({'timestamp': int(key), 'old': old, 'new': row})
        current[key] = row
    if changes:
        result['events'].append({'pair':pair, 'source_sha256':source_digest,
            'received_as_of_utc':as_of.astimezone(UTC).isoformat(),
            'revisions_explicitly_accepted':accept_revisions, 'changes':copy.deepcopy(changes)})
    return result


def validate_state(state):
    if (not isinstance(state,dict) or state.get('schema') != 'issue43_ny17_incremental_v1'
            or state.get('entry_permission') is not False
            or state.get('formal_decision_permission') is not False
            or not isinstance(state.get('pairs'),dict) or not isinstance(state.get('events'),list)):
        raise ValueError('invalid archive contract')
    # Replay history proves current materialization has not been silently edited.
    replay = {}
    for event in state['events']:
        if event.get('pair') not in PAIRS:
            raise ValueError('invalid event pair')
        rows = replay.setdefault(event['pair'], {})
        for change in event['changes']:
            key = str(change['timestamp'])
            if rows.get(key) != change['old']:
                raise ValueError('broken revision chain')
            rows[key] = change['new']
    # Empty source batches may establish empty pair slots.
    if {p:r for p,r in state['pairs'].items() if r} != {p:r for p,r in replay.items() if r}:
        raise ValueError('source event/materialization mismatch')


def snapshot(state, pair, as_of, *, publication_lag_seconds=0, closed_holidays=()):
    validate_state(state)
    aware(as_of)
    if pair not in PAIRS or type(publication_lag_seconds) is not int or publication_lag_seconds < 0:
        raise ValueError('invalid snapshot contract')
    rows = list(state['pairs'].get(pair, {}).values())
    # Recompute all retained history; a late/revised H1 invalidates its D1 and W1.
    latest = latest_closed_date(as_of)
    first = (dt.datetime.fromtimestamp(min(r['timestamp'] for r in rows),UTC).date()
             if rows else latest)
    minimum = max(60, sum(1 for i in range(max(0,(latest-first).days)+1)
                         if (first+dt.timedelta(days=i)).weekday()<5))
    study = build_shadow(rows, as_of, minimum=minimum)
    # Holidays are explicit blocking annotations, never synthetic/omitted bars.
    holidays = {dt.date.fromisoformat(d).isoformat() for d in closed_holidays}
    blocked = sorted(holidays.intersection(x['trading_date_ny'] for x in study['d1']))
    latest_closed = as_of.astimezone(UTC) >= close_utc(latest)+dt.timedelta(seconds=publication_lag_seconds)
    d1 = study['d1'][-60:]
    trailing_errors = {d:e for d,e in study['errors'].items()
                       if d >= (d1[0]['trading_date_ny'] if d1 else latest.isoformat())}
    return {'pair':pair,'d1':d1,'w1':study['w1'], 'd1_count':len(d1),
        'w1_count':len(study['w1']), 'errors':study['errors'],
        'latest_ny_date':latest.isoformat(), 'publication_buffer_elapsed':latest_closed,
        'holiday_blocked_dates':blocked,
        'calendar_ready':len(d1)==60 and not trailing_errors and not blocked
            and study['latest_closed_present'] and latest_closed,
        'source_state_sha256':digest(state), 'provider_session_verified':False,
        'native_d1_equivalent_verified':False,'formal_decision_permission':False,
        'entry_permission':False}


def save_atomic(path, state, *, expected_digest=None):
    """Single-writer checkpoint, optimistic stale-state guard, atomic replace.

    No multiprocess locking: concurrent writers must be serialized externally.
    """
    validate_state(state)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    actual = digest(load_archive(path)) if path.exists() else None
    if actual != expected_digest:
        raise ValueError('stale archive checkpoint')
    name = None
    try:
        fd, name = tempfile.mkstemp(dir=path.parent, prefix='.ny17-', suffix='.tmp')
        with os.fdopen(fd,'wb') as f:
            f.write(packed(state)); f.flush(); os.fsync(f.fileno())
        os.replace(name,path)
        name = None
    finally:
        if name is not None:
            Path(name).unlink(missing_ok=True)


def load_archive(path):
    value = json.loads(Path(path).read_bytes())
    validate_state(value)
    return value
