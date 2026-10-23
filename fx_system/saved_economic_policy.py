"""Bounded, offline reference to dated official policy documents; no fetches."""
from collections import Counter
from datetime import date, datetime, timezone
import json
import os
from pathlib import Path
import stat
from urllib.parse import urlsplit

CODE_ROOT = Path(__file__).resolve().parents[1]
RELATIVE_PATH = Path('data/economic-background/reference.json')
MAX_BYTES = 64 * 1024
OFFICIAL_HOSTS = {'USD': 'federalreserve.gov', 'EUR': 'ecb.europa.eu',
                  'JPY': 'boj.or.jp', 'GBP': 'bankofengland.co.uk',
                  'CAD': 'bankofcanada.ca', 'AUD': 'rba.gov.au',
                  'NZD': 'rbnz.govt.nz', 'CHF': 'snb.ch'}
TEXT_LIMITS = {'instrument': 100, 'rate_text': 100, 'source_name': 100,
               'source_url': 1000, 'source_credit': 500}


def _unavailable(reason):
    return {'status': 'unavailable', 'reason': reason, 'facts': [],
            'freshness': 'unverified', 'complete': False}


def normalize_policy_reference(value, *, evaluated_at):
    """Validate reference shape/clocks, not the truth of supplied quotations.

    An official URL is provenance metadata, not proof of a correct extraction.
    Dates remain publisher dates and are never converted to midnight releases.
    """
    if (not isinstance(value, dict) or value.get('schema') != 'saved_policy_reference_v1'
            or not isinstance(value.get('facts'), list) or len(value['facts']) > 128
            or type(evaluated_at) is not int or evaluated_at <= 0):
        return _unavailable('invalid_policy_input')
    valid = []
    for item in value['facts']:
        try:
            if not isinstance(item, dict):
                continue
            currency = item.get('currency')
            if currency not in OFFICIAL_HOSTS:
                continue
            observed = item.get('observed_at_utc')
            if type(observed) is not int or not 0 < observed <= evaluated_at:
                continue
            if any(not isinstance(item.get(k), str) or not item[k].strip()
                   or len(item[k]) > limit or any(ord(c) < 32 for c in item[k])
                   for k, limit in TEXT_LIMITS.items()):
                continue
            published = date.fromisoformat(item['published_date'])
            effective = date.fromisoformat(item['effective_date'])
            # This bounds knowledge by the recorded document-review time.
            # It is not an HTTP receipt or a publisher update timestamp.
            # A future effective date is allowed, but never called effective now.
            if (published.isoformat() != item['published_date']
                    or effective.isoformat() != item['effective_date']
                    or published > datetime.fromtimestamp(observed, timezone.utc).date()
                    or effective < published or item.get('decision') not in ('raised', 'lowered', 'held')):
                continue
            url = urlsplit(item['source_url'])
            host = url.hostname or ''
            expected = OFFICIAL_HOSTS[currency]
            if (url.scheme != 'https' or url.username or url.password or url.port not in (None, 443)
                    or url.query or url.fragment or not url.path or url.path == '/'
                    or not (host == expected or host.endswith('.'+expected))):
                continue
            valid.append({k: item[k] for k in (*TEXT_LIMITS, 'currency', 'published_date',
                                              'effective_date', 'decision', 'observed_at_utc')})
        except (KeyError, TypeError, ValueError, OverflowError, OSError):
            continue
    keys = [(x['currency'], x['instrument'], x['published_date']) for x in valid]
    counts = Counter(keys)
    unique = [x for x, key in zip(valid, keys) if counts[key] == 1]
    latest = {}
    for item in unique:
        key = (item['currency'], item['instrument'])
        if key not in latest or item['published_date'] > latest[key]['published_date']:
            latest[key] = item
    selected = []
    for currency in OFFICIAL_HOSTS:
        selected.extend(sorted((x for x in latest.values() if x['currency'] == currency),
                               key=lambda x: x['instrument'])[:4])
    return {'status': 'saved_reference', 'facts': selected, 'freshness': 'unverified',
            'complete': False, 'rejected_count': len(value['facts'])-len(valid)
            + sum(n for n in counts.values() if n > 1),
            'superseded_count': len(unique)-len(latest),
            'omitted_count': len(latest)-len(selected)}


def load_saved_policy(root, *, evaluated_at):
    """Absent input preserves old output; malformed input never blocks FX."""
    try:
        root = Path(root)
        if (not root.is_absolute() or root.is_symlink()
                or root.resolve().is_relative_to(CODE_ROOT) or CODE_ROOT.is_relative_to(root.resolve())):
            return _unavailable('private_location_required')
        root = root.resolve()
        target = root / RELATIVE_PATH
        if any(p.is_symlink() for p in (target, *target.parents) if p.is_relative_to(root)):
            return _unavailable('invalid_policy_input')
        if not target.resolve().is_relative_to(root):
            return _unavailable('invalid_policy_input')
        try:
            descriptor = os.open(target, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
        except FileNotFoundError:
            return None
        with os.fdopen(descriptor, 'rb') as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                return _unavailable('invalid_policy_input')
            content = stream.read(MAX_BYTES+1)
        if len(content) > MAX_BYTES:
            return _unavailable('oversized_policy_input')
        return normalize_policy_reference(json.loads(content), evaluated_at=evaluated_at)
    except (OSError, ValueError, TypeError, RecursionError):
        return _unavailable('unreadable_policy_input')


def policy_lines(reference, currencies, format_clock):
    if not isinstance(reference, dict):
        return []
    if reference.get('status') != 'saved_reference':
        return ['政策資料：保存入力を確認できない。金利・政策判断は保留']
    lines = []
    for currency in currencies:
        facts = [x for x in reference['facts'] if x['currency'] == currency]
        if not facts:
            lines.append(f'政策資料 {currency}：未収録（政策変更なしを意味しない）')
        for fact in facts:
            decision = {'raised': '引上げ', 'lowered': '引下げ', 'held': '据置き'}[fact['decision']]
            lines.append(f"政策資料 {currency}：{fact['instrument']} {fact['rate_text']}（{decision}）"
                         f"｜公表日 {fact['published_date']}｜資料の適用日 {fact['effective_date']}"
                         f"｜資料確認 {format_clock(fact['observed_at_utc'])}"
                         f"｜出典 {fact['source_name']} {fact['source_url']}｜{fact['source_credit']}")
    lines.append('政策資料は公表時の記録。最新性・適用済みかは未検証。政策見通し・市場予想・市場反応や通貨方向を推定しない。')
    if reference.get('rejected_count') or reference.get('omitted_count'):
        lines.append('政策資料：形式・重複・件数制限で掲載できない入力あり。網羅性は未検証')
    return lines
