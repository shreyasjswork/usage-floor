"""Settings, supervisor state and the event log, all plain JSON on disk."""

from __future__ import annotations

import copy
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_CONFIG: dict[str, Any] = {
    "version": 1,
    "enabled": True,
    "graceMinutes": 10,
    "resumeOnLift": True,
    "plans": {},
}
DEFAULT_STATE: dict[str, Any] = {"blocked": {}, "threads": {}}
EVENT_LOG_LIMIT = 2_000_000


def iso(timestamp: float | None = None) -> str:
    moment = time.time() if timestamp is None else timestamp
    return datetime.fromtimestamp(moment, UTC).isoformat(timespec="seconds")


def load(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    """Read a JSON object, filling missing keys from `default`. A missing or broken file yields the default."""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return copy.deepcopy(default)
    if not isinstance(value, dict):
        return copy.deepcopy(default)
    return {**copy.deepcopy(default), **value}


def save(path: Path, value: dict[str, Any]) -> None:
    """Write atomically, so a crash never leaves half a settings file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".next")
    temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def log(path: Path, event: str, **details: Any) -> None:
    """Append one JSON line; rotate once the log passes 2 MB."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.stat().st_size > EVENT_LOG_LIMIT:
        path.replace(path.with_suffix(".previous.jsonl"))
    with path.open("a", encoding="utf-8") as out:
        out.write(json.dumps({"time": iso(), "event": event, **details}) + "\n")
