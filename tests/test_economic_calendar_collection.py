"""Production path tests with fake transport and local Git only."""
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from test_economic_calendar_health import health, reference_payload, CLOCK
from fx_system.economic_calendar_collection import (ALLOWED_CONFIG, BASE_URL, CONFIG_PATH,
    COLLECTION_PATH, collection_enabled, prepare_calendar, _get)
from fx_system.private_runtime import prepare_optional_calendar
from fx_system.saved_economic_calendar import RELATIVE_PATH, load_saved_calendar, build_outlook_with_saved_calendar
from fx_system.scheduled_outlook import build_scheduled_outlook
from fx_system.validate_strategy_snapshot import validate_strategy_snapshot
from diagnostics.monitoring_result_history import pack_generation, restore_generation


class CollectionTests(unittest.TestCase):
    def config(self, root, value=None):
        path=Path(root)/CONFIG_PATH; path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(ALLOWED_CONFIG if value is None else value))

    def fake_get(self, calls, *, status_failure=False, calendar_failure=False):
        def fetch(url, *, clock):
            calls.append(url)
            if url==BASE_URL+'status':
                if status_failure: raise TimeoutError('SYNTHETIC_PRIVATE_DETAIL')
                return 200,json.dumps(health()).encode(),CLOCK
            if calendar_failure: return 503,b'SYNTHETIC_PRIVATE_RESPONSE',CLOCK
            return 200,json.dumps(reference_payload()).encode(),CLOCK
        return fetch

    def test_no_configuration_or_nonexplicit_flag_means_no_fetch_or_writes(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            for value in (None, {**ALLOWED_CONFIG,'enabled':False}, {**ALLOWED_CONFIG,'enabled':1},
                          {**ALLOWED_CONFIG,'max_requests_per_run':2.0}):
                if value is not None:self.config(root,value)
                self.assertFalse(collection_enabled(root))
                self.assertEqual(prepare_calendar(root,run_id='123',get=lambda *a,**k:self.fail('network')),
                                 {'status':'disabled','requests':0})
                self.assertFalse((root/COLLECTION_PATH).exists())

    def test_malformed_deep_config_or_switch_failure_cannot_stop_refresh(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); self.config(root)
            (root/CONFIG_PATH).write_text('['*1100+'0'+']'*1100)
            self.assertFalse(collection_enabled(root))
            env={'FX_DATA_ROOT':str(root)}
            self.assertEqual(prepare_optional_calendar(root,'123',env),env)
            with patch('fx_system.economic_calendar_collection.collection_enabled',side_effect=RuntimeError('PRIVATE')):
                self.assertEqual(prepare_optional_calendar(root,'123',env),env)

    def test_two_calls_originals_envelope_and_same_run_no_retry(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); self.config(root); calls=[]; commits=[]
            out=io.StringIO()
            with contextlib.redirect_stdout(out),contextlib.redirect_stderr(out):
                result=prepare_calendar(root,run_id='123',clock=lambda:CLOCK,
                    get=self.fake_get(calls),persist=lambda r,f:commits.append(list(f)))
            self.assertEqual(out.getvalue(),'')
            self.assertEqual(result,{'status':'saved','requests':2})
            self.assertEqual(len(calls),2)
            self.assertIn('limit=500',calls[1]); self.assertIn('offset=0',calls[1])
            raw=root/'data/economic-calendar/originals/123/calendar.response'
            self.assertEqual(raw.read_bytes(),json.dumps(reference_payload()).encode())
            self.assertEqual(raw.stat().st_mode&0o777,0o600)
            self.assertEqual(len(commits),1)
            self.assertTrue(all(p.is_relative_to(root) for p in commits[0]))
            saved=load_saved_calendar(root,evaluated_at=CLOCK)
            self.assertEqual(saved['events'][0]['source_health']['status'],'degraded')
            again=prepare_calendar(root,run_id='123',clock=lambda:CLOCK,get=self.fake_get(calls),persist=lambda *a:None)
            self.assertEqual(again['requests'],0); self.assertEqual(len(calls),2)

    def test_status_failure_still_saves_calendar_with_unverified_source(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); self.config(root); calls=[]
            result=prepare_calendar(root,run_id='123',clock=lambda:CLOCK,
                get=self.fake_get(calls,status_failure=True),persist=lambda *a:None)
            self.assertEqual(result['status'],'saved'); self.assertEqual(len(calls),2)
            self.assertEqual(load_saved_calendar(root,evaluated_at=CLOCK)['events'][0]['source_health']['status'],'unverified')
            receipt=(root/'data/economic-calendar/originals/123/manifest.json').read_text()
            self.assertNotIn('SYNTHETIC_PRIVATE_DETAIL',receipt)

    def test_malformed_success_payload_preserves_body_without_poisoning_reference(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); self.config(root); calls=[]
            def get(url,*,clock):
                calls.append(url)
                return 200,b'{"events":[],"invalid":NaN}',CLOCK
            result=prepare_calendar(root,run_id='123',clock=lambda:CLOCK,get=get,persist=lambda *a:None)
            self.assertEqual(result['status'],'unavailable'); self.assertEqual(len(calls),2)
            self.assertFalse((root/RELATIVE_PATH).exists())
            self.assertEqual((root/'data/economic-calendar/originals/123/calendar.response').read_bytes(),
                             b'{"events":[],"invalid":NaN}')

    def test_calendar_failure_preserves_previous_reference_and_captures_received_error_body(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); self.config(root); calls=[]
            prepare_calendar(root,run_id='123',clock=lambda:CLOCK,get=self.fake_get(calls),persist=lambda *a:None)
            original=(root/RELATIVE_PATH).read_bytes()
            result=prepare_calendar(root,run_id='124',clock=lambda:CLOCK,
                get=self.fake_get(calls,calendar_failure=True),persist=lambda *a:None)
            self.assertEqual(result['status'],'unavailable')
            self.assertEqual((root/RELATIVE_PATH).read_bytes(),original)
            self.assertEqual((root/'data/economic-calendar/originals/124/calendar.response').read_bytes(),b'SYNTHETIC_PRIVATE_RESPONSE')
            self.assertNotIn('SYNTHETIC_PRIVATE_RESPONSE',(root/COLLECTION_PATH).read_text())

    def test_runtime_optin_and_provider_failure_do_not_change_core_32(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);self.config(root);calls=[]
            with patch('fx_system.economic_calendar_collection._get',self.fake_get(calls)), \
                 patch('fx_system.economic_calendar_collection._persist'), \
                 patch('fx_system.economic_calendar_collection.time.time',return_value=CLOCK):
                # Clock injection for this helper is tested on prepare_calendar;
                # here run acquisition with a stable synthetic wrapper.
                from fx_system import economic_calendar_collection as collection
                def prepare(r,*,run_id):
                    return prepare_calendar(r,run_id=run_id,clock=lambda:CLOCK,get=self.fake_get(calls),persist=lambda *a:None)
                with patch.object(collection,'prepare_calendar',side_effect=prepare):
                    env=prepare_optional_calendar(root,'123',{'FX_DATA_ROOT':str(root)})
            self.assertEqual(env['FX_ECONOMIC_CALENDAR_SAVED_ENABLED'],'true')
            self.assertEqual(len(calls),2)
            with patch.dict(os.environ,env,clear=True):
                outlook=build_outlook_with_saved_calendar({}, {}, evaluated_at=CLOCK)
            self.assertEqual(validate_strategy_snapshot({'evaluated_at':CLOCK,'scheduled_outlook':outlook}),[])
            self.assertEqual(restore_generation(pack_generation(outlook['rows'],evaluated_at=CLOCK))['rows'],outlook['rows'])
            old=build_scheduled_outlook({}, {}, evaluated_at=CLOCK)
            for a,b in zip(old['strategy_assessments'],outlook['strategy_assessments']):
                b=dict(b); context=b.pop('economic_calendar_context');self.assertEqual(a,b)
                self.assertEqual(context['collection_status'],'saved')
            with patch('fx_system.economic_calendar_collection.prepare_calendar',side_effect=OSError('PRIVATE')):
                env=prepare_optional_calendar(root,'124',{'FX_DATA_ROOT':str(root)})
            self.assertEqual(env['FX_ECONOMIC_CALENDAR_COLLECTION_STATUS'],'unavailable')
            with patch.dict(os.environ,env,clear=True):
                failed=build_outlook_with_saved_calendar({}, {}, evaluated_at=CLOCK+10)
            self.assertEqual(failed['strategy_assessments'][0]['economic_calendar_context']['acquisition_age_seconds'],10)

    def test_real_refresh_entry_continues_after_optional_collection_exception(self):
        from fx_system import private_runtime as runtime
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            env={'GITHUB_RUN_ID':'123','GITHUB_SHA':'a'*40,
                 'GITHUB_REPOSITORY':runtime.CODE_REPOSITORY,'GITHUB_REF':'refs/heads/main'}
            def refresh(command,*,env,**kwargs):
                self.assertEqual(env['FX_ECONOMIC_CALENDAR_COLLECTION_STATUS'],'unavailable')
                self.assertEqual(env['FX_ECONOMIC_CALENDAR_SAVED_ENABLED'],'true')
                return 0
            output=io.StringIO()
            with patch.dict(os.environ,env,clear=True), patch.object(sys,'argv',['runner','refresh','--state',str(root)]), \
                 patch.object(runtime,'private_root',return_value=root), patch.object(runtime,'verify_ready'), \
                 patch('fx_system.economic_calendar_collection.collection_enabled',return_value=True), \
                 patch('fx_system.economic_calendar_collection.prepare_calendar',side_effect=OSError('SYNTHETIC_PRIVATE_ERROR')), \
                 patch.object(runtime,'run_private',side_effect=refresh), contextlib.redirect_stdout(output):
                self.assertEqual(runtime.main(),0)
            self.assertEqual(output.getvalue(),'FX_STAGE refresh success\n')

    def test_public_root_symlinks_and_invalid_run_cannot_fetch(self):
        from fx_system.saved_economic_calendar import CODE_ROOT
        self.assertFalse(collection_enabled(CODE_ROOT))
        with tempfile.TemporaryDirectory() as folder, tempfile.TemporaryDirectory() as outside:
            root=Path(folder);self.config(root)
            with self.assertRaises(ValueError):
                prepare_calendar(root,run_id='../escape',get=lambda *a,**k:self.fail('network'))
            (root/'data').symlink_to(outside,target_is_directory=True)
            with self.assertRaises(ValueError):
                prepare_calendar(root,run_id='123',get=lambda *a,**k:self.fail('network'))

    def test_transport_blocks_redirects_and_enforces_response_limit(self):
        class Response:
            code=302
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read1(self,size):
                if hasattr(self,'done'):return b''
                self.done=True;return b'{}'
        class Opener:
            def open(self,request,timeout):
                self.request=request;self.timeout=timeout;return Response()
        opener=Opener()
        with patch('urllib.request.build_opener',return_value=opener) as build:
            code,body,stamp=_get(BASE_URL+'status',clock=lambda:CLOCK)
        self.assertEqual(code,302);self.assertEqual(body,b'{}')
        self.assertIsNone(build.call_args.args[0].redirect_request(None,None,None,None,None,None))
        with patch('urllib.request.build_opener',return_value=Opener()), \
             patch('fx_system.economic_calendar_collection.MAX_BYTES',1):
            with self.assertRaises(ValueError):_get(BASE_URL+'status',clock=lambda:CLOCK)

    def test_real_local_git_persistence_keeps_originals_separate_from_snapshot(self):
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder);root=base/'checkout';remote=base/'remote.git'
            subprocess.run(['git','init','--bare',str(remote)],capture_output=True,check=True)
            subprocess.run(['git','init','-b','main',str(root)],capture_output=True,check=True)
            def git(*args):
                return subprocess.run(['git','-C',str(root),*args],capture_output=True,check=True,text=True).stdout.strip()
            git('remote','add','origin',str(remote));self.config(root)
            (root/'data').mkdir();(root/'data/latest.json').write_text('{"generated_at":1}')
            git('add','.');git('-c','user.name=synthetic','-c','user.email=synthetic@localhost','commit','-m','initial')
            git('push','origin','HEAD:main');old=git('rev-parse','HEAD')
            with patch('fx_system.private_runtime.verify_ready'):
                prepare_calendar(root,run_id='123',clock=lambda:CLOCK,get=self.fake_get([]))
            self.assertEqual(git('rev-list','--count',old+'..HEAD'),'1')
            self.assertEqual(git('show','HEAD:data/latest.json'),'{"generated_at":1}')
            self.assertEqual(git('status','--porcelain'),'')
            names=git('diff','--name-only',old,'HEAD').splitlines()
            self.assertTrue(all(n.startswith('data/economic-calendar/') for n in names))
            saved=subprocess.run(['git','--git-dir',str(remote),'show','main:data/economic-calendar/reference.json'],capture_output=True,check=True)
            self.assertEqual(saved.stdout,(root/RELATIVE_PATH).read_bytes())
            # The existing snapshot writer must accept the later collection
            # commit and preserve its original receipts when saving FX data.
            from fx_system.private_runtime import save_snapshot
            with patch.dict(os.environ,{'FX_DATA_ROOT':str(root),'FX_ECONOMIC_CALENDAR_SAVED_ENABLED':'true'},clear=True):
                outlook=build_outlook_with_saved_calendar({}, {}, evaluated_at=CLOCK)
            snap={'generated_at':2,'evaluated_at':CLOCK,'scheduled_outlook':outlook}
            (root/'data/latest.json').write_text(json.dumps(snap))
            (root/'data/cache.json').write_text('{}')
            save_snapshot(root,'123','a'*40)
            self.assertEqual(git('rev-list','--count',old+'..HEAD'),'2')
            self.assertEqual(json.loads(git('show','HEAD:data/latest.json')),snap)
            self.assertEqual(json.loads(git('show','HEAD:data/economic-calendar/reference.json')),
                             json.loads(saved.stdout))
