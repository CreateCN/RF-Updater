from __future__ import annotations

import hashlib
import os
import re
import shutil
import stat
import tarfile
import threading
import zipfile
import zlib
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .i18n import t
from .models import UpdaterError
from .network import CHUNK, Progress, check_cancel, no_progress

MAX_UNPACKED = 16 * 1024**3
MAX_FILES = 100_000
RESERVED = re.compile(r"^(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)", re.I)


def safe_path(name: str) -> PurePosixPath:
    path = PurePosixPath(name)
    if (not name or "\\" in name or "\x00" in name or path.is_absolute()
            or any(p in {"..", "."} or ":" in p or p.endswith((".", " "))
                   or RESERVED.match(p) for p in path.parts)
            or not path.parts):
        raise UpdaterError(t("archive.unsafe_path", name=repr(name)))
    return path


@dataclass
class Entry:
    name: str
    kind: str
    size: int
    mode: int
    source: object
    target: str | None = None


def extract_package(package: Path, destination: Path, target: str,
                    cancel: threading.Event, progress: Progress = no_progress) -> list[dict]:
    """Extract files first and links last, with no writes through archive links."""
    archive = None
    try:
        entries = []
        if target in {"windows", "macos"}:
            archive = zipfile.ZipFile(package)
            for info in archive.infolist():
                mode = info.external_attr >> 16
                kind = "dir" if info.is_dir() else ("symlink" if stat.S_ISLNK(mode) else "file")
                if stat.S_IFMT(mode) not in {0, stat.S_IFREG, stat.S_IFDIR, stat.S_IFLNK}:
                    raise UpdaterError(t("archive.zip_special"))
                link = None
                if kind == "symlink":
                    if info.file_size > 4096:
                        raise UpdaterError(t("archive.symlink_long"))
                    link = archive.read(info).decode("utf-8")
                entries.append(Entry(info.filename, kind, info.file_size, mode, info, link))
        else:
            archive = tarfile.open(package, "r:gz")
            # Iterate with a cap rather than getmembers() on an unbounded archive.
            declared = 0
            for info in archive:
                kind = ("dir" if info.isdir() else "file" if info.isfile() else
                        "symlink" if info.issym() else "hardlink" if info.islnk() else "special")
                entries.append(Entry(info.name, kind, info.size, info.mode, info, info.linkname))
                declared += max(info.size, 0)
                if declared > MAX_UNPACKED:
                    raise UpdaterError(t("archive.max_unpacked"))
                if len(entries) > MAX_FILES:
                    raise UpdaterError(t("archive.max_files"))
            # tar stops at its zero end-marker before gzip necessarily reads its
            # trailer. Drain the bounded remainder so gzip CRC/length are checked.
            while archive.fileobj.read(CHUNK):
                check_cancel(cancel)
                if archive.fileobj.tell() > MAX_UNPACKED + MAX_FILES * 1024:
                    raise UpdaterError(t("archive.trailing"))
        if len(entries) > MAX_FILES:
            raise UpdaterError(t("archive.max_files"))
        entries = [e for e in entries if PurePosixPath(e.name).parts[:1] != ("__MACOSX",)]
        # tar commonly includes an explicit '.' root entry.
        entries = [e for e in entries if not (e.kind == "dir" and e.name in {".", "./"})]
        names: dict[str, Entry] = {}
        total = 0
        for entry in entries:
            check_cancel(cancel)
            path = safe_path(entry.name)
            key = path.as_posix()
            collision_key = key.casefold() if target in {"windows", "macos"} else key
            if collision_key in names:
                raise UpdaterError(t("archive.duplicate", path=key))
            names[collision_key] = entry
            if entry.kind == "special" or entry.size < 0:
                raise UpdaterError(t("archive.special"))
            if entry.kind == "file":
                total += entry.size
            if total > MAX_UNPACKED:
                raise UpdaterError(t("archive.max_unpacked"))
        for key, entry in names.items():
            for parent in PurePosixPath(key).parents:
                parent_entry = names.get(parent.as_posix())
                if parent_entry and parent_entry.kind != "dir":
                    raise UpdaterError(t("archive.path_through", name=entry.name))
        destination.mkdir(parents=True, exist_ok=False)
        if shutil.disk_usage(destination).free < total + 64 * 1024**2:
            raise UpdaterError(t("archive.disk_full"))
        manifest = []
        done = 0
        progress("extract", done, total)
        for entry in entries:
            check_cancel(cancel)
            path = destination / safe_path(entry.name)
            if entry.kind == "dir":
                path.mkdir(parents=True, exist_ok=True)
                continue
            if entry.kind != "file":
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            stream = archive.open(entry.source) if isinstance(archive, zipfile.ZipFile) else archive.extractfile(entry.source)
            if stream is None:
                raise UpdaterError(t("archive.read_entry", name=entry.name))
            digest = hashlib.sha256()
            written = 0
            with stream, path.open("xb") as output:
                while chunk := stream.read(CHUNK):
                    check_cancel(cancel)
                    written += len(chunk)
                    done += len(chunk)
                    if written > entry.size:
                        raise UpdaterError(t("archive.entry_oversize"))
                    output.write(chunk)
                    digest.update(chunk)
                    progress("extract", done, total)
            if written != entry.size:
                raise UpdaterError(t("archive.entry_incomplete", name=entry.name))
            path.chmod(0o755 if entry.mode & 0o111 else 0o644)
            manifest.append({"path": safe_path(entry.name).as_posix(), "size": written, "sha256": digest.hexdigest()})
        for entry in entries:
            if entry.kind not in {"symlink", "hardlink"}:
                continue
            check_cancel(cancel)
            path = destination / safe_path(entry.name)
            path.parent.mkdir(parents=True, exist_ok=True)
            if entry.kind == "hardlink":
                source = destination / safe_path(entry.target or "")
                if source.is_symlink() or not source.is_file():
                    raise UpdaterError(t("archive.bad_hardlink"))
                source_record = next((r for r in manifest if r["path"] == safe_path(entry.target).as_posix()), None)
                if not source_record:
                    raise UpdaterError(t("archive.unverified_hardlink"))
                os.link(source, path)
                manifest.append({**source_record, "path": safe_path(entry.name).as_posix()})
            else:
                link = entry.target or ""
                if not link or "\\" in link or ":" in link or "\x00" in link or PurePosixPath(link).is_absolute():
                    raise UpdaterError(t("archive.unsafe_symlink"))
                # Check before creating; the final pass also detects chained escapes and cycles.
                resolved = (path.parent / link).resolve()
                if not resolved.is_relative_to(destination.resolve()):
                    raise UpdaterError(t("archive.symlink_escape"))
                os.symlink(link, path, target_is_directory=resolved.is_dir())
                manifest.append({"path": safe_path(entry.name).as_posix(), "link": link})
        for record in manifest:
            if "link" in record:
                resolved = (destination / record["path"]).resolve()
                if not resolved.is_relative_to(destination.resolve()) or not resolved.exists():
                    raise UpdaterError(t("archive.symlink_broken"))
        return manifest
    except (OSError, ValueError, RuntimeError, EOFError, tarfile.TarError, zipfile.BadZipFile, zlib.error) as exc:
        raise UpdaterError(t("archive.failed", error=exc)) from exc
    finally:
        if archive is not None:
            archive.close()
