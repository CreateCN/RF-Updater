from __future__ import annotations

import hashlib
import json
import os
import platform
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from .i18n import t


class UpdaterError(Exception):
    """An actionable failure that can be shown to the user."""


class Cancelled(UpdaterError):
    pass


class NetworkInterrupted(UpdaterError):
    """A transient transport failure; the partial download stays resumable."""


PLATFORMS = {
    "windows": ("Windows x64", "https://api.rocketfoundry.net/download/windows", ".zip"),
    "macos": ("macOS Apple Silicon", "https://api.rocketfoundry.net/download/macos", ".zip"),
    "linux": ("Linux x64", "https://api.rocketfoundry.net/download/linux", ".tar.gz"),
}


def native_platform() -> str:
    machine = platform.machine().lower()
    if sys.platform == "win32" and machine in {"amd64", "x86_64"}:
        return "windows"
    if sys.platform == "darwin" and machine in {"arm64", "aarch64"}:
        return "macos"
    if sys.platform.startswith("linux") and machine in {"amd64", "x86_64"}:
        return "linux"
    raise UpdaterError(t("engine.unsupported_platform"))


def default_root() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library/Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
    return base / "RF-Updater"


@dataclass(frozen=True)
class Release:
    platform: str
    url: str
    size: int | None = None
    etag: str | None = None
    modified: str | None = None
    sha256: str | None = None

    @property
    def comparable(self) -> bool:
        return bool(self.etag or self.modified or self.sha256)

    @property
    def identity(self) -> str:
        # Stable across CDN redirects and expiring signed URLs.
        evidence = self.sha256 or self.etag or self.modified or "unknown"
        raw = json.dumps([self.platform, self.url, evidence, self.size])
        return hashlib.sha256(raw.encode()).hexdigest()[:20]

    @property
    def label(self) -> str:
        return self.modified or t("gui.build_id", id=self.identity[:8])

    def to_dict(self) -> dict:
        return asdict(self)


def read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default
    except (OSError, ValueError) as exc:
        raise UpdaterError(t("engine.read_json_failed", name=path.name, error=exc)) from exc


def atomic_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    with temp.open("w", encoding="utf-8") as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)
