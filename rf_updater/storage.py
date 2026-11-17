"""Bounded, link-safe inventory and explicitly selected cleanup of managed data."""
from __future__ import annotations

import os
import re
import shutil
import stat
import tempfile
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import logbook
from .engine import Engine, exclusive
from .i18n import t
from .models import PLATFORMS, Cancelled, Release, UpdaterError, default_root, read_json
from .network import no_progress
from .preferences import remember_root

GENERATION = re.compile(r"[0-9a-f]{20}-[0-9a-f]{8}\Z")
CACHE = re.compile(r"([0-9a-f]{20})\.(?:part|json)\Z")
MAX_SCAN_ENTRIES = 250_000
MAX_LIST_ITEMS = 2_000


def is_link(path: Path) -> bool:
    info = path.lstat()
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & 0x400)


@dataclass(frozen=True)
class StorageItem:
    key: str
    name: str
    kind: str
    status: str
    size: int
    path: Path
    deletable: bool = False
    complete: bool = True


@dataclass
class Inventory:
    root: Path
    items: list[StorageItem] = field(default_factory=list)
    disk_free: int = 0
    disk_total: int = 0
    warnings: list[str] = field(default_factory=list)
    root_exists: bool = True

    @property
    def totals(self) -> dict[str, int]:
        result = {key: 0 for key in ("cache", "active", "previous", "old", "other")}
        for item in self.items:
            category = item.kind if item.kind in result else "other"
            result[category] += item.size
        return result


def _size(path: Path, cancel: threading.Event, budget: list[int]) -> tuple[int, bool]:
    total, complete = 0, True
    pending = [path]
    while pending:
        if cancel.is_set():
            raise Cancelled(t("storage.scan_cancelled"))
        node = pending.pop()
        budget[0] += 1
        if budget[0] > MAX_SCAN_ENTRIES:
            raise UpdaterError(t("storage.scan_limit"))
        try:
            info = node.lstat()
            if is_link(node):
                total += info.st_size  # Never traverse a link or Windows junction.
            elif stat.S_ISDIR(info.st_mode):
                with os.scandir(node) as entries:
                    for entry in entries:
                        pending.append(Path(entry.path))
                        if len(pending) + budget[0] > MAX_SCAN_ENTRIES:
                            raise UpdaterError(t("storage.scan_limit_short"))
            elif stat.S_ISREG(info.st_mode):
                total += info.st_size
        except OSError:
            complete = False
    return total, complete


def _managed_container(root: Path, name: str) -> Path | None:
    path = root / name
    if path.exists() or path.is_symlink():
        if is_link(path) or not path.is_dir():
            raise UpdaterError(t("storage.not_directory", name=name))
        if not path.resolve().is_relative_to(root):
            raise UpdaterError(t("storage.outside"))
        return path
    return None


def _cache_release(path: Path, identity: str) -> Release | None:
    try:
        if is_link(path) or not path.is_file() or path.stat().st_size > 64 * 1024:
            return None
        release = Release(**read_json(path))
        if (release.platform not in PLATFORMS or not isinstance(release.url, str)
                or release.size is not None and (not isinstance(release.size, int) or release.size <= 0)):
            return None
        return release if release.identity == identity else None
    except (OSError, UpdaterError, TypeError, ValueError):
        return None


def _installation(engine: Engine, path: Path) -> dict | None:
    try:
        receipt_path = path / "receipt.json"
        if is_link(receipt_path) or not receipt_path.is_file() or receipt_path.stat().st_size > 32 * 1024**2:
            return None
        receipt = read_json(receipt_path)
        installation = receipt["installation"]
        if (installation["generation"] != path.name or not isinstance(receipt["files"], list)
                or not isinstance(installation.get("installed_at"), str)):
            return None
        release = Release(**installation["release"])
        if release.platform not in PLATFORMS or release.identity != path.name.rsplit("-", 1)[0]:
            return None
        return installation
    except (OSError, UpdaterError, KeyError, TypeError, ValueError):
        return None


def scan(engine: Engine, cancel: threading.Event, progress=no_progress) -> Inventory:
    if cancel.is_set():
        raise Cancelled(t("storage.scan_cancelled"))
    root = engine.root
    state = engine.state()
    result = Inventory(root, root_exists=root.is_dir())
    ancestor = root
    while not ancestor.exists() and ancestor.parent != ancestor:
        ancestor = ancestor.parent
    usage = shutil.disk_usage(ancestor)
    result.disk_free, result.disk_total = usage.free, usage.total
    budget = [0]
    protected = {item["generation"]: key for key in ("active", "previous") if (item := state.get(key))}
    for group in ("cache", "installs"):
        try:
            container = _managed_container(root, group)
        except (OSError, UpdaterError) as exc:
            result.warnings.append(str(exc))
            continue
        if not container:
            continue
        seen = set()
        with os.scandir(container) as entries:
            for entry in entries:
                if cancel.is_set():
                    raise Cancelled(t("storage.scan_cancelled"))
                path = Path(entry.path)
                if path.name in seen:
                    continue
                if len(result.items) >= MAX_LIST_ITEMS:
                    raise UpdaterError(t("storage.list_limit"))
                size, complete = _size(path, cancel, budget)
                linked = is_link(path)
                if group == "cache":
                    match = CACHE.fullmatch(path.name)
                    release = _cache_release(container / f"{match[1]}.json", match[1]) if match and not linked else None
                    if release:
                        identity = match[1]
                        pair = [container / f"{identity}.part", container / f"{identity}.json"]
                        members = [member for member in pair if member.exists() or member.is_symlink()]
                        safe = all(not is_link(member) and member.is_file() for member in members)
                        if safe:
                            for member in members:
                                if member != path:
                                    value, ok = _size(member, cancel, budget)
                                    size, complete = size + value, complete and ok
                            seen.update(member.name for member in members)
                            part = container / f"{identity}.part"
                            downloaded = part.stat().st_size if part.exists() else 0
                            status = (t("storage.status.record_only") if not part.exists() else t("storage.status.downloaded") if release.size == downloaded
                                      else t("storage.status.partial") if release.size is None or downloaded < release.size else t("storage.status.size_anomaly"))
                            result.items.append(StorageItem(f"cache/{identity}", f"{PLATFORMS[release.platform][0]} · {identity[:8]}", "cache", status, size, part if part.exists() else pair[1], complete, complete))
                            continue
                if group == "installs" and not linked and path.is_dir() and GENERATION.fullmatch(path.name):
                    installation = _installation(engine, path)
                    kind = protected.get(path.name, "old")
                    if kind in {"active", "previous"} or installation:
                        status = {"active": t("storage.status.active"), "previous": t("storage.status.previous"), "old": t("storage.status.old")}[kind]
                        try:
                            date = datetime.fromisoformat(installation["installed_at"]).astimezone().strftime("%Y-%m-%d %H:%M")
                            name = f"{date} · {path.name[-8:]}"
                        except (TypeError, KeyError, ValueError):
                            name = path.name
                        result.items.append(StorageItem(f"installs/{path.name}", name, kind, status, size, path, kind == "old" and complete, complete))
                        continue
                result.items.append(StorageItem(f"{group}/{path.name}", path.name, "other", t("storage.status.other"), size, path, False, complete))
                if not complete:
                    result.warnings.append(t("storage.warning_incomplete", name=path.name))
                progress("storage_scan", budget[0], None)
    if any(not item.complete for item in result.items):
        result.warnings.append(t("storage.warning_partial"))
    return result


@dataclass
class CleanupResult:
    removed: int
    estimated_bytes: int
    errors: list[str]
    inventory: Inventory


def cleanup(engine: Engine, keys: list[str], *, allow_old=False) -> CleanupResult:
    if not keys:
        raise UpdaterError(t("storage.no_selection"))
    engine.state()
    with exclusive(engine.root):
        inventory = scan(engine, threading.Event())
        entries = {item.key: item for item in inventory.items}
        running = engine.game_running()
        selected = []
        for key in dict.fromkeys(keys):
            item = entries.get(key)
            if not item or not item.deletable or item.kind not in {"cache", "old"}:
                raise UpdaterError(t("storage.selection_changed"))
            if item.kind == "old" and running:
                raise UpdaterError(t("storage.game_running"))
            if item.kind == "old" and not allow_old:
                raise UpdaterError(t("storage.backup_required"))
            selected.append(item)
        removed, size, errors = 0, 0, []
        # Validation of the entire selection precedes any deletion. The root lock
        # prevents a cooperative installer changing active/previous during cleanup.
        for item in selected:
            try:
                if item.kind == "cache":
                    directory = _managed_container(engine.root, "cache")
                    identity = item.key.split("/")[1]
                    for suffix in ("part", "json"):
                        path = directory / f"{identity}.{suffix}"
                        if path.exists() or path.is_symlink():
                            if is_link(path) or not path.is_file():
                                raise UpdaterError(t("storage.cache_changed"))
                            path.unlink()
                else:
                    directory = _managed_container(engine.root, "installs")
                    path = directory / item.path.name
                    if is_link(path) or not path.resolve().is_relative_to(directory):
                        raise UpdaterError(t("storage.install_changed"))
                    shutil.rmtree(path)
                removed += 1
                size += item.size
            except (OSError, UpdaterError) as exc:
                errors.append(f"{item.name}：{exc}")
        logbook.record(engine.root, "cleanup", removed=removed, bytes=size, errors=errors)
        return CleanupResult(removed, size, errors, scan(engine, threading.Event()))


def switch_directory(engine: Engine, destination: Path) -> Engine:
    root = destination.expanduser().resolve()
    if root != engine.root and (root.is_relative_to(engine.root) or engine.root.is_relative_to(root)):
        raise UpdaterError(t("storage.nested"))
    if not root.exists() and root == default_root().expanduser().resolve():
        root.mkdir(parents=True, exist_ok=True)
    if not root.is_dir():
        raise UpdaterError(t("storage.target_missing"))
    candidate = Engine(root, engine.target, engine.network)
    # Leaving a directory does not modify it and must remain possible when its
    # disk is disconnected or read-only. Only the destination needs a write lock.
    with exclusive(root):
        state = candidate.state()
        try:
            for item in (state.get("active"), state.get("previous")):
                if not item:
                    continue
                release = Release(**item["release"])
                if (release.platform not in PLATFORMS or not isinstance(release.url, str)
                        or any(value is not None and not isinstance(value, str)
                               for value in (release.etag, release.modified, release.sha256))
                        or not isinstance(item.get("installed_at"), str)
                        or not isinstance(item.get("package_sha256"), str)
                        or not re.fullmatch(r"[0-9a-f]{64}", item["package_sha256"])):
                    raise ValueError("invalid installation record fields")
                datetime.fromisoformat(item["installed_at"])
                candidate.network.validate_url(release.url)
        except (KeyError, TypeError, ValueError) as exc:
            raise UpdaterError(t("storage.target_state")) from exc
        for name in ("cache", "installs"):
            _managed_container(root, name)
        with tempfile.TemporaryFile(dir=root):
            pass
        remember_root(root, engine.root)
    logbook.record(root, "directory_switch", source=str(engine.root))
    candidate.root_must_exist = True
    return candidate
