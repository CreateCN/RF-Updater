"""Coordinate independent update checks and one exclusive foreground task."""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import QObject, QThread, Signal, Slot, Qt

from ..engine import Engine
from ..i18n import t
from ..models import Cancelled, Release, UpdaterError
from .. import logbook, storage


@dataclass
class Notice:
    operation: str
    title: str
    detail: str = ""
    tone: str = "success"
    retry: str | None = None


@dataclass
class TaskProgress:
    phase: str = "prepare"
    done: int = 0
    total: int | None = None
    speed: float | None = None


class Worker(QObject):
    result = Signal(int, object)
    error = Signal(int, object)
    progress = Signal(int, str, object, object)
    finished = Signal()

    def __init__(self, job_id: int, function: Callable, cancel: threading.Event, owner_thread: QThread):
        super().__init__()
        self.job_id, self.function, self.cancel = job_id, function, cancel
        self.owner_thread = owner_thread
        self.last_progress = 0.0
        self.last_phase = ""

    def report(self, phase, done, total):
        now = time.monotonic()
        if phase != self.last_phase or now - self.last_progress >= .1 or done == total:
            self.last_phase, self.last_progress = phase, now
            self.progress.emit(self.job_id, phase, done, total)

    @Slot()
    def run(self):
        try:
            self.result.emit(self.job_id, self.function(self.cancel, self.report))
        except Exception as exc:
            self.error.emit(self.job_id, exc)
        finally:
            # Return ownership while still executing on the worker's own thread.
            # QObject/Python wrapper destruction then happens only on the GUI
            # thread, avoiding concurrent Shiboken/GIL and QObject mutex teardown.
            self.moveToThread(self.owner_thread)
            self.finished.emit()


@dataclass
class Job:
    thread: QThread
    worker: Worker
    cancel: threading.Event
    operation: str
    retry: str
    saved_notice: Notice | None = None


class Controller(QObject):
    changed = Signal()
    idle = Signal()
    completed = Signal(str, bool)

    def __init__(self, engine: Engine, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.jobs: dict[int, Job] = {}
        self.sequence = 0
        self.check_id: int | None = None
        self.task_id: int | None = None
        self.operation: str | None = None
        self.active: dict | None = None
        self.previous: dict | None = None
        self.state_error: str | None = None
        self.release: Release | None = None
        self.remote_status = "unchecked"
        self.check_error: str | None = None
        self.notice: Notice | None = None
        self.progress = TaskProgress()
        self.download_baseline: tuple[float, int] | None = None
        self.cancelling = False
        self.closing = False
        self.inventory: storage.Inventory | None = None
        self.storage_revision = 0
        self.game_session: dict | None = None
        self.refresh_state()
        self.refresh_game_status()

    @property
    def checking(self) -> bool:
        return self.check_id is not None

    @property
    def busy(self) -> bool:
        return self.task_id is not None

    @property
    def game_running(self) -> bool:
        return self.game_session is not None

    def refresh_game_status(self):
        session = self.engine.game_running()
        changed = ((session is None) != (self.game_session is None)
                   or bool(session and self.game_session
                           and session.get("generation") != self.game_session.get("generation")))
        self.game_session = session
        if changed:
            self.changed.emit()

    @property
    def can_launch(self) -> bool:
        return bool(self.active and not self.busy and not self.closing and not self.state_error
                    and not self.game_running)

    @property
    def can_install(self) -> bool:
        return bool(self.release and not self.checking and not self.busy
                    and not self.closing and not self.check_error and not self.state_error
                    and not self.game_running)

    def refresh_state(self):
        try:
            state = self.engine.state()
            self.active, self.previous = state["active"], state["previous"]
            for installation in (self.active, self.previous):
                if installation:
                    Release(**installation["release"])
                    if not isinstance(installation.get("installed_at"), str):
                        raise UpdaterError(t("task.state_date_missing"))
            self.state_error = None
        except (UpdaterError, OSError, ValueError, TypeError, KeyError) as exc:
            self.active, self.previous, self.state_error = None, None, str(exc)

    def _start(self, operation: str, function: Callable, *, retry=None, saved_notice=None):
        self.sequence += 1
        job_id = self.sequence
        thread = QThread(self)
        thread.setProperty("job_id", job_id)
        event = threading.Event()
        worker = Worker(job_id, function, event, self.thread())
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.result.connect(self._result)
        worker.error.connect(self._error)
        worker.progress.connect(self._progress)
        # quit() is thread-safe. Direct connection lets cleanup proceed even while
        # the window is waiting for the last queued GUI result during shutdown.
        worker.finished.connect(thread.quit, Qt.ConnectionType.DirectConnection)
        thread.finished.connect(self._reap)
        self.jobs[job_id] = Job(thread, worker, event, operation, retry or operation, saved_notice)
        if operation == "check":
            self.check_id = job_id
            self.check_error = None
        else:
            self.task_id, self.operation = job_id, operation
            self.notice, self.download_baseline = None, None
            self.progress = TaskProgress()
            self.cancelling = False
        self.changed.emit()
        thread.start()

    def check(self):
        if not self.checking and not self.busy and not self.closing:
            self._start("check", lambda cancel, progress: self.engine.check())

    def install(self, *, reinstall=False):
        if self.busy or self.checking or self.closing or self.state_error or self.game_running:
            return
        if not reinstall and not self.can_install:
            return
        release = self.release

        def run(cancel, progress):
            latest = self.engine.check()[0] if reinstall else release
            return self.engine.install(latest, cancel, progress)
        self._start("install", run, retry="reinstall" if reinstall else "install")

    def verify(self):
        if self.active and not self.busy and not self.checking and not self.closing:
            # A failed verification is repaired by a full reinstall, offered as the retry.
            self._start("verify", lambda cancel, progress: self.engine.verify(cancel, progress), retry="reinstall")

    def rollback(self):
        if self.previous and not self.busy and not self.checking and not self.closing and not self.game_running:
            self._start("rollback", lambda cancel, progress: self.engine.rollback())

    def launch(self):
        if self.can_launch:
            self._start("launch", lambda cancel, progress: self.engine.launch())

    @property
    def storage_unlocked(self) -> bool:
        return not self.jobs and not self.closing

    def scan_storage(self, *, preserve_notice=False):
        if self.storage_unlocked:
            engine = self.engine
            self._start("storage_scan", lambda cancel, progress: storage.scan(engine, cancel, progress),
                        retry="scan_storage", saved_notice=self.notice if preserve_notice else None)

    def change_directory(self, path):
        if self.storage_unlocked:
            engine = self.engine
            self._start("directory", lambda cancel, progress: storage.switch_directory(engine, path), retry="scan_storage")

    def clean_storage(self, keys, *, allow_old=False):
        if self.storage_unlocked and keys:
            engine = self.engine
            self._start("cleanup", lambda cancel, progress: storage.cleanup(engine, keys, allow_old=allow_old), retry="scan_storage")

    def retry(self):
        if not self.notice or not self.notice.retry:
            self.check()
        elif self.notice.retry in {"install", "reinstall"}:
            self.install(reinstall=self.notice.retry == "reinstall")
        else:
            getattr(self, self.notice.retry)()

    def cancel_task(self):
        if self.task_id is not None and self.operation in {"install", "verify", "storage_scan"}:
            self.jobs[self.task_id].cancel.set()
            self.cancelling = True
            self.changed.emit()

    def shutdown(self):
        self.closing = True
        self.cancelling = True
        for job in self.jobs.values():
            job.cancel.set()
        self.changed.emit()
        if not self.jobs:
            self.idle.emit()

    @Slot(int, str, object, object)
    def _progress(self, job_id, phase, done, total):
        if job_id != self.task_id:
            return
        speed = None
        if phase == "download":
            now = time.monotonic()
            if self.download_baseline is None:
                self.download_baseline = (now, done)
            elapsed = now - self.download_baseline[0]
            if elapsed > .5:
                speed = max(0, done - self.download_baseline[1]) / elapsed
        self.progress = TaskProgress(phase, done, total, speed)
        self.changed.emit()

    @Slot(int, object)
    def _result(self, job_id, result):
        job = self.jobs.get(job_id)
        if not job:
            return
        operation = job.operation
        if operation == "check":
            if job_id != self.check_id:
                return
            self.check_id = None
            self.release, self.remote_status = result
            self.check_error = None
        elif job_id == self.task_id:
            self.task_id, self.operation = None, None
            if operation == "directory":
                self.engine = result
                self.release, self.remote_status, self.check_error = None, "unchecked", None
                self.inventory = None
                self.storage_revision += 1
            self.refresh_state()
            self.refresh_game_status()
            if operation == "install":
                self.inventory = None
                self.storage_revision += 1
                self.release = Release(**result["release"])
                self.remote_status = "current" if self.release.comparable else "unknown"
                self.check_error = None
                detail = (t("task.install_done_checksum") if result["publisher_checksum"]
                          else t("task.install_done_local"))
                self.notice = Notice(operation, t("task.install_done"), detail)
                self.progress = TaskProgress("complete", 1, 1)
            elif operation == "verify":
                self.notice = Notice(operation, t("task.verify_done"), t("task.verify_done_detail", count=result))
                self.progress = TaskProgress("complete", 1, 1)
            elif operation == "rollback":
                self.inventory = None
                self.storage_revision += 1
                self.release, self.remote_status = None, "unchecked"
                self.notice = Notice(operation, t("task.rollback_done"), t("task.rollback_done_detail"))
            elif operation == "launch":
                self.notice = Notice(operation, t("task.launch_done"), t("task.launch_done_detail"))
            elif operation == "storage_scan":
                self.inventory = result
                self.storage_revision += 1
                self.notice = job.saved_notice or Notice(operation, t("task.scan_done"), t("task.scan_done_detail", count=len(result.items)))
            elif operation == "directory":
                self.notice = Notice(operation, t("task.directory_done"), t("task.directory_done_detail"))
            elif operation == "cleanup":
                self.inventory = result.inventory
                self.storage_revision += 1
                self.notice = Notice(operation, t("task.cleanup_done", count=result.removed),
                                     t("task.list_separator").join(result.errors) if result.errors else t("task.cleanup_done_detail"),
                                     "warning" if result.errors else "success", "scan_storage" if result.errors else None)
        else:
            return
        self.changed.emit()
        self.completed.emit(operation, True)

    @Slot(int, object)
    def _error(self, job_id, error):
        job = self.jobs.get(job_id)
        if not job:
            return
        if job.operation == "check":
            if job_id != self.check_id:
                return
            self.check_id = None
            self.check_error = str(error)
            self.release, self.remote_status = None, "unavailable"
        elif job_id == self.task_id:
            self.task_id, self.operation = None, None
            if job.operation == "install":
                self.inventory = None
                self.storage_revision += 1
            cancelled = isinstance(error, Cancelled)
            if not cancelled:
                logbook.record(self.engine.root, "task_error", operation=job.operation, error=str(error))
            detail = str(error)
            if not cancelled:
                detail += t("task.log_path", path=logbook.log_path(self.engine.root))
            self.notice = Notice(job.operation, t("task.cancelled") if cancelled else t(f"task.error.{job.operation}"),
                                 detail, "warning" if cancelled else "error", job.retry)
            self.refresh_state()
            self.refresh_game_status()
        else:
            return
        self.changed.emit()
        self.completed.emit(job.operation, False)

    @Slot()
    def _reap(self):
        thread = self.sender()
        job_id = thread.property("job_id")
        # finished is emitted before native thread-local cleanup. Join it before
        # deleting either wrapper. Worker has already returned to GUI ownership.
        thread.wait()
        job = self.jobs.pop(job_id, None)
        if job:
            job.worker.deleteLater()
        thread.deleteLater()
        self.changed.emit()
        if not self.jobs:
            self.idle.emit()
