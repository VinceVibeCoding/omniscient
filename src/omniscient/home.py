"""Where a user's Omniscient data lives (the "home"), separate from the engine code.

The engine is installable (`uv tool install ...`); each user's data (settings, secrets,
project registry, the daemon's state) lives in a home folder:

1. `$OMNISCIENT_HOME` if set;
2. else the nearest folder, from the current directory upwards, holding
   `config/omniscient.toml`;
3. else `~/.omniscient`.

Layout of a home:
    config/omniscient.toml   settings          config/profile.toml   theme, language
    .env                     secrets (600)     repos/                project registry
    .omniscient/             machine state: the daemon's database, tokens, logs
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

ENV_VAR = "OMNISCIENT_HOME"
DEFAULT_HOME = Path.home() / ".omniscient"
CONFIG_REL = Path("config") / "omniscient.toml"


@dataclass(frozen=True)
class Home:
    root: Path

    @property
    def config(self) -> Path:
        return self.root / CONFIG_REL

    @property
    def profile(self) -> Path:
        return self.root / "config" / "profile.toml"

    @property
    def env_file(self) -> Path:
        return self.root / ".env"

    @property
    def repos(self) -> Path:
        return self.root / "repos"

    @property
    def state(self) -> Path:
        return self.root / ".omniscient"

    @property
    def exists(self) -> bool:
        return self.config.is_file()


def packaged(name: str) -> Path:
    """A folder shipped inside the package (omniscient/resources/<name>)."""
    return Path(str(resources.files("omniscient") / "resources" / name))


def _search_up(start: Path) -> Path | None:
    for folder in (start, *start.parents):
        if (folder / CONFIG_REL).is_file():
            return folder
    return None


def find_home(cwd: Path | None = None, environ: dict[str, str] | None = None) -> Home:
    """Resolve the current user's home (it may not exist yet: see Home.exists)."""
    env = os.environ if environ is None else environ
    if env.get(ENV_VAR):
        return Home(Path(env[ENV_VAR]).expanduser().resolve())
    found = _search_up((cwd or Path.cwd()).resolve())
    return Home(found if found is not None else DEFAULT_HOME)
