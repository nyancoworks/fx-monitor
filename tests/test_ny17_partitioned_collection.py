import datetime as dt
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from diagnostics.issue43_ny_runtime import empty_checkpoint, observation
from fx_system.monitor_pairs import PAIR_KEYS
from fx_system.ny17_storage.checkpoint import save
from fx_system.ny17_storage.partition_store import PartitionStore
from fx_system.ny_integration import configured


class PartitionedCollectionTest(unittest.TestCase):
    def test_normal_collection_accepts_more_than_monolithic_limit(self):
        stamp = 1795791600
        with TemporaryDirectory() as folder:
            root = Path(folder)
            directory = root / "private"
            directory.mkdir(mode=0o700)
            store = PartitionStore(directory / ".partition-store")
            # Model a valid large archive envelope with synthetic receipt padding.
            # Each individual object fits the format's object limit.
            payload = "x" * (4 * 1024 * 1024 + 1)
            self.assertGreater(len(PAIR_KEYS) * len(payload), 64 * 1024 * 1024)
            with store.publish(None):
                entries = {}
                for pair in PAIR_KEYS:
                    state = empty_checkpoint()
                    state["receipts"] = [{"pair": pair, "available_at_utc": "2026-01-01T00:00:00+00:00", "synthetic_padding": payload}]
                    entries[pair] = store.put(save(store, state))
                store.advance(560, store.put({"schema": 2, "pairs": entries}))
            store.db.close()
            with patch.dict(os.environ, {"FX_NY17_MODE": "adopt",
                                         "FX_NY17_ARCHIVE_DIR": str(directory),
                                         "FX_NY17_STORAGE_MODE": "partitioned_candidate",
                                         "FX_NY17_EVIDENCE_PROFILE": "",
                                         "FX_NY17_RESTORE_FAILED": "0"}):
                context = configured(root, root / "data/cache.json", root / "data/latest.json")
                bar = dict(timestamp=stamp, open=1.0, high=1.2, low=0.9, close=1.1)
                now = stamp + 3600
                context.queue = [observation("EURUSD", [bar], dt.datetime.fromtimestamp(now, dt.timezone.utc))]
                context.synchronize({"evaluated_at": now, "pairs": {}})
                self.assertIsNone(context.failure)
                state = context.pair_checkpoint("EURUSD")
                self.assertEqual(state["archive"]["pairs"]["EURUSD"][str(stamp)], bar)
                self.assertEqual(context.context("EURUSD", now)["observed_availability"]["covered_h1"], 1)
                self.assertEqual(context.sidecar.read_window("EURUSD", stamp, now), {str(stamp): bar})
                self.assertFalse((directory / "ny17-checkpoint.json").exists())
