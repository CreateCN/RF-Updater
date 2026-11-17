# Architecture Overview (0.5)

[中文](../architecture.md) | **English**

This document describes the current code structure and design constraints. The original design decisions from the 0.2 redesign are kept in [design.md](../design.md) (historical, Chinese).

## Layers

```text
┌─────────────────────────────────────────────────────────┐
│ GUI (PySide6 Qt Widgets)                                 │
│   gui.py            window composition, pages, language  │
│                     switching, tray, timers              │
│   ui/controller.py  QThread worker task model, state,    │
│                     notices                              │
│   ui/widgets.py     panels/details/task area/artwork     │
│   ui/directories.py directory page (choice/scan/cleanup) │
│   ui/theme.py       design tokens, per-language fonts    │
├─────────────────────────────────────────────────────────┤
│ Engine (standard library only, shared with CLI, no Qt)   │
│   engine.py      lock, generation installs, verify,      │
│                  rollback, launch, running awareness     │
│   network.py     HTTPS, probe, resume, digests, retry    │
│                  exception type                          │
│   archive.py     restricted extraction (ZIP/TAR.GZ)      │
│   storage.py     bounded inventory, switch, cleanup      │
│   preferences.py directory memory and settings           │
│   models.py      Release/error types/atomic JSON         │
│   runtime.py     external-process environment cleanup    │
│   logbook.py     diagnostics (JSON lines, rotation)      │
│   i18n.py        three-language catalogs, t(), detection │
├─────────────────────────────────────────────────────────┤
│ Entry points: __main__.py (7 CLI commands, lazy GUI)     │
│               run_updater.py (PyInstaller entry)         │
└─────────────────────────────────────────────────────────┘
```

**Core constraint**: the engine never imports Qt. The CLI works without a display and without PySide6; the GUI is just one consumer of the engine. Translation therefore lives in the standard-library `i18n.py` rather than the Qt tr system.

## Data and trust boundaries

- Installation records keep `state.json` schema 1: `active`/`previous` pointers, fully validated on read (field types, generation directory legality, no path escape).
- **Transactional generation installs**: each install writes an independent `installs/<build-id>-<ID>/`; failures before the commit (atomic state.json replacement) delete the whole generation, while an interrupt after the commit starts still retains the complete new generation. Incomplete generations are never referenced by pointers and never auto-deleted (they may hold recoverable data).
- **Build identity**: `Release.identity` = sha256(platform, URL, evidence, size)[:20]; evidence prefers the official SHA-256, then ETag, then Last-Modified. Stable across CDN redirects and expiring signed URLs. ETag/modified time are not in-game version numbers; when comparison is impossible the status is explicitly `unknown`.
- **Honest verification**: "official checksum verified" is claimed only when an official SHA-256 exists; otherwise transfer length + archive integrity + a local digest. A local digest is not a publisher signature.
- **Network security**: HTTPS enforced hop-by-hop including redirects; frozen bundles load the bundled Mozilla CA; resume uses Range + If-Range with strict Content-Range checks on 206; `Repr-Digest` vs `Content-Digest` are distinguished (a 206's Content-Digest hashes only the range).
- **Extraction defenses**: rejects absolute paths, `..`, backslashes, colons, Windows reserved names, trailing dots/spaces; case-fold collision detection on Windows/macOS; files written first, links created last; symlink escape checked before and after creation; hard links must target verified files; 16 GiB / 100,000-file caps; the gzip trailer is explicitly drained to verify CRC.
- **Concurrency**: `.updater.lock` OS lock (msvcrt/flock), released on process death; the lock file is never deleted.
- **User data**: old installs and cache are never auto-deleted; cleanup requires explicit selection, current/rollback versions are hard-protected, old installs need a backup acknowledgement; the whole batch is validated before item-by-item deletion, failures reported per item. Scans never follow symlinks/junctions and stop at 250,000 nodes / 2,000 items.
- **Disconnected directories**: when a saved location is unavailable the user is asked to connect the disk or choose another location — it is never recreated on another volume (diagnostic logging obeys this too).

## Task model (GUI)

- QObject `Worker` moved into a QThread runs engine calls; results/errors/progress return to the main thread via signals, progress coalesced to ~10 Hz.
- Check tasks and change tasks are tracked separately: launching stays possible during a check; install/verify/rollback/cleanup are serialized.
- Results must match the current task ID; stale signals are dropped. A failed check only clears remote information, preserving local launch ability.
- Cancellation uses `threading.Event`, checked between download/digest/extraction chunks; closing disables new tasks and waits for threads — never terminates them.
- Workers `moveToThread` back to the GUI thread while still on their own thread; after `thread.wait()` everything is `deleteLater`-ed on the GUI thread, avoiding Shiboken cross-thread teardown races.

## Running awareness and resilience (0.4)

- `launch()` writes `game-session.json` (PID, executable path, command, generation); `game_running()` combines liveness with executable-path matching (Linux `/proc/<pid>/exe` plus cmdline fallback for script wrappers; Windows `QueryFullProcessImageNameW`; macOS `proc_pidpath`, with `open -W` judged by the waiting process's liveness). Reused PIDs are not misdetected; an unreadable process image is conservatively treated as running.
- While running: the engine refuses install/rollback, storage refuses old-install cleanup, the GUI disables the corresponding buttons and shows "Running"; the GUI polls every 2 s and recovers automatically after exit.
- Download retries: only `NetworkInterrupted` (connection errors, truncated responses) triggers cancellable 2s/8s/32s backoff, at most 3 times; the resume cache keeps progress. Checksum mismatches, HTTP errors and build changes stay fatal.
- Diagnostics: `logbook.record()` opens/closes the file per event (no persistent handle, safe for test fixtures), 1 MB rotation with 3 backups; skipped entirely when the data root does not exist.

## Localization (0.5)

- `i18n.py`: `t(key, **params)` falls back from the active language to the source (zh-CN); plurals select one/other by `count`; damaged catalogs degrade silently.
- Detection: GUI `QLocale.system()` (Traditional Han script or TW/HK/MO → zh-TW, other Chinese → zh-CN, else en); CLI `RF_UPDATER_LANG` > `LC_ALL` > `LC_MESSAGES` > `LANG`, unset → zh-CN.
- Switching: `language` in `settings.json` (null = follow system); follow mode re-detects on every launch and follows `LocaleChange` live; manual choices apply immediately (`retranslate()` for static text + per-frame `t()` for dynamic text + qtbase translator + fonts + tray menu).
- Details: [localization guide](localization.md).

## Packaging

- PyInstaller 6.22.3 onedir, Qt Core/Gui/Widgets only; a custom QtGui hook keeps just the desktop platform plugins; WebEngine/QML/QtQuick/QtPdf/Tk excluded.
- Bundled: Mozilla CA (certifi), `rf_updater/locales/*.json`, `qtbase_{en,zh_CN,zh_TW}.qm`, third-party licenses.
- Before launching external processes, `LD_LIBRARY_PATH`/DLL search directories are restored and only Qt plugin paths pointing into `_MEIPASS` are removed.
- Cross-compilation is forbidden; Linux builds are limited by the build machine's glibc.

## Test structure

112 tests + 20 Qt scenarios, all using loopback HTTP and synthetic packages (running awareness uses a local sleep fixture); no network access, no real game. The suite pins zh-CN. See [testing & building](testing.md).
