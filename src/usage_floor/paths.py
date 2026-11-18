"""Where Usage Floor keeps its files and where it finds T3 Code.

Every location can be overridden with an environment variable, so the tool works with a default
T3 Code install as well as with a relocated one.

| Variable              | Default                                                        |
| --------------------- | -------------------------------------------------------------- |
| `USAGE_FLOOR_HOME`    | `%LOCALAPPDATA%\\usage-floor` (Windows), `~/.local/state/usage-floor` |
| `USAGE_FLOOR_T3_HOME` | `T3CODE_HOME`, else `~/.t3`                                    |
| `USAGE_FLOOR_T3_CLI`  | `T3CODE_CLI_PATH`, else `t3` on `PATH`, else `<t3 home>/bin/t3` |
"""

from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path


def _default_home() -> Path:
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "usage-floor"
    return Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state") / "usage-floor"


def _find_cli(t3_home: Path) -> str:
    explicit = os.environ.get("USAGE_FLOOR_T3_CLI") or os.environ.get("T3CODE_CLI_PATH")
    if explicit:
        return explicit
    on_path = shutil.which("t3")
    if on_path:
        return on_path
    for name in ("t3.exe", "t3.cmd", "t3"):
        candidate = t3_home / "bin" / name
        if candidate.exists():
            return str(candidate)
    return "t3"


@dataclass(frozen=True)
class Paths:
    """Resolved locations for one Usage Floor installation."""

    home: Path
    t3_home: Path
    t3_cli: str

    @property
    def config(self) -> Path:
        return self.home / "config.json"

    @property
    def state(self) -> Path:
        return self.home / "state.json"

    @property
    def events(self) -> Path:
        return self.home / "events.jsonl"

    @property
    def lock(self) -> Path:
        return self.home / "supervisor.lock"

    @property
    def t3_state_db(self) -> Path:
        return self.t3_home / "userdata" / "statev2.sqlite"

    @property
    def t3_runtime(self) -> Path:
        return self.t3_home / "userdata" / "server-runtime.json"


def resolve() -> Paths:
    t3_home = Path(os.environ.get("USAGE_FLOOR_T3_HOME") or os.environ.get("T3CODE_HOME") or Path.home() / ".t3")
    home = Path(os.environ.get("USAGE_FLOOR_HOME") or _default_home())
    return Paths(home=home, t3_home=t3_home, t3_cli=_find_cli(t3_home))
