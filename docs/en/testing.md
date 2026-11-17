# Testing & Building

[中文](../testing.md) | **English**

## Environment setup

```sh
python -m venv .venv
# activate .venv
python -m pip install -e . -r requirements-build.txt
```

- Python 3.11+ (local verification uses 3.14.4); runtime dependency `PySide6==6.12.0`; build dependencies `pyinstaller==6.22.3`, `certifi==2026.10.23`.
- Linux desktop tests need Qt platform-plugin system libraries: on Debian/Ubuntu install `libxcb-cursor0 libxkbcommon-x11-0 libegl1 libopengl0 libgl1 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-render-util0 fonts-noto-cjk`; real X11 window tests need `xvfb-run`.
- In Windows PowerShell set environment variables like `$env:QT_QPA_PLATFORM='offscreen'`.

## Test philosophy

- **No network, no real game**: every test uses a loopback HTTP server (`Server` in `tests/support.py`) and tiny synthetic ZIP/TAR.GZ packages. Running-awareness tests use a local `sleep 30` fixture process and only terminate processes they created.
- **Pinned language**: `tests/__init__.py` pins i18n to zh-CN and GUI tests additionally fix the language via settings, so assertions are stable on any CI machine locale.
- **Real control acceptance**: Qt scenarios click real visible controls via QTest and wait for real threads and signals; no sleep-based timing guesses (`wait_until` polls conditions).
- Dates, package sizes and digests in screenshots and test output come from synthetic installs and do not represent official versions.

## Running tests

```sh
# full unit + integration + Qt scenarios (no display server)
QT_QPA_PLATFORM=offscreen python -m unittest discover -v

# Qt desktop acceptance only (20 scenarios)
QT_QPA_PLATFORM=offscreen python -m scripts.qa_gui

# real X11 window on Linux
xvfb-run -a env QT_QPA_PLATFORM=xcb python -m scripts.qa_gui --screenshots docs/qa/qt

# hi-DPI acceptance
QT_QPA_PLATFORM=offscreen QT_SCALE_FACTOR=1.5 python -m scripts.qa_gui
QT_QPA_PLATFORM=offscreen QT_SCALE_FACTOR=2 python -m scripts.qa_gui

# key/parameter parity across the three catalogs
python -m scripts.i18n_report

# a single test
QT_QPA_PLATFORM=offscreen python -m unittest tests.test_engine.EngineTests.test_full_install_update_verify_rollback -v
```

Current size: **112 tests** (archive 18, engine 19, gui 20, i18n 9, cli 5, logbook 4, network 17, runtime 4, storage 16), of which 20 are Qt scenarios.

## Acceptance matrix (before each release)

| Environment | Command | Notes |
| --- | --- | --- |
| offscreen | `unittest discover` | full suite, no window system |
| Xvfb/xcb | `scripts.qa_gui` | real X11 window on Linux |
| 150% / 200% | `QT_SCALE_FACTOR` + `qa_gui` | hi-DPI logical-pixel layout |
| bundle smoke | `scripts.smoke_native dist/RF-Updater/RF-Updater` | packaged window stays running |
| CLI languages | `RF_UPDATER_LANG=en/zh-TW … verify` | multilingual bundle output |
| checksum | `sha256sum -c dist/*.sha256` | artifact integrity |

Windows/macOS native acceptance, code signing and macOS notarization must run in their respective environments; passing offscreen is not equivalent to native desktop acceptance on those systems.

## Packaging

```sh
python -m scripts.build
```

- Builds only on the current OS (cross-compilation forbidden): Linux → `dist/RF-Updater/` + `RF-Updater-linux-x64.tar.gz`; Windows → ZIP; macOS → `RF-Updater.app` + ditto ZIP. Each with a `.sha256`.
- Collected: Qt desktop plugins (custom hook drops image/document viewer plugins), Mozilla CA and its license, `rf_updater/locales/*.json`, `qtbase_{en,zh_CN,zh_TW}.qm`, third-party licenses, README/LICENSE/docs.
- Excluded: WebEngine, QML, QtQuick, QtPdf, Tk, UPX.
- Local Linux install: `python -m scripts.install_linux --launch` (verifies the checksum, keeps older versions, updates `~/.local/bin/rf-updater` and the menu entry, never touches game data).

## CI

[.github/workflows/ci.yml](../../.github/workflows/ci.yml): three platforms (ubuntu-22.04 / windows-2022 / macos-15), Python 3.13:

1. Install runtime and build dependencies (Linux additionally installs Qt system libraries and Noto CJK fonts)
2. Full offscreen test suite
3. Linux Xvfb/xcb interaction checks
4. 150% / 200% hi-DPI checks
5. Native packaging + window smoke test
6. Upload artifacts (no automatic release publishing)

Linux builds on Ubuntu 22.04 for an older glibc baseline; local glibc 2.43 builds are only accepted on the current system.

## Conventions for new tests

- Engine/storage tests go in `tests/test_<module>.py`, reusing the `Server` and synthetic-package fixtures; temporary directories use `tempfile.TemporaryDirectory` + `addCleanup`.
- GUI scenarios join `GuiTests` in `tests/test_gui.py`: use `open_window()`/`click()`/`idle()`/`wait_until()`; modal dialogs via `patch.object(window, "confirm", …)` or a QTimer inspecting the real dialog; screenshots via `capture(name)` (enabled by the `RF_QA_SCREENSHOTS` environment variable).
- Assertions on user-visible text use zh-CN wording (the suite is pinned); new i18n keys must be added to all three catalogs and pass `scripts.i18n_report`.
