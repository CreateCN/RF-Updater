# Changelog / 变更日志

All notable changes to RF-Updater are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/); versions use SemVer.
本文件记录 RF-Updater 的重要变更，格式遵循 Keep a Changelog，版本号采用语义化版本。

## [0.5.0] - 2026-11-17

### Added
- Localization: Simplified Chinese (source), Traditional Chinese (zh-TW/zh-HK/zh-MO) and English; 340-key JSON catalogs in `rf_updater/locales/`.
- Automatic language selection from the machine locale at initialization (GUI: `QLocale.system()`; CLI: `RF_UPDATER_LANG` > `LC_ALL` > `LC_MESSAGES` > `LANG`), re-detected on every launch and followed live via `LocaleChange` in follow-system mode.
- Manual language override on the About page (applies immediately, persisted in `settings.json`); Qt standard dialogs translated via bundled `qtbase_*.qm`; per-language font selection.
- `scripts/i18n_report.py` coverage checker; 18 new tests (i18n unit, CLI language, GUI language scenarios). Suite now 112 tests / 20 Qt scenarios.
- Bilingual documentation: English README, architecture, testing and localization guides; documentation index.

### 新增
- 本地化：简体中文（源语言）、繁体中文（覆盖 zh-TW/zh-HK/zh-MO）、English；`rf_updater/locales/` 三语言 JSON 目录各 340 键。
- 初始化按机器区域标识自动选择语言（GUI 读 `QLocale.system()`；CLI 按 `RF_UPDATER_LANG` > `LC_ALL` > `LC_MESSAGES` > `LANG`），每次启动重检测，跟随系统模式下运行中经 `LocaleChange` 即时切换。
- 关于页手动语言覆盖（即时生效，持久化于 `settings.json`）；Qt 标准对话框加载随包 `qtbase_*.qm`；字体按语言选择。
- `scripts/i18n_report.py` 覆盖率检查；新增 18 项测试（i18n 单元、CLI 语言、GUI 语言场景），套件达 112 项测试 / 20 项 Qt 场景。
- 双语文档：英文 README、架构、测试与本地化指南；文档索引。

### Changed
- All user-visible strings (GUI, engine errors, notices, directory page, tray, CLI) routed through `i18n.t()`; engine and CLI remain Qt-free.
- Test suite pins Simplified Chinese so existing assertions hold on any CI locale.

### 变更
- 全部用户可见文本（GUI、引擎错误、通知、目录页、托盘、CLI）经 `i18n.t()` 输出；引擎与 CLI 保持零 Qt 依赖。
- 测试套件钉住简体中文，既有断言不受 CI 机器区域影响。

### Fixed
- First full three-platform remote CI passed (run 44088390829). Issues found and fixed along the way: Windows lock-probe read raised a raw `PermissionError` (now a proper contention error); Windows offscreen font database enumerated no system fonts, causing full-width Latin rendering (now registers known system font files, forces the family via QSS, and uses a logical-pixel font base); long checkbox/button labels shortened and title labels made wrappable so layouts no longer depend on specific font metrics; tests normalized temp paths (`/private/var`, 8.3 short names), used real process images for fake sessions, and explicit UTF-8 decoding; Linux xcb dependency set completed.

### 修复
- 首次三平台远程 CI 完整通过（运行 44088390829）。期间发现并修复：Windows 锁探测读取抛裸 `PermissionError`（现统一为竞争错误）；Windows offscreen 字体数据库不枚举系统字体导致拉丁字符全角渲染（现注册已知系统字体文件、QSS 强制字体族、逻辑像素字体基准）；长复选框/按钮文案精简、标题标签可换行，布局不再依赖特定字体度量；测试统一临时路径解析（`/private/var`、8.3 短名）、伪造会话使用真实进程镜像、显式 UTF-8 解码；Linux 补齐 xcb 依赖。

## [0.4.0] - 2026-11-17

### Added
- Game-running awareness: launch session record (`game-session.json`) + cross-platform process probing (Linux `/proc`, Windows `QueryFullProcessImageNameW`, macOS `proc_pidpath`); update/rollback/old-install cleanup blocked while running, auto-recovery on exit; PID-reuse safe.
- Automatic download retries: `NetworkInterrupted` type, 2s/8s/32s cancellable backoff (max 3), resume keeps progress; checksum/HTTP/build-change errors stay fatal.
- One-click "Reinstall to repair" after failed verification.
- System tray (show/check/quit) and desktop notifications for task results; periodic update checks every 4h while the window is open (About-page toggles, `settings.json`).
- Diagnostic log `logs/updater.log` (JSON lines, 1 MB rotation ×3); error details include the log path.

### 新增
- 游戏运行感知：启动会话记录（`game-session.json`）+ 跨平台进程探测（Linux `/proc`、Windows `QueryFullProcessImageNameW`、macOS `proc_pidpath`）；运行中阻止更新/回退/旧安装清理，退出后自动恢复；PID 复用不误判。
- 下载自动重试：`NetworkInterrupted` 类型，2s/8s/32s 可取消退避（最多 3 次），续传保留进度；校验/HTTP/构建变化错误保持致命。
- 校验失败后一键“重新安装修复”。
- 系统托盘（显示/检查/退出）与任务结果桌面通知；窗口打开期间每 4 小时定时检查（关于页开关，`settings.json`）。
- 诊断日志 `logs/updater.log`（JSON 行，1 MB 轮转×3）；错误详情附日志路径。

### Fixed
- Diagnostic logging no longer recreates a disconnected data directory; download failures are logged as `install_failed`.

### 修复
- 诊断日志不再重建失联的数据目录；下载失败补记 `install_failed`。

## [0.3.0] - 2026-11-16

### Added
- Visual directory management: choose/remember/switch data locations (up to 12 recent), categorized size breakdown and free-space display, explicit checkbox cleanup with current/rollback protection and backup acknowledgement for old installs.
- `storage.py` bounded link-safe inventory (250,000 nodes / 2,000 items), lock-held revalidated cleanup; `preferences.py` directory memory (`directories.json`), disconnected-directory recovery without recreation.
- 15 storage backend tests + 5 Qt scenarios (80 total).

### 新增
- 可视化目录管理：选择/记住/切换数据位置（最多 12 个最近位置）、分类大小与可用空间展示、显式勾选清理（当前/回退版本保护，旧安装需备份确认）。
- `storage.py` 有界且不跟随链接的清点（250,000 节点 / 2,000 项）、持锁重验后清理；`preferences.py` 目录记忆（`directories.json`）、失联目录提示恢复而不重建。
- 新增 15 项存储后端测试 + 5 项 Qt 场景（共 80 项）。

## [0.2.0] - 2026-11-16

### Changed
- GUI redesigned from Tk to PySide6/Qt 6.12.0: dark spaceflight theme, four-page layout, standard controls, keyboard focus, hi-DPI (100/150/200%) support.
- QObject worker/QThread task model: independent check vs. change tasks, 10 Hz progress coalescing, stale-result isolation, safe cross-thread teardown, close waits for threads.

### 变更
- GUI 由 Tk 改为 PySide6/Qt 6.12.0：深色航天主题、四页布局、标准控件、键盘焦点、高分屏（100/150/200%）。
- QObject worker/QThread 任务模型：检查与变更任务分轨、10 Hz 进度合并、过期结果隔离、跨线程安全销毁、关闭等待线程结束。

### Compatibility
- Reads 0.1 `state.json` (schema 1) unchanged; 60 tests passing.

### 兼容
- 直接读取 0.1 的 `state.json`（schema 1），无需迁移；60 项测试通过。

## [0.1.0] - 2026-11-16

### Added
- Initial release: standard-library engine (HTTPS with certificate/hostname verification, resumable Range downloads with build-change detection, restricted extraction, transactional generation installs, SHA-256 verification, rollback, OS file locking), Tk GUI, CLI, PyInstaller bundles with Mozilla CA.
- End-to-end verification against the real official Linux package; 51 tests.

### 新增
- 首个版本：标准库引擎（HTTPS 证书/主机名验证、Range 断点续传与构建变化检测、受限解压、事务式代际安装、SHA-256 校验、回退、OS 文件锁）、Tk 界面、CLI、附带 Mozilla CA 的 PyInstaller 打包。
- 对真实官方 Linux 包完成端到端验证；51 项测试。

[0.5.0]: docs/verification-0.5.md
[0.4.0]: docs/verification-0.4.md
[0.3.0]: docs/verification-0.3.md
[0.2.0]: docs/verification-0.2.md
[0.1.0]: docs/verification.md
