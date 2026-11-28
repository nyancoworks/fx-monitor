"""Content identity and lossless partitioned NY17 event replay."""
import datetime as dt
import hashlib
import json
from collections import defaultdict

from ..monitor_pairs import PAIR_KEYS as PAIRS

MAX_RAW = 8 * 1024 * 1024


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def month(timestamp):
    return dt.datetime.fromtimestamp(timestamp, dt.timezone.utc).strftime("%Y-%m")


def append(store, segments, offset, events):
    groups = defaultdict(list)
    for index, event in enumerate(events, offset):
        partitions = defaultdict(list)
        for position, change in enumerate(event["changes"]):
            partitions[month(change["timestamp"])].append([position, change])
        metadata = {key: value for key, value in event.items() if key != "changes"}
        for period, changes in partitions.items():
            groups[event["pair"], period].append([index, metadata, changes])
    refs = dict(segments)
    for (pair, period), fragments in groups.items():
        bucket = f"{pair}/{period}"
        key = store.put(fragments)
        existing = refs.get(bucket, [])
        if key not in existing:
            refs[bucket] = [*existing, key]
    return refs


def restore(store, manifest, *, pair=None, start=None, end=None):
    fragments = {}
    for bucket, keys in manifest.items():
        symbol, period = bucket.split("/")
        if (pair is not None and symbol != pair or
                start is not None and period < month(start) or
                end is not None and period > month(end - 1)):
            continue
        for key in keys:
            for index, metadata, changes in store.get(key):
                original, collected = fragments.setdefault(index, (metadata, {}))
                if original != metadata:
                    raise ValueError("conflicting event metadata")
                for position, change in changes:
                    timestamp = change["timestamp"]
                    if metadata["pair"] != symbol or month(timestamp) != period:
                        raise ValueError("invalid segment placement")
                    if (start is None or timestamp >= start) and (end is None or timestamp < end):
                        if position in collected:
                            raise ValueError("duplicate event change")
                        collected[position] = change
    events = []
    rows = defaultdict(dict)
    for _, (metadata, changes) in sorted(fragments.items()):
        if not changes:
            continue
        ordered = [change for _, change in sorted(changes.items())]
        events.append({**metadata, "changes": ordered})
        prices = rows[metadata["pair"]]
        for change in ordered:
            stamp = str(change["timestamp"])
            if prices.get(stamp) != change["old"]:
                raise ValueError("broken revision chain")
            prices[stamp] = change["new"]
    return events, dict(rows)
