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

    def test_single_hour_query_preserves_full_end_hour(self):
        from unittest.mock import Mock
        from fx_system.ny_history_backfill import request_rows

        stamp = int(datetime(2026, 11, 27, 2, tzinfo=timezone.utc).timestamp())
        session = Mock()
        response = session.get.return_value
        response.status_code = 200
        response.headers = {}
        response.json.return_value = {
            'status': 'ok', 'meta': {'symbol': 'USD/JPY', 'interval': '1h'},
            'values': [{'datetime': '2026-11-27 02:00:00', 'open': '1', 'high': '2',
                        'low': '1', 'close': '2'}],
        }
        self.assertIn(stamp, request_rows(session, 'test', 'USDJPY', stamp, stamp))
        self.assertEqual(session.get.call_args.kwargs['params']['end_date'], '2026-11-27 02:59:59')

    def test_empty_response_and_plan_error_have_different_outcomes(self):
        from unittest.mock import Mock
        from fx_system.ny_history_backfill import BackfillResponseError, response_data

        response = Mock(status_code=400)
        response.json.return_value = {'status': 'error', 'code': 400,
                                      'message': 'No data is available on the specified dates'}
        self.assertIsNone(response_data(response))
        response.json.return_value['message'] = 'Your plan does not permit historical data'
        with self.assertRaises(BackfillResponseError):
            response_data(response)
