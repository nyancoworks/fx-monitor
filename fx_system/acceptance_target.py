"""Fail-closed routing for offline collection acceptance."""
import os
from pathlib import Path
from urllib.parse import unquote, urlsplit


def enabled():
    return os.environ.get("FX_OFFLINE_ACCEPTANCE") == "1"


def verify_identity(repository, ref):
    if enabled():
        return (repository, ref) in {
            ("nyancoworks/fx-monitor", "refs/heads/ny17-storage-migration"),
            ("nyancoworks/fx-monitor-data", "refs/heads/ny17-validation"),
        }
    return (repository, ref) == ("nyancoworks/fx-monitor", "refs/heads/main")


def verify_remote(root, git):
    if os.environ.get("GIT_ALLOW_PROTOCOL") != "file":
        raise ValueError("offline acceptance requires Git file-only policy")
    expected = root.parent / "ny17-acceptance-remote.git"
    if expected.is_symlink() or not expected.is_dir() or not (expected / "objects").is_dir():
        raise ValueError("offline acceptance requires a sibling bare repository")
    for args in (("remote", "get-url", "--all", "origin"),
                 ("remote", "get-url", "--push", "--all", "origin")):
        configured = git(root, *args).splitlines()
        if len(configured) != 1:
            raise ValueError("offline acceptance requires exactly one Git endpoint")
        url = urlsplit(configured[0])
        if (url.scheme != "file" or url.netloc or url.query or url.fragment
                or Path(unquote(url.path)) != expected
                or Path(unquote(url.path)).resolve() != expected):
            raise ValueError("offline acceptance Git endpoint is outside the sandbox")


def offline_environment(env):
    # No provider key, release token, or explicit Git config override can leak
    # into a fixture process. A local Git remote is checked again by each stage.
    return {k: v for k, v in env.items()
            if not (k.endswith(("_KEY", "_TOKEN")) or k.startswith("GIT_CONFIG_"))}
