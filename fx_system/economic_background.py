"""Summarize saved calendar evidence without inferring policy or price effects."""


def summarize_background(events, currencies):
    """Keep policy-related calendars distinct from verified policy facts.

    Counts describe this assessment's saved reference window, not coverage of
    the economy. Values remain original strings in the events, never scores.
    """
    result = {"version": 1, "currencies": []}
    for currency in currencies:
        row = {"currency": currency, "policy_rate": "unassessed",
               "policy_stance": "unassessed", "market_reaction": "unassessed"}
        for category, key in (("central-banks-monetary-policy", "policy"),
                              ("economic-indicators", "indicators")):
            selected = [e for e in events if e.get("currency") == currency
                        and e.get("category") == category]
            active = [e for e in selected if e.get("provider_status") != "cancelled"]
            upcoming = [e for e in active if e.get("timing") == "upcoming"
                        and type(e.get("scheduled_at_utc")) is int]
            row[key] = {
                "event_count": len(selected),
                "upcoming_count": len(upcoming),
                "next_scheduled_at_utc": min((e["scheduled_at_utc"] for e in upcoming), default=None),
                "uncertain_count": sum(e.get("timing") == "uncertain" for e in active),
                "cancelled_count": len(selected) - len(active),
            }
        # A stored string is evidence availability, not a verified first print,
        # comparable surprise, current policy rate, or causal market reaction.
        numeric = [e for e in events if e.get("currency") == currency
                   and e.get("provider_status") not in ("cancelled", "estimated")
                   and e.get("freshness") != "stale"]
        row["saved_values"] = {
            key: sum(isinstance(e.get(field), str) and bool(e[field].strip())
                     and (key != "actual" or e.get("timing") == "past_release_window")
                     for e in numeric)
            for key, field in (("actual", "actual_raw"), ("consensus", "consensus_raw"),
                               ("prior", "prior_raw"))
        }
        result["currencies"].append(row)
    return result
