"""Publish immutable NY17 objects and one generation pointer in a Git commit."""
import json
import os
from pathlib import Path
import subprocess
import tempfile

from .events import canonical
from .partition_store import PartitionStore


class GitGeneration:
    def __init__(self, repository, branch="ny17-validation-store", remote="origin"):
        if not branch.startswith("ny17-validation-"):
            raise ValueError("isolated validation branch required")
        self.repository = repository
        self.ref = "refs/heads/" + branch
        self.remote = remote

    def git(self, *args, data=None, index=None):
        env = os.environ.copy()
        if index is not None:
            env["GIT_INDEX_FILE"] = str(index)
        result = subprocess.run(["git", "-C", str(self.repository), *args], input=data,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
        if result.returncode:
            raise RuntimeError("Git operation failed: " + args[0])
        return result.stdout

    def remote_head(self):
        return self.git("ls-remote", "--refs", self.remote, self.ref).decode().split("\t")[0].strip() or None

    def fetch(self):
        head = self.remote_head()
        if head is not None:
            # The current tree contains the retained roots and their objects.
            # A fresh runner does not need historical commit trees to restore.
            self.git("fetch", "--no-tags", "--depth=1", self.remote, head)
        return head

    def publish(self, store, expected):
        head = self.fetch()
        roots = store.roots()
        if not roots:
            raise ValueError("no committed generation")
        receipt = canonical({"schema": 1, "roots": roots, "partitions": store.db.execute(
            "SELECT id,used FROM partitions ORDER BY id").fetchall()})
        known = {}
        if head:
            old_receipt = self.git("show", head + ":generation.json")
            known = self.inventory(head)
            if old_receipt == receipt:
                return head
            old_generation = json.loads(old_receipt)["roots"][0][0]
            if roots[0][0] <= old_generation or not any(
                    tuple(item) == tuple(json.loads(old_receipt)["roots"][0]) for item in roots[1:]):
                raise ValueError("generation does not extend remote lineage")
        if head != expected:
            raise ValueError("stale Git parent")
        with tempfile.TemporaryDirectory() as temp:
            index = Path(temp) / "git-index"
            self.git("read-tree", head if head else "--empty", index=index)
            for key, partition in store.db.execute("SELECT key,partition FROM objects ORDER BY key"):
                path = f"partitions/{partition}/{key}"
                if key in known:
                    if known[key] != path:
                        raise ValueError("published object relocated")
                    continue
                payload = store.root / str(partition) / key
                store.read(payload, key)
                blob = self.git("hash-object", "-w", str(payload.resolve())).decode().strip()
                self.git("update-index", "--add", "--cacheinfo", f"100644,{blob},{path}", index=index)
            blob = self.git("hash-object", "-w", "--stdin", data=receipt).decode().strip()
            self.git("update-index", "--add", "--cacheinfo", f"100644,{blob},generation.json", index=index)
            tree = self.git("write-tree", index=index).decode().strip()
            parents = ("-p", head) if head else ()
            commit = self.git("commit-tree", tree, *parents, "-m", "Publish isolated NY17 generation").decode().strip()
            # No force. A competing sibling commit is rejected by the remote.
            try:
                self.git("push", self.remote, f"{commit}:{self.ref}")
            except RuntimeError:
                if self.remote_head() != commit:
                    raise
            return commit

    def inventory(self, commit):
        paths = self.git("ls-tree", "-r", "--name-only", "-z", commit, "--", "partitions")
        return {path.rsplit("/", 1)[-1]: path for path in paths.decode().split("\0") if path}


class GitReader:
    def __init__(self, transport, commit):
        self.transport, self.commit = transport, commit
        self.locations = transport.inventory(commit)
        self.receipt = json.loads(transport.git("show", commit + ":generation.json"))

    def get(self, key):
        if key not in self.locations:
            raise ValueError("missing Git object")
        data = self.transport.git("show", self.commit + ":" + self.locations[key])
        with tempfile.NamedTemporaryFile() as scratch:
            scratch.write(data)
            scratch.flush()
            return PartitionStore.read(Path(scratch.name), key)
