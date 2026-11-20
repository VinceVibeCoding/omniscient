"""The home (user data) is separate from the engine and resolved at command time."""

from __future__ import annotations

from pathlib import Path

from omniscient.home import ENV_VAR, Home, find_home, packaged

REPO = Path(__file__).resolve().parents[1]


def _make_home(root: Path) -> Home:
    (root / "config").mkdir(parents=True)
    (root / "config" / "omniscient.toml").write_text("", "utf-8")
    return Home(root)


def test_env_var_wins_over_search_up(tmp_path: Path) -> None:
    home = find_home(cwd=REPO, environ={ENV_VAR: str(tmp_path)})

    assert home.root == tmp_path.resolve()


def test_search_up_finds_a_home_from_a_subfolder(tmp_path: Path) -> None:
    checkout = tmp_path / "checkout"
    _make_home(checkout)
    nested = checkout / "src" / "omniscient"
    nested.mkdir(parents=True)

    home = find_home(cwd=nested, environ={})

    assert home.root == checkout.resolve()
    assert home.exists


def test_no_home_falls_back_to_dot_omniscient(tmp_path: Path) -> None:
    home = find_home(cwd=tmp_path, environ={})

    assert home.root == Path.home() / ".omniscient"
    assert not Home(tmp_path / "empty").exists


def test_home_paths_are_under_the_root(tmp_path: Path) -> None:
    home = Home(tmp_path)

    assert home.state == tmp_path / ".omniscient"
    assert home.repos == tmp_path / "repos"
    assert home.profile == tmp_path / "config" / "profile.toml"
    assert home.env_file == tmp_path / ".env"


def test_packaged_resources_ship_the_systemd_unit() -> None:
    assert (packaged("templates") / "systemd" / "omniscient.service").is_file()
    assert not (packaged("templates") / "omniscient-cycle.service").exists()
