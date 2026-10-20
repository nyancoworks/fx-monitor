"""Default-off capture of existing new-pair responses; no network or adoption."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import uuid

PAIRS = {'CADJPY', 'CHFJPY'}
MAX_BYTES = 2 * 1024 * 1024
_failed = 0
_saved = 0

def status():
    return {'enabled': bool(os.getenv('FX_H1_EVIDENCE_DIR')), 'saved': _saved,
            'failed': _failed, 'adopted': False}

def _write(path, data):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())

def capture(response, *, secret, pair, interval, outputsize, started_at, received_at):
    """Preserve exact bytes privately; failures never trigger acquisition retry."""
    global _failed, _saved
    configured = os.getenv('FX_H1_EVIDENCE_DIR')
    pair = pair.replace('/', '')
    if not configured or pair not in PAIRS or interval != '1h':
        return
    temporary = None
    try:
        directory = Path(configured)
        root = Path(__file__).resolve().parents[1]
        if not directory.is_absolute() or directory == root or root in directory.parents:
            raise ValueError('isolated absolute directory required')
        for ancestor in (directory, *directory.parents):
            if ancestor.is_symlink():
                raise ValueError('symlink forbidden')
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        if directory.stat().st_mode & 0o077:
            raise ValueError('private directory required')
        body = response.content
        if not isinstance(body, bytes) or not body or len(body) > MAX_BYTES:
            raise ValueError('invalid response size')
        if not secret or secret.encode() in body:
            raise ValueError('secret in response')
        payload = json.loads(body)
        meta = payload.get('meta', {})
        if (response.status_code != 200 or payload.get('status') == 'error'
                or not isinstance(payload.get('values'), list)
                or meta.get('symbol', '').replace('/', '') != pair
                or meta.get('interval') != '1h'
                or ('timezone' in meta and meta['timezone'] != 'UTC')):
            raise ValueError('response identity mismatch')
        if type(started_at) is not int or type(received_at) is not int or received_at < started_at:
            raise ValueError('invalid receipt clock')
        digest = hashlib.sha256(body).hexdigest()
        receipt = {'schema': 'fx_existing_h1_response_receipt_v1', 'provider': 'Twelve Data',
                   'pair': pair, 'interval': interval, 'requested_timezone': 'UTC',
                   'outputsize': outputsize, 'request_started_at': started_at,
                   'received_at': received_at, 'http_status': 200,
                   'response_sha256': digest, 'response_bytes': len(body),
                   'source': 'existing_natural_collection_response',
                   'archive_adopted': False, 'entry_permission': False}
        encoded = json.dumps(receipt, sort_keys=True).encode()
        if secret.encode() in encoded:
            raise ValueError('secret in receipt')
        temporary = Path(tempfile.mkdtemp(prefix='.pending-', dir=directory))
        _write(temporary / 'response.json', body)
        _write(temporary / 'response.sha256', (digest + '\n').encode())
        _write(temporary / 'receipt.json', encoded)
        if hashlib.sha256((temporary / 'response.json').read_bytes()).hexdigest() != digest:
            raise ValueError('readback mismatch')
        os.rename(temporary, directory / (pair + '-' + str(received_at) + '-' + uuid.uuid4().hex))
        temporary = None
        _saved += 1
        print('H1_EVIDENCE_CAPTURE saved', flush=True)
    except Exception:
        _failed += 1
        print('H1_EVIDENCE_CAPTURE failed; no retry or adoption', flush=True)
    finally:
        if temporary is not None:
            shutil.rmtree(temporary)
