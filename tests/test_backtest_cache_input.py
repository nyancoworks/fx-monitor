import copy
import hashlib
import json
import unittest
from datetime import datetime,timezone
from zoneinfo import ZoneInfo
from fx_system.backtest_cache_input import PAIRS,batches_from_cache,daily_batches_from_snapshot


class CacheInputTests(unittest.TestCase):
    def fixture(self):
        bar={'timestamp':300,'open':1.,'high':1.2,'low':.9,'close':1.1}
        return {pair:{'m5':[dict(bar)],'h1':[],
                      'bar_provenance':{'m5:300':'Twelve Data'}} for pair in PAIRS}

    def read(self,data,now=600):
        raw=json.dumps(data).encode()
        sha=hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()
        return batches_from_cache(raw,expected_git_blob=sha,evaluated_at=now)

    def test_all16_and_no_invented_d1_or_original_mutation(self):
        data=self.fixture();original=copy.deepcopy(data)
        batches,report=self.read(data)
        self.assertEqual(len(batches),16);self.assertEqual(report['accepted_rows'],16)
        self.assertFalse(report['d1_from_cache_used'])
        self.assertEqual(data,original)
        self.assertTrue(all(b['rows'][0]['captured_at']==600 for b in batches))

    def test_unknown_source_and_forming_rows_are_reported_not_filled(self):
        data=self.fixture();data['EURUSD']['bar_provenance']={}
        batches,report=self.read(data)
        self.assertEqual(report['accepted_rows'],15)
        self.assertEqual(len(report['unknown_source_rows']),1)
        batches,report=self.read(data,now=599)
        self.assertEqual(batches,[]);self.assertEqual(len(report['forming_rows']),16)

    def test_canonical_hash_and_pair_completeness_required(self):
        with self.assertRaises(ValueError):batches_from_cache(b'{}',expected_git_blob='0'*40,evaluated_at=600)
        data=self.fixture();del data['EURUSD']
        with self.assertRaises(ValueError):self.read(data)


class DailyInputTests(unittest.TestCase):
    def fixture(self):
        end=int(datetime(2030,1,1,17,tzinfo=ZoneInfo('America/New_York')).timestamp())
        bar={'timestamp':end-86400,'session_end_utc':end,'open':100,'high':102,'low':99,'close':101}
        return {'evaluated_at':end+1,'ny17_transport':{'restore_ok':True,'save_ok':True},
                'pairs':{pair:{'d1':{'candles':[bar], 'quality':{'calendar':'America/New_York 17:00'}},
                               'decision_quality':{'ny17':{'adoption_ready':True}}} for pair in PAIRS}}

    def read(self,value):
        raw=json.dumps(value).encode();sha=hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()
        return daily_batches_from_snapshot(raw,expected_git_blob=sha,evaluated_at=value['evaluated_at'])

    def test_daily_boundary_month_and_original_preserved(self):
        data=self.fixture();old=copy.deepcopy(data);rows,quality=self.read(data)
        self.assertEqual(data,old);self.assertEqual(quality['d1_rows'],16)
        self.assertEqual(rows[0]['month'],'2029-12')
        self.assertEqual(rows[0]['rows'][0]['session_policy'],'NY17_verified')
        self.assertFalse(quality['provider_publication_clock_verified'])

    def test_unknown_daily_is_unavailable_not_native_UTC_substitution(self):
        data=self.fixture();data['pairs']['EURUSD']['decision_quality']['ny17']['adoption_ready']=False
        rows,quality=self.read(data);self.assertEqual(len(rows),15)
        self.assertEqual(quality['unavailable_d1_pairs'],['EURUSD'])

    def test_persistence_failure_or_false_daily_boundary_stops(self):
        data=self.fixture();data['ny17_transport']['save_ok']=False
        with self.assertRaises(ValueError):self.read(data)
        data=self.fixture();data['pairs']['EURUSD']['d1']['candles'][0]['session_end_utc']+=3600
        with self.assertRaises(ValueError):self.read(data)


if __name__=='__main__':unittest.main()
