"""Offline, advisory-only economic calendar context for saved FX assessments.

Input is a separately verified snapshot, never a live network request.
No entry permission, trading action, grade, or direction is derived here.
"""
from copy import deepcopy
from .monitor_pairs import PAIR_KEYS

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
                or pair not in PAIR_KEYS or strategy not in WINDOWS or (pair, strategy) in seen):
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
            if (type(observed) is not int or observed > calendar["observed_at_utc"]
                    or type(when) is not int or event.get("reference_only") is not True
                    or currency not in (pair[:3], pair[3:])
                    or not clock - before <= when <= clock + after):
                continue
            item = deepcopy(event)
            if when > clock or observed < when:
                for key in ("actual", "actual_raw", "surprise"):
                    item[key] = None
                item["status"] = "scheduled" if when > clock else "release_unverified"
                item["numeric_comparison_verified"] = False
            item["relation"] = "base" if currency == pair[:3] else "quote"
            item["timing"] = "upcoming" if when > clock else "past_release_window"
            selected.append(item)
        selected.sort(key=lambda x: (x["scheduled_at_utc"], x["currency"]))
        assessment["economic_calendar_context"] = {
            "status": ("available" if calendar.get("complete") is True else "partial")
                      if valid else "unavailable",
            "events": selected,
            "attribution_url": calendar.get("attribution_url") if valid else None,
            "advisory_only": True, "changes_grade": False,
            "market_reaction": "unassessed",
            "policy_interpretation": "unassessed",
        }
    if seen != {(p, s) for p in PAIR_KEYS for s in WINDOWS}:
        raise ValueError("missing canonical assessments")
    # Snapshot validator requires row copies to match canonical assessments.
    canonical = {(a["pair"], a["strategy"]): a for a in assessments}
    rows = result.get("rows")
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError("invalid outlook row")
            saved = row.get("strategy_assessments")
            if not isinstance(saved, dict) or set(saved) != set(WINDOWS):
                raise ValueError("invalid row strategy assessments")
            for strategy in WINDOWS:
                key = (row.get("pair"), strategy)
                if key not in canonical:
                    raise ValueError("unknown row strategy")
                row["strategy_assessments"][strategy] = deepcopy(canonical[key])
    result["economic_calendar_context"] = {
        "status": ("available" if calendar.get("complete") is True else "partial")
                  if valid else "unavailable",
        "observed_at_utc": calendar["observed_at_utc"] if valid else None,
        "advisory_only": True, "changes_grades": False,
    }
    return result
