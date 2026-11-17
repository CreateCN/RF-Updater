# 0.5 本地化验证（简体中文 / 繁体中文 / English）

验证日期：2026-11-17（Asia/Shanghai）。本机 Linux x86_64、Python 3.14.4、PySide6 6.12.0。

## 新增能力

- **三语言目录**：`rf_updater/locales/{zh-CN,zh-TW,en}.json`，各 340 键，键集合与模板参数完全一致（`scripts/i18n_report` 退出码 0）。zh-CN 为源语言；en 全译；zh-TW 简繁转换 + 术语修正（軟體/檔案/快取/目錄/下載/安裝/校驗/還原/預設/設定/日誌/視窗/網路/伺服器等）。
- **纯标准库 i18n 核心**：`i18n.py` 提供 `t()`、复数（count 选择 one/other）、缺失键回退源语言、损坏目录静默降级；引擎与 CLI 零 Qt 依赖。
- **初始化自动切换**：GUI 启动按 `QLocale.system()` 检测（繁体脚本或 TW/HK/MO → zh-TW，其余中文 → zh-CN，其他 → en）；CLI 按 `RF_UPDATER_LANG` > `LC_ALL` > `LC_MESSAGES` > `LANG`，未设置 → zh-CN。首次启动零配置即系统语言。
- **运行中跟随**：跟随系统模式下 `QEvent.LocaleChange` 触发即时切换；手动固定语言时忽略系统变化；每次启动重新检测。
- **手动覆盖**：关于页语言下拉（跟随系统（当前：X）/ 简体中文 / 繁體中文 / English），即时生效无需重启，持久化于 `settings.json` 的 `language` 字段（schema 1 不变，非法值回退 null）。
- **全界面覆盖**：GUI 静态文本经 `retranslate()`、动态文本每帧经 `t()`；引擎错误、任务通知、目录页、托盘菜单、CLI 输出全部本地化；Qt 标准对话框加载随包 `qtbase_*.qm`；字体按语言重选。
- **打包**：package-data + PyInstaller add-data 收集语言目录与 qtbase qm；独立包内资产已核实存在。

## 自动化结果

- **112 项回归通过**：0.4 的 94 项（中文断言零改写，套件钉住 zh-CN）+ 新增 18 项（i18n 单元 9、CLI 语言 5、GUI 语言场景 4）。
- **20 项 Qt 场景**在 offscreen、Xvfb/xcb 原生窗口、150% 与 200% 缩放全部通过，含英文 900×640 最小窗口无水平滚动条、语言切换无原始键泄漏。
- `scripts.i18n_report`：340 个使用键在三语言中均存在且参数一致，无未用键。

## 独立包验证

- `python -m scripts.build` 重建 Linux x64 包；`dist/RF-Updater-linux-x64.tar.gz.sha256` 校验通过。
- 包内 `_internal/rf_updater/locales/` 三目录与 `_internal/qt-translations/` 三个 qm 均存在。
- `--version` 返回 0.5.0；`RF_UPDATER_LANG=en … verify` 输出 "Error: Install the game first."；`RF_UPDATER_LANG=zh-TW` 输出 "錯誤：請先安裝遊戲。"。
- Xvfb 中打包 GUI 窗口持续运行（scripts.smoke_native）。

## 远程 CI（三平台首次完整验证）

运行 [44088390829](https://github.com/CreateCN/RF-Updater/actions/runs/44088390829)（提交 `3cca732`）：**ubuntu-22.04 / windows-2022 / macos-15 全部 success**，各平台完成 offscreen 全量测试、高分屏检查、原生打包与窗口冒烟（Linux 另含 Xvfb/xcb 真实窗口交互）。

首次远程 CI 暴露并修复的跨平台问题（提交 `f5d1e92`→`3cca732`）：

- **Windows 引擎真实 bug**：`exclusive()` 探测读取被另一进程锁定的文件时抛裸 `PermissionError`；现将读取与加锁整体纳入竞争处理，统一转为 `UpdaterError`。
- **Windows offscreen 字体数据库不枚举系统字体**（诊断实锤：app font="Sans Serif"，Segoe UI/Arial 全缺失），泛型回退以全角渲染拉丁字符；修复为候选族缺失时按语言/平台 `addApplicationFont` 注册已知系统字体文件，并以 QSS 强制字体族、应用字体改用逻辑像素基准。
- **布局韧性**：长复选框/按钮文案三语言精简、标题类标签允许换行、语言下拉改最小内容长度策略——不再依赖特定字体度量。
- **测试跨平台**：临时目录统一 `resolve()`（macOS `/var`→`/private/var`、Windows 8.3 短路径）；伪造运行会话用 `_process_image()` 取真实进程镜像（macOS framework Python）；文本读取与 CLI 子进程显式 UTF-8；可执行位断言仅 POSIX。
- **Linux xcb**：补齐 xcb 依赖库后真实 X11 窗口交互通过。

## 已知限制

- 繁体术语以 TW 为准，zh-HK/zh-MO 共用 zh-TW 目录，未做地区独立目录。
- 语言切换时已存在的任务通知保留原语言直到下次操作；运行中任务的错误消息按抛出时语言显示。
- 代码签名与 macOS 公证仍未执行（需证书与 Apple 账号）；CI 只上传产物，不发布 Release。
- README/docs 正文为简体中文（软件界面已三语言，文档索引与 README 已双语）；游戏内容、官网链接、构建元数据不在本地化范围。
