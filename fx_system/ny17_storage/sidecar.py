"""Pair-scoped NY17 state for the normal collection stages."""
from pathlib import Path

from diagnostics.issue43_ny_runtime import NYSidecar, empty_checkpoint, validate_checkpoint

from .checkpoint import rebuild, save
from .events import restore
from .partition_store import PartitionStore


class PairCapture(NYSidecar):
    def __init__(self, directory, value):
        super().__init__(directory, enabled=True)
        self.value = value

    def load(self):
        return self.value

    def _commit(self, value):
        validate_checkpoint(value)
        self.value = value

    def quality(self, *args, **kwargs):
        # The normal analysis computes quality once at its final clock.
        return {}


class PartitionedSidecar:
    def __init__(self, directory):
        self.directory = Path(directory)

    def store(self):
        if not (self.directory / ".partition-store/index.sqlite").is_file():
            raise ValueError("partitioned restore required")
        return PartitionStore(self.directory / ".partition-store")

    def load(self):
        store = self.store()
        try:
            _, key = store.roots()[0]
            return store.get(key)
        finally:
            store.db.close()

    def load_pair(self, pair):
        store = self.store()
        try:
            generation, key = store.roots()[0]
            entry = store.get(key)["pairs"].get(pair)
            if entry is None:
                return {**empty_checkpoint(), "generation": generation}
            return rebuild(store, store.get(entry))
        finally:
            store.db.close()

    def read_window(self, pair, start, end):
        """Read a bounded H1 interval without materializing other months."""
        if type(start) is not int or type(end) is not int or start >= end:
            raise ValueError("invalid half-open H1 interval")
        store = self.store()
        try:
            _, key = store.roots()[0]
            entry = store.get(key)["pairs"].get(pair)
            if entry is None:
                return {}
            _, rows = restore(store, store.get(entry)["refs"], pair=pair, start=start, end=end)
            return rows.get(pair, {})
        finally:
            store.db.close()

    def apply(self, transform, pairs):
        store = self.store()
        try:
            generation, key = store.roots()[0]
            original = store.get(key)["pairs"]
            with store.publish(generation):
                updated = dict(original)
                for pair in sorted(pairs):
                    old_index = store.get(original[pair]) if pair in original else None
                    old = rebuild(store, old_index) if old_index else empty_checkpoint()
                    capture = PairCapture(self.directory, old)
                    transform(pair, capture)
                    if capture.value == old:
                        continue
                    offset = len(old["archive"]["events"])
                    updated[pair] = store.put(save(
                        store, capture.value, old_index["refs"] if old_index else None, offset))
                if updated != original:
                    store.advance(generation + 1, store.put({"schema": 2, "pairs": updated}))
        finally:
            store.db.close()

    def update(self, observations):
        pairs = {row["pair"] for row in observations}
        self.apply(lambda pair, capture: capture.update(
            [row for row in observations if row["pair"] == pair]), pairs)

    def seed_additional_originals(self, evidence_directory, as_of):
        from ..ny_integration import PrivateArchive
        from ..ny_observed_policy import verify_originals
        contracts = verify_originals(evidence_directory)

        def seed(pair, capture):
            # Reuse the existing original-evidence checks with a scoped reader.
            class SeedCapture(PairCapture):
                def update(self, observations, **kwargs):
                    return super().update([o for o in observations if o["pair"] == pair], **kwargs)

            seeded = SeedCapture(self.directory, capture.value)
            PrivateArchive.seed_additional_originals(seeded, evidence_directory, as_of)
            capture.value = seeded.value

        missing = set(contracts) - set(self.load()["pairs"])
        if missing:
            self.apply(seed, missing)

    def synchronize(self, production, captured, **kwargs):
        def synchronize(pair, capture):
            pairs = production["pairs"]
            scoped = {**production, "pairs": {pair: pairs[pair]} if pair in pairs else {}}
            capture.synchronize(scoped, [row for row in captured if row["pair"] == pair], **kwargs)

        self.apply(synchronize, set(production["pairs"]) | {row["pair"] for row in captured})
