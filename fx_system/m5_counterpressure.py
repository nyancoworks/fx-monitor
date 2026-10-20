"""Advisory M5 counterpressure against an independently verified H1 direction.

Closed candles only. No indicator gate or execution clearance is inferred.
"""
from __future__ import annotations
import math

def assess_m5_counterpressure(bars, direction):
    base={"status":"unverified","direction":direction,"against_direction":False,
          "observation_only":True}
    if direction not in ("long","short") or not isinstance(bars,list) or len(bars)<4:
        return {**base,"reason":"M5 series or H1 direction unavailable"}
    window=bars[-4:]
    for candle in window:
        if not isinstance(candle,dict) or type(candle.get("timestamp")) is not int:
            return {**base,"reason":"Invalid M5 timestamp"}
        values=[candle.get(k) for k in ("open","high","low","close")]
        if any(type(v) not in (int,float) or not math.isfinite(v) or v<=0 for v in values):
            return {**base,"reason":"Invalid M5 OHLC"}
        o,h,l,c=values
        if not l<=min(o,c)<=max(o,c)<=h:
            return {**base,"reason":"Inconsistent M5 OHLC"}
    if any(window[i+1]["timestamp"]-window[i]["timestamp"]!=300 for i in range(3)):
        return {**base,"reason":"M5 closed candles are not contiguous"}
    closes=[c["close"] for c in window]
    rising=closes[-3]<closes[-2]<closes[-1] and closes[-1]>closes[0]
    falling=closes[-3]>closes[-2]>closes[-1] and closes[-1]<closes[0]
    against=(rising if direction=="short" else falling)
    return {**base,"status":"counter_rebound" if against else "no_counter_rebound",
            "against_direction":against,"last_timestamp":window[-1]["timestamp"],
            "last_close":closes[-1],
            "reason":("Three consecutive M5 closes move against H1 direction"
                      if against else "No three-close counterdirection sequence observed")}
