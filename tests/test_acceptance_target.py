from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from fx_system.acceptance_target import offline_environment, verify_identity, verify_remote


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


class AcceptanceTargetTest(unittest.TestCase):
    def test_ref_and_remote_allowlist(self):
        with TemporaryDirectory() as temp, patch.dict("os.environ", {
            "FX_OFFLINE_ACCEPTANCE": "1", "GIT_ALLOW_PROTOCOL": "file"
        }):
            directory = Path(temp)
            target = directory / "ny17-acceptance-remote.git"
            target.mkdir()
            git(target, "init", "--bare")
            root = directory / "state"
            root.mkdir()
            git(root, "init")
            git(root, "remote", "add", "origin", target.as_uri())
            verify_remote(root, git)
            self.assertFalse(verify_identity("nyancoworks/fx-monitor", "refs/heads/main"))
            self.assertTrue(verify_identity("nyancoworks/fx-monitor-data", "refs/heads/ny17-validation"))
            git(root, "remote", "set-url", "--push", "origin", "https://github.com/example/data.git")
            with self.assertRaisesRegex(ValueError, "outside"):
                verify_remote(root, git)

    def test_tokens_and_config_injections_removed(self):
        self.assertEqual(offline_environment({"FX_DATA_REPO_TOKEN": "unused",
                                              "TWELVE_DATA_API_KEY": "unused",
                                              "GIT_CONFIG_COUNT": "1",
                                              "GIT_ALLOW_PROTOCOL": "file"}),
                         {"GIT_ALLOW_PROTOCOL": "file"})
