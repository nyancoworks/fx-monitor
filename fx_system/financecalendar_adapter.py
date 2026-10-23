"""Normalize a caller-supplied Finance Calendar /calendar page; never fetch data.

One bounded live sample was verified; ongoing freshness is unverified. Preserve originals
in private storage separately. No forecast inference, numeric conversion or score.
"""
from collections import Counter
from copy import deepcopy
from datetime import date, datetime
import math

ATTRIBUTION_URL = 'https://www.financecalendar.com'
COUNTRY_CURRENCY = {'US': 'USD', 'GB': 'GBP', 'EU': 'EUR', 'DE': 'EUR',
                    'JP': 'JPY', 'CA': 'CAD', 'AU': 'AUD', 'CH': 'CHF', 'NZ': 'NZD'}
CATEGORIES = {'economic-indicators', 'central-banks-monetary-policy'}
STATUSES = {'confirmed', 'estimated', 'rescheduled', 'cancelled', 'released'}
TEXT_FIELDS = ('id', 'series_code', 'title', 'name', 'country', 'category', 'impact',
               'period', 'unit', 'source_url', 'source_name', 'source_id',
               'verification_url', 'verification_method', 'time_role', 'release_stage')
LICENSE_FIELDS = ('id', 'url', 'terms_url', 'attribution', 'attribution_url', 'notice', 'adapted')
RIGHTS_FIELDS = ('basis', 'access_basis', 'reviewed_at', 'attribution', 'source_url', 'terms_url', 'notice')
OBSERVATION_LICENSE_FIELDS = ('spdx', 'url', 'attribution', 'policy', 'vintage_notice')


def _instant(value):
    if not isinstance(value, str) or 'T' not in value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            return None
        stamp = parsed.timestamp()
        return int(stamp) if math.isfinite(stamp) and stamp > 0 and stamp.is_integer() else None
    except (ValueError, OverflowError, OSError):
        return None


def _date(value):
    try:
        return date.fromisoformat(value).isoformat() if isinstance(value, str) else None
    except ValueError:
        return None


def _metadata(value, fields):
    if not isinstance(value, dict):
        return None
    # Explicit projection prevents raw payloads/unknown fields entering history.
    return {k: deepcopy(value[k]) for k in fields if k in value
            and (value[k] is None or isinstance(value[k], str) or type(value[k]) is bool)}


def normalize_calendar(payload, *, observed_at_utc, source_status=None, status_observed_at_utc=None):
    """Return reference-only input for build_scheduled_outlook.

    observed_at_utc is a trusted caller acquisition time, not a provider build
    clock. This one-page adapter never claims comprehensive market coverage.
    Source verification age is reported without inventing a freshness threshold.
    """
    if type(observed_at_utc) is not int or observed_at_utc <= 0:
        raise ValueError('invalid calendar acquisition clock')
    result = {'schema': 'financecalendar_reference_v1', 'provider': 'financecalendar.com',
              'observed_at_utc': observed_at_utc, 'events': [], 'complete': False,
              'coverage': 'unverified', 'page_complete': False,
              'attribution_url': ATTRIBUTION_URL, 'attribution': None,
              'freshness': 'unverified', 'omitted_count': 0, 'warnings': []}
    if not isinstance(payload, dict) or not isinstance(payload.get('events'), list) or 'error' in payload:
        result['warnings'].append('invalid_calendar_page')
        return result
    result['attribution'] = _metadata(payload.get('attribution'),
                                     ('source', 'terms', 'docs', 'source_licenses', 'source_rights'))
    if not result['attribution']:
        result['warnings'].append('provider_attribution_missing')
    from .economic_calendar_health import source_health_index
    health = source_health_index(source_status, observed_at_utc=status_observed_at_utc,
                                 calendar_observed_at_utc=observed_at_utc)
    rows = payload['events']
    count, total = payload.get('count'), payload.get('total')
    result['page_complete'] = (type(count) is int and type(total) is int
                               and count == total == len(rows))
    if not result['page_complete']:
        result['warnings'].append('pagination_or_counts_unverified')
    ids = Counter(r['id'] for r in rows if isinstance(r, dict) and isinstance(r.get('id'), str))
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get('id'), str) or not row['id'] or ids[row['id']] != 1:
            result['omitted_count'] += 1
            continue
        country = row.get('country')
        if (not isinstance(country, str) or country not in COUNTRY_CURRENCY
                or not isinstance(row.get('category'), str) or row['category'] not in CATEGORIES
                or not isinstance(row.get('status'), str) or row['status'] not in STATUSES):
            result['omitted_count'] += 1
            continue
        updated = _instant(row.get('updated_at'))
        verified = _instant(row.get('last_verified_at'))
        reviewed = _instant(row.get('manually_reviewed_at'))
        if any(t is not None and t > observed_at_utc for t in (updated, verified, reviewed)):
            result['omitted_count'] += 1
            continue
        event = {k: row[k] for k in TEXT_FIELDS if isinstance(row.get(k), str)}
        event.update(currency=COUNTRY_CURRENCY[country], observed_at_utc=observed_at_utc,
                     reference_only=True, provider_status=row['status'],
                     date=_date(row.get('date')), release_tz=row.get('release_tz') if isinstance(row.get('release_tz'), str) else None,
                     time_precision=row.get('time_precision') if isinstance(row.get('time_precision'), str) else 'unspecified',
                     updated_at_utc=updated, last_verified_at_utc=verified,
                     manually_reviewed_at_utc=reviewed,
                     source_verification_age_seconds=observed_at_utc-verified if verified is not None else None,
                     freshness='stale' if row.get('data_stale') is True else 'unverified',
                     source_license=_metadata(row.get('source_license'), LICENSE_FIELDS),
                     source_rights=_metadata(row.get('source_rights'), RIGHTS_FIELDS),
                     numeric_comparison_verified=False, actual=None, surprise=None)
        # A range bound or calendar date must never become an exact release time.
        first, alias = _instant(row.get('release_at_utc')), _instant(row.get('time_utc'))
        exact = (event['time_precision'] in ('minute', 'second', 'unspecified')
                 and row.get('all_day') is not True
                 and not row.get('time_window_start') and not row.get('time_window_end')
                 and not row.get('date_window_start') and not row.get('date_window_end'))
        conflict = (row.get('release_at_utc') is not None and first is None
                    or row.get('time_utc') is not None and alias is None
                    or first is not None and alias is not None and first != alias)
        event['scheduled_at_utc'] = (first if first is not None else alias) if exact and not conflict else None
        event['timing_conflict'] = bool(conflict)
        for field in ('time_window_start', 'time_window_end'):
            event[field + '_utc'] = _instant(row.get(field))
        for field in ('date_window_start', 'date_window_end'):
            event[field] = _date(row.get(field))
        # Values are recorded strings only, never parsed across incompatible units.
        # No nested observation/revision payload is copied into a historical view.
        for field in ('actual', 'consensus', 'prior'):
            value = row.get(field)
            event[field + '_raw'] = value if isinstance(value, str) else None
        when = event['scheduled_at_utc']
        if (when is None or when > observed_at_utc or row['status'] in ('estimated', 'cancelled')
                or row.get('observation_status') == 'stale'):
            event['actual_raw'] = None
        event['observation_credits'] = []
        observations = row.get('observations')
        if isinstance(observations, list):
            for observation in observations:
                if not isinstance(observation, dict) or observation.get('role') not in ('actual', 'prior'):
                    continue
                role = observation['role']
                clocks = [_instant(observation.get(k)) for k in ('known_at', 'first_seen_at', 'source_updated_at')]
                if any(t is not None and t > observed_at_utc for t in clocks):
                    event[role + '_raw'] = None
                    continue
                if event[role + '_raw'] is not None:
                    event['observation_credits'].append({
                        'role': role,
                        'source_license': _metadata(observation.get('source_license'), OBSERVATION_LICENSE_FIELDS),
                        'source_rights': _metadata(observation.get('source_rights'), OBSERVATION_LICENSE_FIELDS),
                    })
        event['source_health'] = deepcopy(health.get(event.get('source_id'), {
            'status': 'unverified', 'generation_match': 'unverified', 'current_freshness': 'unverified'}))
        event['status'] = row['status']
        result['events'].append(event)
    if result['omitted_count']:
        result['warnings'].append('unsupported_invalid_or_duplicate_rows_omitted')
    return result
