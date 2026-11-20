"""Every test runs against an isolated, throwaway Omniscient home.

Tests must never read or write the developer's real home (.env, registry), and must pass in
a fresh clone that has no home at all (CI, contributors). Tests that need a specific layout
still override OMNISCIENT_HOME or monkeypatch paths themselves.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from omniscient.home import ENV_VAR


@pytest.fixture(autouse=True)
def isolated_home(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> Path:
    root = tmp_path_factory.mktemp("omniscient-home")
    (root / "config").mkdir()
    (root / "config" / "omniscient.toml").write_text("", encoding="utf-8")
    (root / "repos").mkdir()
    monkeypatch.setenv(ENV_VAR, str(root))
    return root
