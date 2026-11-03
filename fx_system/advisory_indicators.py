"""Calculation-only moving averages and standard-deviation bands.

Shared numerical helpers for the current Super Bollinger calculation and
historical interpretation. No strategy or trade permission is defined here.
"""
from __future__ import annotations
import math


def _validate(values, period):
    if type(period) is not int or period < 1:
        raise ValueError("period must be a positive integer")
    if any(type(x) not in (int, float) or not math.isfinite(x) for x in values):
        raise ValueError("values must be finite numbers")


def sma_series(values, period):
    """Trailing simple moving average; None before a full window."""
    _validate(values, period)
    out = [None] * len(values)
    running = 0.0
    for i, value in enumerate(values):
        running += value
        if i >= period:
            running -= values[i - period]
        if i >= period - 1:
            out[i] = running / period
    return out



def stddev_bands(values, period=21, multipliers=(1, 2, 3)):
    """SMA-centered population-standard-deviation bands, full windows only.

    The 21-period/1-3 sigma parameters are *research defaults*, not
    verified original Super Bollinger specifications. No lagging span or
    trading signal is inferred here.
    """
    _validate(values, period)
    if any(type(k) not in (int, float) or not math.isfinite(k) or k <= 0 for k in multipliers):
        raise ValueError("multipliers must be finite positive numbers")
    mid = sma_series(values, period)
    out = []
    for i, center in enumerate(mid):
        if center is None:
            out.append(None)
            continue
        window = values[i - period + 1:i + 1]
        variance = sum((x - center) ** 2 for x in window) / period
        deviation = math.sqrt(variance)
        out.append({"middle": center, "stddev": deviation,
                    "bands": {str(k): {"upper": center + k * deviation,
                                       "lower": center - k * deviation}
                              for k in multipliers}})
    return out
