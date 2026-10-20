"""Conservative M15 price-action watch diagnostic; never an order signal."""
from __future__ import annotations
import math
from .core import INTERVALS
from .indicator_research import rci_series


def m15_entry_shadow(frames, h4_setup, quality):
    """Look for a completed-candle breakout with no future bars or trade authority.

    Assumes frames were rebuilt from verified M5 in evaluate_data. A missing or
    stale M15 latest candle blocks even a watch observation.
    """
    result = {"stage": "m15_entry_shadow", "status": "not_ready",
              "direction": None, "pattern": None, "entry_confirmed": False,
              "advisory_only": True}
    # M15 research uses its own verified closed-candle quality.
    # Formal execution keeps the independent global gates.
    tfs=quality.get("timeframes",{})
    if not isinstance(tfs,dict) or any(
            not isinstance(tfs.get(tf),dict) or tfs[tf].get("ok") is not True
            for tf in ("h4","h1","m15")):
        return {**result, "reason": "H4/H1/M15 completed-candle quality unverified"}
    direction = h4_setup.get("direction")
    if h4_setup.get("status") != "watch_only" or direction not in ("long", "short"):
        return {**result, "reason": "H4 setup not confirmed"}
    bars = frames.get("m15", [])
    now = quality.get("evaluated_at")
    if not isinstance(now, int) or len(bars) < 4:
        return {**result, "reason": "M15 history or evaluation clock insufficient"}
    # Revalidate the local decision window, even if upstream quality was marked ready.
    window = bars[-4:]
    for bar in window:
        if not isinstance(bar, dict):
            return {**result, "reason": "M15 candle invalid"}
        stamp = bar.get("timestamp")
        if type(stamp) is not int or stamp % INTERVALS["m15"]:
            return {**result, "reason": "M15 timestamp invalid"}
        values = [bar.get(k) for k in ("open", "high", "low", "close")]
        if any(type(v) not in (int, float) or not math.isfinite(v) or v <= 0 for v in values):
            return {**result, "reason": "M15 OHLC invalid"}
        o, h, l, c = values
        if not (l <= min(o, c) <= max(o, c) <= h):
            return {**result, "reason": "M15 OHLC inconsistent"}
    latest = bars[-1]
    expected = (now // INTERVALS["m15"] - 1) * INTERVALS["m15"]
    # Permit at most one missed M15 close for saved monitoring research.
    # More delay, future candles, or missing timeframe provenance remain blocked.
    lag=expected-latest["timestamp"]
    if lag not in (0, INTERVALS["m15"]):
        return {**result, "reason": "latest completed M15 candle outside one-bar observation tolerance"}
    delayed=lag>0
    if any(bars[i + 1]["timestamp"] - bars[i]["timestamp"] != INTERVALS["m15"]
           for i in range(len(bars) - 4, len(bars) - 1)):
        return {**result, "reason": "M15 candles not contiguous"}
    invalidation = h4_setup.get("invalidation")
    if (type(invalidation) not in (int, float) or not math.isfinite(invalidation) or invalidation <= 0):
        return {**result, "reason": "H4 invalidation missing"}
    prior = bars[-4:-1]
    high = max(b["high"] for b in prior)
    low = min(b["low"] for b in prior)
    close = latest["close"]
    if direction == "long" and close <= invalidation:
        return {**result, "status": "invalidated", "direction": direction, "reason": "H4 invalidation crossed"}
    if direction == "short" and close >= invalidation:
        return {**result, "status": "invalidated", "direction": direction, "reason": "H4 invalidation crossed"}
    closes = [bar["close"] for bar in bars]
    rci = {str(period): rci_series(closes, period)[-1] for period in (9, 26)}
    rci_alignment = {
        period: None if value is None else
        ("aligned" if (value > 0 if direction == "long" else value < 0) else
         "neutral" if value == 0 else "opposed")
        for period, value in rci.items()
    }
    breakout = close > high if direction == "long" else close < low
    return {**result, "status": "watch_pattern" if breakout else "waiting",
            "direction": direction, "pattern": "three_bar_close_breakout" if breakout else None,
            "m15_last_timestamp": latest["timestamp"],
            "m15_observation_delay_minutes": lag//60,
            "current_trigger_confirmed": False,
            "observation_scope": "delayed_reference" if delayed else "completed_candle_reference",
            "reference_high": high, "reference_low": low,
            "invalidation": invalidation,
            "rci": rci,
            "rci_alignment": rci_alignment,
            "reason": "research-only close breakout; structural target, RR, event and quote gates not verified"}
