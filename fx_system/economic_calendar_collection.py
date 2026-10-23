"""Bounded keyless collection in an existing private refresh; disabled by default.

No schedules, retries, redirect following, orders or public payload output.
"""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

from .saved_economic_calendar import CODE_ROOT, MAX_BYTES, RELATIVE_PATH

CONFIG_PATH = Path('config/economic-calendar.json')
COLLECTION_PATH = Path('data/economic-calendar/collection.json')
ALLOWED_CONFIG = {'schema': 'economic_calendar_collection_v1', 'enabled': True,
                  'max_requests_per_run': 2}
BASE_URL = 'https://www.financecalendar.com/wp-json/fc/v1/'


def _private_path(root, relative):
    root = Path(root)
    if (not root.is_absolute() or root.is_symlink()
            or root.resolve().is_relative_to(CODE_ROOT) or CODE_ROOT.is_relative_to(root.resolve())):
        raise ValueError('private location required')
    root = root.resolve()
    target = root / relative
    if not target.resolve().is_relative_to(root) or any(
            p.is_symlink() for p in (target, *target.parents) if p.is_relative_to(root)):
        raise ValueError('invalid private path')
    return target


def _read(path, limit=MAX_BYTES):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError('regular file required')
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError('input too large')
    return data


def collection_enabled(root):
    try:
        value = json.loads(_read(_private_path(root, CONFIG_PATH), 4096))
        return (isinstance(value, dict) and value == ALLOWED_CONFIG
                and value.get('enabled') is True and type(value.get('max_requests_per_run')) is int)
    except (OSError, ValueError, TypeError, RecursionError, RuntimeError):
        return False


def _write(path, data, *, original=False):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if original:
        with path.open('xb') as stream:
            os.chmod(path, 0o600)
            stream.write(data)
        return
    descriptor, name = tempfile.mkstemp(dir=path.parent, prefix='.calendar-')
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(data)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False).encode() + b'\n'


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _get(url, *, clock):
    # No authentication or caller-supplied URL; one attempt, bounded response.
    opener = urllib.request.build_opener(_NoRedirect)
    started = time.monotonic()
    try:
        response = opener.open(urllib.request.Request(url, headers={
            'User-Agent': 'FX-Monitor-Calendar/1.0'}), timeout=5)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        chunks, size = [], 0
        while True:
            if time.monotonic() - started > 12:
                raise TimeoutError('calendar response deadline')
            chunk = response.read1(min(8192, MAX_BYTES + 1 - size))
            if not chunk:
                break
            chunks.append(chunk); size += len(chunk)
            if size > MAX_BYTES:
                raise ValueError('calendar response too large')
        return response.code, b''.join(chunks), int(clock())


def _persist(root, files):
    # Reuse the configured private writer; never publish a response to code repo.
    from .private_runtime import git, verify_ready
    verify_ready(root)
    if git(root, 'diff', '--cached', '--name-only'):
        raise ValueError('unexpected staged private files')
    names = [str(p.relative_to(root)) for p in files]
    try:
        git(root, 'add', '--', *names)
        staged = git(root, 'diff', '--cached', '--name-only').splitlines()
        if not set(staged) <= set(names):
            raise ValueError('unexpected staged private files')
        if staged:
            git(root, '-c', 'user.name=github-actions[bot]', '-c',
                'user.email=41898286+github-actions[bot]@users.noreply.github.com',
                'commit', '-m', 'Save optional economic calendar reference and original receipts')
            git(root, 'push', 'origin', 'HEAD:refs/heads/main')
    except Exception:
        # Remove only our index entries, preserving all bytes and unrelated
        # staging. Optional calendar files must not poison save_snapshot's set.
        git(root, 'reset', '--', *names)
        raise


def prepare_calendar(root, *, run_id, clock=time.time, get=None, persist=None):
    """At most two GETs per existing run; preserve each received body privately.

    Call only after private_runtime verified the checkout/run identity. The
    explicit private configuration is the activation switch, not a new schedule.
    Returns fixed state metadata; caller must not allow failures to stop FX.
    """
    if not collection_enabled(root):
        return {'status': 'disabled', 'requests': 0}
    if not isinstance(run_id, str) or not run_id.isdigit():
        raise ValueError('invalid private run identity')
    root = Path(root).resolve()
    manifest_path = _private_path(root, Path('data/economic-calendar/originals') / run_id / 'manifest.json')
    collection_path = _private_path(root, COLLECTION_PATH)
    reference_path = _private_path(root, RELATIVE_PATH)
    if manifest_path.exists():
        try:
            existing = json.loads(_read(manifest_path, 4096))
            state = existing.get('status') if isinstance(existing, dict) else None
        except (OSError, ValueError, TypeError):
            state = None
        return {'status': state if state in ('saved', 'unavailable') else 'unavailable',
                'requests': 0, 'already_attempted': True}
    now = int(clock())
    if now <= 0:
        raise ValueError('invalid acquisition clock')
    day = datetime.fromtimestamp(now, timezone.utc).date()
    query = urllib.parse.urlencode({'from': (day-timedelta(days=2)).isoformat(),
        'to': (day+timedelta(days=8)).isoformat(),
        'country': 'US,GB,EU,DE,JP,CA,AU,CH,NZ', 'limit': 500, 'offset': 0})
    fetch = get if get is not None else _get
    writer = persist if persist is not None else _persist
    manifest = {'schema': 'economic_calendar_receipt_v1', 'run_id': run_id,
                'started_at_utc': now, 'requests': [], 'status': 'attempting'}
    # Reserve this run before I/O. Interrupted/duplicate stages never retry it.
    _write(manifest_path, _json(manifest), original=True)
    files = [manifest_path]
    envelopes = {}
    for name, suffix in (('status', 'status'), ('calendar', 'calendar?' + query)):
        receipt = {'endpoint': name, 'status': 'attempting'}
        manifest['requests'].append(receipt)
        _write(manifest_path, _json(manifest))
        try:
            code, body, observed = fetch(BASE_URL + suffix, clock=clock)
            if type(observed) is not int or observed < now or not isinstance(body, bytes):
                raise ValueError('invalid received evidence')
            target = _private_path(root, manifest_path.parent.relative_to(root) / (name + '.response'))
            _write(target, body, original=True)
            files.append(target)
            receipt.update(http_status=code, observed_at_utc=observed,
                           sha256=hashlib.sha256(body).hexdigest(), size_bytes=len(body))
            payload = json.loads(body)
            if code != 200 or not isinstance(payload, dict) or 'error' in payload:
                raise ValueError('unusable provider response')
            if name == 'calendar' and not isinstance(payload.get('events'), list):
                raise ValueError('unusable calendar response')
            # Reject non-finite/invalid-Unicode payloads while the completed raw
            # response is still retained; never fail later at envelope write.
            _json(payload)
            envelopes[name] = {'observed_at_utc': observed, 'payload': payload}
            receipt['status'] = 'received'
        except Exception:
            # No exception text, URLs, private response or credential logging.
            receipt['status'] = 'unavailable'
        _write(manifest_path, _json(manifest))
    outcome = 'saved' if 'calendar' in envelopes else 'unavailable'
    if 'calendar' in envelopes:
        value = {'schema': 'financecalendar_saved_input_v1', **envelopes}
        _write(reference_path, _json(value))
        files.append(reference_path)
    manifest['status'] = outcome
    _write(manifest_path, _json(manifest))
    attempt = {'schema': 'economic_calendar_collection_result_v1', 'run_id': run_id,
               'observed_at_utc': int(clock()), 'status': outcome,
               'requests': len(manifest['requests'])}
    _write(collection_path, _json(attempt)); files.append(collection_path)
    writer(root, files)
    return {'status': outcome, 'requests': len(manifest['requests'])}
