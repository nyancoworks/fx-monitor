"""Small, private Dukascopy presence check for historical missing H1 hours.

This is a separate bid-tick source, never a repair to Twelve Data candles or
the canonical archive. Targets and results live only in the private checkout.
"""
import datetime as dt
import lzma
import time

import requests

from .dukascopy_ticks import decode_ticks, tick_url
from .monitor_pairs import PAIRS

SCHEMA = 'private_backup_hour_presence_v1'
MAX_TARGETS = 6
MAX_PER_RUN = 3
MAX_COMPRESSED_BYTES = 1_000_000
MAX_RAW_BYTES = 5_000_000


def probe(config, previous, session, now, deadline):
    if (not isinstance(config, dict) or config.get('schema') != SCHEMA
            or not isinstance(config.get('targets'), list)
            or not 1 <= len(config['targets']) <= MAX_TARGETS):
        raise ValueError('invalid private backup request')
    targets = config['targets']
    identities = []
    for item in targets:
        if not isinstance(item, dict) or set(item) != {'pair', 'hour_utc'} or item['pair'] not in PAIRS:
            raise ValueError('invalid backup target')
        hour = item['hour_utc']
        if type(hour) is not int or hour % 3600 or not 1735689600 <= hour < now - 3600:
            raise ValueError('invalid historical UTC hour')
        identities.append((item['pair'], hour))
    if len(identities) != len(set(identities)):
        raise ValueError('duplicate backup hour')
    if previous is not None and (not isinstance(previous, dict) or previous.get('schema') != SCHEMA
                                 or previous.get('targets') != targets
                                 or not isinstance(previous.get('results'), dict)):
        raise ValueError('backup receipt identity changed')
    results = dict(previous['results']) if previous else {}
    calls = 0
    for pair, stamp in identities:
        ident = pair.replace('/', '') + ':' + str(stamp)
        if ident in results:
            continue
        if calls >= MAX_PER_RUN or time.monotonic() + 12 >= deadline:
            break
        hour = dt.datetime.fromtimestamp(stamp, dt.timezone.utc)
        result = {'pair': pair, 'hour_utc': stamp, 'provider': 'Dukascopy bid ticks',
                  'received_at': int(time.time()), 'status': 'unavailable', 'tick_count': 0}
        try:
            calls += 1  # Count attempted requests, including timeouts.
            response = session.get(tick_url(pair.replace('/', ''), hour), timeout=(3, 8))
            if response.status_code in (403, 429):
                result['status'] = 'access_blocked'
                results[ident] = result
                break
            if response.status_code == 404:
                result['status'] = 'http_404'
            elif response.ok:
                if len(response.content) > MAX_COMPRESSED_BYTES:
                    result['status'] = 'oversize'
                else:
                    decoder = lzma.LZMADecompressor()
                    raw = decoder.decompress(response.content, max_length=MAX_RAW_BYTES + 1)
                    if len(raw) > MAX_RAW_BYTES or not decoder.eof or decoder.unused_data:
                        raise ValueError('invalid bounded tick payload')
                    ticks = decode_ticks(response.content, pair.replace('/', ''))
                    result['tick_count'] = len(ticks)
                    result['status'] = 'ticks_present' if ticks else 'no_ticks'
                    if ticks:
                        bids = [t['bid'] for t in sorted(ticks, key=lambda t: t['ms'])]
                        result['bid_ohlc'] = {'open': bids[0], 'high': max(bids),
                                              'low': min(bids), 'close': bids[-1]}
            else:
                result['status'] = 'http_error'
        except (requests.RequestException, lzma.LZMAError, ValueError, TypeError):
            result['status'] = 'unavailable'
        results[ident] = result
    return {'schema': SCHEMA, 'targets': targets, 'results': results,
            'scope': 'private_source_presence_only_not_canonical_h1'}, calls
