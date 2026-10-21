"""Already-saved input binding with temporary local Git, no network."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from fx_system.backtest_cache_input import PAIRS
from fx_system.backtest_persistence import saved_input
from fx_system.private_runtime import save_snapshot, command


class SavedInputTests(unittest.TestCase):
    def test_push_receipt_binds_input_and_wrong_run_or_local_changes_fail(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/'checkout';root.mkdir();remote=Path(folder)/'remote.git'
            def git(*args):
                return subprocess.run(['git','-C',str(root),*args],capture_output=True,check=True,text=True).stdout.strip()
            subprocess.run(['git','init','--bare',str(remote)],capture_output=True,check=True)
            git('init','-b','main');git('remote','add','origin',str(remote));(root/'data').mkdir()
            (root/'data/latest.json').write_text('{"generated_at":1}')
            git('add','.');git('-c','user.name=synthetic','-c','user.email=test@localhost','commit','-m','initial')
            git('push','origin','HEAD:main')
            bar={'timestamp':300,'open':100,'high':102,'low':99,'close':101}
            cache={p:{'m5':[bar],'h1':[],'bar_provenance':{'m5:300':'Twelve Data'}} for p in PAIRS}
            (root/'data/cache.json').write_text(json.dumps(cache))
            (root/'data/latest.json').write_text(json.dumps({'generated_at':2,'evaluated_at':600,
                'ny17_transport':{'restore_ok':True,'save_ok':True}}))
            save_snapshot(root,'123','a'*40)
            batches,quality,source=saved_input(root,'123','a'*40)
            self.assertEqual(quality['intraday']['accepted_rows'],16);self.assertEqual(len(batches),16)
            self.assertEqual(source['data_commit'],git('rev-parse','HEAD'))
            with self.assertRaises(ValueError):saved_input(root,'124','a'*40)
            with self.assertRaises(ValueError):saved_input(root,'123','b'*40)
            receipt=root/'.private-run/123/snapshot.receipt.json';receipt.unlink()
            with self.assertRaises(FileNotFoundError):saved_input(root,'123','a'*40)
            (root/'data/cache.json').write_text('{}')
            with self.assertRaises(ValueError):saved_input(root,'123','a'*40)
            self.assertIn('fx_system.backtest_persistence',command('backtest',root,'123','a'*40))


if __name__=='__main__':unittest.main()
