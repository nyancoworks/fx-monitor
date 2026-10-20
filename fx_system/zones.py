"""Reproducible H1 pivot zone evidence; proposal only, not a verified entry zone."""
from __future__ import annotations
import math
from .core import technical


def propose_h1_zone(h1, direction, invalidation):
    """Last confirmed 2L/2R pivot candle range, without inventing a price band.

    A proposal is not independent zone verification or an executable setup.
    """
    if direction not in ("long","short") or len(h1)<15:
        return {"status":"unavailable","reason":"direction_or_history_missing"}
    rows=sorted(h1,key=lambda r:r["timestamp"])
    if any(type(r.get("timestamp")) is not int or
           any(type(r.get(k)) not in (int,float) or not math.isfinite(r[k]) for k in ("high","low"))
           for r in rows):
        return {"status":"unavailable","reason":"invalid_candle"}
    analysis=technical(rows)
    key="confirmed_swing_lows" if direction=="long" else "confirmed_swing_highs"
    swings=analysis.get(key,[])
    if not swings:
        return {"status":"unavailable","reason":"confirmed_pivot_missing"}
    pivot=swings[-1]
    matches=[r for r in rows if r["timestamp"]==pivot["timestamp"]]
    if len(matches)!=1:
        return {"status":"unavailable","reason":"pivot_candle_missing"}
    candle=matches[0]
    low,high=candle["low"],candle["high"]
    if low<=0 or high<=low or type(invalidation) not in (int,float) or not math.isfinite(invalidation):
        return {"status":"unavailable","reason":"invalid_zone_bounds"}
    if abs(pivot["price"]-invalidation)>1e-8:
        return {"status":"unavailable","reason":"invalidation_pivot_mismatch"}
    return {"status":"proposed","low":low,"high":high,"pivot_timestamp":pivot["timestamp"],
            "pivot_price":pivot["price"],"basis":"confirmed_H1_2left_2right_pivot_candle",
            "verified":False}
