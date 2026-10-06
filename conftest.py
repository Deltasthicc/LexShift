"""Repository-wide pytest hook.

pytest empties `--basetemp` (set in pytest.ini) before every run. On Windows an editor, a file watcher or an antivirus scan can keep
the previous folder open, removal then fails with `PermissionError`, and every test errors before it starts. Use a fresh folder for
that run instead of failing.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest


@pytest.hookimpl(tryfirst=True)
def pytest_configure(config):
    base = getattr(config.option, "basetemp", None)
    if not base:
        return
    path = Path(str(base)).resolve()
    for stale in path.parent.glob(f"{path.name}-*"):  # folders an earlier fallback left behind
        shutil.rmtree(stale, ignore_errors=True)
    if not path.exists():
        return
    try:
        shutil.rmtree(path)
    except OSError:
        config.option.basetemp = str(path.with_name(f"{path.name}-{os.getpid()}"))
