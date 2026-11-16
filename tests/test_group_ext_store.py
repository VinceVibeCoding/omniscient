"""ExtensionStore: cache, disabled list persistence and permissions, safe removal."""

from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

from omniscient.group.ext_guide import EXAMPLE_COMMAND
from omniscient.group.ext_schema import ExtensionError
from omniscient.group.ext_store import ExtensionStore
from tests.ext_support import manifest, write_ext
from tests.platform_marks import WINDOWS


@pytest.fixture
def store(tmp_path: Path) -> ExtensionStore:
    write_ext(tmp_path / "extensions")
    return ExtensionStore(tmp_path / "extensions", tmp_path / "state")


def test_view_never_holds_a_path(store: ExtensionStore, tmp_path: Path) -> None:
    view = store.view()
    assert (
        view["extensions"][0]["id"] == "resume-page"
        and view["extensions"][0]["enabled"]
    )
    assert str(tmp_path) not in json.dumps(view)


def test_cache_until_reload(store: ExtensionStore, tmp_path: Path) -> None:
    write_ext(tmp_path / "extensions", manifest(id="second"))
    assert len(store.view()["extensions"]) == 1
    store.reload()
    assert len(store.view()["extensions"]) == 2


def test_disabled_list_persists_with_private_mode(
    store: ExtensionStore, tmp_path: Path
) -> None:
    store.disable("resume-page")
    path = tmp_path / "state" / "extensions.json"
    assert json.loads(path.read_text()) == {"disabled": ["resume-page"]}
    if not WINDOWS:
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    again = ExtensionStore(tmp_path / "extensions", tmp_path / "state")
    assert again.view()["extensions"][0]["enabled"] is False
    again.enable("resume-page")
    assert json.loads(path.read_text()) == {"disabled": []}


def test_unknown_extension_is_404(store: ExtensionStore) -> None:
    with pytest.raises(ExtensionError) as err:
        store.disable("ghost")
    assert err.value.status == 404


def test_corrupt_disabled_file_is_logged_not_fatal(
    store: ExtensionStore, tmp_path: Path, caplog
) -> None:
    (tmp_path / "state").mkdir(exist_ok=True)
    (tmp_path / "state" / "extensions.json").write_text("{bad")
    assert store.disabled() == frozenset()
    assert "unreadable" in caplog.text


def test_expand_refuses_disabled_and_unknown(store: ExtensionStore) -> None:
    assert store.expand("resume", "7") == {
        "text": "Résume la page en 7 points, en français.",
        "attach_page": True,
    }
    store.disable("resume-page")
    for name in ("resume", "nope"):
        with pytest.raises(ExtensionError) as err:
            store.expand(name, "")
        assert err.value.status == 404


def test_remove_deletes_the_folder_and_the_disabled_entry(
    store: ExtensionStore, tmp_path: Path
) -> None:
    store.disable("resume-page")
    store.remove("resume-page")
    assert not (tmp_path / "extensions" / "resume-page").exists()
    assert store.view()["extensions"] == []
    assert json.loads((tmp_path / "state" / "extensions.json").read_text()) == {
        "disabled": []
    }


def test_remove_can_clean_an_invalid_extension(
    store: ExtensionStore, tmp_path: Path
) -> None:
    (tmp_path / "extensions" / "resume-page" / "evil.js").write_text("x")
    store.reload()
    assert store.view()["errors"]
    store.remove("resume-page")
    assert store.view()["errors"] == []


@pytest.mark.parametrize("bad", ["..", "../x", "a/b", "", ".", "A", "a" * 41])
def test_remove_refuses_path_tricks(
    store: ExtensionStore, tmp_path: Path, bad: str
) -> None:
    (tmp_path / "x").mkdir()
    with pytest.raises(ExtensionError):
        store.remove(bad)
    assert (tmp_path / "x").exists() and (tmp_path / "extensions").exists()


def test_remove_refuses_a_symlink_and_keeps_its_target(
    store: ExtensionStore, tmp_path: Path
) -> None:
    target = tmp_path / "precious"
    target.mkdir()
    (target / "keep.txt").write_text("keep")
    (tmp_path / "extensions" / "linked").symlink_to(target, target_is_directory=True)
    with pytest.raises(ExtensionError, match="refusée"):
        store.remove("linked")
    assert (target / "keep.txt").exists()


def test_remove_unknown_is_404_and_files_are_refused(
    store: ExtensionStore, tmp_path: Path
) -> None:
    with pytest.raises(ExtensionError) as err:
        store.remove("ghost")
    assert err.value.status == 404
    (tmp_path / "extensions" / "afile").write_text("x")
    with pytest.raises(ExtensionError, match="refusée"):
        store.remove("afile")


def test_example_is_what_the_store_loads() -> None:
    assert EXAMPLE_COMMAND["id"] == "resume-page"
