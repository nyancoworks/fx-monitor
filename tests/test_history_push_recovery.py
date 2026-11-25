import unittest
from unittest.mock import patch

from diagnostics import monitoring_result_git_store as store


class HistoryPushRecoveryTests(unittest.TestCase):
    def test_retry_uses_same_commit_when_parent_has_not_changed(self):
        error = store.HistoryGitError('git_rejected', 'push')
        with patch.object(store, '_git', side_effect=[error, '']) as git:
            with patch.object(store, '_remote_head', return_value='parent'):
                store._push_history('repo', 'candidate', 'parent')
        self.assertEqual(git.call_count, 2)
        self.assertEqual(git.call_args_list[0], git.call_args_list[1])

    def test_remote_already_has_candidate_after_timeout(self):
        error = store.HistoryGitError('git_timeout', 'push')
        with patch.object(store, '_git', side_effect=error) as git:
            with patch.object(store, '_remote_head', return_value='candidate'):
                store._push_history('repo', 'candidate', 'parent')
        git.assert_called_once()

    def test_changed_remote_is_never_overwritten(self):
        error = store.HistoryGitError('git_rejected', 'push')
        with patch.object(store, '_git', side_effect=error) as git:
            with patch.object(store, '_remote_head', return_value='other-writer'):
                with self.assertRaises(store.HistoryGitError):
                    store._push_history('repo', 'candidate', 'parent')
        git.assert_called_once()
