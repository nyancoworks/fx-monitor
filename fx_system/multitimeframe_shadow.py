"""Read-only H4/H1/M15 observation, separate from the legacy trade grade."""


def multitimeframe_shadow(h4, h1, m15, comparison, quality):
    h4 = h4 or {}
    h1 = h1 or {}
    m15 = m15 or {}
    comparison = comparison or {}
    quality = quality or {}
    direction = h4.get("direction") if h4.get("direction") in ("long", "short") else None
    result = {
        "advisory_only": True,
        "entry_confirmed": False,
        "direction": direction,
        "h4_status": h4.get("status"),
        "h1_rci": h1.get("rci", {}),
        "h1_rci_alignment": h1.get("alignment", {}),
        "m15_status": m15.get("status"),
        "invalidation_source": "m15" if m15.get("status") == "invalidated" else None,
        "m15_pattern": m15.get("pattern"),
        "m15_rci": m15.get("rci", {}),
        "m15_rci_alignment": m15.get("rci_alignment", {}),
        "legacy_h1_comparison": comparison.get("status"),
        "data_ready": quality.get("ready") is True,
    }
    if not result["data_ready"]:
        status = "data_unverified"
    elif direction is None or h4.get("status") != "watch_only":
        status = "h4_unavailable"
    elif m15.get("status") == "invalidated":
        status = "h4_invalidated"
    elif comparison.get("status") == "divergent":
        status = "h1_h4_divergence"
    elif m15.get("status") == "watch_pattern":
        status = "price_action_watch"
    elif m15.get("status") == "waiting":
        status = "waiting_for_price_action"
    else:
        status = "m15_unavailable"
    result["status"] = status
    result["missing_trade_gates"] = [
        "structural_target_and_rr", "economic_event_clearance",
        "executable_quote_and_spread", "independent_execution_check"
    ]
    return result
