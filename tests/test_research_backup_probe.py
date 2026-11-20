import datetime as dt
import lzma
import struct
import time
import unittest

from fx_system.research_backup_probe import probe, SCHEMA


class Response:
    def __init__(self, code, payload=b''):
        self.status_code = code
        self.ok = code == 200
        self.content = payload


class Session:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def get(self, url, timeout):
        self.calls.append(url)
        assert url.startswith('https://datafeed.dukascopy.com/datafeed/EURUSD/')
        return next(self.responses)


class TestBackupPresence(unittest.TestCase):
    def test_absent_hour_and_present_hour_are_distinct_private_receipts(self):
        hours = [int(dt.datetime(2026, 6, 2, h, tzinfo=dt.timezone.utc).timestamp()) for h in (1, 2)]
        config = {'schema': SCHEMA, 'targets': [{'pair': 'EUR/USD', 'hour_utc': h} for h in hours]}
        tick = struct.pack('>IIIff', 100, 110100, 110000, 1.0, 1.0)
        session = Session([Response(404), Response(200, lzma.compress(tick))])
        now = int(dt.datetime(2026, 11, 20, tzinfo=dt.timezone.utc).timestamp())
        receipt, calls = probe(config, None, session, now, time.monotonic()+30)
        self.assertEqual(calls, 2)
        statuses = [receipt['results']['EURUSD:'+str(h)]['status'] for h in hours]
        self.assertEqual(statuses, ['http_404', 'ticks_present'])
        self.assertEqual(receipt['results']['EURUSD:'+str(hours[1])]['bid_ohlc']['close'], 1.1)
        self.assertEqual(receipt['scope'], 'private_source_presence_only_not_canonical_h1')
        self.assertEqual(probe(config, receipt, session, now, time.monotonic()+30)[1], 0)

    def test_changed_target_rejected_without_request(self):
        config = {'schema': SCHEMA, 'targets': [{'pair': 'EUR/USD', 'hour_utc': 1780362000}]}
        session = Session([])
        with self.assertRaises(ValueError):
            probe(config, {'schema': SCHEMA, 'targets': [], 'results': {}}, session,
                  time.time(), time.monotonic()+30)
        self.assertEqual(session.calls, [])
