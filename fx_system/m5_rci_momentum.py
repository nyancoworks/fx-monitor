"""M5 RCI 9/26/52 descriptive momentum observation on completed candles.

No proprietary strategy reproduction, forecast, or entry permission.
"""
from __future__ import annotations
import math
from .indicator_research import rci_series

def m5_history_diagnostic(rows, required=54):
    """Describe real completed M5 bars; never synthesize candles or hide gaps."""
    if not isinstance(rows,list):
        return {"status":"insufficient","required_bars":required,"available_bars":0,"missing_bars":None}
    sample=rows[-required:]
    stamps=[b.get("timestamp") for b in sample if isinstance(b,dict)]
    if len(stamps)!=len(sample) or any(type(t) is not int or t%300 for t in stamps):
        return {"status":"invalid","required_bars":required,"available_bars":len(sample),"missing_bars":None}
    gaps=[{"from":a+300,"to":b-300,"missing_bars":(b-a)//300-1}
          for a,b in zip(stamps,stamps[1:]) if b-a>300]
    if any(b<=a for a,b in zip(stamps,stamps[1:])):
        return {"status":"invalid","required_bars":required,"available_bars":len(sample),"missing_bars":None}
    return {"status":"complete" if len(sample)>=required and not gaps else
            "gapped" if gaps else "insufficient",
            "required_bars":required,"available_bars":len(sample),
            "missing_bars":sum(g["missing_bars"] for g in gaps),
            "gaps":gaps[:8],"last_timestamp":stamps[-1] if stamps else None}

def observe_m5_rci(rows, direction):
    result={"status":"unverified","direction":direction,"advisory_only":True,
            "rci":{}}
    if not isinstance(rows,list) or len(rows)<54:
        return {**result,"reason":"M5 history insufficient","required_bars":54,
                "available_bars":len(rows) if isinstance(rows,list) else 0}
    sample=rows[-54:]
    prev=None
    closes=[]
    for row in sample:
        if not isinstance(row,dict):
            return {**result,"reason":"Invalid candle"}
        stamp=row.get("timestamp")
        close=row.get("close")
        if (type(stamp) is not int or stamp%300 or
                type(close) not in (int,float) or not math.isfinite(close) or close<=0):
            return {**result,"reason":"M5 candle invalid"}
        if prev is not None and stamp-prev!=300:
            return {**result,"reason":"M5 gap in latest 54 bars",
                    "gap_start":prev+300,"gap_end":stamp-300,
                    "missing_bars":max(0,(stamp-prev)//300-1)}
        prev=stamp
        closes.append(close)
    observations={}
    for period in (9,26,52):
        series=rci_series(closes,period)
        before,previous,current=series[-3:]
        if before is None or previous is None or current is None:
            return {**result,"reason":"RCI history insufficient"}
        slope=current-previous
        prior_slope=previous-before
        observations[str(period)]={"value":round(current,3),
                                    "previous":round(previous,3),
                                    "change":round(slope,3),
                                    "turn":("up" if prior_slope<0 and slope>0 else
                                            "down" if prior_slope>0 and slope<0 else "none"),
                                    "movement":("rising" if slope>0 else
                                                "falling" if slope<0 else "flat")}
    for fast,slow in (("9","26"),("9","52"),("26","52")):
        a,b=observations[fast],observations[slow]
        # A cross requires both previous and current values; equality is ambiguous.
        previous_diff=a["previous"]-b["previous"]
        current_diff=a["value"]-b["value"]
        observations[fast]["cross_"+slow]=(
            "up" if previous_diff<0 and current_diff>0 else
            "down" if previous_diff>0 and current_diff<0 else "none")
    # A one-bar RCI change is a descriptive observation, never a reversal signal.
    short=observations["9"]["movement"]
    against=(short=="rising" if direction=="short" else
             short=="falling" if direction=="long" else None)
    return {**result,"status":"calculated","rci":observations,
            "short_term_against_direction":against,
            "last_timestamp":prev,
            "reason":"Completed-candle RCI turn/cross observations are descriptive, not confirmed entry signals"}
