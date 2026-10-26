import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from fx_system.backtest_failure import metadata, safe_failure_line, PREFIX

class FailureTests(unittest.TestCase):
    def test_only_fixed_metadata_survives_private_log(self):
        for error,code in [(ValueError('conflicting archive revision'),'archive_revision_conflict'),
                           (ValueError('secret URL private price'),'unclassified')]:
            data=metadata(error,'storage')
            line=safe_failure_line('private raw data\n'+PREFIX+json.dumps(data)+'\nprivate traceback')
            self.assertEqual(json.loads(line[len(PREFIX):])['code'],code)
            self.assertNotIn('secret',line)
            self.assertNotIn('private',line)

    def test_transport_failure_and_status_are_bounded(self):
        from fx_system.backtest_release_store import GitHubStorage
        class Response:
            status_code=503
            headers={}
            def close(self): pass
        class Session:
            def request(self,*args,**kwargs): return Response()
        api=GitHubStorage('synthetic-token',session=Session())
        with self.assertRaises(ValueError) as error:
            api.request('GET','')
        self.assertEqual(metadata(error.exception,'storage',api),
            {'code':'http_failure','phase':'storage','requests':1,'http_status':503})
        with patch.dict('sys.modules', requests=SimpleNamespace(Timeout=TimeoutError,ConnectionError=ConnectionError)):
            self.assertEqual(metadata(ConnectionError('secret'),'storage')['code'],'connection')

    def test_malformed_or_extra_payload_never_passes_through(self):
        valid=metadata(ValueError('storage HTTP operation failed'),'storage')
        for change in [{'requests':True},{'requests':65},{'phase':'secret'},
                       {'http_status':999},{'raw':'secret'},{'code':'secret'}]:
            self.assertEqual(safe_failure_line(PREFIX+json.dumps({**valid,**change})),
                             PREFIX+'{"code":"unclassified"}')
        self.assertEqual(safe_failure_line(PREFIX+'invalid'),PREFIX+'{"code":"unclassified"}')
