"""Calendar alignment of caller-verified NY17 candles; no source attestation."""
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

NY17 = "America/New_York 17:00"


def ny17_sequence_valid(rows, timeframe):
    """Use session END dates, never the weekday of the start-label timestamp.

    Match the existing NY17 converter's end-minus-86400 daily label and
    Sunday-open weekly label. Missing weekdays/weeks stay missing; no holiday
    closures are inferred. DST offsets come from America/New_York.
    """
    if timeframe not in ("d1", "w1"):
        return False
    ny = ZoneInfo("America/New_York")
    previous = None
    for row in rows:
        start, end = row.get("timestamp"), row.get("session_end_utc")
        if type(start) is not int or type(end) is not int:
            return False
        try:
            close = datetime.fromtimestamp(end, ny)
            if close.time() != time(17) or close.weekday() > 4:
                return False
            day = close.date()
            if timeframe == "d1":
                expected_start = end - 86400
            else:
                if close.weekday() != 4:
                    return False
                monday = day - timedelta(days=4)
                expected_start = int(datetime.combine(monday, time(17), ny).timestamp()) - 86400
            if start != expected_start:
                return False
            if previous is not None:
                expected = previous + timedelta(days=7 if timeframe == "w1" else 1)
                while timeframe == "d1" and expected.weekday() > 4:
                    expected += timedelta(days=1)
                if day != expected:
                    return False
            previous = day
        except (OverflowError, OSError, ValueError):
            return False
    return bool(rows)
