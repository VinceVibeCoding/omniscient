"""Platform markers shared by the tests (Windows runs the same suite in CI)."""

from __future__ import annotations

import sys

import pytest

WINDOWS = sys.platform == "win32"

posix_only_modes = pytest.mark.skipif(
    WINDOWS,
    reason="Unix mode bits (0600/0700) do not exist on Windows: the same promise is "
    "kept by an icacls ACL, covered in tests/test_group_windows.py",
)
posix_only_symlinks = pytest.mark.skipif(
    WINDOWS,
    reason="creating a symlink needs a privilege a Windows user does not have by default",
)
