from .events import append, restore


def save(store, state, refs=None, offset=0):
    archive = state["archive"]
    outer = {key: value for key, value in state.items() if key not in ("archive", "receipts")}
    entries = state["receipts"]
    receipts = [store.put(entries[i:i + 256]) for i in range(0, len(entries), 256)]
    metadata = {key: value for key, value in archive.items() if key not in ("events", "pairs")}
    refs = append(store, refs or {}, offset, archive["events"][offset:])
    return dict(refs=refs, outer=store.put(outer), metadata=store.put(metadata), receipts=receipts,
                empty_pairs=sorted(pair for pair, rows in archive["pairs"].items() if not rows))


def rebuild(store, index):
    events, rows = restore(store, index["refs"])
    rows.update({pair: {} for pair in index["empty_pairs"]})
    archive = {**store.get(index["metadata"]), "events": events, "pairs": rows}
    outer = store.get(index["outer"])
    if "receipts" in index:
        outer["receipts"] = [item for key in index["receipts"] for item in store.get(key)]
    return {**outer, "archive": archive}
