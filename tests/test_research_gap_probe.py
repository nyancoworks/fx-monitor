import datetime as dt
import time
import unittest

from fx_system.research_gap_probe import probe, SCHEMA


class Quota:
    def delay(self, now):
        return 0

    def reserve(self, now):
        pass

    def observe(self, headers, wall, monotonic):
        pass


class Response:
    status_code = 200
    ok = True
    headers = {'api-credits-request': '1'}

    def __init__(self, values):
        self.values = values

    def json(self):
        return {'values': self.values}


class Session:
    def __init__(self, count):
        self.count = count
        self.calls = 0

    def get(self, url, params, timeout):
        self.calls += 1
        assert url == 'https://api.twelvedata.com/time_series'
        assert 'outputsize' not in params
        assert params['symbol'] == 'EUR/USD' and params['interval'] == '1h'
        assert params['timezone'] == 'UTC' and params['apikey'] == 'test-key'
        start = dt.datetime.strptime(params['start_date'], '%Y-%m-%d %H:%M:%S')
        values = [{'datetime': (start + dt.timedelta(hours=i)).strftime('%Y-%m-%d %H:%M:%S'),
                   'open': '1.0', 'high': '1.1', 'low': '0.9', 'close': '1.05'}
                  for i in range(self.count)]
        return Response(values)


def check_receipt(count, status):
    config = {'schema': SCHEMA, 'targets': [{'pair': 'EUR/USD', 'ny_date': '2026-06-03'}]}
    now = int(dt.datetime(2026, 11, 20, tzinfo=dt.timezone.utc).timestamp())
    budget = {'utc_day': '2026-11-20', 'requests': 10, 'credits': 10,
              'daily_limit': 800, 'reserve': 80}
    session = Session(count)
    receipt, calls = probe(config, None, session, 'test-key', budget, now, Quota(), time.monotonic()+30)
    assert calls == session.calls == 1
    result = receipt['results']['EURUSD:2026-06-03']
    assert result['status'] == status and len(result['rows']) == count
    assert result['provider'] == 'Twelve Data' and 'test-key' not in str(receipt)
    assert budget['requests'] == 11 and budget['credits'] == 11
    receipt2, calls2 = probe(config, receipt, session, 'test-key', budget, now, Quota(), time.monotonic()+30)
    assert calls2 == 0 and receipt2['results'] == receipt['results']


class TestResearchGapProbe(unittest.TestCase):
    def test_full_and_incomplete_sessions(self):
        check_receipt(24, 'complete')
        check_receipt(23, 'incomplete')

    def test_changed_identity_rejected_before_request(self):
        config = {'schema': SCHEMA, 'targets': [{'pair': 'EUR/USD', 'ny_date': '2026-06-03'}]}
        with self.assertRaises(ValueError):
            probe(config, {'schema': SCHEMA, 'targets': [], 'results': {}}, Session(24), 'test-key',
                  {}, time.time(), Quota(), time.monotonic()+30)
