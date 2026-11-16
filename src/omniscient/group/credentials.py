"""omnigroup credentials: the hook token file, widget tokens (hashes only) and file modes.

Two credentials, two powers (see docs/omnigroup.md, « Modèle de menace »):
- the **hook credential** (`<home>/.omniscient/group.token`, 0600) lets the agents' hook
  post events and wait for the pending its own call opened (with a wait ticket);
- a **widget token** answers, prompts and reads everything. It is minted by pairing,
  returned once, and only its SHA-256 is kept (table `widget_tokens` of group.db).

Files: the state folder is 0700, the token file and group.db (with its -wal/-shm/-journal
companions) 0600. The token file is written atomically (mkstemp in the folder + replace).
"""

from __future__ import annotations

import getpass
import hashlib
import hmac
import logging
import os
import re
import secrets
import sqlite3
import stat
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from omniscient.group.models import iso, utcnow
from omniscient.home import Home

log = logging.getLogger(__name__)

TOKEN_FILE = "group.token"
DB_FILE = "group.db"
TOKEN_MIN_LEN = 32
DIR_MODE = 0o700
FILE_MODE = 0o600
DB_COMPANIONS = ("-wal", "-shm", "-journal")
MAX_WIDGETS = 8  # pairing more widgets forgets the oldest
NONCE = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
_SCHEMA = """
CREATE TABLE IF NOT EXISTS widget_tokens (
    hash TEXT PRIMARY KEY, client_name TEXT NOT NULL, created_at TEXT NOT NULL);
"""


# ---- modes ----------------------------------------------------------------------------

ICACLS_TIMEOUT_S = 15.0
REPLACE_TRIES = 6
REPLACE_PAUSE_S = 0.05
# characters icacls would read as syntax in an account name
_ACCOUNT_OK = re.compile(
    r"^[^\x00-\x1f\"/\\\[\]:;|=,+*?<>()]+(\\[^\x00-\x1f\"/\\\[\]:;|=,+*?<>()]+)?$"
)
Runner = Callable[..., Any]


def _on_windows() -> bool:
    return sys.platform == "win32"


def current_account(environ: dict[str, str] | None = None) -> str:
    """`DOMAIN\\user` (or just `user`) of the person running this process."""
    env = os.environ if environ is None else environ
    try:
        user = getpass.getuser()
    except (KeyError, OSError):
        user = env.get("USERNAME", "")
    domain = env.get("USERDOMAIN", "")
    account = f"{domain}\\{user}" if domain and user else user
    if not account or not _ACCOUNT_OK.match(account):
        raise ValueError("compte Windows courant introuvable ou inattendu")
    return account


def icacls_argv(path: Path, account: str, is_dir: bool) -> list[str]:
    """The icacls call that leaves only `account` with access to `path`."""
    grant = f"{account}:(OI)(CI)(F)" if is_dir else f"{account}:(F)"
    return ["icacls", str(path), "/inheritance:r", "/grant:r", grant]


def restrict_to_current_user(
    path: Path,
    is_dir: bool | None = None,
    runner: Runner = subprocess.run,
    windows: bool | None = None,
    account: str | None = None,
) -> bool:
    """Make `path` private to the current user. POSIX: chmod 0700 (dir) / 0600 (file).
    Windows: icacls (no inheritance, only this account), best effort: a failure is logged
    and returns False, never raises. A missing path is fine (True)."""
    try:
        directory = path.is_dir() if is_dir is None else is_dir
    except OSError:
        return False
    if not (_on_windows() if windows is None else windows):
        mode = DIR_MODE if directory else FILE_MODE
        try:
            if stat.S_IMODE(path.stat().st_mode) != mode:
                path.chmod(mode)
        except FileNotFoundError:
            return True
        return True
    try:
        argv = icacls_argv(path, account or current_account(), directory)
        done = runner(
            argv, stdin=subprocess.DEVNULL, capture_output=True, text=True,
            timeout=ICACLS_TIMEOUT_S, check=False,
        )  # fmt: skip
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        log.warning("omnigroup: cannot restrict %s to the current user: %s", path, exc)
        return False
    if done.returncode != 0:
        log.warning("omnigroup: icacls failed on %s (code %s)", path, done.returncode)
        return False
    return True


def secure_dir(path: Path) -> Path:
    """Create `path` (and parents) and make it private to the user (0700 / ACL)."""
    path.mkdir(parents=True, exist_ok=True, mode=DIR_MODE)
    restrict_to_current_user(path, is_dir=True)
    return path


def secure_file(path: Path) -> None:
    """Make an existing file private to the user (a missing one is fine)."""
    restrict_to_current_user(path, is_dir=False)


def replace_file(src: str | Path, dst: str | Path) -> None:
    """os.replace, retried briefly: on Windows it fails while a reader holds `dst` open."""
    for attempt in range(REPLACE_TRIES):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if not _on_windows() or attempt == REPLACE_TRIES - 1:
                raise
            time.sleep(REPLACE_PAUSE_S * (attempt + 1))


def secure_db_files(db: Path) -> None:
    """Pre-create the database 0600 (SQLite gives its journals the same mode) and
    tighten any companion file left by an older run."""
    if str(db) == ":memory:":
        return
    secure_dir(db.parent)
    fd = os.open(db, os.O_RDWR | os.O_CREAT, FILE_MODE)
    os.close(fd)
    for suffix in ("", *DB_COMPANIONS):
        secure_file(db.with_name(db.name + suffix))


# ---- hook credential --------------------------------------------------------------------


def hook_token_path(home: Home) -> Path:
    return home.state / TOKEN_FILE


def db_path(home: Home) -> Path:
    return home.state / DB_FILE


def read_hook_token(home: Home) -> str | None:
    """The hook token, or None when the daemon never ran in this home."""
    try:
        token = hook_token_path(home).read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None
    return token or None


def write_atomic(path: Path, text: str) -> None:
    """Write `text` to `path` through a 0600 temp file in the same folder, then replace."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        replace_file(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def load_or_create_hook_token(home: Home) -> str:
    """The hook token (created 0600 on first use); refuses a short or empty file."""
    path = hook_token_path(home)
    secure_dir(path.parent)
    token = read_hook_token(home)
    if token is None and not path.exists():
        write_atomic(path, secrets.token_urlsafe(32) + "\n")
        token = read_hook_token(home)
    if not _on_windows():
        mode = stat.S_IMODE(path.stat().st_mode)
        if mode != FILE_MODE:
            log.warning("omnigroup: token file was mode %o, tightening to 600", mode)
    restrict_to_current_user(path, is_dir=False)
    if token is None or len(token) < TOKEN_MIN_LEN:
        raise RuntimeError(f"jeton omnigroup invalide : supprime {path} et relance")
    return token


def same_secret(given: str, expected: str) -> bool:
    return hmac.compare_digest(given.encode(), expected.encode())


# ---- widget tokens -----------------------------------------------------------------------


def token_hash(token: str) -> str:
    """SHA-256 of a token, hex (what group.db keeps)."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def proof(stored_hash: str, nonce: str) -> str:
    """HMAC-SHA256(key = the raw token hash, message = nonce), hex: the daemon proves it
    knows the widget's token hash without the widget sending its token."""
    key = bytes.fromhex(stored_hash)
    return hmac.new(key, nonce.encode("utf-8"), hashlib.sha256).hexdigest()


class WidgetTokens:
    """Widget token hashes in group.db (its own connection; thread-safe)."""

    def __init__(self, path: Path | str) -> None:
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._lock = threading.Lock()
        with self._lock:
            self._db.executescript(_SCHEMA)
            self._db.commit()

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def mint(self, client_name: str, now: datetime | None = None) -> str:
        """A new widget token: its hash is stored, the plaintext is returned once."""
        token = secrets.token_urlsafe(32)
        stamp = iso(now or utcnow())
        with self._lock:
            self._db.execute(
                "INSERT INTO widget_tokens (hash, client_name, created_at) "
                "VALUES (?, ?, ?)",
                (token_hash(token), client_name, stamp),
            )
            self._db.execute(
                "DELETE FROM widget_tokens WHERE hash NOT IN (SELECT hash FROM "
                "widget_tokens ORDER BY rowid DESC LIMIT ?)",
                (MAX_WIDGETS,),
            )
            self._db.commit()
        return token

    def is_valid(self, token: str) -> bool:
        if not token:
            return False
        with self._lock:
            row = self._db.execute(
                "SELECT 1 FROM widget_tokens WHERE hash = ?", (token_hash(token),)
            ).fetchone()
        return row is not None

    def hashes(self) -> list[str]:
        with self._lock:
            rows = self._db.execute(
                "SELECT hash FROM widget_tokens ORDER BY rowid DESC"
            ).fetchall()
        return [r[0] for r in rows]

    def revoke_all(self) -> int:
        """Forget every widget token; returns how many were dropped."""
        with self._lock:
            count = self._db.execute("DELETE FROM widget_tokens").rowcount
            self._db.commit()
        return count

    def proofs(self, nonce: str) -> list[str]:
        """One proof per paired widget for GET /health?nonce=…"""
        return [proof(h, nonce) for h in self.hashes()]
