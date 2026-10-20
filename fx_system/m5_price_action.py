"""Independent completed M5 price-action observation for H1-led daytrade review."""
from __future__ import annotations
import math

def observe_m5_price_action(bars, direction):
    result={"status":"unverified","pattern":None,"direction":direction,
            "entry_permission":False,"advisory_only":True}
    if direction not in ("long","short") or not isinstance(bars,list) or len(bars)<4:
        return {**result,"reason":"H1 direction or M5 observation window unavailable"}
    window=bars[-4:]
    for bar in window:
        if not isinstance(bar,dict) or type(bar.get("timestamp")) is not int:
            return {**result,"reason":"M5 candle timestamp invalid"}
        vals=[bar.get(k) for k in ("open","high","low","close")]
        if any(type(v) not in (int,float) or not math.isfinite(v) or v<=0 for v in vals):
            return {**result,"reason":"M5 OHLC invalid"}
        o,h,l,c=vals
        if not l<=min(o,c)<=max(o,c)<=h:
            return {**result,"reason":"M5 OHLC inconsistent"}
    if any(window[i+1]["timestamp"]-window[i]["timestamp"]!=300 for i in range(3)):
        return {**result,"reason":"M5 completed candles not contiguous"}
    latest=window[-1]
    high=max(x["high"] for x in window[:-1])
    low=min(x["low"] for x in window[:-1])
    breakout=latest["close"]>high if direction=="long" else latest["close"]<low
    rejection=(latest["close"]>latest["open"] and latest["low"]<min(x["low"] for x in window[-3:-1])
               if direction=="long" else
               latest["close"]<latest["open"] and latest["high"]>max(x["high"] for x in window[-3:-1]))
    pattern="three_bar_close_breakout" if breakout else "two_bar_rejection" if rejection else None
    return {**result,"status":"watch_pattern" if pattern else "waiting",
            "pattern":pattern,"last_timestamp":latest["timestamp"],
            "reference_high":high,"reference_low":low,
            "reason":"completed M5 price action; execution price and macro/event gates unverified"}
