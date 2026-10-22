"""Offline, advisory-only economic calendar context for saved FX assessments.

Input is a separately verified snapshot, never a live network request.
No entry permission, trading action, grade, or direction is derived here.
"""
from copy import deepcopy

WINDOWS = {"swing": (86400, 7 * 86400), "daytrade": (6 * 3600, 36 * 3600)}


def enrich_outlook(outlook, calendar):
    """Attach calendar evidence to exactly 32 canonical assessments.

    The caller must provide a trustworthy acquisition clock and explicit
    completeness flag. Absent/unverified input stays unavailable.
    """
    if not isinstance(outlook, dict) or type(outlook.get("evaluated_at")) is not int:
        raise ValueError("invalid outlook")
    result = deepcopy(outlook)
    clock = result["evaluated_at"]
    assessments = result.get("strategy_assessments")
    if not isinstance(assessments, list) or len(assessments) != 32:
        raise ValueError("expected 32 assessments")
    valid = (isinstance(calendar, dict) and isinstance(calendar.get("events"), list)
             and type(calendar.get("observed_at_utc")) is int
             and calendar["observed_at_utc"] <= clock)
    events = calendar["events"] if valid else []
    seen = set()
    for assessment in assessments:
        if not isinstance(assessment, dict):
            raise ValueError("invalid assessment")
        pair, strategy = assessment.get("pair"), assessment.get("strategy")
        if (not isinstance(pair, str) or len(pair) != 6 or not pair.isalpha()
                or strategy not in WINDOWS or (pair, strategy) in seen):
            raise ValueError("invalid or duplicate assessment")
        seen.add((pair, strategy))
        before, after = WINDOWS[strategy]
        selected = []
        for event in events:
            if not isinstance(event, dict):
                continue
            observed = event.get("observed_at_utc")
            when = event.get("scheduled_at_utc")
            currency = event.get("currency")
            if (type(observed) is not int or observed > clock
                    or type(when) is not int or event.get("reference_only") is not True
                    or currency not in (pair[:3], pair[3:])
                    or not clock - before <= when <= clock + after):
                continue
            item = deepcopy(event)
            if when > clock:
                for key in ("actual", "actual_raw", "surprise"):
                    item[key] = None
                item["status"] = "scheduled"
                item["numeric_comparison_verified"] = False
            item["relation"] = "base" if currency == pair[:3] else "quote"
            item["timing"] = "upcoming" if when > clock else "past_release_window"
            selected.append(item)
        selected.sort(key=lambda x: (x["scheduled_at_utc"], x["currency"]))
        assessment["economic_calendar_context"] = {
            "status": ("available" if calendar.get("complete") is True else "partial")
                      if valid else "unavailable",
            "events": selected,
            "attribution_url": "https://www.financecalendar.com" if valid else None,
            "advisory_only": True, "changes_grade": False,
            "market_reaction": "unassessed",
            "policy_interpretation": "unassessed",
        }
    result["economic_calendar_context"] = {
        "status": ("available" if calendar.get("complete") is True else "partial")
                  if valid else "unavailable",
        "observed_at_utc": calendar["observed_at_utc"] if valid else None,
        "advisory_only": True, "changes_grades": False,
    }
    return result
