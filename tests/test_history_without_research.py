"""Canonical history still persists, rotates and protects input identity alone."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from diagnostics import monitoring_result_git_store as store
from test_history_calendar_capacity import outlook, CLOCK


class HistoryWithoutResearchTests(unittest.TestCase):
    def test_persist_rotate_preserve_old_artifact_and_reject_changed_input(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); remote=root/'remote.git';repo=root/'repo'
            subprocess.run(['git','init','--bare',str(remote)],check=True,capture_output=True)
            subprocess.run(['git','init',str(repo)],check=True,capture_output=True)
            subprocess.run(['git','-C',str(repo),'remote','add','origin',str(remote)],check=True,capture_output=True)
            def publish(clock, identity):
                rows=outlook(clock)['rows']
                return store.publish_results(repo,rows,evaluated_at=clock,source_run_id=123,
                    source_commit='a'*40,allow_create=True,
                    snapshot={'evaluated_at':clock,'scheduled_outlook':{'rows':rows}},
                    input_identity=identity)
            identity={'sha256':'b'*64,'git_blob_sha':'c'*40}
            first=publish(CLOCK,identity)
            def git(*args, stdin=None):
                return store._git(repo,*args,stdin=stdin)
            self.assertEqual(git('ls-tree','--name-only',first['head']).splitlines(),['history.json','provenance.json'])
            # Preserve an existing legacy followup object, without producing new ones.
            blob=git('hash-object','-w','--stdin',stdin=b'{"legacy":true}')
            tree=git('mktree',stdin=('100644 blob '+blob+'\told.json\n').encode())
            root_tree=git('mktree',stdin=(git('ls-tree',first['head'])+'\n040000 tree '+tree+'\tfollowup\n').encode())
            head=git('-c','user.name=Synthetic','-c','user.email=synthetic@example.invalid',
                     'commit-tree',root_tree,'-p',first['head'],stdin=b'Synthetic old artifact\n')
            git('push','origin',head+':'+store.REF)
            self.assertEqual(publish(CLOCK,identity)['status'],'unchanged')
            with self.assertRaises(ValueError):publish(CLOCK,{**identity,'git_blob_sha':'d'*40})
            for n in range(1,5):result=publish(CLOCK+n*3600,identity)
            self.assertEqual(git('ls-tree','-r','--name-only',result['head']).splitlines(),
                             ['followup/old.json','history.json','provenance.json'])
            self.assertEqual(git('show',result['head']+':followup/old.json'),'{"legacy":true}')
            history=json.loads(git('show',result['head']+':history.json'))
            self.assertEqual([g['evaluated_at'] for g in history],[CLOCK+n*3600 for n in (2,3,4)])
            provenance=json.loads(git('show',result['head']+':provenance.json'))
            self.assertEqual(provenance[str(CLOCK+14400)]['snapshot_identity'],identity)

    def test_mismatched_snapshot_rejected_before_remote_access(self):
        with patch.object(store,'read_remote_history') as read:
            with self.assertRaises(ValueError):
                store.publish_results('unused',[],evaluated_at=CLOCK,source_run_id=123,
                    source_commit='a'*40,snapshot={'evaluated_at':CLOCK-1})
            read.assert_not_called()


if __name__=='__main__':unittest.main()
