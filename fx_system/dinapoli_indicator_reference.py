"""Closed-bar DiNapoli indicator references; never a trade permission gate.

MACD coefficients and Original Stochastic formulas follow the author-side
CQG settings and CQG calculation documentation. External chart parity is
not verified; these values remain advisory references.
"""
from math import isfinite


def _prices(values):
    if not isinstance(values, (list, tuple)) or not values:
        raise ValueError("nonempty price series required")
    if any(type(x) not in (int, float) or not isfinite(x) or x <= 0 for x in values):
        raise ValueError("positive finite prices required")
    return list(values)


def _ema(values, alpha):
    out = [float(values[0])]
    for x in values[1:]:
        out.append(out[-1] + alpha * (x - out[-1]))
    return out


def _smoothed(values, period):
    """CQG Smo: first full-window SMA, then Wilder-style 1/period updates."""
    out = []; seed = []; previous = None
    for value in values:
        if value is None:
            seed = []; previous = None
        elif previous is None:
            seed.append(value)
            if len(seed) == period:
                previous = sum(seed) / period
        else:
            previous += (value-previous) / period
        out.append(previous)
    return out


def indicator_reference(rows):
    """Calculate only from caller-verified closed OHLC candles.

    Caller must verify timestamp ordering, closure, source and continuity.
    No Fibonacci anchor is inferred; no entry decision is made.
    """
    if not isinstance(rows, (list, tuple)) or not rows:
        return {"status": "insufficient", "advisory_only": True}
    try:
        timestamps = [row["timestamp"] for row in rows]
        if any(type(t) is not int for t in timestamps) or any(
            b <= a for a, b in zip(timestamps, timestamps[1:])
        ):
            raise ValueError("timestamps must increase")
        high = _prices([row["high"] for row in rows])
        low = _prices([row["low"] for row in rows])
        close = _prices([row["close"] for row in rows])
        if any(not (l <= c <= h) for l, c, h in zip(low, close, high)):
            raise ValueError("invalid candle range")
    except (KeyError, TypeError, ValueError):
        return {"status": "invalid", "advisory_only": True}
    if len(rows) < 8:
        return {"status": "insufficient", "advisory_only": True}
    fast, slow = _ema(close, .213), _ema(close, .108)
    macd_line = [a-b for a,b in zip(fast, slow)]
    signal = _ema(macd_line, .199)
    closing_ranges = []; total_ranges = []
    for i in range(7, len(rows)):
        hi, lo = max(high[i-7:i+1]), min(low[i-7:i+1])
        closing_ranges.append(close[i]-lo)
        total_ranges.append(hi-lo)
    # Original is a ratio of separately smoothed ranges, not a smoothed ratio.
    numerator = _smoothed(closing_ranges, 3)
    denominator = _smoothed(total_ranges, 3)
    ks = [100*n/r if n is not None and r is not None and r>0 else None
          for n, r in zip(numerator, denominator)]
    ds = _smoothed(ks, 3)
    k, d = ks[-1], ds[-1]
    previous_k, previous_d = (ks[-2], ds[-2]) if len(ks)>1 else (None, None)
    return {
        "status": "calculated",
        "last_timestamp": timestamps[-1],
        "macd": {"line": macd_line[-1], "signal": signal[-1],
                 "histogram": macd_line[-1]-signal[-1]},
        "preferred_stochastic": {"slow_k": k, "slow_d": d,
            "algorithm": "cqg_original_ratio_of_smoothed_ranges_v2",
            "period": 8, "k_smoothing": 3, "d_smoothing": 3,
            "smoothing_seed": "first_three_valid_values_sma",
            "status": "calculated" if k is not None and d is not None else
                      "warmup_or_zero_smoothed_range",
            "previous_k":previous_k,"previous_d":previous_d,
            "k_movement":("unverified" if k is None or previous_k is None else
                          "rising" if k>previous_k else "falling" if k<previous_k else "flat"),
            "cross":("unverified" if any(v is None for v in (k,d,previous_k,previous_d)) else
                     "up" if previous_k<=previous_d and k>d else
                     "down" if previous_k>=previous_d and k<d else "none")},
        "assumptions": ["first_observation_ema_seed",
                        "cqg_original_separately_smoothed_ranges",
                        "three_observation_sma_seed_then_one_third_updates",
                        "chart_parity_not_verified"],
        "advisory_only": True,
    }
