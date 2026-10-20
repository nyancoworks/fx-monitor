"""Private NY17 state transport across ephemeral GitHub Actions runners.

Opt-in deployment ONLY. Remote state is a dedicated Git ref, not data/latest.json.
No provider APIs; no price, API key or credentials in logs. Publish is
optimistic concurrency protected by remote fast-forward; no force pushes.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import lzma
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from diagnostics.issue43_ny_runtime import MAX_CHECKPOINT_BYTES, validate_checkpoint

BRANCH = "ny17-archive-state"
STATE = "ny17-checkpoint.json.xz"
BACKUP = "ny17-checkpoint.previous.json.xz"
MANIFEST = "manifest.json"
BASE = ".transport-base"
RESTORED = ".transport-restored.json"
RESTORED_MANIFEST = ".transport-manifest.json"
MAX_COMPRESSED_BYTES = MAX_CHECKPOINT_BYTES


def git(*args, input_data=None):
    proc = subprocess.run(["git", *args], input=input_data, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, check=False)
    if proc.returncode:
        # Never expose git stderr: it can contain remote URL tokens.
        raise RuntimeError("archive Git operation failed: " + args[0])
    return proc.stdout


def remote_head():
    out = git("ls-remote", "--heads", "origin", "refs/heads/" + BRANCH).decode("ascii").strip()
    if not out:
        return None
    lines = out.splitlines()
    if len(lines) != 1:
        raise ValueError("unexpected remote state ref")
    sha, ref = lines[0].split()
    if ref != "refs/heads/" + BRANCH or len(sha) != 40:
        raise ValueError("invalid remote state ref")
    return sha


def assert_directory(directory):
    p = Path(directory)
    if not p.is_absolute() or p.is_symlink():
        raise ValueError("absolute non-symlink archive directory required")
    if not p.exists():
        p.mkdir(mode=0o700, parents=True)
    if p.stat().st_mode & 0o077:
        raise ValueError("archive directory must be private")
    return p


def atomically_write(path, data):
    if path.is_symlink():
        raise ValueError("symlink archive file forbidden")
    fd, name = tempfile.mkstemp(prefix=".ny17-transport-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        os.chmod(path, 0o600)
        dfd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
    finally:
        Path(name).unlink(missing_ok=True)


def checked_json(raw):
    if len(raw) > MAX_CHECKPOINT_BYTES:
        raise ValueError("checkpoint too large")
    obj = json.loads(raw)
    validate_checkpoint(obj)
    return obj


def unpack(blob, expected):
    if len(blob) > MAX_COMPRESSED_BYTES:
        raise ValueError("compressed checkpoint too large")
    # LZMA streaming prevents pathological expanded zip bombs.
    decoder = lzma.LZMADecompressor()
    raw = decoder.decompress(blob, max_length=MAX_CHECKPOINT_BYTES + 1)
    if not decoder.eof or decoder.unused_data or len(raw) > MAX_CHECKPOINT_BYTES:
        raise ValueError("invalid or excessive compressed checkpoint")
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError("checkpoint transport digest mismatch")
    checked_json(raw)
    return raw


def restore(directory, evidence, *, pilot_max_runs=None, continuous=False):
    if continuous and pilot_max_runs is not None:
        raise ValueError("continuous and pilot modes are exclusive")
    p = assert_directory(directory)
    sha = remote_head()
    if sha:
        git("fetch", "--no-tags", "origin", sha)
        manifest = json.loads(git("show", "FETCH_HEAD:" + MANIFEST))
        persisted_runs = manifest.get("shadow_pilot_runs", 0)
        if type(persisted_runs) is not int or persisted_runs < 0:
            raise ValueError("invalid shadow pilot count")
        if pilot_max_runs is not None and persisted_runs >= pilot_max_runs:
            return {"status": "pilot_complete", "shadow_pilot_runs": persisted_runs}
        if manifest.get("schema") not in (1, 2) or manifest.get("generation", 0) <= 0:
            raise ValueError("invalid archive manifest")
        verified = {}
        if manifest["schema"] == 2:
            if not continuous:
                raise ValueError("journal archive requires continuous mode")
            raw, previous = reconstruct_journal("FETCH_HEAD", manifest)
            verified["ny17-checkpoint.json"] = raw
            if previous is not None:
                verified["ny17-checkpoint.previous.json"] = previous
        for filename, target, field in (() if manifest["schema"] == 2 else (
            (STATE, "ny17-checkpoint.json", "state_sha256"),
            (BACKUP, "ny17-checkpoint.previous.json", "backup_sha256"),
        )):
            expected = manifest.get(field)
            if expected is None and filename == BACKUP:
                continue
            if not isinstance(expected, str) or len(expected) != 64:
                raise ValueError("missing archive checksum")
            raw = unpack(git("show", "FETCH_HEAD:" + filename), expected)
            obj = checked_json(raw)
            if filename == STATE and obj["generation"] != manifest["generation"]:
                raise ValueError("archive generation mismatch")
            verified[target] = raw
        # Verify ALL remote blobs before changing the local state.
        # In an ephemeral runner this directory starts empty; don't partially
        # install a valid current checkpoint with an invalid/missing backup.
        if any((p / target).exists() for target in ("ny17-checkpoint.json", "ny17-checkpoint.previous.json")):
            raise ValueError("restore requires an empty ephemeral archive directory")
        for target, raw in verified.items():
            atomically_write(p / target, raw)
        status = "restored"
    else:
        if continuous:
            raise ValueError("continuous restore refuses missing remote archive; no silent reseed")
        persisted_runs = 0
        from fx_system.ny_integration import PrivateArchive
        from diagnostics.issue43_ny_incremental import UTC
        archive = PrivateArchive(p, enabled=True)
        archive.bootstrap(evidence, dt.datetime.now(UTC))
        state = checked_json((p / "ny17-checkpoint.json").read_bytes())
        if state["generation"] <= 0:
            raise ValueError("archive bootstrap did not seed")
        status = "seeded"
    atomically_write(p / BASE, (sha or "none").encode())
    atomically_write(p / ".shadow-pilot-runs", str(persisted_runs).encode())
    raw = (p / "ny17-checkpoint.json").read_bytes()
    if continuous:
        atomically_write(p / RESTORED, raw)
        atomically_write(p / RESTORED_MANIFEST, json.dumps(manifest, sort_keys=True).encode())
    return {"status": status, "generation": checked_json(raw)["generation"],
            "checkpoint_sha256": hashlib.sha256(raw).hexdigest(),
            "restored_ref": sha, "shadow_pilot_runs": persisted_runs,
            "checkpoint_bytes": len(raw),
            "capacity_warning": len(raw) >= MAX_CHECKPOINT_BYTES * 3 // 4}


def publish(directory, *, pilot_max_runs=None, continuous=False):
    if continuous and pilot_max_runs is not None:
        raise ValueError("continuous and pilot modes are exclusive")
    p = assert_directory(directory)
    base = (p / BASE).read_text().strip()
    if base != "none" and (len(base) != 40 or not all(c in "0123456789abcdef" for c in base)):
        raise ValueError("invalid restore base")
    current = remote_head()
    if (current or "none") != base:
        raise ValueError("remote archive moved; fail closed, rerun against latest archive")
    state_raw = (p / "ny17-checkpoint.json").read_bytes()
    value = checked_json(state_raw)
    if continuous:
        return publish_journal(p, current, state_raw, value)
    count_path = p / ".shadow-pilot-runs"
    persisted_runs = int(count_path.read_text()) if count_path.exists() else 0
    if persisted_runs < 0 or (pilot_max_runs is not None and persisted_runs >= pilot_max_runs):
        raise ValueError("shadow pilot run limit reached")
    if value["generation"] <= 0:
        raise ValueError("refuse to persist an unseeded archive")
    backup_path = p / "ny17-checkpoint.previous.json"
    blobs = {STATE: lzma.compress(state_raw, preset=3)}
    manifest = {"schema": 1, "generation": value["generation"],
                "shadow_pilot_runs": persisted_runs + 1,
                "state_sha256": hashlib.sha256(state_raw).hexdigest(),
                "backup_sha256": None}
    if backup_path.exists():
        backup_raw = backup_path.read_bytes()
        checked_json(backup_raw)
        blobs[BACKUP] = lzma.compress(backup_raw, preset=3)
        manifest["backup_sha256"] = hashlib.sha256(backup_raw).hexdigest()
    blobs[MANIFEST] = (json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n").encode()
    hashes = {}
    for name, blob in blobs.items():
        if len(blob) > MAX_COMPRESSED_BYTES:
            raise ValueError("compressed archive capacity exceeded")
        hashes[name] = git("hash-object", "-w", "--stdin", input_data=blob).decode("ascii").strip()
    entries = "".join("100644 blob " + hashes[name] + "\t" + name + "\n" for name in sorted(hashes))
    tree = git("mktree", input_data=entries.encode()).decode("ascii").strip()
    args = ["commit-tree", tree]
    if current:
        args += ["-p", current]
    commit = git(*args, "-m", "Update private NY17 archive checkpoint").decode("ascii").strip()
    # No force push. If another publisher won, git rejects stale parent.
    git("push", "origin", commit + ":refs/heads/" + BRANCH)
    atomically_write(p / BASE, commit.encode())
    atomically_write(count_path, str(persisted_runs + 1).encode())
    return {"status": "persisted", "generation": value["generation"],
            "checkpoint_sha256": manifest["state_sha256"], "persisted_ref": commit,
            "shadow_pilot_runs": persisted_runs + 1}


def bounded_delta(blob, expected):
    if len(blob) > MAX_COMPRESSED_BYTES:
        raise ValueError("journal compressed capacity exceeded")
    decoder = lzma.LZMADecompressor()
    raw = decoder.decompress(blob, max_length=MAX_CHECKPOINT_BYTES + 1)
    if not decoder.eof or decoder.unused_data or len(raw) > MAX_CHECKPOINT_BYTES:
        raise ValueError("invalid journal compression")
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError("journal digest mismatch")
    return json.loads(raw)


def reconstruct_journal(ref, manifest):
    from .ny_archive_journal import apply, encode, CONSOLIDATE_EVERY, MAX_RETAINED_BYTES
    journal = manifest.get("journal")
    if (not isinstance(journal, list) or len(journal) >= CONSOLIDATE_EVERY or
            type(manifest.get("retained_bytes")) is not int or
            not 0 <= manifest["retained_bytes"] <= MAX_RETAINED_BYTES):
        raise ValueError("invalid journal manifest")
    raw = unpack(git("show", ref + ":" + STATE), manifest["base_sha256"])
    previous = None
    for index, item in enumerate(journal):
        name = "delta-" + str(index + 1).zfill(2) + ".json.xz"
        if item.get("path") != name or item.get("previous_sha256") != hashlib.sha256(raw).hexdigest():
            raise ValueError("journal chain mismatch")
        delta = bounded_delta(git("show", ref + ":" + name), item["delta_sha256"])
        previous = raw
        if item.get("backup_delta_sha256") is not None:
            backup_name = "backup-delta-" + str(index + 1).zfill(2) + ".json.xz"
            backup_delta = bounded_delta(git("show", ref + ":" + backup_name), item["backup_delta_sha256"])
            previous = encode(apply(checked_json(raw), backup_delta))
            checked_json(previous)
        raw = encode(apply(checked_json(raw), delta))
        if hashlib.sha256(raw).hexdigest() != item["state_sha256"]:
            raise ValueError("journal reconstructed state mismatch")
        checked_json(raw)
    if hashlib.sha256(raw).hexdigest() != manifest["state_sha256"] or checked_json(raw)["generation"] != manifest["generation"]:
        raise ValueError("journal head mismatch")
    if not journal and manifest.get("backup_sha256") is not None:
        previous = unpack(git("show", ref + ":" + BACKUP), manifest["backup_sha256"])
    if (hashlib.sha256(previous).hexdigest() if previous is not None else None) != manifest.get("backup_sha256"):
        raise ValueError("journal backup mismatch")
    return raw, previous


def retained_object_bytes(ref):
    objects = b"\n".join(line.split()[0] for line in git("rev-list", "--objects", ref).splitlines()) + b"\n"
    sizes = git("cat-file", "--batch-check=%(objectsize)", input_data=objects)
    try:
        return sum(int(line) for line in sizes.splitlines())
    except ValueError as exc:
        raise ValueError("archive retained capacity unavailable") from exc


def publish_journal(p, current, state_raw, value):
    from .ny_archive_journal import difference, apply, encode, CONSOLIDATE_EVERY, MAX_RETAINED_BYTES, OBJECT_OVERHEAD_RESERVE
    from diagnostics.issue43_ny_incremental import digest
    if not current:
        raise ValueError("continuous publish requires restored remote lineage")
    previous_raw = (p / RESTORED).read_bytes()
    previous = checked_json(previous_raw)
    prior_manifest = json.loads((p / RESTORED_MANIFEST).read_bytes())
    if hashlib.sha256(previous_raw).hexdigest() != prior_manifest["state_sha256"]:
        raise ValueError("restored journal anchor mismatch")
    if state_raw == previous_raw:
        return {"status": "unchanged", "generation": value["generation"],
                "checkpoint_sha256": prior_manifest["state_sha256"], "persisted_ref": current,
                "shadow_pilot_runs": prior_manifest.get("shadow_pilot_runs", 0),
                "checkpoint_bytes": len(state_raw), "retained_bytes": prior_manifest.get("retained_bytes"),
                "capacity_warning": len(state_raw) >= MAX_CHECKPOINT_BYTES * 3 // 4 or
                    (prior_manifest.get("retained_bytes", 0) >= MAX_RETAINED_BYTES * 3 // 4)}
    if value["generation"] <= previous["generation"]:
        raise ValueError("continuous checkpoint lineage mismatch")
    backup_raw = (p / "ny17-checkpoint.previous.json").read_bytes()
    backup = checked_json(backup_raw)
    if (not previous["generation"] <= backup["generation"] < value["generation"] or
            value["previous_checkpoint_sha256"] != digest(backup)):
        raise ValueError("continuous backup checkpoint lineage mismatch")
    delta = difference(previous, value)
    if encode(apply(previous, delta)) != state_raw:
        raise ValueError("checkpoint serialization not canonical")
    journal = list(prior_manifest.get("journal", []))
    blobs = {}
    hashes = {}
    prior_total = prior_manifest.get("retained_bytes") if prior_manifest.get("schema") == 2 else retained_object_bytes(current)
    consolidate = prior_manifest.get("schema") != 2 or len(journal) + 1 >= CONSOLIDATE_EVERY
    if consolidate:
        blobs[STATE] = lzma.compress(state_raw, preset=3)
        blobs[BACKUP] = lzma.compress(backup_raw, preset=3)
        journal = []
        base_hash = hashlib.sha256(state_raw).hexdigest()
    else:
        # Copy only known archive blobs from the restored tree. No price data
        # enters main, and no Git history/evidence ref is rewritten or deleted.
        names = [STATE, BACKUP, *(j["path"] for j in journal)]
        names += ["backup-delta-" + str(i + 1).zfill(2) + ".json.xz"
                  for i, j in enumerate(journal) if j.get("backup_delta_sha256") is not None]
        for name in names:
            hashes[name] = git("rev-parse", current + ":" + name).decode().strip()
        payload = encode(delta)
        name = "delta-" + str(len(journal) + 1).zfill(2) + ".json.xz"
        blobs[name] = lzma.compress(payload, preset=3)
        item = {"path": name, "delta_sha256": hashlib.sha256(payload).hexdigest(),
                        "previous_sha256": hashlib.sha256(previous_raw).hexdigest(),
                        "state_sha256": hashlib.sha256(state_raw).hexdigest()}
        if backup_raw != previous_raw:
            backup_payload = encode(difference(previous, backup))
            if encode(apply(previous, json.loads(backup_payload))) != backup_raw:
                raise ValueError("backup serialization not canonical")
            blobs["backup-" + name] = lzma.compress(backup_payload, preset=3)
            item["backup_delta_sha256"] = hashlib.sha256(backup_payload).hexdigest()
        journal.append(item)
        base_hash = prior_manifest["base_sha256"]
    retained = prior_total + sum(len(b) for b in blobs.values()) + OBJECT_OVERHEAD_RESERVE
    if retained > MAX_RETAINED_BYTES:
        raise ValueError("retained archive budget exceeded; preserve remote and request capacity review")
    manifest = {"schema": 2, "generation": value["generation"],
                "state_sha256": hashlib.sha256(state_raw).hexdigest(),
                "backup_sha256": hashlib.sha256(backup_raw).hexdigest(),
                "base_sha256": base_hash, "journal": journal,
                "shadow_pilot_runs": prior_manifest.get("shadow_pilot_runs", 0),
                "retained_bytes": retained, "consolidate_every": CONSOLIDATE_EVERY,
                "retention": "lossless_no_delete_budgeted"}
    blobs[MANIFEST] = encode(manifest)
    if len(blobs[MANIFEST]) > OBJECT_OVERHEAD_RESERVE // 2:
        raise ValueError("journal manifest capacity exceeded")
    for name, blob in blobs.items():
        if len(blob) > MAX_COMPRESSED_BYTES:
            raise ValueError("journal blob capacity exceeded")
        hashes[name] = git("hash-object", "-w", "--stdin", input_data=blob).decode().strip()
    entries = "".join("100644 blob " + hashes[name] + "\t" + name + "\n" for name in sorted(hashes))
    tree = git("mktree", input_data=entries.encode()).decode().strip()
    commit = git("commit-tree", tree, "-p", current, "-m", "Update private NY17 journal checkpoint").decode().strip()
    # Fast-forward only; both preflight CAS and server-side push reject races.
    git("push", "origin", commit + ":refs/heads/" + BRANCH)
    atomically_write(p / BASE, commit.encode())
    atomically_write(p / RESTORED, state_raw)
    atomically_write(p / RESTORED_MANIFEST, encode(manifest))
    return {"status": "persisted", "generation": value["generation"],
            "checkpoint_sha256": manifest["state_sha256"], "persisted_ref": commit,
            "shadow_pilot_runs": manifest["shadow_pilot_runs"],
            "journal_entries": len(journal), "consolidated": consolidate,
            "new_compressed_bytes": sum(len(b) for b in blobs.values()), "retained_bytes": retained,
            "checkpoint_bytes": len(state_raw),
            "capacity_warning": retained >= MAX_RETAINED_BYTES * 3 // 4 or len(state_raw) >= MAX_CHECKPOINT_BYTES * 3 // 4}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=["restore", "publish"])
    parser.add_argument("--directory", required=True)
    parser.add_argument("--evidence-directory", default="evidence/issue43-h1-originals")
    parser.add_argument("--pilot-max-runs", type=int, choices=[2])
    parser.add_argument("--continuous", action="store_true")
    args = parser.parse_args()
    result = restore(args.directory, args.evidence_directory, pilot_max_runs=args.pilot_max_runs, continuous=args.continuous) if args.operation == "restore" else publish(args.directory, pilot_max_runs=args.pilot_max_runs, continuous=args.continuous)
    if result.get("capacity_warning"):
        print("::warning::NY17 archive at 75 percent capacity; review lossless retention before hard limit", file=sys.stderr)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()

