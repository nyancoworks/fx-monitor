"""Bounded operational metadata; never forward exception text or request URLs."""
import json

PREFIX = 'FX_BACKTEST_FAILURE '
CODES = {
    'storage HTTP operation failed': 'http_failure',
    'storage request budget exhausted': 'request_budget',
    'conflicting archive revision': 'archive_revision_conflict',
    'unexpected storage redirect': 'redirect_rejected',
    'backup differs; refuse writes/deletion': 'backup_mismatch',
    'asset readback differs': 'asset_mismatch',
    'invalid derived index': 'invalid_index',
    'invalid bundle compression': 'invalid_bundle',
    'archive writer changed; preserve unreferenced uploads': 'writer_changed',
    'published pointer not verified': 'pointer_unverified',
    'published index restoration failed': 'index_unverified',
    'private destination required': 'destination_rejected',
    'insufficient room for recoverable generation': 'capacity',
}
PHASES = ('saved_input', 'storage', 'result_save')


def metadata(error, phase, api=None):
    # Only a fixed lookup is allowed; unknown messages never leave private logs.
    code = CODES.get(str(error), 'unclassified') if isinstance(error, ValueError) else 'unclassified'
    try:
        import requests
        if isinstance(error, requests.Timeout): code = 'timeout'
        elif isinstance(error, requests.ConnectionError): code = 'connection'
    except ImportError:
        pass
    return {'code': code, 'phase': phase,
            'requests': getattr(api, 'calls', 0),
            'http_status': getattr(api, 'last_status', 0)}


def safe_failure_line(log):
    for line in log.splitlines():
        if not line.startswith(PREFIX): continue
        try:
            value = json.loads(line[len(PREFIX):])
            if (set(value) != {'code','phase','requests','http_status'} or
                value['code'] not in set(CODES.values()) | {'unclassified','timeout','connection'} or
                value['phase'] not in PHASES or
                type(value['requests']) is not int or not 0 <= value['requests'] <= 64 or
                type(value['http_status']) is not int or
                value['http_status'] not in (0, *range(100,600))):
                continue
            return PREFIX + json.dumps(value, sort_keys=True)
        except (ValueError, TypeError, KeyError):
            continue
    return PREFIX + '{"code":"unclassified"}'
