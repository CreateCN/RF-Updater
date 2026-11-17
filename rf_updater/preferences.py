"""Per-user directory choices, independent of the selected game data directory."""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

from .i18n import t
from .models import UpdaterError, default_root, read_json


def preferences_path() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library/Preferences"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "RF-Updater" / "directories.json"


def load() -> dict:
    value = read_json(preferences_path(), {"schema": 1, "root": None, "recent_roots": []})
    if (not isinstance(value, dict) or value.get("schema") != 1 or "root" not in value
            or not isinstance(value.get("recent_roots"), list)):
        raise UpdaterError(t("prefs.corrupt"))
    paths = value["recent_roots"]
    root = value["root"]
    if ((root is not None and (not isinstance(root, str) or not Path(root).is_absolute()))
            or any(not isinstance(path, str) or not Path(path).is_absolute() for path in paths)):
        raise UpdaterError(t("prefs.invalid_paths"))
    return value


def saved_root() -> Path | None:
    value = load()["root"]
    return Path(value) if value else None


def choices(current: Path) -> list[Path]:
    try:
        data = load()
        paths = [current, *map(Path, data["recent_roots"]), default_root()]
    except UpdaterError:
        paths = [current, default_root()]
    return list(dict.fromkeys(path.expanduser().resolve() for path in paths))


DEFAULT_SETTINGS = {"schema": 1, "periodic_check": True, "check_interval_hours": 4, "notifications": True, "language": None}


def settings_path() -> Path:
    return preferences_path().with_name("settings.json")


def load_settings() -> dict:
    """Tolerant reader: a damaged settings file falls back to defaults, never blocks the GUI."""
    try:
        value = read_json(settings_path(), dict(DEFAULT_SETTINGS))
    except UpdaterError:
        return dict(DEFAULT_SETTINGS)
    if not isinstance(value, dict) or value.get("schema") != 1:
        return dict(DEFAULT_SETTINGS)
    result = dict(DEFAULT_SETTINGS)
    for key in ("periodic_check", "notifications"):
        if isinstance(value.get(key), bool):
            result[key] = value[key]
    hours = value.get("check_interval_hours")
    if isinstance(hours, int) and 1 <= hours <= 24:
        result["check_interval_hours"] = hours
    if value.get("language") in (None, "zh-CN", "zh-TW", "en"):
        result["language"] = value["language"]
    return result


def save_settings(value: dict) -> None:
    merged = {**DEFAULT_SETTINGS, **{key: value[key] for key in DEFAULT_SETTINGS if key in value}}
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix="settings-", delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(merged, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.chmod(0o600)
        os.replace(temporary, path)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


def remember_root(root: Path, previous: Path) -> None:
    path = preferences_path()
    try:
        recent = load()["recent_roots"]
    except UpdaterError:
        # An explicit directory selection repairs only the directory preference,
        # never a game's installation record or files.
        recent = []
    roots = list(dict.fromkeys([str(root), str(previous), *recent]))[:12]
    value = {"schema": 1, "root": str(root), "recent_roots": roots}
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix="directories-", delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.chmod(0o600)
        os.replace(temporary, path)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)
