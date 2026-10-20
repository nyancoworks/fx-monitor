"""Explain usable market observations and input quality without trade authorization."""
from .core import screen_setup, confirm_m5_entry, MIN_BARS


def assess_input_layers(frames, quality, now):
    intraday_reasons = list(quality["intraday_monitoring_reasons"])
    intraday_ready = not intraday_reasons
    coverage = {}
    for tf in ("m5", "h1", "h4", "d1", "w1"):
        check = quality["timeframes"][tf]
        coverage[tf] = {
            "count": len(frames.get(tf, [])),
            "required_count": {"h1": 35, "h4": 15}.get(tf, MIN_BARS[tf]),
            "structure_sufficient": len(frames.get(tf, [])) >= {"h1": 35, "h4": 15}.get(tf, MIN_BARS[tf]),
            "fresh": bool(check.get("fresh")),
            "age_minutes": check.get("age_minutes"),
            "latest_closed_present": quality["closed_candle_freshness"].get(tf, {}).get("latest_closed_present"),
        }
    # screen_setup uses H1/H4; unconfirmed D1 never supplies macro clearance.
    if intraday_ready:
        structure = screen_setup(frames, now)
        entry = confirm_m5_entry(structure, frames["m5"], now)
        structure = {**structure, "m5_entry_check": entry}
    else:
        structure = {"grade": "C", "entry_confirmed": False,
                     "reason": "Intraday inputs unavailable",
                     "data_quality_reasons": intraday_reasons}
    return {
        "schema": "decision_input_layers_v1", "evaluated_at": now,
        "acquisition_quality": {"intraday_ready": intraday_ready,
                                "reasons": intraday_reasons},
        "decision_input_coverage": {
            "intraday_screening_available": intraday_ready,
            "data_ready": bool(quality["ready"]),
            "timeframes": coverage,
            "data_quality_reasons": list(quality["reasons"]),
        },
        "intraday_screening": structure,
    }
