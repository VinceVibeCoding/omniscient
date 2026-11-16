"""Extension manifests: schema rules, loading, collisions and expansion."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from omniscient.group.ext_schema import ExtensionError, parse_manifest
from omniscient.group.extensions import expand, load_all, load_folder
from tests.ext_support import command, manifest, write_ext


def refused(**extra: Any) -> str:
    with pytest.raises(ExtensionError) as err:
        parse_manifest(manifest(**extra))
    return err.value.message


def test_a_minimal_manifest_is_valid() -> None:
    ext = parse_manifest(manifest())
    assert ext.id == "demo" and ext.commands == () and ext.author == ""


def test_unknown_keys_are_refused_everywhere() -> None:
    assert "inconnue" in refused(extra=1)
    assert "inconnue" in refused(commands=[command(shell="rm")])
    assert "inconnue" in refused(commands=[command(args=[{"name": "n", "code": 1}])])


@pytest.mark.parametrize("bad", ["Demo", "-a", "a" * 41, "a_b", ""])
def test_id_format(bad: str) -> None:
    assert "id" in refused(id=bad)


def test_id_must_equal_folder_name() -> None:
    with pytest.raises(ExtensionError):
        parse_manifest(manifest(), "other")


def test_schema_version_and_required_fields() -> None:
    assert "schema" in refused(schema=2)
    assert "schema" in refused(schema=True)
    data = manifest()
    del data["version"]
    with pytest.raises(ExtensionError):
        parse_manifest(data)
    assert "version" in refused(version="1.0")


@pytest.mark.parametrize("name", ["Resume", "1a", "a" * 31, "a_b"])
def test_command_name_format(name: str) -> None:
    assert "name" in refused(commands=[command(name)])


def test_unknown_placeholder_is_invalid_and_braces_escape() -> None:
    assert "non déclaré" in refused(commands=[command(prompt="Fais {x}")])
    assert "non déclaré" in refused(commands=[command(prompt="Fais {}")])
    assert "non déclaré" in refused(commands=[command(prompt="{n!r}")])
    assert "non déclaré" in refused(commands=[command(prompt="{n:>5}")])
    assert "accolades" in refused(commands=[command(prompt="oups {")])
    parse_manifest(manifest(commands=[command(prompt="json {{a}} {n}")]))


def test_caps() -> None:
    assert "2000" in refused(commands=[command(prompt="x" * 2001)])
    assert "au plus" in refused(commands=[command(f"c{i}") for i in range(21)])
    assert "200" in refused(
        commands=[command(args=[{"name": "n", "default": "x" * 201}])]
    )
    steps = [{"prompt": "a"}] * 9
    wf = {"name": "w", "title": "W", "steps": steps}
    assert "au plus" in refused(workflows=[wf])
    assert "étape" in refused(workflows=[{**wf, "steps": []}])
    theme = {"id": "t", "label": "T", "colors": {"--accent": "#fff"}}
    assert "au plus" in refused(themes=[{**theme, "id": f"t{i}"} for i in range(11)])
    preset = {"id": "p", "label": "P", "kind": "openai"}
    assert "au plus" in refused(
        provider_presets=[{**preset, "id": f"p{i}"} for i in range(11)]
    )


def test_duplicate_names_inside_an_extension() -> None:
    assert "double" in refused(commands=[command("a"), command("a")])
    wf = {"name": "a", "title": "W", "steps": [{"prompt": "x"}]}
    assert "double" in refused(commands=[command("a")], workflows=[wf])


@pytest.mark.parametrize(
    "value",
    [
        "url(http://x)",
        "var(--x)",
        "red",
        "#ggg",
        "#12345",
        "rgb(1,2)",
        "rgb(300,0,0)",
        "rgb(1,2,3);x",
        "expression(1)",
        5,
    ],
)
def test_theme_values_are_strict(value: Any) -> None:
    theme = {"id": "t", "label": "T", "colors": {"--accent": value}}
    assert "couleur" in refused(themes=[theme])


@pytest.mark.parametrize(
    "value",
    [
        "#fff",
        "#aabbcc",
        "#aabbccdd",
        "rgb(1, 2, 3)",
        "rgba(1,2,3,0.5)",
        "rgba(1,2,3,1)",
    ],
)
def test_theme_values_accepted(value: str) -> None:
    theme = {"id": "t", "label": "T", "colors": {"--accent": value}}
    assert parse_manifest(manifest(themes=[theme])).themes[0].colors == (
        ("--accent", value),
    )


def test_theme_keys_come_from_the_allowlist() -> None:
    for key in ("--radius", "--osd-mono", "background", "--x", "--gap"):
        theme = {"id": "t", "label": "T", "colors": {key: "#fff"}}
        assert "non autorisée" in refused(themes=[theme])


def test_presets_never_carry_keys_and_check_syntax_only() -> None:
    ok = {
        "id": "p",
        "label": "P",
        "kind": "openai-compatible",
        "base_url": "http://127.0.0.1:11434/v1",
        "model": "m",
    }
    assert (
        parse_manifest(manifest(provider_presets=[ok]))
        .presets[0]
        .base_url.endswith("/v1")
    )
    assert "inconnue" in refused(provider_presets=[{**ok, "api_key": "sk-123456789"}])
    assert "type inconnu" in refused(provider_presets=[{**ok, "kind": "evil"}])
    for url in (
        "ftp://x.test",
        "http://evil.example/v1",
        "https://u:p@x.test",
        "https://x.test/?a=1",
        "file:///etc",
    ):
        assert "base_url" in refused(provider_presets=[{**ok, "base_url": url}])
    fixed = {"id": "p", "label": "P", "kind": "openai", "base_url": "https://x.test"}
    assert "réservé" in refused(provider_presets=[fixed])
    parse_manifest(
        manifest(provider_presets=[{"id": "p", "label": "P", "kind": "gemini"}])
    )
    # https to a host that would not resolve is fine at load time: no DNS here
    parse_manifest(
        manifest(provider_presets=[{**ok, "base_url": "https://nope.invalid/v1"}])
    )


# ---- loading ---------------------------------------------------------------------------


def test_load_all_lists_valid_and_reports_invalid(tmp_path: Path) -> None:
    write_ext(tmp_path, manifest(id="good"))
    bad = write_ext(tmp_path, manifest(id="bad"))
    (bad / "extension.json").write_text("{nope", encoding="utf-8")
    write_ext(tmp_path, manifest(id="wrong"), folder="other")
    (tmp_path / "README.md").write_text("guide", encoding="utf-8")
    (tmp_path / ".install-x").mkdir()
    result = load_all(tmp_path)
    assert [e.id for e in result.extensions] == ["good"]
    assert {e.id for e in result.errors} == {"bad", "other"}
    assert all(e.message for e in result.errors)


def test_missing_root_is_empty(tmp_path: Path) -> None:
    assert load_all(tmp_path / "none").extensions == ()


def test_extra_files_make_it_invalid(tmp_path: Path) -> None:
    folder = write_ext(tmp_path, manifest(id="a"))
    (folder / "evil.js").write_text("x")
    result = load_all(tmp_path)
    assert result.extensions == () and "non autorisé" in result.errors[0].message
    (folder / "evil.js").unlink()
    (folder / "sub").mkdir()
    assert load_all(tmp_path).extensions == ()


def test_symlinks_are_never_followed(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "x").write_text("x")
    root = tmp_path / "root"
    folder = write_ext(root, manifest(id="a"))
    (folder / "README.md").symlink_to(outside / "x")
    assert "symboliques" in load_all(root).errors[0].message
    (folder / "README.md").unlink()
    real = write_ext(outside, manifest(id="b"))
    (root / "b").symlink_to(real, target_is_directory=True)
    result = load_all(root)
    assert [e.id for e in result.extensions] == ["a"] and result.errors[0].id == "b"


def test_size_and_encoding_limits(tmp_path: Path) -> None:
    folder = write_ext(tmp_path, manifest(id="a"))
    (folder / "README.md").write_bytes(b"x" * (64 * 1024 + 1))
    assert "Ko" in load_all(tmp_path).errors[0].message
    (folder / "README.md").write_bytes(b"\xff\xfe\x00")
    assert "UTF-8" in load_all(tmp_path).errors[0].message
    (folder / "README.md").write_text("ok")
    (folder / "extension.json").write_bytes(b"\xff")
    assert "UTF-8" in load_all(tmp_path).errors[0].message


def test_collisions_across_extensions_and_builtins(tmp_path: Path) -> None:
    write_ext(tmp_path, manifest(id="aaa", commands=[command("resume")]))
    write_ext(tmp_path, manifest(id="bbb", commands=[command("resume")]))
    write_ext(tmp_path, manifest(id="ccc", commands=[command("reload")]))
    wf = {"name": "help", "title": "W", "steps": [{"prompt": "x"}]}
    write_ext(tmp_path, manifest(id="ddd", workflows=[wf]))
    result = load_all(tmp_path)
    assert [e.id for e in result.extensions] == ["aaa"]
    messages = {e.id: e.message for e in result.errors}
    assert (
        "aaa" in messages["bbb"]
        and "intégrée" in messages["ccc"]
        and "intégrée" in messages["ddd"]
    )


def test_non_strict_ignores_other_files(tmp_path: Path) -> None:
    folder = write_ext(tmp_path, manifest(id="a"))
    (folder / ".git").mkdir()
    ext = load_folder(folder, strict=False, check_name=False)
    assert [n for n, _ in ext.files] == ["extension.json"]


# ---- expansion -------------------------------------------------------------------------


def cmd(prompt: str, args: list[dict]) -> Any:
    data = manifest(
        commands=[{"name": "c", "title": "C", "prompt": prompt, "args": args}]
    )
    return parse_manifest(data).commands[0]


def test_expand_basics_and_defaults() -> None:
    c = cmd(
        "En {n} points sur {sujet}",
        [{"name": "n", "default": "5"}, {"name": "sujet", "default": "ça"}],
    )
    assert expand(c, "") == "En 5 points sur ça"
    assert expand(c, "7") == "En 7 points sur ça"
    assert expand(c, '3 "la page web"') == "En 3 points sur la page web"


def test_expand_errors() -> None:
    c = cmd("{a} {b}", [{"name": "a"}, {"name": "b", "default": "x"}])
    with pytest.raises(ExtensionError, match="requis"):
        expand(c, "")
    with pytest.raises(ExtensionError, match="au plus"):
        expand(c, "1 2 3")
    with pytest.raises(ExtensionError, match="mal formés"):
        expand(c, '"oops')
    with pytest.raises(ExtensionError, match="trop longs"):
        expand(c, "x" * 2001)


def test_expand_values_are_not_reinterpreted() -> None:
    c = cmd("a {{x}} {n}", [{"name": "n"}])
    assert expand(c, "'{n} {x} {{'") == "a {x} {n} {x} {{"


def test_expand_result_is_capped() -> None:
    c = cmd("{a}{a}{a}{a}{a}", [{"name": "a"}])
    with pytest.raises(ExtensionError, match="dépasse"):
        expand(c, "x" * 1800)


def test_json_roundtrip_of_manifest_file(tmp_path: Path) -> None:
    folder = write_ext(tmp_path, manifest(id="a"))
    assert json.loads((folder / "extension.json").read_text())["id"] == "a"
    assert os.path.isdir(folder)
