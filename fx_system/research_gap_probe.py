"""Bounded historical H1 research receipts; never modify the decision feed.

Targets are kept only in the private data repository. A response is retained
there with its provenance even when it cannot complete a NY-close session.
"""
import datetime as dt
import json
import time
from zoneinfo import ZoneInfo

import requests

from .core import parse_row
from .monitor_pairs import PAIRS

SCHEMA = 'private_h1_gap_probe_v1'
MAX_TARGETS = 20
MAX_PER_RUN = 4
NY = ZoneInfo('America/New_York')


def probe(config, previous, session, key, budget, now, quota, deadline):
    if (not isinstance(config, dict) or config.get('schema') != SCHEMA
            or not isinstance(config.get('targets'), list)
            or not 1 <= len(config['targets']) <= MAX_TARGETS):
        raise ValueError('invalid private research request')
    targets = config['targets']
    identities = []
    for item in targets:
        if not isinstance(item, dict) or set(item) != {'pair', 'ny_date'} or item['pair'] not in PAIRS:
            raise ValueError('invalid private research target')
        date = dt.date.fromisoformat(item['ny_date'])
        if date.weekday() >= 5 or not dt.date(2025, 1, 1) <= date < dt.datetime.fromtimestamp(now, NY).date():
            raise ValueError('invalid historical NY session')
        identities.append((item['pair'], item['ny_date']))
    if len(set(identities)) != len(identities):
        raise ValueError('duplicate historical target')
    if previous is not None and (not isinstance(previous, dict) or previous.get('schema') != SCHEMA
                                 or previous.get('targets') != targets
                                 or not isinstance(previous.get('results'), dict)):
        raise ValueError('research receipt identity changed')
    results = dict(previous['results']) if previous else {}
    calls = 0
    for pair, day in identities:
        ident = pair.replace('/', '') + ':' + day
        if ident in results:
            continue
        if (calls >= MAX_PER_RUN or
                budget.get('utc_day') != dt.datetime.fromtimestamp(now, dt.timezone.utc).date().isoformat() or
                budget.get('provider_daily_exhausted') or
                budget.get('credits', 0) >= budget.get('daily_limit', 800) - budget.get('reserve', 80) - 1):
            break
        delay = quota.delay(time.monotonic())
        if time.monotonic() + delay + 20 >= deadline:
            break
        if delay:
            time.sleep(delay)
        quota.reserve(time.monotonic())
        calls += 1
        budget['requests'] += 1
        budget['credits'] += 1
        end = dt.datetime.combine(dt.date.fromisoformat(day), dt.time(17), NY).astimezone(dt.timezone.utc)
        start = end - dt.timedelta(days=1)
        request = {'symbol': pair, 'interval': '1h', 'timezone': 'UTC',
                   'start_date': start.strftime('%Y-%m-%d %H:%M:%S'),
                   'end_date': (end-dt.timedelta(hours=1)).strftime('%Y-%m-%d %H:%M:%S'),
                   'apikey': key}
        result = {'pair': pair, 'ny_date': day, 'provider': 'Twelve Data',
                  'requested_timezone': 'UTC', 'received_at': int(time.time()),
                  'status': 'unavailable', 'rows': []}
        try:
            response = session.get('https://api.twelvedata.com/time_series', params=request, timeout=(5, 12))
            quota.observe(response.headers, time.time(), time.monotonic())
            try:
                credits = max(1, int(response.headers.get('api-credits-request', '1')))
            except (TypeError, ValueError):
                credits = 1
            budget['credits'] += credits - 1
            if response.status_code == 429:
                budget['provider_daily_exhausted'] = True
            elif response.ok:
                payload = response.json()
                if isinstance(payload, dict) and isinstance(payload.get('values'), list):
                    rows = [parse_row(row, 3600, now) for row in payload['values']]
                    rows = sorted({row['timestamp']: row for row in rows if row}.values(), key=lambda row: row['timestamp'])
                    expected = list(range(int(start.timestamp()), int(end.timestamp()), 3600))
                    result['rows'] = [row for row in rows if row['timestamp'] in expected]
                    result['status'] = 'complete' if [row['timestamp'] for row in result['rows']] == expected else 'incomplete'
        except (requests.RequestException, ValueError, TypeError, KeyError):
            pass
        results[ident] = result
        if budget.get('provider_daily_exhausted'):
            break
    return {'schema': SCHEMA, 'targets': targets, 'results': results,
            'scope': 'private_research_not_decision_or_feed'}, calls
