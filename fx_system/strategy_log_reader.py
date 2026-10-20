"""Read-only parser for scheduled strategy assessment logs."""
import json
import re


class StrategyLogError(ValueError):
    """The scheduled assessment log is incomplete or inconsistent."""


def parse_strategy_log(lines, pairs):
    """Read a single run without inventing omitted strategy outcomes."""
    pairs = tuple(pairs)
    if len(set(pairs)) != len(pairs):
        raise StrategyLogError("duplicate configured pair")
    expected = {(pair, strategy) for pair in pairs
                for strategy in ("swing", "daytrade")}
    records = {}
    summary = None
    timestamps = set()
    for line in lines:
        line=re.sub(r"^\ufeff?\d{4}-\d{2}-\d{2}T\S+Z\s+", "", line)
        if line.startswith("SCHEDULED_STRATEGY_SUMMARY "):
            if summary is not None:
                raise StrategyLogError("multiple summaries")
            summary = json.loads(line.split(" ", 1)[1])
        elif line.startswith("SCHEDULED_STRATEGY_ASSESSMENT "):
            item = json.loads(line.split(" ", 1)[1])
            row = item["assessment"]
            key = (row["pair"], row["strategy"])
            if key not in expected or key in records:
                raise StrategyLogError("unexpected or duplicate strategy")
            if row.get("evaluated_at") != item.get("evaluated_at"):
                raise StrategyLogError("assessment timestamp mismatch")
            records[key] = row
            timestamps.add(item["evaluated_at"])
    if summary is None or summary.get("canonical_assessment_field") != "strategy_assessments":
        raise StrategyLogError("missing canonical summary")
    if summary.get("advisory_only") is not True:
        raise StrategyLogError("not advisory")
    if len(timestamps) != 1 or summary.get("evaluated_at") not in timestamps:
        raise StrategyLogError("mixed evaluation times")
    if set(records) != expected or summary.get("assessment_count") != len(expected):
        raise StrategyLogError("missing strategy assessments")
    counts = {"review": 0, "skip": 0, "evaluation_pending": 0}
    for row in records.values():
        state = row.get("assessment")
        if state not in counts:
            raise StrategyLogError("unknown assessment state")
        counts[state] += 1
        if state == "review" and row.get("grade") not in ("A", "B", "C"):
            raise StrategyLogError("review grade missing")
        if state != "review" and row.get("grade") is not None:
            raise StrategyLogError("non-review grade")
    if summary.get("assessment_counts") != counts:
        raise StrategyLogError("assessment count mismatch")
    return [records[(pair, strategy)] for pair in pairs
            for strategy in ("swing", "daytrade")]
