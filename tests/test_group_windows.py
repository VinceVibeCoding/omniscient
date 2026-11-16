"""Windows-native behaviour of the omnigroup engine, tested on every platform with
injected runners (no real icacls / taskkill / message box is started here)."""

from __future__ import annotations

import io
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from omniscient.group import claude_locate as cl
from omniscient.group import cli_group_setup as setup
from omniscient.group import credentials as cred
from omniscient.group import hook_command as hc
from omniscient.group import pairing, procctl
from omniscient.group.hook_client import use_utf8_streams
from omniscient.group.hook_install import claude_hooks, copilot_hooks, plan
from omniscient.group.hook_match import is_ours, is_status_command, without_ours
from omniscient.home import Home

WIN_CMD = "'C:/Users/Jean Dupont/.local/bin/omniscient-hook.exe'"


# ---- restrict_to_current_user ----------------------------------------------------


class Recorder:
    def __init__(self, code: int = 0) -> None:
        self.calls: list[list[str]] = []
        self.kwargs: list[dict[str, Any]] = []
        self.code = code

    def __call__(self, argv: list[str], **kw: Any) -> Any:
        self.calls.append(list(argv))
        self.kwargs.append(kw)
        return SimpleNamespace(returncode=self.code)


def test_icacls_argv_for_a_file_and_a_directory(tmp_path: Path) -> None:
    f = tmp_path / "t"
    f.write_text("x", encoding="utf-8")
    run = Recorder()
    assert cred.restrict_to_current_user(f, False, run, True, "PC\\jean dupont")
    assert run.calls[-1] == [
        "icacls", str(f), "/inheritance:r", "/grant:r", "PC\\jean dupont:(F)"
    ]  # fmt: skip
    assert cred.restrict_to_current_user(tmp_path, True, run, True, "PC\\jean")
    assert run.calls[-1][-1] == "PC\\jean:(OI)(CI)(F)"
    assert all(k.get("check") is False and "shell" not in k for k in run.kwargs)


def test_icacls_failure_is_logged_not_raised(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    f = tmp_path / "t"
    f.write_text("x", encoding="utf-8")
    with caplog.at_level("WARNING", logger="omniscient.group.credentials"):
        assert not cred.restrict_to_current_user(f, False, Recorder(5), True, "PC\\u")
        boom = cred.restrict_to_current_user(f, False, _raiser, True, "PC\\u")
    assert boom is False and "icacls" in caplog.text


def _raiser(argv: list[str], **kw: Any) -> Any:
    raise FileNotFoundError("icacls")


def test_a_missing_path_is_not_an_error_on_windows(tmp_path: Path) -> None:
    run = Recorder()
    assert cred.restrict_to_current_user(tmp_path / "no", False, run, True, "PC\\u")
    assert run.calls == []


@pytest.mark.parametrize("env", [{"USERNAME": 'x;y"z', "USERDOMAIN": "PC"}])
def test_current_account_refuses_odd_names(
    env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cred.getpass, "getuser", lambda: 'x:"y')
    with pytest.raises(ValueError):
        cred.current_account(env)


def test_current_account_joins_domain_and_user(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cred.getpass, "getuser", lambda: "jean")
    assert cred.current_account({"USERDOMAIN": "PC"}) == "PC\\jean"
    assert cred.current_account({}) == "jean"


def test_posix_branch_still_chmods(tmp_path: Path) -> None:
    f = tmp_path / "t"
    f.write_text("x", encoding="utf-8")
    run = Recorder()
    assert cred.restrict_to_current_user(f, False, run, False)
    assert run.calls == []  # no icacls on POSIX


# ---- process control --------------------------------------------------------------


def test_spawn_kwargs_per_platform() -> None:
    assert procctl.spawn_kwargs(False) == {"start_new_session": True}
    flags = (
        procctl.spawn_kwargs.__wrapped__
        if hasattr(procctl.spawn_kwargs, "__wrapped__")
        else None
    )
    assert flags is None


def test_taskkill_argv_kills_the_tree() -> None:
    assert procctl.taskkill_argv(42, False) == ["taskkill", "/T", "/PID", "42"]
    assert procctl.taskkill_argv(42, True) == ["taskkill", "/T", "/F", "/PID", "42"]


def test_terminate_and_kill_use_taskkill_on_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(procctl, "is_windows", lambda: True)
    proc = SimpleNamespace(pid=7, poll=lambda: None)
    run = Recorder()
    procctl.terminate(proc, run)  # type: ignore[arg-type]
    procctl.kill(proc, run)  # type: ignore[arg-type]
    assert run.calls == [["taskkill", "/T", "/PID", "7"], ["taskkill", "/T", "/F", "/PID", "7"]]  # fmt: skip


def test_a_finished_process_is_left_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(procctl, "is_windows", lambda: True)
    run = Recorder()
    procctl.kill(SimpleNamespace(pid=7, poll=lambda: 0), run)  # type: ignore[arg-type]
    assert run.calls == []


# ---- claude CLI -------------------------------------------------------------------


def test_exe_is_launched_directly_and_cmd_needs_a_real_exe(tmp_path: Path) -> None:
    exe = tmp_path / "claude.exe"
    assert cl.launch_prefix(str(exe), True) == (str(exe),)
    shim = tmp_path / "claude.cmd"
    assert cl.launch_prefix(str(shim), True) == ("cmd.exe", "/d", "/c", str(shim))
    exe.write_bytes(b"MZ")
    assert cl.launch_prefix(str(shim), True) == (str(exe),)


def test_cmd_shim_finds_the_npm_native_binary(tmp_path: Path) -> None:
    real = tmp_path.joinpath(*cl.NPM_NATIVE)
    real.parent.mkdir(parents=True)
    real.write_bytes(b"MZ")
    assert cl.launch_prefix(str(tmp_path / "claude.cmd"), True) == (str(real),)


def test_cmd_launch_refuses_metacharacters() -> None:
    cl.check_shim_args(["cmd.exe", "/d", "/c", "x.cmd", "-p", "--resume", "ab-1"])
    with pytest.raises(ValueError):
        cl.check_shim_args(["cmd.exe", "/d", "/c", "x.cmd", "a&calc"])
    cl.check_shim_args(["claude.exe", "a&b"])  # a real exe takes anything


def test_find_claude_uses_path_then_the_native_installer(tmp_path: Path) -> None:
    assert cl.find_claude(lambda n: "C:/x/claude.exe", {}, True) == "C:/x/claude.exe"
    assert cl.find_claude(lambda n: None, {"USERPROFILE": str(tmp_path)}, True) is None
    launcher = tmp_path / ".local" / "bin" / "claude.exe"
    launcher.parent.mkdir(parents=True)
    launcher.write_bytes(b"MZ")
    env = {"USERPROFILE": str(tmp_path)}
    assert cl.find_claude(lambda n: None, env, True) == str(launcher)
    assert cl.find_claude(lambda n: None, env, False) is None  # POSIX: PATH only


def test_resolve_command_keeps_a_configured_path_and_resolves_a_bare_name() -> None:
    assert cl.resolve_command(["C:\\bin\\claude.exe", "-x"]) == (
        "C:\\bin\\claude.exe",
        "-x",
    )
    got = cl.resolve_command(["claude"], lambda n: "/opt/claude", {}, False)
    assert got == ("/opt/claude",)
    assert cl.resolve_command(["claude"], lambda n: None, {}, False) == ("claude",)


# ---- hook commands ---------------------------------------------------------------


def test_base_command_on_windows_uses_forward_slashes(tmp_path: Path) -> None:
    exe = tmp_path / "bin dir" / "omniscient-hook.exe"
    cmd = hc.base_command(Home(tmp_path / "my home"), lambda _n: str(exe), windows=True)
    assert "\\" not in cmd
    assert cmd.startswith("'") and " --home '" in cmd


def test_claude_hooks_use_the_exec_form_on_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(hc, "is_windows", lambda: True)
    hooks = claude_hooks(f"{WIN_CMD} --home 'D:/my home'")
    entry = hooks["PermissionRequest"][0]["hooks"][0]
    assert entry["command"] == "C:/Users/Jean Dupont/.local/bin/omniscient-hook.exe"
    assert entry["args"] == ["--home", "D:/my home", "--source", "claude"]
    fast = hooks["Stop"][0]["hooks"][0]
    assert fast["args"][-1] == "--fast"
    assert all(is_ours(g) for gs in hooks.values() for g in gs[0]["hooks"])


def test_exec_form_is_recognised_and_removed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(hc, "is_windows", lambda: True)
    ours = claude_hooks(WIN_CMD)
    user = {"Stop": [{"hooks": [{"type": "command", "command": "notify.exe"}]}]}
    merged = {"Stop": user["Stop"] + ours["Stop"]}
    assert without_ours(merged) == user


def test_copilot_entries_get_a_powershell_twin_on_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("omniscient.group.hook_install.is_windows", lambda: True)
    entry = copilot_hooks(WIN_CMD)["sessionStart"][0]
    assert entry["powershell"] == f"& {entry['bash']}" and is_ours(entry)


def test_statusline_string_is_shortened_or_quoted() -> None:
    short = lambda p: "C:/Users/JEAND~1/x/omniscient-hook.exe"
    plain = hc.line_command("/a/b --statusline", True, short)
    assert plain == "/a/b --statusline"
    spaced = hc.line_command(f"{WIN_CMD} --statusline", True, short)
    assert spaced == "C:/Users/JEAND~1/x/omniscient-hook.exe --statusline"
    quoted = hc.line_command(f"{WIN_CMD} --statusline", True, lambda p: None)
    assert quoted.startswith('"C:/Users/Jean Dupont/') and quoted.endswith(
        '" --statusline'
    )
    assert is_status_command(quoted) and is_status_command(spaced)
    assert (
        hc.line_command(f"{WIN_CMD} --statusline", False) == f"{WIN_CMD} --statusline"
    )


def test_windows_backslash_paths_are_recognised() -> None:
    assert is_status_command("C:/p/omniscient-hook.exe --statusline")
    entry = {"command": "C:\\p\\omniscient-hook.exe", "args": ["--source", "claude"]}
    assert is_ours(entry)


def test_plan_installs_the_exec_form(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(hc, "is_windows", lambda: True)
    path = tmp_path / "settings.json"
    p = plan("claude", "install", path, WIN_CMD)
    data = json.loads(p.after or "{}")
    hook = data["hooks"]["Stop"][0]["hooks"][0]
    assert hook["command"].endswith("omniscient-hook.exe") and "args" in hook


# ---- utf-8 streams / pairing -----------------------------------------------------


def test_hook_streams_are_switched_to_utf8() -> None:
    class Stream(io.StringIO):
        def __init__(self) -> None:
            super().__init__()
            self.seen: dict[str, str] = {}

        def reconfigure(self, **kw: str) -> None:  # type: ignore[override]
            self.seen = kw

    stream = Stream()
    use_utf8_streams(stream, io.StringIO())  # a plain StringIO has no reconfigure
    assert stream.seen == {"encoding": "utf-8", "errors": "replace"}


def test_native_windows_pairing_uses_the_message_box(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pairing, "is_native_windows", lambda: True)
    shown: list[str] = []
    assert pairing.show_code_on_windows(
        "123456", lambda a: False, lambda c: shown.append(c) or True
    )
    assert shown == ["123456"]


def test_pairing_under_wsl_keeps_the_powershell_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pairing, "is_native_windows", lambda: False)
    seen: list[list[str]] = []

    def launcher(argv: Any) -> bool:
        seen.append(list(argv))
        return True

    assert pairing.show_code_on_windows("123456", launcher, lambda c: False)
    assert seen[0][0] == "powershell.exe"


def test_interrupt_kills_the_tree_on_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(procctl, "is_windows", lambda: True)
    run = Recorder()
    procctl.interrupt(SimpleNamespace(pid=9, poll=lambda: None), run)  # type: ignore[arg-type]
    assert run.calls == [["taskkill", "/T", "/F", "/PID", "9"]]
    assert len(procctl.stop_ladder()) == 1  # nothing gentler to try after that


# ---- group setup, native Windows mode ---------------------------------------------


class Say:
    def __init__(self) -> None:
        self.lines: list[str] = []
        self.hook_calls: list[dict[str, Any]] = []

    def hooks(self, **kw: Any) -> None:
        self.hook_calls.append(kw)

    def deps(self, claude: str | None, healthy: bool = True) -> setup.SetupDeps:
        def forbidden(*a: Any, **k: Any) -> Any:
            raise AssertionError("the native mode never downloads the widget")

        return setup.SetupDeps(
            say=self.lines.append,
            health=lambda port: healthy,
            fetch=forbidden,
            hooks=self.hooks,
            downloads=forbidden,
            attest=forbidden,
            native_windows=True,
            find_claude=lambda: claude,
        )


def test_native_setup_installs_hooks_and_never_downloads_the_widget() -> None:
    say = Say()
    setup.run_setup(setup.SetupOptions(write=True), say.deps("C:/bin/claude.exe"))
    text = "\n".join(say.lines)
    assert say.hook_calls and say.hook_calls[0]["write"] is True
    assert "Mode Windows natif" in text and "C:/bin/claude.exe" in text
    assert "installé séparément" in text and "ouvre l'application Omnigroup" in text
    assert "WSL" not in text.replace("sans WSL", "") and "systemd" not in text


def test_native_setup_says_when_claude_is_missing() -> None:
    say = Say()
    setup.run_setup(setup.SetupOptions(), say.deps(None, healthy=False))
    text = "\n".join(say.lines)
    assert "claude introuvable" in text and "install.ps1" in text
    assert "omniscient group serve" in text and "systemd" not in text
    assert "Aperçu seulement" in text


# ---- the real ACL (Windows only) ----------------------------------------------------


@pytest.mark.skipif(sys.platform != "win32", reason="icacls exists on Windows only")
def test_restrict_to_current_user_leaves_only_this_account(tmp_path: Path) -> None:
    folder = tmp_path / "state"
    folder.mkdir()
    secret = folder / "group.token"
    secret.write_text("x" * 40, encoding="utf-8")
    assert cred.restrict_to_current_user(folder, is_dir=True)
    assert cred.restrict_to_current_user(secret, is_dir=False)
    for target in (folder, secret):
        listing = subprocess.run(
            ["icacls", str(target)], capture_output=True, text=True, check=True
        ).stdout
        user = cred.current_account().split("\\")[-1].lower()
        assert user in listing.lower()
        assert "(I)" not in listing  # nothing inherited
        # administrators and SYSTEM may remain (they can take ownership anyway); other
        # people and groups must not be able to read the secret
        for broad in ("Everyone", "BUILTIN\\Users", "Authenticated Users"):
            assert broad not in listing
    assert secret.read_text(encoding="utf-8") == "x" * 40  # still ours to read
    (folder / "new.json").write_text("{}", encoding="utf-8")  # and to write


@pytest.mark.skipif(sys.platform != "win32", reason="taskkill exists on Windows only")
def test_a_real_process_tree_is_killed_by_taskkill() -> None:
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        **procctl.spawn_kwargs(),
    )
    procctl.kill(proc)
    assert proc.wait(15) != 0
