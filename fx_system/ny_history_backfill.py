"""One-time private backfill. No market requests until the full plan fits."""
import argparse
from collections import defaultdict
import datetime as dt
import json
import os
import time

from diagnostics.issue43_ny_runtime import NYSidecar
from diagnostics.issue43_ny_shadow import build_shadow, close_utc, latest_closed_date
from .core import ny17_frames
from .indicator_calendar import ny17_sequence_valid
from .ny_history_segments import WEEKDAY_WINDOW, encode_segment, read_segment
from .ny_observed_policy import supported_source, verify_originals
from .private_runtime import CODE_REPOSITORY, git, private_root, push_snapshot, verify_ready

HOUR = 3600
API = 'https://api.twelvedata.com'
BATCH = 5000


def missing_ranges(archived, clock):
    day = latest_closed_date(clock)
    missing = []
    remaining = WEEKDAY_WINDOW
    while remaining:
        if day.weekday() < 5:
            end = int(close_utc(day).timestamp())
            missing.extend(t for t in range(end - 24 * HOUR, end, HOUR) if str(t) not in archived)
            remaining -= 1
        day -= dt.timedelta(days=1)
    ranges = []
    for stamp in sorted(missing):
        # A short range may span a weekend. Retained observations split ranges.
        if (ranges and stamp - ranges[-1][1] <= 72 * HOUR
                and stamp - ranges[-1][0] < BATCH * HOUR
                and not any(str(t) in archived for t in range(ranges[-1][1]+HOUR, stamp, HOUR))):
            ranges[-1][1] = stamp
        else:
            ranges.append([stamp, stamp])
    return ranges


def request_rows(session, key, pair, first, last):
    format_utc = lambda stamp: dt.datetime.fromtimestamp(stamp, dt.timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    symbol = pair[:3] + '/' + pair[3:]
    response = session.get(API + '/time_series', headers={'Authorization': 'apikey ' + key},
                           params={'symbol': symbol, 'interval': '1h', 'timezone': 'UTC',
                                   'start_date': format_utc(first), 'end_date': format_utc(last),
                                   'outputsize': BATCH}, timeout=(5, 15))
    response.raise_for_status()
    payload = response.json()
    meta = payload['meta']
    if (payload.get('status') != 'ok' or meta.get('symbol') != symbol
            or meta.get('interval') != '1h' or meta.get('exchange_timezone', 'UTC') != 'UTC'
            or int(response.headers.get('api-credits-request', '1')) != 1):
        raise ValueError('unverified backfill response')
    rows = {}
    for item in payload['values']:
        stamp = int(dt.datetime.strptime(item['datetime'], '%Y-%m-%d %H:%M:%S')
                    .replace(tzinfo=dt.timezone.utc).timestamp())
        if not first <= stamp <= last or stamp in rows:
            raise ValueError('unexpected timestamp in backfill response')
        rows[stamp] = {'timestamp': stamp, **{field: float(item[field])
                       for field in ('open', 'high', 'low', 'close')}}
    return rows


def macro_counts(rows, clock):
    study = build_shadow(rows, clock, minimum=WEEKDAY_WINDOW)
    frames = ny17_frames(study, int(clock.timestamp()))
    counts = {}
    for tf, candles in frames.items():
        index = max(0, len(candles) - 1)
        while index > 0 and ny17_sequence_valid(candles[index-1:index+1], tf):
            index -= 1
        counts[tf] = {'complete': len(candles), 'latest_contiguous': len(candles) - index}
    return counts


def run(root, key):
    import requests
    from .main import DAILY_LIMIT, DAILY_RESERVE

    directory = root / 'ny17-history'
    if directory.is_symlink():
        raise ValueError('unsafe history directory')
    manifest_path = directory / 'manifest.json'
    if manifest_path.exists() or manifest_path.is_symlink():
        raise ValueError('one-time history backfill already published')
    archive = NYSidecar(root / '.private-ny17').load()
    originals = verify_originals(root / 'evidence' / 'issue43-h1-originals')
    clock = dt.datetime.now(dt.timezone.utc)
    plan = []
    for pair, existing in sorted(archive['archive']['pairs'].items()):
        if not supported_source(archive, pair, originals) or pair in archive['blocked_pairs']:
            raise ValueError('unverified retained history')
        plan.extend((pair, start, end) for start, end in missing_ranges(existing, clock))
    if not plan or len(plan) > 250 or len(archive['archive']['pairs']) != 16:
        raise ValueError('history acquisition outside one-time request limit')
    with requests.Session() as session:
        response = session.get(API + '/api_usage', headers={'Authorization': 'apikey ' + key},
                               timeout=(5, 15))
        response.raise_for_status()
        usage = response.json()
        daily = usage['plan_daily_limit']
        if (type(daily) is not int or type(usage['daily_usage']) is not int
                or type(usage['plan_limit']) is not int or not 1 <= usage['plan_limit'] <= 1000
                or usage['daily_usage'] + len(plan) > min(daily, DAILY_LIMIT) - DAILY_RESERVE):
            raise ValueError('insufficient verified credit budget')
        interval = max(10, 65 / usage['plan_limit'])
        batches = defaultdict(dict)
        for pair, start, end in plan:
            time.sleep(interval)
            for stamp, row in request_rows(session, key, pair, start, end).items():
                if str(stamp) not in archive['archive']['pairs'][pair]:
                    if stamp in batches[pair]:
                        raise ValueError('overlapping acquisition results')
                    batches[pair][stamp] = row
    received_at = int(time.time())
    entries = {}
    blobs = {}
    for pair, bars in batches.items():
        years = defaultdict(list)
        for stamp, row in sorted(bars.items()):
            years[dt.datetime.fromtimestamp(stamp, dt.timezone.utc).year].append(row)
        entries[pair] = []
        for year, rows in sorted(years.items()):
            item, blob = encode_segment(pair, year, received_at, rows)
            entries[pair].append(item)
            blobs[f"{pair}-{year}-{item['sha256']}.json.gz"] = blob
    if not blobs or sum(map(len, blobs.values())) > 16 * 1024 * 1024:
        raise ValueError('backfill capacity or availability unverified')
    directory.mkdir(mode=0o700)
    for name, blob in blobs.items():
        (directory / name).write_bytes(blob)
    for pair, items in entries.items():
        for item in items:
            read_segment(directory, pair, item, received_at)
    report = {}
    for pair, existing in archive['archive']['pairs'].items():
        new = batches.get(pair, {})
        report[pair] = {'before': macro_counts(existing.values(), clock),
                        'after': macro_counts([*existing.values(), *new.values()], clock)}
    manifest_path.write_text(json.dumps({'schema': 1, 'pairs': entries, 'coverage': report,
                                        'requests': len(plan)+1,
                                        'received_counts': {pair: len(rows) for pair, rows in batches.items()}},
                                       sort_keys=True))
    git(root, 'add', '--', 'ny17-history')
    git(root, '-c', 'user.name=github-actions[bot]', '-c',
        'user.email=41898286+github-actions[bot]@users.noreply.github.com',
        'commit', '-m', 'Save verified initial NY17 history segments')
    push_snapshot(root)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--state', required=True)
    args = parser.parse_args()
    try:
        if (os.getenv('GITHUB_REPOSITORY') != CODE_REPOSITORY
                or os.getenv('GITHUB_REF') != 'refs/heads/main'
                or os.getenv('GITHUB_EVENT_NAME') != 'workflow_dispatch'):
            raise ValueError('trusted manual dispatch required')
        root = private_root(args.state)
        verify_ready(root)
        run(root, os.environ['TWELVE_DATA_API_KEY'])
    except Exception:
        print('FX NY17 initial backfill failed')
        return 1
    print('FX NY17 initial backfill saved')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
