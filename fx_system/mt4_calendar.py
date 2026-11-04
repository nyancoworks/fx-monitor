"""Explicit NY-close server convention, not every broker's MT4 timezone."""
from datetime import datetime
from zoneinfo import ZoneInfo

CALENDAR = 'mt4_ny_close_h4_v1'
NY = ZoneInfo('America/New_York')
CONTINUITY = 'mt4_ny_close_complete_h4_v2'


def complete_start(stamp):
    return h4_start(stamp) == stamp and all(h4_start(stamp+i*3600) == stamp for i in range(4))


def next_complete_start(stamp):
    # A server-clock change can leave a partial bucket. It is not a full H4
    # candle and must neither be invented nor mistaken for a missing full bar.
    return next(t for t in range(stamp+14400, stamp+12*3600, 3600) if complete_start(t))


def sequence_valid(rows):
    if not rows:
        return False
    stamps = [row.get('timestamp') for row in rows]
    if any(type(t) is not int or not complete_start(t) for t in stamps):
        return False
    return all(b == next_complete_start(a) for a,b in zip(stamps,stamps[1:]))


def h4_start(stamp):
    offset = int(datetime.fromtimestamp(stamp, NY).utcoffset().total_seconds()) + 7*3600
    return (int(stamp)+offset)//14400*14400-offset


def expected_h4(now):
    # Look at actual UTC instants so DST is handled without naive local clocks.
    starts = {h4_start(int(now)-i*3600) for i in range(10)}
    return max(t for t in starts if t+14400 <= int(now) and complete_start(t))


def aggregate_h4(rows):
    buckets = {}
    for row in rows:
        stamp = row['timestamp']
        if type(stamp) is not int or stamp % 3600:
            raise ValueError('H4 requires UTC-labelled whole H1 observations')
        bucket = buckets.setdefault(h4_start(stamp), {})
        if stamp in bucket:
            raise ValueError('duplicate H1 observation')
        bucket[stamp] = row
    result = []
    for start, values in sorted(buckets.items()):
        expected = [start+i*3600 for i in range(4)]
        if any(t not in values or h4_start(t) != start for t in expected):
            continue
        group = [values[t] for t in expected]
        result.append({'timestamp':start, 'open':group[0]['open'],
            'high':max(r['high'] for r in group), 'low':min(r['low'] for r in group),
            'close':group[-1]['close']})
    return result
