from datetime import UTC, datetime
from pathlib import Path

import frontmatter
import pytest

from omniscient.brain import Idea, IdeaScores, write_idea
from omniscient.verdicts import apply_owner_verdict

NOW = datetime(2026, 11, 12, 23, 0, tzinfo=UTC)


def _idea(vault: Path, status: str = "debated") -> Path:
    idea = Idea(
        title="Run coach",
        pitch="Coach from FIT files, long enough.",
        status=status,  # type: ignore[arg-type]
        scores=IdeaScores(
            novelty=0.5, impact=0.5, feasibility=0.5, fit=0.5, effort=0.5
        ),
        sources=(),
        projects=("run-tracker",),
        created=NOW,
    )
    return write_idea(vault, idea, score=0.56, council="**Verdict:** reshape")


@pytest.mark.parametrize(
    ("verdict", "status", "owner"),
    [
        ("drop", "dropped", "drop"),
        ("pursue", "debated", "pursue"),
        ("reshape", "debated", "reshape"),
    ],
)
def test_apply_owner_verdict(
    tmp_path: Path, verdict: str, status: str, owner: str
) -> None:
    path = _idea(tmp_path)

    apply_owner_verdict(tmp_path, path.stem, verdict)

    meta = frontmatter.load(path)
    assert meta["status"] == status
    assert meta["owner_verdict"] == owner


def test_apply_owner_verdict_rejects_unknown_idea_and_path_tricks(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="unknown idea"):
        apply_owner_verdict(tmp_path, "../../AGENTS", "drop")


def test_apply_owner_verdict_rejects_unknown_verdict(tmp_path: Path) -> None:
    path = _idea(tmp_path)

    with pytest.raises(ValueError, match="verdict must be one of"):
        apply_owner_verdict(tmp_path, path.stem, "maybe")
