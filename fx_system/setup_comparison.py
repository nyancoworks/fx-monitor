"""Read-only comparison of legacy H1 screening and H4-first shadow."""
def compare_setups(legacy, h4, quality):
    legacy = legacy or {}
    h4 = h4 or {}
    a = legacy.get("direction")
    b = h4.get("direction")
    valid = quality.get("ready") is True
    if not valid:
        status = "data_unverified"
    elif a not in ("long", "short") or b not in ("long", "short"):
        status = "direction_unavailable"
    else:
        status = "aligned" if a == b else "divergent"
    return {
        "status": status,
        "legacy_h1_direction": a if a in ("long", "short") else None,
        "legacy_grade": legacy.get("grade"),
        "h4_shadow_direction": b if b in ("long", "short") else None,
        "h4_shadow_status": h4.get("status"),
        "h1_h4_conflict": status == "divergent",
        "quality_ready": valid,
        "entry_confirmed": False,
        "advisory_only": True,
    }
