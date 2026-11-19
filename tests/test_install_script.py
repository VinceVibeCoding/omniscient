"""install.ps1 cannot run here (Linux): static guarantees about what it may do."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (ROOT / "install.ps1").read_text(encoding="utf-8")
CODE = "\n".join(
    line for line in SCRIPT.splitlines() if not line.lstrip().startswith("#")
)


def test_documented_parameters_exist() -> None:
    head = SCRIPT.split("function ", 1)[0]
    for name in ("$Wheel", "$Installer", "$SkipWidget", "$NoAutostart"):
        assert name in head


def test_only_the_uv_fallback_is_piped_to_iex() -> None:
    hits = [m.group(0) for m in re.finditer(r"(?i)\|\s*iex|Invoke-Expression", CODE)]
    assert len(hits) == 1
    assert "astral.sh/uv/install.ps1" in CODE


def test_needs_no_admin_and_no_git() -> None:
    assert not re.search(r"(?i)-Verb\s+RunAs|git\+https|\bgit\s+clone", CODE)
    assert "Set-ExecutionPolicy" not in CODE


def test_checks_the_wheel_hash_before_installing() -> None:
    assert CODE.index("Get-FileHash") < CODE.index("'tool', 'install'")
    assert "SHA256SUMS" in CODE


def test_no_personal_data() -> None:
    assert not re.search(r"(?i)/home/|C:\\Users\\|@[a-z0-9-]+\.(com|fr)", SCRIPT)
