from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest

from fx_system.ny17_storage.git_generation import GitGeneration
from fx_system.ny17_storage.partition_store import PartitionStore


def git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], check=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout


class NY17ShallowFetchTest(unittest.TestCase):
    def test_empty_runner_fetches_tip_and_can_publish_successor(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            remote, writer, runner = (root / name for name in ("remote", "writer", "runner"))
            for repo in (remote, writer, runner):
                repo.mkdir()
                git(repo, "init", "--bare" if repo == remote else "-q")
            for repo in (writer, runner):
                git(repo, "config", "user.name", "NY17 test")
                git(repo, "config", "user.email", "test@example.invalid")
                git(repo, "remote", "add", "origin", remote.as_uri())
            store = PartitionStore(root / "state")
            transport = GitGeneration(writer)
            head = None
            for generation in (1, 2):
                with store.publish(generation - 1 if generation > 1 else None):
                    store.advance(generation, store.put({"generation": generation}))
                head = transport.publish(store, head)
            empty_runner = GitGeneration(runner)
            self.assertEqual(empty_runner.fetch(), head)
            self.assertEqual(git(runner, "rev-list", "--count", head).strip(), b"1")
            with store.publish(2):
                store.advance(3, store.put({"generation": 3}))
            third = empty_runner.publish(store, head)
            self.assertEqual(empty_runner.remote_head(), third)
            self.assertEqual(git(remote, "rev-list", "--count", third).strip(), b"3")
