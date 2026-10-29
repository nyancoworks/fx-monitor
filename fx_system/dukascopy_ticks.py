"""Dukascopy tick decoding helpers used by the existing M5 recovery path.

Dukascopy .bi5 files are LZMA-compressed 20-byte tick records:
milliseconds into UTC hour, ask/bid integer prices, ask/bid volumes.
"""
from __future__ import annotations
import datetime as dt
import lzma
import struct

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
