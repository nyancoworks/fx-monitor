from datetime import datetime, timezone
import tempfile
from pathlib import Path
import unittest

from fx_system.ny_history_segments import encode_segment, read_segment


class SegmentTest(unittest.TestCase):
    def test_round_trip_and_corruption(self):
        stamp = int(datetime(2025, 1, 1, tzinfo=timezone.utc).timestamp())
        rows = [dict(timestamp=stamp + index * 3600, open=1.2, high=1.3, low=1.1, close=1.2)
                for index in range(8760)]
        received = stamp + 8760 * 3600
        item, blob = encode_segment('USDJPY', 2025, received, rows)
        with tempfile.TemporaryDirectory() as working:
            directory = Path(working)
            path = directory / f"USDJPY-2025-{item['sha256']}.json.gz"
            path.write_bytes(blob)
            self.assertEqual(read_segment(directory, 'USDJPY', item, received), rows)
            with self.assertRaises(ValueError):
                read_segment(directory, 'USDJPY', item, received - 1)
            path.write_bytes(blob + b'corruption')
            with self.assertRaises(ValueError):
                read_segment(directory, 'USDJPY', item, received)

    def test_missing_ranges_exclude_retained_hours(self):
        from fx_system.ny_history_backfill import missing_ranges

        clock = datetime(2026, 11, 27, 23, tzinfo=timezone.utc)
        retained = int(datetime(2026, 11, 27, 2, tzinfo=timezone.utc).timestamp())
        ranges = missing_ranges({str(retained): {}}, clock)
        self.assertTrue(ranges)
        self.assertFalse(any(first <= retained <= last for first, last in ranges))
        self.assertTrue(all(last - first < 5000 * 3600 for first, last in ranges))
