from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from fx_system.acceptance_release import AcceptanceRelease
from fx_system.backtest_release_store import ReleaseWarehouse


class AcceptanceReleaseTest(unittest.TestCase):
    def test_release_warehouse_round_trip_across_process_adapters(self):
        now = int(datetime(2026, 11, 29, tzinfo=timezone.utc).timestamp())
        batch = {"provider": "Synthetic", "pair": "EURUSD", "tf": "h1",
                 "month": "2026-11", "rows": [
                     {"timestamp": now - 3600, "open": 1, "high": 2, "low": 1, "close": 2,
                      "source": "Synthetic", "captured_at": now,
                      "capture_basis": "saved_cache_known_by"}]}
        with TemporaryDirectory() as directory, patch.dict("os.environ", {"FX_OFFLINE_ACCEPTANCE": "1"}):
            root = Path(directory)
            (root / ".private-acceptance").mkdir()
            one = AcceptanceRelease(root)
            result = ReleaseWarehouse(one).cycle([batch], now=now, source={"test": True})
            self.assertEqual(result["added"], 1)
            one.db.close()
            two = AcceptanceRelease(root)
            result = ReleaseWarehouse(two).cycle([batch], now=now, source={"test": True})
            self.assertEqual(result["status"], "unchanged")
            self.assertGreater(two.db.execute("SELECT sum(size) FROM assets").fetchone()[0], 0)
            two.db.close()
