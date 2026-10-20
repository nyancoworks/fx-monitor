"""Offline monitoring-result history. No storage, network or deletion actions."""
import base64
from copy import deepcopy
import gzip
import hashlib
import json
import zlib
from fx_system.monitor_pairs import PAIR_KEYS

SCHEMA = 'monitoring_result_generation_v1'
KEEP = 3
MAX_PLAIN_BYTES = 2 * 1024 * 1024
FORBIDDEN = {'raw', 'receipt', 'receipts', 'api_key', 'authorization', 'secrets'}


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def _validate(payload):
    if not isinstance(payload, dict) or payload.get('schema') != SCHEMA:
        raise ValueError('invalid generation schema')
    clock = payload.get('evaluated_at')
    if type(clock) is not int or clock <= 0:
        raise ValueError('invalid evaluation clock')
    rows = payload.get('rows')
    if not isinstance(rows, list) or len(rows) != len(PAIR_KEYS):
        raise ValueError('all configured pair result rows required')
    if any(not isinstance(row, dict) for row in rows):
        raise ValueError('invalid result row')
    names = [row.get('pair') for row in rows]
    if len(set(names)) != len(PAIR_KEYS) or set(names) != set(PAIR_KEYS):
        raise ValueError('duplicate or unknown pair')
    def inspect(value):
        if isinstance(value, dict):
            if any(str(key).lower() in FORBIDDEN for key in value):
                raise ValueError('result history must not contain source candles or credentials')
            if isinstance(value.get('candles'), (list, dict)):
                raise ValueError('source candle arrays are not monitoring results')
            for child in value.values(): inspect(child)
        elif isinstance(value, list):
            for child in value: inspect(child)
    inspect(rows)
    return payload


def pack_generation(rows, *, evaluated_at):
    payload = _validate({'schema': SCHEMA, 'evaluated_at': evaluated_at, 'rows': deepcopy(rows)})
    plain = _canonical(payload)
    if len(plain) > MAX_PLAIN_BYTES:
        raise ValueError('generation exceeds size limit')
    compressed = gzip.compress(plain, compresslevel=6, mtime=0)
    return {'evaluated_at': evaluated_at,
            'sha256': hashlib.sha256(compressed).hexdigest(),
            'gzip_base64': base64.b64encode(compressed).decode('ascii')}


def restore_generation(generation):
    encoded = generation.get('gzip_base64')
    if not isinstance(encoded, str) or len(encoded) > MAX_PLAIN_BYTES * 2:
        raise ValueError('invalid compressed generation')
    try:
        compressed = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError) as error:
        raise ValueError('invalid base64') from error
    if hashlib.sha256(compressed).hexdigest() != generation.get('sha256'):
        raise ValueError('generation digest mismatch')
    decoder = zlib.decompressobj(wbits=31)
    plain = decoder.decompress(compressed, MAX_PLAIN_BYTES + 1)
    if len(plain) > MAX_PLAIN_BYTES or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
        raise ValueError('invalid or oversized compressed generation')
    payload = _validate(json.loads(plain))
    if payload['evaluated_at'] != generation.get('evaluated_at') or _canonical(payload) != plain:
        raise ValueError('generation identity mismatch')
    return payload


def append_generation(history, rows, *, evaluated_at):
    """Return a new three-generation proposal; leave every original untouched."""
    if not isinstance(history, list) or len(history) > KEEP:
        raise ValueError('invalid result history')
    clocks = [restore_generation(item)['evaluated_at'] for item in history]
    if clocks != sorted(set(clocks)):
        raise ValueError('history clocks must strictly increase')
    incoming = pack_generation(rows, evaluated_at=evaluated_at)
    if clocks and evaluated_at < clocks[-1]:
        raise ValueError('stale writer')
    if clocks and evaluated_at == clocks[-1]:
        if incoming != history[-1]:
            raise ValueError('conflicting evaluation revision')
        return deepcopy(history)
    # This selects retained generations in a new value. It never deletes files.
    return deepcopy((history + [incoming])[-KEEP:])


def latest_restorable(history):
    """Recover a saved reference; never claim that an older result is current."""
    if not isinstance(history, list) or len(history) > KEEP:
        raise ValueError('invalid result history')
    valid, errors = [], []
    for index, generation in enumerate(history):
        try:
            valid.append(restore_generation(generation))
        except (ValueError, TypeError, KeyError, AttributeError, zlib.error):
            errors.append({'index': index, 'reason': 'generation_not_restorable'})
    payload = max(valid, key=lambda item: item['evaluated_at']) if valid else None
    return {'status': ('unavailable' if payload is None else
                       'fallback_reference' if errors else 'latest_saved_reference'),
            'saved_evaluated_at': payload['evaluated_at'] if payload else None,
            'payload': payload, 'errors': errors,
            'current_freshness': 'unverified', 'entry_permission': False}
