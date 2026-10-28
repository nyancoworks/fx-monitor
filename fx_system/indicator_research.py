"""Non-trading indicator research on caller-verified closed candles."""
from __future__ import annotations
import math
from .advisory_indicators import sma_series, stddev_bands
from .indicator_calendar import NY17, ny17_sequence_valid


def rci_series(values, period):
    """Spearman rank correlation of chronological time and price, ties averaged."""
    if type(period) is not int or period < 2:
        raise ValueError("RCI period must be an integer >= 2")
    if any(type(v) not in (int, float) or not math.isfinite(v) for v in values):
        raise ValueError("prices must be finite")
    result = [None] * len(values)
    for end in range(period - 1, len(values)):
        window = values[end - period + 1:end + 1]
        sorted_indices = sorted(range(period), key=lambda i: window[i])
        ranks = [0.0] * period
        pos = 0
        while pos < period:
            stop = pos + 1
            while stop < period and window[sorted_indices[stop]] == window[sorted_indices[pos]]:
                stop += 1
            rank = (pos + 1 + stop) / 2
            for k in range(pos, stop):
                ranks[sorted_indices[k]] = rank
            pos = stop
        center = (period + 1) / 2
        numerator = sum((i + 1 - center) * (rank - center) for i, rank in enumerate(ranks))
        variance = sum((rank - center) ** 2 for rank in ranks)
        time_variance = period * (period * period - 1) / 12
        result[end] = 100 * numerator / math.sqrt(time_variance * variance) if variance else 0.0
    return result


def super_bollinger_context(rows, period=21, lag=21, *, timeframe=None, calendar=None):
    """Closed-bar, read-only Murphy-style band and lagging-span context.

    Compare today's close plotted lag bars back against the historical candle
    range at that plotted location, not merely its historical closing price.
    """
    result={"status":"insufficient","advisory_only":True,
            "period":period,"lag":lag,"mt4_chikou_parameter":lag-1}
    if len(rows)<max(period+1,lag+1):
        return result
    ordered=sorted(rows,key=lambda x:x["timestamp"])
    if any(type(row.get("timestamp")) is not int or
           type(row.get("close")) not in (int,float) or
           type(row.get("high")) not in (int,float) or
           type(row.get("low")) not in (int,float) or
           not all(math.isfinite(row[k]) for k in ("close","high","low")) or
           row["low"]>row["high"] or not row["low"]<=row["close"]<=row["high"]
           for row in ordered):
        return {**result,"status":"invalid"}
    if any("open" in row and (type(row["open"]) not in (int,float) or
           not math.isfinite(row["open"]) or
           not row["low"]<=row["open"]<=row["high"]) for row in ordered):
        return {**result,"status":"invalid"}
    if any(b["timestamp"]<=a["timestamp"] for a,b in zip(ordered,ordered[1:])):
        return {**result,"status":"invalid"}
    # Compare only within a continuous time series. A weekend or provider gap
    # must not be silently treated as the same lag displacement.
    recent=ordered[-max(period+1,lag+1):]
    steps=[b["timestamp"]-a["timestamp"] for a,b in zip(recent,recent[1:])]
    if calendar == NY17:
        contiguous = ny17_sequence_valid(recent,timeframe)
    else:
        contiguous = not steps or all(step>0 and step==steps[-1] for step in steps)
    if not contiguous:
        return {**result,"status":"noncontiguous"}
    closes=[row["close"] for row in ordered]
    bands=stddev_bands(closes,period)
    current,previous=bands[-1],bands[-2]
    past=ordered[-1-lag]
    close=closes[-1]
    location=("above" if close>past["high"] else
              "below" if close<past["low"] else "inside")
    middle=current["middle"]
    slope=middle-previous["middle"]
    return {**result,"status":"calculated",
            "centerline":middle,"centerline_slope":slope,
            "last_close":close,
            "centerline_direction":"up" if slope>0 else "down" if slope<0 else "flat",
            "bands":current["bands"],
            "bandwidth_3sigma":6*current["stddev"],
            "lagging_span":{"location":location,
                "compared_candle_timestamp":past["timestamp"],
                "historical_high":past["high"],"historical_low":past["low"]},
            "last_timestamp":ordered[-1]["timestamp"]}

def _rci_observation(series, *, extreme_level=80):
    """Observed-bar description; +/-80 is a disclosed research convention."""
    value = series[-1] if series else None
    previous = series[-2] if len(series) > 1 else None
    before = series[-3] if len(series) > 2 else None
    change = value - previous if value is not None and previous is not None else None
    prior_change = previous - before if previous is not None and before is not None else None
    side = ("upper" if value is not None and value >= extreme_level else
            "lower" if value is not None and value <= -extreme_level else "inside")
    run = 0
    if side != "inside":
        for sample in reversed(series):
            if sample is None or (sample < extreme_level if side == "upper" else sample > -extreme_level):
                break
            run += 1
    return {
        "value": value, "previous": previous, "change": change,
        "movement": ("unverified" if change is None else "rising" if change > 0 else
                     "falling" if change < 0 else "flat"),
        "turn": ("unverified" if prior_change is None or change is None else
                 "up" if prior_change < 0 and change > 0 else
                 "down" if prior_change > 0 and change < 0 else "none"),
        "extreme_run": {"level": extreme_level,
                        "zone": side if value is not None else "unverified",
                        "observed_bars": run if value is not None else None,
                        "basis": "consecutive_observed_values_not_elapsed_time",
                        "left_censored": bool(run and run == sum(v is not None for v in series))},
    }


def research_snapshot(rows, *, rci_periods=(9, 26, 52), band_period=21, lag=21):
    """Research only; never a trading grade or a verified proprietary signal."""
    ordered = sorted(rows, key=lambda x: x["timestamp"])
    closes = [r["close"] for r in ordered]
    if any(type(v) not in (int, float) or not math.isfinite(v) for v in closes):
        raise ValueError("prices must be finite")
    rci_history = {str(p): rci_series(closes, p) for p in rci_periods}
    rci = {p: (series[-1] if series else None) for p, series in rci_history.items()}
    observations = {p: _rci_observation(series) for p, series in rci_history.items()}
    for fast, slow in (("9", "26"), ("9", "52"), ("26", "52")):
        if fast not in observations or slow not in observations:
            continue
        a, b = observations[fast], observations[slow]
        values = (a["previous"], b["previous"], a["value"], b["value"])
        if any(value is None for value in values):
            cross = "unverified"
        else:
            old, current = values[0] - values[1], values[2] - values[3]
            cross = "up" if old < 0 and current > 0 else "down" if old > 0 and current < 0 else "none"
        a["cross_" + slow] = cross
    sma200 = sma_series(closes, 200)[-1] if closes else None
    bands = stddev_bands(closes, band_period)
    current = bands[-1] if bands else None
    previous = bands[-2] if len(bands) > 1 else None
    lag_comparison = None if len(closes) <= lag else (
        "above" if closes[-1] > closes[-1 - lag] else
        "below" if closes[-1] < closes[-1 - lag] else "equal"
    )
    return {
        "status": "calculated" if current else "insufficient",
        "candles": len(closes),
        "rci": rci,
        "rci_observation": {
            "periods": observations,
            "last_timestamp": ordered[-1]["timestamp"] if ordered else None,
            "basis": "supplied_observed_bars",
            "extreme_level_basis": "independent_descriptive_convention_not_a_teacher_rule",
        },
        "sma100": sma_series(closes,100)[-1] if closes else None,
        "sma200": sma200,
        "band_research": None if current is None else {
            "middle": current["middle"],
            "bands": current["bands"],
            "middle_slope": None if previous is None else current["middle"] - previous["middle"],
            "bandwidth_3sigma": 6 * current["stddev"],
            "bandwidth_change": None if previous is None else 6 * (current["stddev"] - previous["stddev"]),
            "lagged_close_comparison": lag_comparison,
            "lag": lag,
        },
        "super_bollinger_chart_parity_verified": False,
        "advisory_only": True,
        "entry_confirmed": False,
    }

