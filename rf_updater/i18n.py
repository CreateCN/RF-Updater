"""Runtime language selection backed by JSON catalogs; standard library only.

The engine and CLI must work without Qt, so translation lives here rather than
in QTranslator. Qt's own standard dialogs are translated separately by loading
the bundled qtbase_*.qm files in the GUI layer.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

LOCALES = ("zh-CN", "zh-TW", "en")
SOURCE = "zh-CN"

_current = SOURCE
_catalogs: dict[str, dict] = {}
_loaded = False


def _read_catalog(locale: str) -> str:
    name = f"{locale}.json"
    try:
        from importlib import resources
        return resources.files("rf_updater").joinpath("locales", name).read_text(encoding="utf-8")
    except (OSError, ValueError, ModuleNotFoundError, TypeError):
        return (Path(__file__).resolve().parent / "locales" / name).read_text(encoding="utf-8")


def _load() -> None:
    global _loaded
    if _loaded:
        return
    for locale in LOCALES:
        try:
            data = json.loads(_read_catalog(locale))
            _catalogs[locale] = data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            _catalogs[locale] = {}
    _loaded = True


def reload() -> None:
    """Drop cached catalogs (used by tests and after catalog edits)."""
    global _loaded
    _catalogs.clear()
    _loaded = False


def use(locale: str) -> str:
    global _current
    _current = locale if locale in LOCALES else SOURCE
    return _current


def current() -> str:
    return _current


def available() -> tuple[str, ...]:
    return LOCALES


def match_name(name: str) -> str:
    """Map a machine locale identifier (QLocale.name() or env var) to a catalog."""
    tag = (name or "").replace("-", "_").lower()
    parts = tag.split("_")
    if parts[0] == "zh":
        if any(part in {"tw", "hk", "mo", "hant"} for part in parts[1:]):
            return "zh-TW"
        return "zh-CN"
    return "en"


def from_environment() -> str:
    """CLI detection: explicit override first, then the usual locale variables."""
    for variable in ("RF_UPDATER_LANG", "LC_ALL", "LC_MESSAGES", "LANG"):
        value = os.environ.get(variable, "").strip()
        if value:
            return match_name(value.split(".")[0].split("@")[0])
    return SOURCE


def t(key: str, **params) -> str:
    """Translate a key in the active language, falling back to the source language.

    Plural values are objects {"one": ..., "other": ...} selected by `count`.
    A missing key returns the key itself so gaps are visible but never fatal.
    """
    _load()
    for locale in dict.fromkeys((_current, SOURCE)):
        value = _catalogs.get(locale, {}).get(key)
        if value is None:
            continue
        if isinstance(value, dict):
            form = "one" if params.get("count") == 1 else "other"
            value = value.get(form) or value.get("other") or value.get("one")
        if not isinstance(value, str):
            continue
        try:
            return value.format(**params)
        except (KeyError, IndexError, ValueError):
            return value
    return key
