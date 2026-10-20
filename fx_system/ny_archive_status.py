"""Attach price-free persistence evidence to the existing published snapshot."""
import argparse
import json
from pathlib import Path


def annotate(snapshot, restored, persisted, *, restore_ok, save_ok):
    evidence = {"restore_ok": restore_ok, "save_ok": save_ok}
    for prefix, result in (("restore", restored), ("save", persisted)):
        for key in ("status", "generation", "checkpoint_sha256", "restored_ref", "persisted_ref",
                    "shadow_pilot_runs", "journal_entries", "consolidated", "new_compressed_bytes", "retained_bytes",
                    "checkpoint_bytes", "capacity_warning"):
            if key in result:
                evidence[prefix + "_" + key] = result[key]
    snapshot["ny17_transport"] = evidence
    if not restore_ok or not save_ok:
        reason = "NY archive restore/save unverified; persistent continuity not ready"
        snapshot["ready_count"] = 0
        for pair, data in snapshot.get("pairs", {}).items():
            quality = data.get("decision_quality", {})
            quality["ready"] = False
            quality["reasons"] = list(dict.fromkeys([*quality.get("reasons", []), reason]))
            summary=snapshot.get("quality", {}).get(pair, {})
            summary["ok"] = False
            summary["decision_data_ready"] = False
            summary["data_quality_reasons"] = quality["reasons"]
            assessment = data.get("setup", {}).get("input_assessment", {})
            if assessment:
                assessment["decision_input_coverage"]["formal_data_ready"] = False
                assessment["decision_input_coverage"]["formal_data_blockers"] = quality["reasons"]
        # This module changes data readiness only. It may not silently revoke
        # or introduce a strategy decision: any unexpected permitted entry is
        # a release-contract violation and stops publication for review.
        if snapshot.get("signal_eligible_count", 0):
            raise ValueError("unexpected eligible entry during archive failure")
    return snapshot


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", default="data/latest.json")
    parser.add_argument("--restore-result", required=True)
    parser.add_argument("--save-result", required=True)
    parser.add_argument("--restore-outcome", required=True)
    parser.add_argument("--save-outcome", required=True)
    args = parser.parse_args()
    def read(path):
        try:
            return json.loads(Path(path).read_bytes())
        except (OSError, ValueError):
            return {}
    restored, saved = read(args.restore_result), read(args.save_result)
    restore_ok = args.restore_outcome == "success" and restored.get("status") == "restored"
    save_ok = args.save_outcome == "success" and saved.get("status") in ("persisted", "unchanged")
    target = Path(args.snapshot)
    value = annotate(json.loads(target.read_bytes()), restored, saved,
                     restore_ok=restore_ok, save_ok=save_ok)
    target.write_text(json.dumps(value, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
