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

## 已知限制

- 繁体术语以 TW 为准，zh-HK/zh-MO 共用 zh-TW 目录，未做地区独立目录。
- 语言切换时已存在的任务通知保留原语言直到下次操作；运行中任务的错误消息按抛出时语言显示。
- Windows/macOS 的 qtbase 翻译与字体选择已实现但仅在本机 Linux 验证；远程 CI 未在本工作区执行。
- README/docs 正文仍为简体中文（软件界面已三语言）；游戏内容、官网链接、构建元数据不在本地化范围。
