"""Explicit NY-close server convention, not every broker's MT4 timezone."""
from datetime import datetime
from zoneinfo import ZoneInfo

CALENDAR = 'mt4_ny_close_h4_v1'
NY = ZoneInfo('America/New_York')


def h4_start(stamp):
    offset = int(datetime.fromtimestamp(stamp, NY).utcoffset().total_seconds()) + 7*3600
    return (int(stamp)+offset)//14400*14400-offset


def expected_h4(now):
    # Look at actual UTC instants so DST is handled without naive local clocks.
    starts = {h4_start(int(now)-i*3600) for i in range(10)}
    return max(t for t in starts if t+14400 <= int(now))


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
