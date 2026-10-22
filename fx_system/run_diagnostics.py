"""Small private diagnostics bound to the exact saved snapshot; no network."""
from collections import Counter
import hashlib
import json

LIMIT = 64 * 1024
PREFIX = 'SNAPSHOT_VALIDATION '


def build_diagnostics(snapshot_bytes, source, *, validation_log='', returncode=None, env=None):
    snapshot = json.loads(snapshot_bytes)
    if snapshot.get('evaluated_at') != source.get('evaluated_at'):
        raise ValueError('diagnostic snapshot clock mismatch')
    if type(returncode) is not int:
        returncode = None
    secrets = [value for name, value in (env or {}).items()
               if isinstance(value, str) and len(value) >= 6
               and (name.endswith('_TOKEN') or name.endswith('_KEY'))]
    def redact(value):
        for secret in secrets:
            value = value.replace(secret, '[REDACTED]')
        return value
    def bounded(value):
        return redact(str(value))[:512]
    validation = {'outcome': 'success' if returncode == 0 else
                  'failure' if type(returncode) is int else 'unavailable',
                  'returncode': returncode, 'report_status': 'unavailable', 'passed': None,
                  'failures': [], 'failure_count': None}
    reports = [line[len(PREFIX):] for line in validation_log.splitlines() if line.startswith(PREFIX)]
    if len(reports) == 1:
        try:
            report = json.loads(reports[0])
            failures = report['failures']; passed = report['passed']
            if (type(passed) is not bool or not isinstance(failures, list)
                    or any(not isinstance(x, str) for x in failures)
                    or passed != (len(failures) == 0)
                    or type(returncode) is not int or passed != (returncode == 0)):
                raise ValueError('inconsistent validation report')
            validation.update(report_status='available', passed=passed,
                              failures=[bounded(x) for x in failures[:128]], failure_count=len(failures))
        except (ValueError, KeyError, TypeError):
            validation['report_status'] = 'invalid'
    elif len(reports) > 1:
        validation['report_status'] = 'ambiguous'
    pairs = {}
    allowed = ('attempted', 'status', 'reason', 'request_as_of', 'returned_closed_bars',
               'returned_latest_closed', 'catchup_request_as_of', 'catchup_returned_latest_closed')
    from .monitor_pairs import PAIR_KEYS
    for pair in PAIR_KEYS:
        data = snapshot.get('pairs', {}).get(pair, {})
        quality = data.get('decision_quality', {})
        raw = data.get('decision_data', {}).get('raw', {})
        provenance = data.get('decision_data', {}).get('provenance', {})
        inventory = {}
        for tf in ('m5', 'h1'):
            rows = raw.get(tf, [])
            stamps = [b.get('timestamp') for b in rows[-24:]]
            inventory[tf] = {'retained_count': len(rows),
                'latest_timestamp': stamps[-1] if stamps else None,
                'latest_source': provenance.get(tf+':'+str(stamps[-1])) if stamps else None,
                'last_24_source_counts': dict(Counter(provenance.get(tf+':'+str(t), 'unknown') for t in stamps))}
        acquisition = data.get('acquisition', {})
        errors = snapshot.get('quality', {}).get(pair, {}).get('provider_errors', {})
        pairs[pair] = {'decision_ready': quality.get('ready'),
            'intraday_ready': quality.get('intraday_monitoring_ready'),
            'decision_reasons': [bounded(x) for x in quality.get('reasons', [])[:32]],
            'primary_errors': {tf: bounded(errors[tf]) for tf in ('m5','h1') if tf in errors},
            'acquisition': {tf: {k: v if type(v) in (int, bool, type(None)) else bounded(v)
                                for k, v in acquisition.get(tf, {}).items() if k in allowed}
                            for tf in ('m5', 'h1')},
            'sources': inventory}
    result = {'schema': 'private_run_diagnostics_v1', 'source': dict(source),
        'snapshot_git_blob_sha': hashlib.sha1(b'blob '+str(len(snapshot_bytes)).encode()+b'\0'+snapshot_bytes).hexdigest(),
        'validation': validation, 'pairs': pairs, 'truncated': False}
    def encode(value):
        def scrub(item):
            if isinstance(item, str): return redact(item)
            if isinstance(item, dict): return {redact(k): scrub(v) for k, v in item.items()}
            if isinstance(item, list): return [scrub(v) for v in item]
            return item
        return json.dumps(scrub(value), ensure_ascii=False, sort_keys=True,
                          allow_nan=False).encode('utf-8')+b'\n'
    encoded = encode(result)
    if len(encoded) > LIMIT:
        result['truncated'] = True
        result['pairs'] = {}
        validation['failures'] = validation['failures'][:32]
        encoded = encode(result)
    if len(encoded) > LIMIT:
        raise ValueError('private diagnostic exceeds limit')
    return encoded
