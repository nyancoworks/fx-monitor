"""Issue43 read-only NY17 H1 -> D1/W1 shadow contract.

All OHLC results remain diagnostic until independent provider/session validation.
No network, no production cache mutation, no trading permission.
"""
from __future__ import annotations
import datetime as dt
import math
from collections import defaultdict
from zoneinfo import ZoneInfo

UTC = dt.timezone.utc
NY = ZoneInfo("America/New_York")
HOUR = 3600


def close_utc(trading_date):
    if not isinstance(trading_date, dt.date) or isinstance(trading_date, dt.datetime):
        raise TypeError("date required")
    if trading_date.weekday() >= 5:
        raise ValueError("weekend is not a nominal NY trading day")
    return dt.datetime.combine(trading_date, dt.time(17), NY).astimezone(UTC)


def latest_closed_date(as_of):
    if not isinstance(as_of, dt.datetime) or as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("timezone-aware as_of required")
    local = as_of.astimezone(NY)
    day = local.date() if local.time() >= dt.time(17) else local.date() - dt.timedelta(days=1)
    while day.weekday() >= 5:
        day -= dt.timedelta(days=1)
    return day


def aggregate_one(rows_by_timestamp, trading_date, as_of, source="Twelve Data"):
    close = close_utc(trading_date)
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("naive as_of")
    if as_of.astimezone(UTC) < close:
        return None, "not_closed"
    end = int(close.timestamp())
    start = end - 24 * HOUR
    picked = []
    for t in range(start, end, HOUR):
        row = rows_by_timestamp.get(t)
        if not isinstance(row, dict):
            return None, "missing_h1"
        try:
            o, h, l, c = (row[k] for k in ("open", "high", "low", "close"))
            if (not all(type(v) in (int, float) and math.isfinite(v) and v > 0 for v in (o, h, l, c))
                or l > min(o, c) or h < max(o, c)):
                return None, "bad_ohlc"
        except (KeyError, TypeError):
            return None, "bad_ohlc"
        picked.append(row)
    return {
        "trading_date_ny": trading_date.isoformat(), "session_start_utc": start,
        "session_end_utc": end, "h1_count": 24,
        "ohlc": {"open": picked[0]["open"], "high": max(r["high"] for r in picked),
                 "low": min(r["low"] for r in picked), "close": picked[-1]["close"]},
        "provider": source, "nominal_session": True,
        "provider_session_verified": False, "entry_permission": False
    }, None


def build_shadow(rows, as_of, minimum=60):
    if type(minimum) is not int or minimum <= 0:
        raise ValueError("minimum must be positive")
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("naive as_of")
    bytime = {}
    duplicates = set()
    bad_timestamps = 0
    for r in rows:
        t = r.get("timestamp") if isinstance(r, dict) else None
        if type(t) is not int or t % HOUR:
            bad_timestamps += 1
            continue
        if t in bytime:
            duplicates.add(t)
        bytime[t] = r
    day = latest_closed_date(as_of)
    dates = []
    while len(dates) < minimum:
        if day.weekday() < 5:
            dates.append(day)
        day -= dt.timedelta(days=1)
    dates.reverse()
    d1 = []
    errors = {}
    for day in dates:
        end = int(close_utc(day).timestamp())
        start = end - 24 * HOUR
        if any(t in duplicates for t in range(start, end, HOUR)):
            errors[day.isoformat()] = "duplicate_h1"
            continue
        value, error = aggregate_one(bytime, day, as_of)
        if error:
            errors[day.isoformat()] = error
        else:
            d1.append(value)
    weekly = defaultdict(list)
    for bar in d1:
        date = dt.date.fromisoformat(bar["trading_date_ny"])
        monday = date - dt.timedelta(days=date.weekday())
        weekly[monday.isoformat()].append(bar)
    w1 = []
    for week, items in sorted(weekly.items()):
        weekdays_present = {dt.date.fromisoformat(x["trading_date_ny"]).weekday() for x in items}
        if weekdays_present != {0, 1, 2, 3, 4}:
            continue
        items.sort(key=lambda x: x["session_end_utc"])
        w1.append({
            "week_start_ny": week, "close_utc": items[-1]["session_end_utc"],
            "d1_count": 5,
            "ohlc": {"open": items[0]["ohlc"]["open"],
                     "high": max(x["ohlc"]["high"] for x in items),
                     "low": min(x["ohlc"]["low"] for x in items),
                     "close": items[-1]["ohlc"]["close"]},
            "provider_session_verified": False, "entry_permission": False
        })
    actual_last = d1[-1]["trading_date_ny"] if d1 else None
    expected = dates[-1].isoformat()
    return {
        "schema": "issue43_ny17_shadow_v1", "evaluated_at_utc": as_of.astimezone(UTC).isoformat(),
        "expected_last_ny_date": expected, "actual_last_ny_date": actual_last,
        "latest_closed_present": actual_last == expected,
        "d1_count": len(d1), "d1_required": minimum,
        "weekly_complete_count": len(w1),
        "structurally_complete": len(d1) == minimum and not errors,
        "invalid_timestamps": bad_timestamps, "duplicates": len(duplicates),
        "errors": errors, "d1": d1, "w1": w1,
        "provider_session_verified": False, "native_d1_equivalent_verified": False,
        "formal_decision_permission": False, "entry_permission": False
    }

