"""Fresh-runner history transfer preserves remote originals without loading them."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from diagnostics import monitoring_result_git_store as store
from test_history_calendar_capacity import outlook, CLOCK


class FilteredHistoryTests(unittest.TestCase):
    def test_fresh_runner_reads_and_pushes_without_legacy_blob_or_ancestors(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            remote, seed, fresh = (root/name for name in ('remote.git', 'seed', 'fresh'))
            for path, bare in ((remote, True), (seed, False), (fresh, False)):
                subprocess.run(['git', 'init', *(['--bare'] if bare else []), str(path)],
                               check=True, capture_output=True)
            store._git(remote, 'config', 'uploadpack.allowFilter', 'true')
            # file:// uses the transport protocol, unlike Git's local hardlinks.
            for path in (seed, fresh):
                store._git(path, 'remote', 'add', 'origin', remote.as_uri())
            rows = outlook(CLOCK)['rows']
            first = store.publish_results(seed, rows, evaluated_at=CLOCK,
                source_run_id=1, source_commit='a'*40, allow_create=True)
            blob = store._git(seed, 'hash-object', '-w', '--stdin', stdin=os.urandom(1024*1024))
            followup = store._git(seed, 'mktree', stdin=f'100644 blob {blob}\told.bin\n'.encode())
            tree = store._git(seed, 'mktree', stdin=(store._git(seed, 'ls-tree', first['head']) +
                f'\n040000 tree {followup}\tfollowup\n').encode())
            head = store._git(seed, '-c', 'user.name=Synthetic', '-c',
                'user.email=synthetic@example.invalid', 'commit-tree', tree,
                '-p', first['head'], stdin=b'Synthetic retained artifact\n')
            store._git(seed, 'push', 'origin', head+':'+store.REF)
            saved = store.read_remote_history(fresh)
            self.assertEqual(saved['head'], head)
            self.assertEqual(saved['history'], store.read_remote_history(seed)['history'])
            def missing():
                return store._git(fresh, 'rev-list', '--objects', '--all', '--missing=print')
            self.assertIn('?'+blob, missing())
            self.assertEqual(store._git(fresh, 'rev-list', '--count', head), '1')
            result = store.publish_results(fresh, outlook(CLOCK+3600)['rows'],
                evaluated_at=CLOCK+3600, source_run_id=2, source_commit='b'*40)
            self.assertEqual(result['status'], 'persisted')
            self.assertIn('?'+blob, missing())
            self.assertEqual(store._git(remote, 'rev-parse', result['head']+':followup'), followup)
            self.assertEqual(store._git(remote, 'rev-parse', result['head']+'^'), head)
            self.assertEqual(store._git(remote, 'cat-file', '-s', blob), str(1024*1024))

    def test_timeout_classification_excludes_private_command_and_stderr(self):
        with patch.object(store.subprocess, 'run', side_effect=subprocess.TimeoutExpired(
                ['PRIVATE_URL'], 30, stderr=b'PRIVATE_SECRET')):
            with self.assertRaises(store.HistoryGitError) as raised:
                store._git('unused', 'fetch', 'PRIVATE_URL')
        self.assertEqual((raised.exception.reason, raised.exception.operation), ('git_timeout', 'fetch'))
        self.assertNotIn('PRIVATE', str(raised.exception))


if __name__ == '__main__':
    unittest.main()
