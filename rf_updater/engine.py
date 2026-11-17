from __future__ import annotations

import contextlib
import hashlib
import os
import plistlib
import shutil
import subprocess
import sys
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from . import logbook
from .archive import extract_package, safe_path
from .i18n import t
from .models import NetworkInterrupted, Release, UpdaterError, atomic_json, default_root, native_platform, read_json
from .network import CHUNK, Network, Progress, check_cancel, no_progress
from .runtime import external_environment, external_libraries
from .preferences import saved_root

# Backoff between automatic download retries; only transient transport errors retry.
RETRY_DELAYS = (2, 8, 32)


def _process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        if sys.platform == "win32":
            import ctypes
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            handle = kernel.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
            if not handle:
                return False
            kernel.CloseHandle(handle)
            return True
        os.kill(pid, 0)
        if sys.platform.startswith("linux"):
            # A zombie is exiting; the reaper thread collects it momentarily.
            status = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
            if status == "Z":
                return False
        return True
    except (OSError, ValueError, IndexError):
        return False


def _process_image(pid: int) -> str | None:
    """Best-effort executable path of a live process, for PID-reuse defence."""
    try:
        if sys.platform == "win32":
            import ctypes
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            handle = kernel.OpenProcess(0x1000, False, pid)
            if not handle:
                return None
            try:
                buffer = ctypes.create_unicode_buffer(32768)
                size = ctypes.c_uint32(len(buffer))
                if kernel.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
                    return buffer.value
                return None
            finally:
                kernel.CloseHandle(handle)
        if sys.platform == "darwin":
            import ctypes
            libproc = ctypes.CDLL("/usr/lib/libproc.dylib")
            buffer = ctypes.create_string_buffer(4096)  # PROC_PIDPATHINFO_MAXSIZE
            if libproc.proc_pidpath(pid, buffer, len(buffer)) > 0:
                return buffer.value.decode("utf-8", "replace")
            return None
        return os.readlink(f"/proc/{pid}/exe")
    except (OSError, ValueError):
        return None


@contextlib.contextmanager
def exclusive(root: Path):
    """OS locks are released on process death; never delete the lock file."""
    root.mkdir(parents=True, exist_ok=True)
    with (root / ".updater.lock").open("a+b") as stream:
        try:
            stream.seek(0)
            if stream.read(1) == b"":
                stream.write(b"0")
                stream.flush()
            stream.seek(0)
            if sys.platform == "win32":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            # Windows raises PermissionError even on the probe read while another
            # process holds the byte lock; that is contention, not a disk fault.
            raise UpdaterError(t("engine.locked")) from exc
        try:
            yield
        finally:
            stream.seek(0)
            if sys.platform == "win32":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def find_executable(payload: Path, target: str) -> str:
    if target == "macos":
        apps = sorted(p for p in payload.rglob("*.app") if p.is_dir() and "rocket" in p.name.lower())
        for app in apps:
            info = app / "Contents/Info.plist"
            try:
                data = plistlib.loads(info.read_bytes())
                binary = app / "Contents/MacOS" / safe_path(data["CFBundleExecutable"])
                if binary.is_file() and not binary.is_symlink():
                    binary.chmod(binary.stat().st_mode | 0o111)
                    return app.relative_to(payload).as_posix()
            except (OSError, KeyError, ValueError, plistlib.InvalidFileException):
                continue
    else:
        candidates = []
        for path in payload.rglob("*"):
            if not path.is_file() or path.is_symlink():
                continue
            name = path.name.lower().replace(" ", "").replace("-", "").replace("_", "")
            if not name.startswith("rocketfoundry") or "server" in name or "crash" in name:
                continue
            if target == "windows" and path.suffix.lower() != ".exe":
                continue
            if target == "linux" and path.suffix.lower() not in {"", ".x86_64"}:
                continue
            score = (0 if name in {"rocketfoundry", "rocketfoundry.exe", "rocketfoundry.x86_64"} else 1,
                     len(path.relative_to(payload).parts))
            candidates.append((score, path))
        if candidates:
            candidates.sort(key=lambda pair: (pair[0], str(pair[1])))
            if len(candidates) > 1 and candidates[0][0] == candidates[1][0]:
                raise UpdaterError(t("engine.ambiguous_executable"))
            executable = candidates[0][1]
            if target == "linux":
                executable.chmod(executable.stat().st_mode | 0o111)
            return executable.relative_to(payload).as_posix()
    raise UpdaterError(t("engine.executable_missing"))


class Engine:
    def __init__(self, root: Path | None = None, target: str | None = None, network: Network | None = None):
        preferred = saved_root() if root is None else None
        self.root = (root or preferred or default_root()).expanduser().resolve()
        self.root_must_exist = preferred is not None
        self.target = target or native_platform()
        self.network = network or Network()

    @property
    def state_path(self) -> Path:
        return self.root / "state.json"

    def state(self) -> dict:
        if self.root_must_exist and not self.root.is_dir():
            raise UpdaterError(t("engine.root_disconnected"))
        state = read_json(self.state_path, {"schema": 1, "active": None, "previous": None})
        if not isinstance(state, dict) or state.get("schema") != 1:
            raise UpdaterError(t("engine.state_schema"))
        for key in ("active", "previous"):
            item = state.get(key)
            if item is None:
                continue
            if (not isinstance(item, dict) or not isinstance(item.get("generation"), str)
                    or not isinstance(item.get("executable"), str) or not isinstance(item.get("release"), dict)):
                raise UpdaterError(t("engine.state_corrupt"))
            generation = safe_path(item["generation"])
            if len(generation.parts) != 1:
                raise UpdaterError(t("engine.state_generation"))
            safe_path(item["executable"])
            if not (self.root / "installs" / generation).resolve().is_relative_to(self.root / "installs"):
                raise UpdaterError(t("engine.state_escape"))
        return state

    def payload(self, installation: dict) -> Path:
        return self.root / "installs" / installation["generation"] / "game"

    def game_running(self) -> dict | None:
        """The recorded launch session, only while its process is demonstrably alive.

        A reused PID running another executable does not count. When the process
        image cannot be read, liveness alone is treated conservatively as running.
        """
        try:
            session = read_json(self.root / "game-session.json")
        except (UpdaterError, OSError):
            return None
        if not isinstance(session, dict) or not isinstance(session.get("pid"), int):
            return None
        pid = session["pid"]
        if not _process_alive(pid):
            return None
        command = session.get("command") or []
        if command and command[0] == "open":
            return session  # macOS: `open -W` lives exactly while the app runs.
        executable = session.get("executable")
        image = _process_image(pid)
        if image and isinstance(executable, str):
            normalize = str.lower if sys.platform == "win32" else str
            if normalize(image) == normalize(executable):
                return session
            if sys.platform.startswith("linux"):
                # Script wrappers: the kernel keeps the script path in argv.
                try:
                    cmdline = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
                    if executable.encode("utf-8") in cmdline:
                        return session
                except OSError:
                    pass
            return None
        return session

    def _ensure_game_stopped(self) -> None:
        if self.game_running():
            raise UpdaterError(t("engine.game_running"))

    def check(self) -> tuple[Release, str]:
        release = self.network.probe(self.target)
        active = self.state()["active"]
        if not active:
            status = "available"
        elif not release.comparable:
            status = "unknown"
        elif active["release"].get("platform") != self.target:
            status = "available"
        elif Release(**active["release"]).identity == release.identity:
            status = "current"
        else:
            status = "available"
        return release, status

    def install(self, release: Release, cancel: threading.Event, progress: Progress = no_progress) -> dict:
        if release.platform != self.target:
            raise UpdaterError(t("engine.platform_mismatch"))
        self.state()  # A disconnected saved directory must not be recreated on another volume.
        with exclusive(self.root):
            state = self.state()
            self._ensure_game_stopped()
            # Incomplete generations are never referenced by state.json. Leave them alone
            # after a crash; they may contain data worth recovering.
            if release.size and shutil.disk_usage(self.root).free < release.size + 128 * 1024**2:
                raise UpdaterError(t("engine.disk_full"))
            logbook.record(self.root, "install_start", identity=release.identity, size=release.size)
            try:
                package, digest = self._download(release, cancel, progress)
            except BaseException as exc:
                logbook.record(self.root, "install_failed", identity=release.identity, error=str(exc))
                raise
            generation = f"{release.identity}-{uuid.uuid4().hex[:8]}"
            stage = self.root / "installs" / generation
            stage.mkdir(parents=True)
            commit_started = False
            try:
                manifest = extract_package(package, stage / "game", self.target, cancel, progress)
                executable = find_executable(stage / "game", self.target)
                check_cancel(cancel)
                installation = {
                    "generation": generation, "executable": executable,
                    "release": release.to_dict(), "package_sha256": digest,
                    "installed_at": datetime.now(timezone.utc).isoformat(),
                    "publisher_checksum": bool(release.sha256),
                }
                atomic_json(stage / "receipt.json", {"installation": installation, "files": manifest})
                progress("activate", 0, 1)
                # Once the state write starts, retain this complete generation even
                # if interrupted just after os.replace commits the pointer.
                commit_started = True
                atomic_json(self.state_path, {"schema": 1, "active": installation, "previous": state["active"]})
            except BaseException as exc:
                logbook.record(self.root, "install_failed", identity=release.identity, error=str(exc))
                if not commit_started:
                    shutil.rmtree(stage, ignore_errors=True)
                raise
            # No fallible cleanup after the commit: a committed installation is success.
            logbook.record(self.root, "install_complete", generation=generation,
                           publisher_checksum=bool(release.sha256))
            return installation

    def _download(self, release: Release, cancel: threading.Event, progress: Progress) -> tuple[Path, str]:
        """Retry transient transport failures with backoff; resumes from the .part cache.

        Checksum mismatches, HTTP errors and build changes stay fatal: retrying
        them cannot help and would hide a real problem.
        """
        for attempt in range(len(RETRY_DELAYS) + 1):
            try:
                return self.network.download(release, self.root / "cache", cancel, progress)
            except NetworkInterrupted as exc:
                if attempt >= len(RETRY_DELAYS) or cancel.is_set():
                    raise
                logbook.record(self.root, "download_retry", attempt=attempt + 1, error=str(exc))
                progress("retry", attempt + 1, len(RETRY_DELAYS))
                if cancel.wait(RETRY_DELAYS[attempt]):
                    check_cancel(cancel)
        raise UpdaterError(t("engine.download_failed"))

    def rollback(self) -> dict:
        self.state()
        with exclusive(self.root):
            state = self.state()
            self._ensure_game_stopped()
            previous = state["previous"]
            if not previous:
                raise UpdaterError(t("engine.no_previous"))
            if not (self.payload(previous) / previous["executable"]).exists():
                raise UpdaterError(t("engine.previous_missing"))
            atomic_json(self.state_path, {"schema": 1, "active": previous, "previous": state["active"]})
            logbook.record(self.root, "rollback_complete", generation=previous["generation"])
            return previous

    def verify(self, cancel: threading.Event, progress: Progress = no_progress) -> int:
        self.state()
        with exclusive(self.root):
            active = self.state()["active"]
            if not active:
                raise UpdaterError(t("engine.not_installed"))
            payload = self.payload(active)
            receipt = read_json(payload.parent / "receipt.json")
            if not receipt or not isinstance(receipt.get("files"), list):
                raise UpdaterError(t("engine.receipt_missing"))
            records = receipt["files"]
            total = sum(r.get("size", 0) for r in records)
            done = 0
            failures = []
            for record in records:
                check_cancel(cancel)
                path = payload / safe_path(record["path"])
                if not path.resolve().is_relative_to(payload.resolve()):
                    failures.append(record["path"])
                    continue
                if "link" in record:
                    if not path.is_symlink() or os.readlink(path) != record["link"] or not path.exists():
                        failures.append(record["path"])
                    continue
                if path.is_symlink() or not path.is_file() or path.stat().st_size != record["size"]:
                    failures.append(record["path"])
                    continue
                digest = hashlib.sha256()
                with path.open("rb") as stream:
                    while chunk := stream.read(CHUNK):
                        check_cancel(cancel)
                        digest.update(chunk)
                        done += len(chunk)
                        progress("verify_files", done, total)
                if digest.hexdigest() != record["sha256"]:
                    failures.append(record["path"])
            if failures:
                logbook.record(self.root, "verify_failed", failures=len(failures))
                raise UpdaterError(t("engine.verify_failed", count=len(failures), files="\n".join(failures[:5])))
            logbook.record(self.root, "verify_complete", files=len(records))
            return len(records)

    def launch(self) -> int:
        if self.target != native_platform():
            raise UpdaterError(t("engine.launch_platform"))
        self.state()
        with exclusive(self.root):
            active = self.state()["active"]
            if not active:
                raise UpdaterError(t("engine.not_installed"))
            if active["release"]["platform"] != self.target:
                raise UpdaterError(t("engine.launch_mismatch"))
            payload = self.payload(active)
            executable = payload / safe_path(active["executable"])
            if not executable.resolve().is_relative_to(payload.resolve()) or not executable.exists():
                raise UpdaterError(t("engine.launch_missing"))
            command = ["open", "-W", str(executable)] if self.target == "macos" else [str(executable)]
            logs = self.root / "logs"
            logs.mkdir(exist_ok=True)
            # A log makes missing shared libraries and first-launch issues diagnosable.
            with (logs / "game.log").open("ab") as output, external_libraries():
                process = subprocess.Popen(command, cwd=executable.parent, stdout=output, stderr=output,
                                           start_new_session=sys.platform != "win32", env=external_environment())
            # Reap without tying the game lifetime to the updater window.
            threading.Thread(target=process.wait, daemon=True).start()
            # The session record lets any later window or CLI see the running game.
            atomic_json(self.root / "game-session.json", {
                "pid": process.pid, "executable": str(executable.resolve()), "command": command,
                "generation": active["generation"],
                "started_at": datetime.now(timezone.utc).isoformat(),
            })
            logbook.record(self.root, "launch", pid=process.pid, generation=active["generation"])
            return process.pid
