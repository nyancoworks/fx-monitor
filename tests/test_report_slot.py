from copy import deepcopy
from datetime import datetime
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from fx_system.report_slot import build_slot,validate_slot,REPOSITORY
from fx_system import private_runtime as runtime

START=int(datetime.fromisoformat('2026-11-04T04:50:30+00:00').timestamp())
TARGET=int(datetime.fromisoformat('2026-11-04T05:00:00+00:00').timestamp())
SOURCE={'run_id':123,'source_commit':'a'*40,'source_repository':REPOSITORY,'evaluated_at':START+90}
def start():
    return {'run_id':123,'source_commit':'a'*40,'repository':REPOSITORY,
            'observed_started_at':START,'run_attempt':1,'event':'workflow_dispatch'}

class ReportSlotTests(unittest.TestCase):
    def test_delayed_save_keeps_original_slot_and_later_generation_cannot_fill_it(self):
        delayed = {**SOURCE, 'evaluated_at': TARGET + 90}
        original = build_slot(start(), delayed, 'b'*40)
        self.assertTrue(validate_slot(original, delayed, 'b'*40, TARGET))
        later = {**delayed, 'run_id':124, 'evaluated_at':TARGET+3690}
        later_start = {**start(), 'run_id':124, 'observed_started_at':START+3600}
        successor = build_slot(later_start, later, 'c'*40)
        self.assertTrue(validate_slot(successor, later, 'c'*40, TARGET+3600))
        with self.assertRaises(ValueError):
            validate_slot(successor, later, 'c'*40, TARGET)
        with self.assertRaises(ValueError):
            validate_slot(original, later, 'c'*40, TARGET)

    def test_explicit14_slot_binds_run_source_and_blob_without_api(self):
        value=build_slot(start(),SOURCE,'b'*40)
        self.assertEqual(value['target_scheduled_for'],TARGET)
        self.assertTrue(validate_slot(value,SOURCE,'b'*40,TARGET))
        for source,blob,target in (({**SOURCE,'run_id':124},'b'*40,TARGET),
                (SOURCE,'c'*40,TARGET),(SOURCE,'b'*40,TARGET+3600)):
            with self.assertRaises(ValueError):validate_slot(value,source,blob,target)

    def test_missing_late_retried_or_conflicting_start_never_guesses_slot(self):
        for field,value in [('observed_started_at',START-3600+600),('observed_started_at',TARGET),
                            ('run_attempt',2),('run_attempt',True),('run_id',124),
                            ('source_commit','c'*40),('repository','other/repo')]:
            entry=start();entry[field]=value
            self.assertEqual(build_slot(entry,SOURCE,'b'*40)['status'],'unavailable')
        self.assertEqual(build_slot(None,SOURCE,'b'*40)['status'],'unavailable')

    def test_clock_rolls_to_next_day_not_a_saved_price_clock(self):
        entry=start();entry['observed_started_at']=int(datetime.fromisoformat('2026-11-04T14:50:30+00:00').timestamp())
        source={**SOURCE,'evaluated_at':entry['observed_started_at']+120}
        receipt=build_slot(entry,source,'b'*40)
        self.assertEqual(receipt['target_scheduled_for'],int(datetime.fromisoformat('2026-11-04T15:00:00+00:00').timestamp()))

    def test_runtime_observes_start_once_and_keeps_marker_private(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            def child(*args,**kwargs):
                kwargs['log'].write_text('{"status":"restored"}')
                return 0
            env={'GITHUB_RUN_ID':'123','GITHUB_SHA':'a'*40,'GITHUB_REPOSITORY':REPOSITORY,
                 'GITHUB_REF':'refs/heads/main','GITHUB_RUN_ATTEMPT':'1','GITHUB_EVENT_NAME':'workflow_dispatch'}
            with patch.dict(os.environ,env),patch.object(runtime,'private_root',return_value=root), \
                 patch.object(runtime,'verify_ready'),patch.object(runtime,'run_private',side_effect=child), \
                 patch('sys.argv',['runtime','restore','--state',folder]), \
                 patch.object(runtime.time,'time',return_value=START),contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(runtime.main(),0)
                marker=root/'.private-run/123/collection-start.json';original=marker.read_bytes()
                self.assertEqual(json.loads(original),start())
                self.assertEqual(marker.stat().st_mode&0o777,0o600)
                self.assertEqual(runtime.main(),0)
                self.assertEqual(marker.read_bytes(),original)

if __name__=='__main__':unittest.main()
