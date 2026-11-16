"""export / install / CLI: deterministic zip, preview vs --write, overwrite refusal."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest
from typer.testing import CliRunner

from omniscient import cli_ext
from omniscient.cli import app
from omniscient.group import ext_package as pkg
from omniscient.group.ext_schema import ExtensionError
from tests.ext_support import manifest, write_ext

runner = CliRunner()


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "home"
    (root / "config").mkdir(parents=True)
    (root / "config" / "omniscient.toml").write_text("")
    monkeypatch.setenv("OMNISCIENT_HOME", str(root))
    return root


def source_folder(tmp_path: Path, **extra) -> Path:
    folder = write_ext(
        tmp_path / "src", manifest(id="demo", **extra), folder="whatever"
    )
    (folder / "README.md").write_text("hello")
    (folder / "setup.sh").write_text("rm -rf /")
    (folder / ".git").mkdir()
    return folder


def test_export_is_deterministic_and_only_allowed_files(tmp_path: Path) -> None:
    folder = write_ext(tmp_path / "e", manifest(id="demo"))
    (folder / "README.md").write_text("r")
    (folder / "LICENSE").write_text("MIT")
    first, second = tmp_path / "a.zip", tmp_path / "b.zip"
    pkg.export_zip(folder, first)
    pkg.export_zip(folder, second)
    assert first.read_bytes() == second.read_bytes()
    with zipfile.ZipFile(first) as zf:
        assert zf.namelist() == [
            "demo/LICENSE",
            "demo/README.md",
            "demo/extension.json",
        ]
        assert {i.date_time for i in zf.infolist()} == {(1980, 1, 1, 0, 0, 0)}


def test_export_refuses_an_invalid_extension(tmp_path: Path) -> None:
    folder = write_ext(tmp_path / "e", manifest(id="demo"))
    (folder / "x.js").write_text("x")
    with pytest.raises(ExtensionError):
        pkg.export_zip(folder, tmp_path / "o.zip")
    assert not (tmp_path / "o.zip").exists()


def test_install_copies_only_allowed_files(tmp_path: Path) -> None:
    folder = source_folder(tmp_path)
    with pkg.open_source(str(folder)) as src:
        assert src.ignored == (".git", "setup.sh")
        target = pkg.install(src, tmp_path / "root")
    assert sorted(p.name for p in target.iterdir()) == ["README.md", "extension.json"]


def test_install_refuses_overwrite_unless_forced(tmp_path: Path) -> None:
    folder = source_folder(tmp_path)
    with pkg.open_source(str(folder)) as src:
        target = pkg.install(src, tmp_path / "root")
        (target / "README.md").write_text("mine")
        with pytest.raises(ExtensionError, match="existe déjà"):
            pkg.install(src, tmp_path / "root")
        assert (target / "README.md").read_text() == "mine"
        pkg.install(src, tmp_path / "root", force=True)
    assert (target / "README.md").read_text() == "hello"
    assert not [p for p in (tmp_path / "root").iterdir() if p.name.startswith(".")]


def test_git_sources_are_github_https_only(tmp_path: Path) -> None:
    for url in ("https://evil.example/a/b", "http://github.com/a/b", "git@github.com:a/b.git",
                "https://github.com/a", "https://github.com/a/b/c", "https://github.com/a/b?x=1",
                "https://user@github.com/a/b"):  # fmt: skip
        with (
            pytest.raises(ExtensionError),
            pkg.open_source(url, git_fetch=lambda u, d: None),
        ):
            pass


def test_git_install_uses_the_injected_fetch_and_subpath(tmp_path: Path) -> None:
    calls: list[str] = []

    def fake_fetch(url: str, dest: Path) -> None:
        calls.append(url)
        write_ext(dest / "pack", manifest(id="demo"), folder="inner")

    with pkg.open_source("https://github.com/o/r.git", "pack/inner", fake_fetch) as src:
        assert src.extension.id == "demo"
    assert calls == ["https://github.com/o/r.git"]
    for bad in ("../x", "/etc", "a/../b", ""):
        if bad == "":
            continue
        with (
            pytest.raises(ExtensionError),
            pkg.open_source("https://github.com/o/r", bad, fake_fetch),
        ):
            pass
    with (
        pytest.raises(ExtensionError, match="--path"),
        pkg.open_source(str(tmp_path), "x"),
    ):
        pass


def test_cli_new_validate_list_remove(home: Path) -> None:
    assert runner.invoke(app, ["ext", "new", "demo"]).exit_code == 0
    assert runner.invoke(app, ["ext", "new", "demo"]).exit_code == 1
    assert runner.invoke(app, ["ext", "new", "Bad_Id"]).exit_code == 1
    assert "OK demo" in runner.invoke(app, ["ext", "validate"]).output
    assert "OK demo" in runner.invoke(app, ["ext", "validate", "demo"]).output
    assert "demo 0.1.0" in runner.invoke(app, ["ext", "list"]).output
    (home / "extensions" / "demo" / "evil.js").write_text("x")
    assert runner.invoke(app, ["ext", "validate"]).exit_code == 1
    assert runner.invoke(app, ["ext", "validate", "demo"]).exit_code == 1
    preview = runner.invoke(app, ["ext", "remove", "demo"])
    assert "--write" in preview.output and (home / "extensions" / "demo").exists()
    assert runner.invoke(app, ["ext", "remove", "demo", "--write"]).exit_code == 0
    assert not (home / "extensions" / "demo").exists()


def test_cli_init_writes_the_guide(home: Path) -> None:
    assert runner.invoke(app, ["ext", "init"]).exit_code == 0
    assert "Construire une extension" in (home / "extensions" / "README.md").read_text()
    assert (
        runner.invoke(app, ["ext", "validate"]).exit_code == 0
    )  # the README is not an extension


def test_cli_export(home: Path, tmp_path: Path) -> None:
    runner.invoke(app, ["ext", "new", "demo"])
    out = tmp_path / "demo.zip"
    assert (
        runner.invoke(app, ["ext", "export", "demo", "--out", str(out)]).exit_code == 0
    )
    assert zipfile.ZipFile(out).namelist() == ["demo/README.md", "demo/extension.json"]


def test_cli_install_preview_then_write(home: Path, tmp_path: Path) -> None:
    folder = source_folder(
        tmp_path,
        commands=[
            {
                "name": "go",
                "title": "Go",
                "prompt": "Dis {x}",
                "args": [{"name": "x", "default": "a"}],
            }
        ],
    )
    preview = runner.invoke(app, ["ext", "install", str(folder)])
    assert preview.exit_code == 0
    for needle in (
        "demo 1.0.0",
        "Dis {x}",
        "extension.json",
        "setup.sh",
        "Aperçu seulement",
    ):
        assert needle in preview.output
    assert not (home / "extensions" / "demo").exists()
    done = runner.invoke(app, ["ext", "install", str(folder), "--write"])
    assert (
        done.exit_code == 0
        and (home / "extensions" / "demo" / "extension.json").is_file()
    )
    again = runner.invoke(app, ["ext", "install", str(folder), "--write"])
    assert again.exit_code == 1 and "existe déjà" in again.output
    assert (
        runner.invoke(
            app, ["ext", "install", str(folder), "--write", "--force"]
        ).exit_code
        == 0
    )


def test_cli_install_from_git_with_a_fake(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake(url: str, dest: Path) -> None:
        write_ext(dest, manifest(id="gitext"), folder=".")

    monkeypatch.setitem(cli_ext.GitFetchHook, "fetch", fake)
    result = runner.invoke(app, ["ext", "install", "https://github.com/o/r"])
    assert result.exit_code == 0 and "gitext" in result.output
    assert not (home / "extensions" / "gitext").exists()
    bad = runner.invoke(app, ["ext", "install", "https://evil.example/o/r", "--write"])
    assert bad.exit_code == 1


def test_cli_install_invalid_source_is_refused(home: Path, tmp_path: Path) -> None:
    folder = tmp_path / "bad"
    folder.mkdir()
    (folder / "extension.json").write_text(json.dumps({"schema": 1}))
    assert runner.invoke(app, ["ext", "install", str(folder), "--write"]).exit_code == 1
    assert not (home / "extensions").exists() or not list(
        (home / "extensions").iterdir()
    )
