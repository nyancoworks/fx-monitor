"""Partitioned NY17 transport for the existing collection stages."""
import argparse
from collections import Counter
import json
import os
from pathlib import Path

from .. import ny_archive_transport as legacy
from .checkpoint import save
from .git_generation import GitGeneration, GitReader
from .partition_store import PartitionStore
from .partition_budget import OBJECT_RESERVE

CURRENT = "ny17-checkpoint.json"
PREVIOUS = "ny17-checkpoint.previous.json"
REF = "ny17-validation-collection"


def install(store, transport, head):
    reader = GitReader(transport, head)
    partitions = reader.receipt["partitions"]
    if reader.receipt.get("schema") != 1 or len(reader.receipt["roots"]) > 3:
        raise ValueError("invalid generation manifest")
    observed = Counter()
    with store.publish(None):
        for number, usage in partitions:
            if type(number) is not int or number < 0 or not 0 <= usage <= store.limit:
                raise ValueError("invalid partition accounting")
            store.db.execute("INSERT OR REPLACE INTO partitions VALUES(?,?)", (number, usage))
        for key, path in reader.locations.items():
            partition = int(path.split("/")[1])
            if len(key) != 64 or any(char not in "0123456789abcdef" for char in key):
                raise ValueError("invalid object identity")
            directory = store.root / str(partition)
            directory.mkdir(exist_ok=True)
            payload = transport.git("show", head + ":" + path)
            observed[partition] += len(payload) + OBJECT_RESERVE
            (directory / key).write_bytes(payload)
            store.read(directory / key, key)
            store.db.execute("INSERT INTO objects VALUES(?,?)", (key, partition))
        if dict(observed) != {number: used for number, used in partitions if used}:
            raise ValueError("partition accounting does not match stored objects")
        for generation, key in reversed(reader.receipt["roots"]):
            store.advance(generation, key)


def import_legacy(directory, store):
    """One-time conversion of the pinned legacy current and previous checkpoints."""
    previous = directory / PREVIOUS
    with store.publish(None):
        for source in (previous, directory / CURRENT):
            if not source.exists():
                continue
            state = legacy.checked_json(source.read_bytes())
            archive = state["archive"]
            entries = {}
            pairs = archive["pairs"].keys() | state["blocked_pairs"].keys() | {
                r["pair"] for r in state["receipts"]}
            for pair in sorted(pairs):
                scoped = {**state,
                          "archive": {**archive,
                                      "pairs": {pair: archive["pairs"][pair]} if pair in archive["pairs"] else {},
                                      "events": [e for e in archive["events"] if e["pair"] == pair]},
                          "blocked_pairs": {pair: state["blocked_pairs"][pair]} if pair in state["blocked_pairs"] else {},
                          "receipts": [r for r in state["receipts"] if r["pair"] == pair]}
                entries[pair] = store.put(save(store, scoped))
            store.advance(state["generation"], store.put({"schema": 2, "pairs": entries}))


def restore(directory, store, transport):
    head = transport.fetch()
    if head is None:
        if os.getenv("FX_NY17_CANDIDATE_BOOTSTRAP") != "true":
            raise ValueError("missing candidate archive; explicit bootstrap required")
        legacy.restore(directory, None, continuous=True)
        import_legacy(directory, store)
    else:
        install(store, transport, head)
    legacy.atomically_write(directory / ".partitioned-base", (head or "").encode())
    return receipt(store, "restored", head)


def receipt(store, status, head):
    generation, root = store.roots()[0]
    if store.get(root).get("schema") != 2:
        raise ValueError("unsupported candidate format; bootstrap on a fresh validation ref")
    partitions = store.db.execute("SELECT id,used FROM partitions ORDER BY id").fetchall()
    active, used = max((number, size) for number, size in partitions if size or number == 0)
    return {"status": status, "generation": generation, "generation_root_sha256": root,
            "restored_ref" if status == "restored" else "persisted_ref": head,
            "retained_bytes": used, "capacity_warning": used >= store.prepare,
            "active_partition": active, "partition_limit_bytes": store.limit,
            "remaining_partition_bytes": store.limit - used,
            "total_partition_bytes": sum(size for _, size in partitions),
            "prepared_next_partition": (active + 1, 0) in partitions}


def publish(directory, store, transport):
    expected = (directory / ".partitioned-base").read_text().strip() or None
    receipt(store, "persisted", expected)
    head = transport.publish(store, expected)
    return receipt(store, "unchanged" if expected == head else "persisted", head)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=("restore", "publish"))
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--continuous", action="store_true", required=True)
    args = parser.parse_args()
    directory = legacy.assert_directory(args.directory)
    store = PartitionStore(directory / ".partition-store")
    transport = GitGeneration(Path.cwd(), branch=REF)
    operation = restore if args.operation == "restore" else publish
    print(json.dumps(operation(directory, store, transport), sort_keys=True))


if __name__ == "__main__":
    main()
