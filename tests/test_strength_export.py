"""Synthetic saved strength and local Git only; never market API calls."""
from copy import deepcopy
import contextlib
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from fx_system.strength import compute_strength
from fx_system.monitor_pairs import PAIR_KEYS
from fx_system.strength_export import build_strength_export, validate_strength_export
from fx_system.private_runtime import save_snapshot
from fx_system.strategy_report import report_records


CLOCK = 1800000000
SOURCE = {'source_repository':'nyancoworks/fx-monitor', 'source_commit':'a'*40,
          'run_id':123, 'evaluated_at':CLOCK}


def sample(missing=()):
    pairs = {}
    for pair in PAIR_KEYS:
        if pair in missing: continue
        bars = [{'timestamp':CLOCK-(25-i)*3600, 'open':100, 'high':101, 'low':99, 'close':100}
                for i in range(25)]
        pairs[pair] = {'decision_data': {'raw': {'h1':bars},
            'provenance': {'h1:'+str(b['timestamp']):'Twelve Data' for b in bars}}}
    return {'generated_at':2, 'evaluated_at':CLOCK,
            'currency_strength':compute_strength({'pairs':pairs}, now=CLOCK)}


class StrengthExportTests(unittest.TestCase):
    def test_exact_saved_payload_and_snapshot_blob_identity_without_recalculation(self):
        snapshot = sample(); raw = json.dumps(snapshot).encode(); before = deepcopy(snapshot)
        with patch('fx_system.strength.compute_strength', side_effect=AssertionError('no recalculation')):
            bundle = build_strength_export(raw, SOURCE)
        self.assertEqual(bundle['currency_strength'], snapshot['currency_strength'])
        self.assertEqual(bundle['status'], 'saved')
        self.assertEqual(bundle['currency_strength']['status'], 'complete')
        self.assertEqual(bundle['snapshot_git_blob_sha'], hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest())
        self.assertEqual(validate_strength_export(bundle,SOURCE,bundle['snapshot_git_blob_sha']), [])
        self.assertEqual(snapshot,before)
        self.assertLess(len(json.dumps(bundle)), 20000)

    def test_provisional_and_disconnected_states_are_not_fabricated(self):
        for missing, expected in ((('CADJPY',),'provisional'),
                                 (tuple(p for p in PAIR_KEYS if 'CHF' in p),'unavailable')):
            bundle = build_strength_export(json.dumps(sample(missing)).encode(), SOURCE)
            self.assertEqual(bundle['status'],'saved')
            self.assertEqual(bundle['currency_strength']['status'],expected)
            self.assertEqual(validate_strength_export(bundle,SOURCE,bundle['snapshot_git_blob_sha']), [])

    def test_missing_strength_marks_projection_unavailable_without_old_fallback(self):
        snapshot = {'generated_at':2,'evaluated_at':CLOCK}
        bundle = build_strength_export(json.dumps(snapshot).encode(), SOURCE)
        self.assertEqual(bundle['status'],'unavailable')
        self.assertIsNone(bundle['currency_strength'])
        self.assertTrue(validate_strength_export(bundle,SOURCE,bundle['snapshot_git_blob_sha']))

    def test_corrupt_stale_or_future_strength_is_not_exported_as_saved(self):
        for change in ({'evaluated_at':CLOCK-3600}, {'end_closed_at':CLOCK+3600},
                       {'algorithm':'legacy'}, {'coverage_pairs':True},
                       {'ranking':['USD']*8}, {'scores':{'USD':float('nan')}}):
            snapshot = sample(); snapshot['currency_strength'].update(change)
            bundle = build_strength_export(json.dumps(snapshot).encode(), SOURCE)
            self.assertEqual(bundle['status'],'unavailable')
            self.assertIsNone(bundle['currency_strength'])

    def test_source_and_snapshot_must_match_same_saved_generation(self):
        bundle = build_strength_export(json.dumps(sample()).encode(), SOURCE)
        self.assertTrue(validate_strength_export(bundle,{**SOURCE,'run_id':124},bundle['snapshot_git_blob_sha']))
        self.assertTrue(validate_strength_export(bundle,SOURCE,'b'*40))
        with self.assertRaises(ValueError):
            build_strength_export(json.dumps(sample()).encode(),{**SOURCE,'evaluated_at':CLOCK-1})

    def test_snapshot_and_compact_strength_are_in_one_private_git_commit(self):
        with tempfile.TemporaryDirectory() as folder:
            remote=Path(folder)/'remote.git'; root=Path(folder)/'checkout'
            def git(*args):
                return subprocess.run(['git','-C',str(root),*args],check=True,capture_output=True,text=True).stdout.strip()
            subprocess.run(['git','init','--bare',str(remote)],check=True,capture_output=True)
            root.mkdir(); git('init','-b','main'); git('remote','add','origin',str(remote))
            (root/'data').mkdir(); (root/'data/latest.json').write_text('{"generated_at":1}')
            git('add','.'); git('-c','user.name=synthetic','-c','user.email=synthetic@localhost','commit','-m','initial')
            git('push','origin','HEAD:main'); original=git('rev-parse','HEAD')
            snapshot=sample(); raw=json.dumps(snapshot).encode()
            (root/'data/latest.json').write_bytes(raw); (root/'data/cache.json').write_text('{}')
            public=io.StringIO()
            with contextlib.redirect_stdout(public),contextlib.redirect_stderr(public):
                save_snapshot(root,'123','a'*40)
            self.assertEqual(public.getvalue(),'')
            self.assertEqual(git('rev-list','--count',original+'..HEAD'),'1')
            self.assertEqual((root/'data/latest.json').read_bytes(),raw)
            bundle=json.loads(git('show','HEAD:data/currency-strength.json'))
            source=json.loads(git('show','HEAD:data/source.json'))
            sha=git('rev-parse','HEAD:data/latest.json')
            self.assertEqual(validate_strength_export(bundle,source,sha),[])
            remote_bundle=subprocess.run(['git','--git-dir',str(remote),'show','main:data/currency-strength.json'],
                                         check=True,capture_output=True,text=True).stdout
            self.assertEqual(json.loads(remote_bundle),bundle)

    def test_projection_symlink_cannot_write_outside_private_checkout(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/'checkout'; (root/'data').mkdir(parents=True)
            outside=Path(folder)/'untouched'; outside.write_text('original')
            (root/'data/currency-strength.json').symlink_to(outside)
            (root/'data/latest.json').write_text(json.dumps(sample()))
            with patch('fx_system.private_runtime.git',return_value='{"generated_at":1}'):
                with self.assertRaises(ValueError):save_snapshot(root,'123','a'*40)
            self.assertEqual(outside.read_text(),'original')


class PerStrategyReportTests(unittest.TestCase):
    def test_three_each_and_no_candidate_or_grade_changes(self):
        rows=[{'pair':str(i),'strategy':s,'assessment':'review','grade':'B'}
              for s in ('swing','daytrade') for i in range(5)]
        outlook={'strategy_assessments':rows}; before=deepcopy(outlook)
        result=report_records(outlook)
        self.assertEqual(len(result),6)
        self.assertEqual([r['strategy'] for r in result],['swing']*3+['daytrade']*3)
        self.assertEqual(outlook,before)

    def test_fewer_candidates_are_not_filled_from_skip_or_other_strategy(self):
        rows=[{'pair':str(i),'strategy':'swing','assessment':'review','grade':'B'} for i in range(5)]
        rows += [{'pair':'day','strategy':'daytrade','assessment':'review','grade':'C'},
                 {'pair':'skip','strategy':'daytrade','assessment':'skip','grade':None}]
        result=report_records({'strategy_assessments':rows})
        self.assertEqual(len(result),4)
        self.assertEqual(sum(r['strategy']=='daytrade' for r in result),1)


if __name__=='__main__':unittest.main()
