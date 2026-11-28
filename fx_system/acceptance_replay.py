"""Replay stored collection inputs through the current evaluation functions."""
import hashlib
import json
import os
from pathlib import Path

FILE_LIMIT = 32 * 1024 * 1024


def read(root, name):
    directory = root / ".private-acceptance"

    def content(filename, limit):
        path = directory / filename
        if directory.is_symlink() or path.is_symlink() or path.stat().st_size > limit:
            raise ValueError("invalid acceptance input")
        return path.read_bytes()

    hashes = json.loads(content("inputs.json", 4096))
    raw = content(name, FILE_LIMIT)
    if hashlib.sha256(raw).hexdigest() != hashes.get(name):
        raise ValueError("acceptance input checksum differs")
    return json.loads(raw)


def main():
    from .acceptance_target import enabled, verify_identity
    from .private_runtime import private_root, verify_ready
    if not enabled() or not verify_identity(os.environ.get("GITHUB_REPOSITORY"),
                                              os.environ.get("GITHUB_REF")):
        raise ValueError("offline replay requires an isolated code ref")
    root = private_root(os.environ["FX_DATA_ROOT"])
    verify_ready(root)
    from .main import CACHE, OUTPUT, aggregate, aggregate_h4, compute_strength, finalize_pairs
    from .monitor_pairs import PAIR_KEYS
    from .ny_integration import configured
    from .saved_economic_calendar import build_outlook_with_saved_calendar

    result = read(root, "collection.json")
    observations = read(root, "observations.json")
    cache = read(root, "cache.json")
    clock = read(root, "clock.json")["evaluated_at"]
    if set(result["pairs"]) != set(PAIR_KEYS) or result["evaluated_at"] != clock:
        raise ValueError("recorded inputs do not match the acceptance clock and pair set")
    service = configured(root, CACHE, OUTPUT)
    if service is None:
        raise ValueError("NY17 acceptance requires the configured reader")
    service.queue = observations
    for data in result["pairs"].values():
        raw = data["decision_data"]["raw"]
        for tf, rows in (("m15", aggregate(raw["m5"], 300, 900)),
                         ("h1", raw["h1"]), ("h4", aggregate_h4(raw["h1"]))):
            data[tf]["candles"] = rows[-100:]
    finalize_pairs(result, service, clock)
    if service.failure is not None:
        raise ValueError("replayed NY17 synchronization failed")
    result["scheduled_outlook"] = build_outlook_with_saved_calendar(
        result["pairs"], result["quality"], evaluated_at=clock)
    result["currency_strength"] = compute_strength(result, now=clock)
    result["ready_count"] = len(result["ready_pairs"])
    result["all_pairs_ready"] = result["ready_count"] == len(PAIR_KEYS)
    CACHE.write_text(json.dumps(cache, separators=(",", ":")))
    OUTPUT.write_text(json.dumps(result, separators=(",", ":")))


if __name__ == "__main__":
    main()
