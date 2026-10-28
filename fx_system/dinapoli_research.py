"""Non-gating DMA research and standard Fibonacci calculations.

DMA is displaced for *display*, not evaluated using future candles.
Fibonacci levels are derived from explicitly supplied confirmed swing anchors.
No trade signal, DiNapoli proprietary Fibonacci, or confluence certification.
"""
from __future__ import annotations
import math
from .advisory_indicators import sma_series


DMA_SPECS = ((3, 3), (7, 5), (25, 5))
FIB_RATIOS = (0.382, 0.5, 0.618)
FIB_EXTENSION_RATIOS = (1.0, 1.272, 1.618)


def displaced_sma(values, period, shift):
    """Return raw SMA and shifted plot points.

    Plot at index i+shift for SMA known at i. The value at current index
    cannot use the future plot point as if it were known market evidence.
    """
    if type(shift) is not int or shift < 0:
        raise ValueError("shift must be a nonnegative integer")
    base = sma_series(values, period)
    points = [{"source_index": i, "plot_index": i + shift, "value": value}
              for i, value in enumerate(base) if value is not None]
    return {"period": period, "display_shift": shift, "latest_known": base[-1] if base else None,
            "plot_points": points, "advisory_only": True}


def fibonacci_retracement(swing_low, swing_high, direction):
    """Retracement from a completed impulse high (long) or low (short)."""
    if type(swing_low) not in (int, float) or type(swing_high) not in (int, float):
        raise ValueError("finite numeric swing anchors required")
    if not all(math.isfinite(v) and v > 0 for v in (swing_low, swing_high)):
        raise ValueError("finite positive swing anchors required")
    if swing_high <= swing_low:
        raise ValueError("swing_high must exceed swing_low")
    if direction not in ("long", "short"):
        raise ValueError("direction must be long or short")
    width = swing_high - swing_low
    levels = {str(r): (swing_high - r * width if direction == "long"
                       else swing_low + r * width) for r in FIB_RATIOS}
    extensions = {str(r): (swing_low + r * width if direction == "long"
                           else swing_high - r * width) for r in FIB_EXTENSION_RATIOS}
    return {"direction": direction, "swing_low": swing_low, "swing_high": swing_high,
            "retracement_levels": levels, "extension_levels": extensions,
            "extension_basis": "impulse_range_projection_not_confirmed_structure_target",
            "method": "standard_fibonacci", "advisory_only": True,
            "confirmed_anchors_required": True}


def dma_snapshot(rows):
    """Compute display-only DMA from caller-supplied completed closes."""
    ordered = sorted(rows, key=lambda r: r["timestamp"])
    closes = [r["close"] for r in ordered]
    if any(type(x) not in (int, float) or not math.isfinite(x) for x in closes):
        raise ValueError("invalid closes")
    result = {}
    for p, shift in DMA_SPECS:
        series = sma_series(closes, p)
        current = series[-1-shift] if len(series) > shift else None
        previous = series[-2-shift] if len(series) > shift+1 else None
        result[f'{p}x{shift}'] = {
            'period': p, 'display_shift': shift, 'latest_known': series[-1] if series else None,
            'current_plot': current, 'previous_plot': previous,
            'plot_slope': current-previous if current is not None and previous is not None else None,
            'plot_timestamp': ordered[-1]['timestamp'] if current is not None else None,
            'source_timestamp': ordered[-1-shift]['timestamp'] if current is not None else None,
            'basis': 'historical_sma_displaced_to_current_bar_not_latest_future_plot'}
    return {"candles": len(closes), "dma": result,
            'last_timestamp': ordered[-1]['timestamp'] if ordered else None,
            'saved_close': closes[-1] if closes else None,
            "advisory_only": True,
            "fibonacci_status": "requires_explicit_confirmed_impulse_anchors"}


def confirmed_fibonacci(rows, direction):
    """Standard Fibonacci with conservatively confirmed 2L/2R pivots.

    Long: a confirmed swing low followed by a confirmed swing high.
    Short: a confirmed swing high followed by a confirmed swing low.
    The most recent *completed* pivot of the finishing type is selected;
    the most recent preceding opposite pivot supplies the starting anchor.
    Returns unavailable rather than inferring a swing from unconfirmed bars.
    """
    from .core import technical
    if direction not in ("long", "short"):
        return {"status": "unavailable", "reason": "direction_missing",
                "advisory_only": True}
    ordered = sorted(rows, key=lambda r: r["timestamp"])
    if len(ordered) < 15:
        return {"status": "unavailable", "reason": "confirmed_history_insufficient",
                "advisory_only": True}
    analysis = technical(ordered)
    highs = analysis.get("confirmed_swing_highs", [])
    lows = analysis.get("confirmed_swing_lows", [])
    # Technical exposes the two most recent pivots, all 2L/2R confirmed.
    endings, starts = (highs, lows) if direction == "long" else (lows, highs)
    if not endings:
        return {"status": "unavailable", "reason": "ending_pivot_missing",
                "advisory_only": True}
    end = endings[-1]
    earlier = [p for p in starts if p["timestamp"] < end["timestamp"]]
    if not earlier:
        return {"status": "unavailable", "reason": "preceding_opposite_pivot_missing",
                "advisory_only": True}
    start = earlier[-1]
    low = start["price"] if direction == "long" else end["price"]
    high = end["price"] if direction == "long" else start["price"]
    if high <= low:
        return {"status": "unavailable", "reason": "nonpositive_impulse",
                "advisory_only": True}
    fib = fibonacci_retracement(low, high, direction)
    return {"status": "calculated", "start_pivot": start, "end_pivot": end,
            "pivot_confirmation": "strict_2left_2right",
            "fibonacci": fib, "advisory_only": True,
            }
