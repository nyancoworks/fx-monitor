"""Explicit private data location; default preserves the legacy checkout layout."""
import os
from pathlib import Path


def storage_root(default):
    value = os.environ.get('FX_DATA_ROOT')
    if value is None:
        return Path(default)
    path = Path(value)
    if not value or not path.is_absolute() or path.is_symlink():
        raise ValueError('FX_DATA_ROOT requires an absolute non-symlink directory')
    return path.resolve()
