"""Windows facts for `omniscient group doctor`, read through language-independent APIs.

Never the text of a localized tool (systeminfo, netstat, schtasks, winget): kernel32 calls
and the registry answer the same on every display language. Each reader returns None when
the fact is not available; the checks turn that into an INFO line, never a crash. Importing
this module is safe on Linux (the Windows-only modules are imported inside the readers).
"""

from __future__ import annotations

import platform
import re
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from omniscient.group.update import widget_exe

WEBVIEW2_GUID = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"  # Evergreen WebView2 Runtime
WIDGET_NAME = "Omniscient"
WINDOWS_11_BUILD = 22000
MACHINES = {0x8664: "x64", 0xAA64: "ARM64", 0x14C: "x86"}
LOCALE_NAME_CHARS = 85
MAX_UNINSTALL_ENTRIES = 5000
Runner = Callable[[Sequence[str]], tuple[int, str]]


@dataclass(frozen=True)
class WinFacts:
    """What the Windows checks read; tests inject fakes, `real_facts()` the real thing."""

    os_label: Callable[[], str | None] = lambda: None
    architecture: Callable[[], str | None] = lambda: None
    windows_build: Callable[[], int | None] = lambda: None
    ui_language: Callable[[], str | None] = lambda: None
    ansi_codepage: Callable[[], int | None] = lambda: None
    oem_codepage: Callable[[], int | None] = lambda: None
    powershell_version: Callable[[], str | None] = lambda: None
    webview2_version: Callable[[], str | None] = lambda: None
    widget_version: Callable[[], str | None] = lambda: None
    widget_path: Callable[[], Path | None] = lambda: None
    extras: dict[str, str] = field(default_factory=dict)


def windows_build() -> int | None:
    if sys.platform != "win32":
        return None
    return int(sys.getwindowsversion().build)


def os_label() -> str | None:
    build = windows_build()
    if build is None:
        return None
    name = "Windows 11" if build >= WINDOWS_11_BUILD else "Windows 10"
    edition = platform.win32_edition() or "?"
    return f"{name} (build {build}, édition {edition})"


def architecture() -> str | None:
    """The real CPU family, even for an x64 Python emulated on ARM64 (IsWow64Process2)."""
    if sys.platform != "win32":
        return None
    import ctypes

    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined,unused-ignore]
    try:
        kernel32.GetCurrentProcess.restype = ctypes.c_void_p
        func = kernel32.IsWow64Process2
        func.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_ushort),
            ctypes.POINTER(ctypes.c_ushort),
        ]
        process, native = ctypes.c_ushort(), ctypes.c_ushort()
        if func(
            kernel32.GetCurrentProcess(), ctypes.byref(process), ctypes.byref(native)
        ):
            return MACHINES.get(native.value)
    except (AttributeError, OSError):
        pass  # Windows before 1709: fall back to what Python says
    return {"AMD64": "x64", "ARM64": "ARM64", "x86": "x86"}.get(platform.machine())


def ui_language() -> str | None:
    """Display language as a locale name (fr-FR, en-US), from GetUserDefaultUILanguage."""
    if sys.platform != "win32":
        return None
    import ctypes

    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined,unused-ignore]
    buf = ctypes.create_unicode_buffer(LOCALE_NAME_CHARS)
    langid = kernel32.GetUserDefaultUILanguage()
    return (
        buf.value
        if kernel32.LCIDToLocaleName(langid, buf, LOCALE_NAME_CHARS, 0)
        else None
    )


def _codepage(name: str) -> int | None:
    if sys.platform != "win32":
        return None
    import ctypes

    return int(getattr(ctypes.windll.kernel32, name)())  # type: ignore[attr-defined,unused-ignore]


def ansi_codepage() -> int | None:
    return _codepage("GetACP")


def oem_codepage() -> int | None:
    return _codepage("GetOEMCP")


def webview2_version() -> str | None:
    """The Evergreen runtime's `pv` (0.0.0.0 means removed), machine or user, any view."""
    if sys.platform != "win32":
        return None
    import winreg

    base = r"Microsoft\EdgeUpdate\Clients" + "\\" + WEBVIEW2_GUID
    places = (
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node" + "\\" + base),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE" + "\\" + base),
        (winreg.HKEY_CURRENT_USER, r"Software" + "\\" + base),
    )
    for hive, path in places:
        try:
            with winreg.OpenKey(hive, path) as key:
                found = str(winreg.QueryValueEx(key, "pv")[0])
        except OSError:
            continue
        if found and found != "0.0.0.0":
            return found
    return None


def widget_version() -> str | None:
    """DisplayVersion of the Omniscient uninstall entry (per-user or machine-wide)."""
    if sys.platform != "win32":
        return None
    import winreg

    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for view in (0, winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            found = _uninstall_entry(hive, view)
            if found:
                return found
    return None


def _entry_version(winreg_key: object, name: str) -> str | None:
    """DisplayVersion of the subkey `name` when its DisplayName is the widget's."""
    import winreg

    try:
        with winreg.OpenKey(winreg_key, name) as entry:  # type: ignore[arg-type]
            if winreg.QueryValueEx(entry, "DisplayName")[0] != WIDGET_NAME:
                return None
            return str(winreg.QueryValueEx(entry, "DisplayVersion")[0])
    except OSError:
        return None  # an entry without those values, or one we may not read


def _uninstall_entry(hive: int, view: int) -> str | None:
    import winreg

    sub = r"Software\Microsoft\Windows\CurrentVersion\Uninstall"
    try:
        root = winreg.OpenKey(hive, sub, 0, winreg.KEY_READ | view)
    except OSError:
        return None
    with root:
        for index in range(MAX_UNINSTALL_ENTRIES):
            try:
                name = winreg.EnumKey(root, index)
            except OSError:
                return None  # ERROR_NO_MORE_ITEMS
            found = _entry_version(root, name)
            if found:
                return found
    return None


def powershell_version(run: Runner) -> str | None:
    """Windows PowerShell's own version number (digits only: no localized text)."""
    code, out = run(
        [
            "powershell.exe",
            "-NoProfile",
            "-Command",
            "$PSVersionTable.PSVersion.ToString()",
        ]
    )
    found = re.search(r"\d+(\.\d+)+", out) if code == 0 else None
    return found.group(0) if found else None


def real_facts(run: Runner) -> WinFacts:
    return WinFacts(
        os_label=os_label,
        architecture=architecture,
        windows_build=windows_build,
        ui_language=ui_language,
        ansi_codepage=ansi_codepage,
        oem_codepage=oem_codepage,
        powershell_version=lambda: powershell_version(run),
        webview2_version=webview2_version,
        widget_version=widget_version,
        widget_path=widget_exe,
    )
