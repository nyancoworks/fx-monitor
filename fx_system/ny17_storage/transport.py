"""Compatibility bridge for the existing NY17 restore/refresh/archive stages."""
import argparse
import json
import os
from pathlib import Path

from .. import ny_archive_transport as legacy
from ..ny_archive_journal import encode
from .checkpoint import rebuild, save
from .events import sha
from .git_generation import GitGeneration, GitReader
from .partition_store import PartitionStore

CURRENT = "ny17-checkpoint.json"
PREVIOUS = "ny17-checkpoint.previous.json"
REF = "ny17-validation-collection"


def install(store, transport, head):
    reader = GitReader(transport, head)
    partitions = reader.receipt["partitions"]
    if reader.receipt.get("schema") != 1 or len(reader.receipt["roots"]) > 3:
        raise ValueError("invalid generation manifest")
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
            (directory / key).write_bytes(transport.git("show", head + ":" + path))
            store.db.execute("INSERT INTO objects VALUES(?,?)", (key, partition))
        for generation, key in reversed(reader.receipt["roots"]):
            store.advance(generation, key)


def restore(directory, store, transport):
    head = transport.fetch()
    if head is None:
        if os.getenv("FX_NY17_CANDIDATE_BOOTSTRAP") != "true":
            raise ValueError("missing candidate archive; explicit bootstrap required")
        return legacy.restore(directory, None, continuous=True)
    install(store, transport, head)
    states = []
    for generation, key in store.roots()[:2]:
        raw = encode(rebuild(store, store.get(key)))
        if legacy.checked_json(raw)["generation"] != generation:
            raise ValueError("generation mismatch")
        states.append(raw)
    if not states or any((directory / name).exists() for name in (CURRENT, PREVIOUS)):
        raise ValueError("expected an empty restore directory and a published head")
    for name, raw in zip((CURRENT, PREVIOUS), states):
        legacy.atomically_write(directory / name, raw)
    legacy.atomically_write(directory / legacy.BASE, head.encode())
    return receipt(store, "restored", head, states[0])


def receipt(store, status, head, raw):
    generation = legacy.checked_json(raw)["generation"]
    used = store.db.execute("SELECT max(used) FROM partitions").fetchone()[0]
    return {"status": status, "generation": generation, "checkpoint_sha256": sha(raw),
            "restored_ref" if status == "restored" else "persisted_ref": head,
            "checkpoint_bytes": len(raw), "retained_bytes": used,
            "capacity_warning": used >= store.prepare}


def publish(directory, store, transport):
    raw = (directory / CURRENT).read_bytes()
    state = legacy.checked_json(raw)
    roots = store.roots()
    expected = (directory / legacy.BASE).read_text().strip() if roots else None
    prior = roots[0][0] if roots else None
    with store.publish(prior):
        backup = directory / PREVIOUS
        if not roots and backup.exists():
            previous = legacy.checked_json(backup.read_bytes())
            store.advance(previous["generation"], store.put(save(store, previous)))
            roots = store.roots()
        if roots:
            old_index = store.get(roots[0][1])
            old = rebuild(store, old_index)
            old_events = old["archive"]["events"]
            events = state["archive"]["events"]
            if events[:len(old_events)] != old_events:
                raise ValueError("archive event prefix changed")
            if state["generation"] == old["generation"]:
                if state != old:
                    raise ValueError("changed state under an existing generation")
            elif state["generation"] == old["generation"] + 1:
                root = save(store, state, old_index["refs"], len(old_events))
                store.advance(state["generation"], store.put(root))
            else:
                raise ValueError("unexpected generation")
        else:
            store.advance(state["generation"], store.put(save(store, state)))
        root = store.get(store.roots()[0][1])
        if encode(rebuild(store, root)) != raw:
            raise ValueError("candidate does not preserve checkpoint bytes")
    head = transport.publish(store, expected)
    return receipt(store, "unchanged" if expected == head else "persisted", head, raw)


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
