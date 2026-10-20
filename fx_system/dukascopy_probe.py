"""Non-production Dukascopy connectivity probe. Does not alter trading snapshots.

Dukascopy .bi5 files are LZMA-compressed 20-byte tick records:
milliseconds into UTC hour, ask/bid integer prices, ask/bid volumes.
"""
from __future__ import annotations
import datetime as dt
import lzma
import struct
import socket
import requests

TICK = struct.Struct(">IIIff")

def tick_url(pair: str, hour: dt.datetime) -> str:
    if hour.tzinfo is None:
        raise ValueError("timezone-aware UTC datetime required")
    hour = hour.astimezone(dt.timezone.utc)
    if len(pair) != 6 or not pair.isalpha():
        raise ValueError("invalid pair")
    return (f"https://datafeed.dukascopy.com/datafeed/{pair.upper()}/"
            f"{hour.year}/{hour.month-1:02d}/{hour.day:02d}/{hour.hour:02d}h_ticks.bi5")

def decode_ticks(payload: bytes, pair: str):
    raw = lzma.decompress(payload)
    if len(raw) % TICK.size:
        raise ValueError("invalid tick record size")
    scale = 1000 if pair.upper().endswith("JPY") else 100000
    ticks = []
    for ms, ask, bid, av, bv in TICK.iter_unpack(raw):
        if ms >= 3600000 or ask < bid or bid == 0:
            raise ValueError("invalid Dukascopy tick")
        ticks.append({"ms": ms, "bid": bid / scale, "ask": ask / scale,
                      "bid_volume": bv, "ask_volume": av})
    return ticks

def ticks_to_m5(ticks, hour):
    """Aggregate bid ticks into closed 5-minute candles; omit empty buckets."""
    if hour.tzinfo is None:
        raise ValueError("timezone-aware hour required")
    start = int(hour.timestamp())
    buckets = {}
    for tick in ticks:
        index = tick["ms"] // 300000
        price = tick["bid"]
        if not 0 <= index < 12 or not price > 0:
            raise ValueError("invalid tick")
        b = buckets.setdefault(index, [])
        b.append(price)
    return [{"timestamp": start + index * 300, "open": prices[0],
             "high": max(prices), "low": min(prices), "close": prices[-1],
             "tick_count": len(prices)}
            for index, prices in sorted(buckets.items())]


def compare_ohlc(reference_bars, candidate_bars, fields=("open","high","low","close")):
    """Match UTC timestamps, quantify price differences without asserting equality."""
    reference={r["timestamp"]:r for r in reference_bars}
    matched=[(reference[r["timestamp"]],r) for r in candidate_bars
             if r["timestamp"] in reference]
    return {"matched_bars":len(matched),
            "max_abs_diff":{field:max((abs(a[field]-b[field]) for a,b in matched),default=None)
                            for field in fields},
            "identical_bars":sum(all(a[field]==b[field] for field in fields) for a,b in matched)}

def compare_m5(dukascopy_bars, twelve_bars):
    """Compare exact matching UTC candle opens; do not combine providers."""
    reference = {r["timestamp"]: r for r in twelve_bars}
    matched = []
    for row in dukascopy_bars:
        other = reference.get(row["timestamp"])
        if other is None:
            continue
        matched.append({"timestamp": row["timestamp"],
                        "close_diff": row["close"] - other["close"],
                        "high_diff": row["high"] - other["high"],
                        "low_diff": row["low"] - other["low"]})
    return {"status": "compared" if matched else "no_matching_candles",
            "matched_bars": len(matched),
            "max_abs_close_diff": max((abs(x["close_diff"]) for x in matched), default=None),
            "max_abs_high_diff": max((abs(x["high_diff"]) for x in matched), default=None),
            "max_abs_low_diff": max((abs(x["low_diff"]) for x in matched), default=None)}


def diagnose_connection(host="datafeed.dukascopy.com", port=443):
    """Diagnostic only: distinguish DNS failure from TCP connectivity failure."""
    try:
        addresses=socket.getaddrinfo(host,port,type=socket.SOCK_STREAM)
    except OSError as exc:
        return {"network_stage":"dns","network_error":type(exc).__name__}
    if not addresses:
        return {"network_stage":"dns","network_error":"no_addresses"}
    try:
        with socket.create_connection((host,port),timeout=3):
            pass
    except OSError as exc:
        return {"network_stage":"tcp","network_error":type(exc).__name__}
    return {"network_stage":"https","tcp_connectivity":"ok"}


def probe(pair="EURUSD", hour=None, timeout=12):
    if hour is None:
        hour = dt.datetime.now(dt.timezone.utc).replace(minute=0, second=0, microsecond=0) - dt.timedelta(hours=3)
    url = tick_url(pair, hour)
    response = requests.get(url, timeout=timeout)
    response.raise_for_status()
    if not response.content or response.content[:1] == b"<":
        raise ValueError("empty or non-binary Dukascopy response")
    ticks = decode_ticks(response.content, pair)
    candles = ticks_to_m5(ticks, hour)
    import json
    import pathlib
    cache_path = pathlib.Path(__file__).resolve().parents[1] / "data" / "cache.json"
    try:
        cache = json.loads(cache_path.read_text())
        comparison = compare_m5(candles, cache.get(pair.upper(), {}).get("m5", []))
    except (OSError, ValueError, TypeError):
        comparison = {"status": "reference_unavailable", "matched_bars": 0,
                      "error": "reference cache unavailable"}
    return {"pair": pair, "utc_hour": hour.isoformat(), "url": url,
            "tick_count": len(ticks), "m5_count": len(candles), "m5_last_close": candles[-1]["close"] if candles else None, "twelve_comparison": comparison, "status": "ok" if ticks else "empty",
            "first_bid": ticks[0]["bid"] if ticks else None,
            "last_bid": ticks[-1]["bid"] if ticks else None}

if __name__ == "__main__":
    import json
    try:
        print(json.dumps(probe(), ensure_ascii=False))
    except requests.ConnectTimeout:
        print(json.dumps({"status": "unavailable", "failure_type": "connect_timeout", "host": "datafeed.dukascopy.com", **diagnose_connection()}))
        raise SystemExit(1)
    except requests.ReadTimeout:
        print(json.dumps({"status": "unavailable", "failure_type": "read_timeout", "host": "datafeed.dukascopy.com"}))
        raise SystemExit(1)
    except requests.HTTPError as exc:
        response=exc.response
        status=response.status_code if response is not None else None
        if status==429:
            retry_after=response.headers.get("Retry-After")
            print(json.dumps({"status":"unavailable","failure_type":"http_429_rate_limited","host":"datafeed.dukascopy.com","retry_after":retry_after}))
        else:
            print(json.dumps({"status":"error","failure_type":"http_error","http_status":status,"host":"datafeed.dukascopy.com"}))
        raise SystemExit(1)
    except (requests.RequestException, lzma.LZMAError, ValueError) as exc:
        print(json.dumps({"status": "error", "failure_type": type(exc).__name__, "reason": str(exc)}))
        raise SystemExit(1)
