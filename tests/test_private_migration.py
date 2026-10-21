import contextlib
import importlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from fx_system import private_runtime as runtime
from fx_system.storage_paths import storage_root


class PrivateMigrationTests(unittest.TestCase):
    def test_configured_data_location_and_legacy_default(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(storage_root('/legacy'), Path('/legacy'))
        with tempfile.TemporaryDirectory() as folder:
            with patch.dict(os.environ, {'FX_DATA_ROOT': folder}):
                self.assertEqual(storage_root('/code'), Path(folder).resolve())
            with patch.dict(os.environ, {'FX_DATA_ROOT': 'relative'}):
                with self.assertRaises(ValueError): storage_root('/code')

    def test_public_runtime_refuses_code_checkout_as_private_storage(self):
        with self.assertRaises(ValueError): runtime.private_root(runtime.CODE_ROOT)
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError): runtime.private_root(folder)

    def test_missing_or_partial_migration_cannot_start_collection(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with patch.object(runtime, 'git', return_value='https://github.com/nyancoworks/fx-monitor-data'):
                with self.assertRaises(FileNotFoundError): runtime.verify_ready(root)
                (root/'migration').mkdir()
                (root/'migration/READY.json').write_text(json.dumps({
                    'data_repository': runtime.DATA_REPOSITORY, 'source_bytes_verified': True,
                    'ny17_full_restore_verified': False, 'canonical32_verified': True}))
                with self.assertRaises(ValueError): runtime.verify_ready(root)

    def test_public_repository_cannot_be_the_data_destination(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(runtime, 'git', return_value='https://github.com/nyancoworks/fx-monitor'):
                with self.assertRaises(ValueError): runtime.verify_ready(Path(folder))

    def test_child_failure_output_is_private_and_credentials_redacted(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); log = root/'logs/refresh.log'
            env = {**os.environ, 'TWELVE_DATA_API_KEY': 'test-secret-not-a-real-key'}
            code = "import os,sys; print('SYNTHETIC_PRICE=123.45'); print(os.environ['TWELVE_DATA_API_KEY'],file=sys.stderr); sys.exit(7)"
            public = io.StringIO()
            with contextlib.redirect_stdout(public), contextlib.redirect_stderr(public):
                rc = runtime.run_private([sys.executable, '-c', code], root=root, log=log, env=env)
            self.assertEqual(rc, 7)
            self.assertEqual(public.getvalue(), '')
            self.assertIn('SYNTHETIC_PRICE=123.45', log.read_text())
            self.assertNotIn(env['TWELVE_DATA_API_KEY'], log.read_text())
            self.assertIn('[REDACTED]', log.read_text())
            self.assertEqual(log.stat().st_mode & 0o777, 0o600)

    def test_log_symlink_cannot_write_outside_private_storage(self):
        with tempfile.TemporaryDirectory() as folder, tempfile.TemporaryDirectory() as other:
            target = Path(other)/'untouched'; target.write_text('original')
            log = Path(folder)/'log'; log.symlink_to(target)
            with self.assertRaises(ValueError):
                runtime.run_private([sys.executable, '-c', "print('synthetic')"],
                                    root=Path(folder), log=log, env=dict(os.environ))
            self.assertEqual(target.read_text(), 'original')

    def test_new_source_repository_is_recorded_without_rewriting_old_provenance(self):
        from diagnostics import monitoring_result_git_store as store
        from fx_system.monitor_pairs import PAIR_KEYS
        from diagnostics.monitoring_result_history import restore_generation
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); remote=root/'remote.git'; checkout=root/'checkout'
            subprocess.run(['git','init','--bare',str(remote)],check=True,capture_output=True)
            subprocess.run(['git','init',str(checkout)],check=True,capture_output=True)
            store._git(checkout,'remote','add','origin',str(remote))
            rows=[{'pair':p,'entry_permission':False} for p in PAIR_KEYS]
            store.publish_results(checkout,rows,evaluated_at=1,source_run_id=1,
                                  source_commit='a'*40,allow_create=True)
            store.publish_results(checkout,rows,evaluated_at=2,source_run_id=2,
                                  source_commit='b'*40,source_repository=runtime.CODE_REPOSITORY)
            saved=store.read_remote_history(checkout)
            self.assertEqual(saved['provenance']['1'],{'run_id':1,'source_commit':'a'*40})
            self.assertEqual(saved['provenance']['2']['source_repository'],runtime.CODE_REPOSITORY)
            self.assertEqual(restore_generation(saved['history'][-1])['rows'],rows)

    def test_failure_summary_does_not_expose_exception_text(self):
        env = {'GITHUB_RUN_ID': '123', 'GITHUB_SHA': 'a'*40,
               'GITHUB_REPOSITORY': runtime.CODE_REPOSITORY, 'GITHUB_REF': 'refs/heads/main'}
        out = io.StringIO()
        with patch.dict(os.environ, env), patch.object(sys, 'argv', ['runner', 'refresh', '--state', '/private']), \
             patch.object(runtime, 'private_root', side_effect=ValueError('SYNTHETIC_PRIVATE_DETAIL')), \
             contextlib.redirect_stdout(out):
            self.assertEqual(runtime.main(), 1)
        self.assertNotIn('SYNTHETIC_PRIVATE_DETAIL', out.getvalue())
        self.assertIn('FX_STAGE refresh failed', out.getvalue())

    def test_archive_child_has_explicit_git_identity_on_clean_runner(self):
        # No network or market input: exercise the actual commit-tree command
        # used by the archive writer without relying on host Git configuration.
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            env = {'GITHUB_RUN_ID': '123', 'GITHUB_SHA': 'a'*40,
                   'GITHUB_REPOSITORY': runtime.CODE_REPOSITORY,
                   'GITHUB_REF': 'refs/heads/main',
                   'PATH': os.environ['PATH'], 'GIT_CONFIG_NOSYSTEM': '1',
                   'GIT_CONFIG_GLOBAL': os.devnull}
            subprocess.run(['git', 'init', str(root)], env=env,
                           check=True, capture_output=True)
            tree = subprocess.run(['git', 'mktree'], cwd=root, env=env,
                                  input=b'', capture_output=True, check=True).stdout.decode().strip()
            def commit_child(command, *, env, **kwargs):
                result = subprocess.run(['git', 'commit-tree', tree, '-m', 'synthetic'],
                                        cwd=root, env=env, capture_output=True)
                self.assertEqual(result.returncode, 0, 'archive commit-tree needs explicit identity')
                actor = subprocess.run(['git', 'show', '-s', '--format=%an <%ae>',
                                        result.stdout.decode().strip()], cwd=root, env=env,
                                       capture_output=True, check=True).stdout.decode().strip()
                self.assertEqual(actor, 'github-actions[bot] <41898286+github-actions[bot]@users.noreply.github.com>')
                return 0
            with patch.dict(os.environ, env, clear=True), \
                 patch.object(sys, 'argv', ['runner', 'archive', '--state', str(root)]), \
                 patch.object(runtime, 'private_root', return_value=root), \
                 patch.object(runtime, 'verify_ready'), \
                 patch.object(runtime, 'run_private', side_effect=commit_child), \
                 contextlib.redirect_stdout(io.StringIO()):
                # The archive output parse is mocked separately from Git identity.
                (root/'.private-run/123').mkdir(parents=True)
                (root/'.private-run/123/archive.log').write_text('{"status":"persisted"}')
                self.assertEqual(runtime.main(), 0)


if __name__ == '__main__': unittest.main()
