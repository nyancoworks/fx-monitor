"""Read-only H1 RCI momentum diagnostic, never an entry authorization."""
from __future__ import annotations
import math
from .indicator_research import rci_series


def h1_rci_shadow(rows, h4_setup, quality):
    result = {"status": "not_ready", "advisory_only": True,
              "entry_confirmed": False, "rci": {"26": None, "52": None},
              "alignment": {"26": None, "52": None}}
    if not quality.get("ready"):
        return {**result, "reason": "decision data quality unverified"}
    direction = h4_setup.get("direction")
    if direction not in ("long", "short"):
        return {**result, "reason": "H4 direction unavailable"}
    if not rows:
        return {**result, "reason": "H1 history unavailable"}
    now = quality.get("evaluated_at")
    if type(now) is not int or type(rows[-1].get("timestamp")) is not int:
        return {**result, "reason": "H1 timestamp unavailable"}
    expected = (now // 3600 - 1) * 3600
    if rows[-1]["timestamp"] != expected:
        return {**result, "reason": "latest completed H1 missing"}
    closes = []
    previous = None
    for row in rows:
        stamp = row.get("timestamp")
        close = row.get("close")
        if (type(stamp) is not int or stamp % 3600 or
                (previous is not None and stamp - previous != 3600) or
                type(close) not in (int, float) or not math.isfinite(close) or close <= 0):
            return {**result, "reason": "H1 series invalid or noncontiguous"}
        previous = stamp
        closes.append(close)
    values = {str(p): rci_series(closes, p)[-1] for p in (26, 52)}
    alignment = {
        p: None if v is None else
        ("aligned" if (v > 0 if direction == "long" else v < 0) else
         "neutral" if v == 0 else "opposed")
        for p, v in values.items()
    }
    return {**result, "status": "calculated" if any(v is not None for v in values.values()) else "insufficient",
            "direction": direction, "rci": values, "alignment": alignment,
            "h1_last_timestamp": rows[-1]["timestamp"]}
