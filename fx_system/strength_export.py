"""Small private read projection of saved strength; never recalculate prices."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import re

from .strength import ALGORITHM, CURRENCIES


SCHEMA = 'saved_currency_strength_v1'


def render_strength_summary(value, clock):
    """Display the saved 24h ranking, preserving ties and missing-data limits."""
    if strength_errors(value, clock):
        return '通貨強弱（24時間）：確認できません。'
    if value['status'] == 'unavailable':
        return '通貨強弱（24時間）：データ不足で8通貨を比較できません。'
    groups = []
    for currency in value['ranking']:
        if groups and value['scores'][groups[-1][-1]] == value['scores'][currency]:
            groups[-1].append(currency)
        else:
            groups.append([currency])
    ranking = ' ＞ '.join(' ＝ '.join(group) for group in groups)
    label = '差なし' if len(groups) == 1 else '強い順'
    end = datetime.fromtimestamp(value['end_closed_at'], timezone(timedelta(hours=9)))
    coverage = f"{value['coverage_pairs']}/16ペア"
    provisional = '・一部データによる暫定順位' if value['status'] == 'provisional' else ''
    return (f'通貨強弱（24時間・{end:%m/%d %H:%M} JSTまで）：{label} {ranking}\n'
            f'保存済みH1終値の相対比較（{coverage}{provisional}）。'
            '各候補の6時間強弱とは期間が異なり、売買方向を単独で決めるものではありません。')


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def strength_errors(value, clock):
    if not isinstance(value, dict):
        return ['saved strength missing']
    if (value.get('algorithm') != ALGORITHM or value.get('advisory_only') is not True
            or value.get('evaluated_at') != clock or value.get('lookback_h1_bars') != 24
            or value.get('expected_pairs') != 16):
        return ['saved strength identity mismatch']
    start, end = value.get('start_closed_at'), value.get('end_closed_at')
    if (type(start) is not int or type(end) is not int or type(clock) is not int
            or not 0 < start < end <= clock or end-start != 86400
            or start % 3600 or end % 3600):
        return ['saved strength window invalid']
    coverage = value.get('coverage_pairs'); status = value.get('status')
    if type(coverage) is not int or not 0 <= coverage <= 16:
        return ['saved strength coverage invalid']
    if status not in ('complete', 'provisional', 'unavailable'):
        return ['saved strength status invalid']
    scores, ranking = value.get('scores'), value.get('ranking')
    observations = value.get('observations')
    if (not isinstance(scores, dict) or set(scores) != set(CURRENCIES)
            or not isinstance(observations, dict) or set(observations) != set(CURRENCIES)
            or any(type(n) is not int or n < 0 for n in observations.values())
            or sum(observations.values()) != 2*coverage):
        return ['saved strength currencies invalid']
    if status == 'unavailable':
        if (ranking != [] or any(v is not None for v in scores.values())
                or value.get('connected_all_currencies') is not False):
            return ['disconnected strength contains a ranking']
    elif (value.get('connected_all_currencies') is not True
          or (status == 'complete') != (coverage == 16)
          or not all(_finite(v) for v in scores.values())
          or not isinstance(ranking, list) or len(ranking) != 8 or set(ranking) != set(CURRENCIES)
          or any(scores[a] < scores[b] for a,b in zip(ranking,ranking[1:]))
          or abs(sum(scores.values())) > 0.00005
          or not _finite(value.get('fit_rmse_log_pct')) or value['fit_rmse_log_pct'] < 0):
        return ['connected strength scores invalid']
    return []


def build_strength_export(snapshot_bytes, source):
    """Copy the existing payload and bind it to exact snapshot bytes and source."""
    snapshot = json.loads(snapshot_bytes)
    clock = snapshot.get('evaluated_at')
    if (type(clock) is not int or clock <= 0 or source.get('evaluated_at') != clock
            or source.get('source_repository') != 'nyancoworks/fx-monitor'
            or type(source.get('run_id')) is not int or source['run_id'] <= 0
            or not re.fullmatch('[0-9a-f]{40}', source.get('source_commit', ''))):
        raise ValueError('strength export source mismatch')
    strength = snapshot.get('currency_strength')
    errors = strength_errors(strength, clock)
    blob_sha = hashlib.sha1(b'blob '+str(len(snapshot_bytes)).encode()+b'\0'+snapshot_bytes).hexdigest()
    bundle = {'schema': SCHEMA, 'source': {k: source[k] for k in
            ('source_repository','source_commit','run_id','evaluated_at')},
            'snapshot_git_blob_sha': blob_sha, 'snapshot_byte_length': len(snapshot_bytes),
            'status': 'unavailable' if errors else 'saved', 'errors': errors,
            'currency_strength': None if errors else deepcopy(strength)}
    bundle['summary_version'] = 1
    bundle['summary_text'] = render_strength_summary(strength, clock)
    references = snapshot.get('historical_shape_references')
    if references is not None:
        from .historical_shape_reference import reference_errors
        if not reference_errors(references, clock):
            bundle['historical_shape_references'] = deepcopy(references)
    return bundle


def validate_strength_export(bundle, source, snapshot_blob_sha):
    if not isinstance(bundle, dict) or bundle.get('schema') != SCHEMA:
        return ['strength export schema invalid']
    if bundle.get('source') != source or bundle.get('snapshot_git_blob_sha') != snapshot_blob_sha:
        return ['strength export source or snapshot mismatch']
    if bundle.get('status') != 'saved':
        return ['strength export unavailable']
    errors = strength_errors(bundle.get('currency_strength'), source.get('evaluated_at'))
    if errors:
        return errors
    if 'summary_version' in bundle or 'summary_text' in bundle:
        if (type(bundle.get('summary_version')) is not int or bundle['summary_version'] != 1
                or bundle.get('summary_text') != render_strength_summary(
                    bundle['currency_strength'], source.get('evaluated_at'))):
            return ['strength summary invalid']
    return []
