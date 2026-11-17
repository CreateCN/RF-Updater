# 本地化说明（0.5）

**中文** | [English](en/localization.md)

## 机制

- 翻译核心是纯标准库模块 `rf_updater/i18n.py`，引擎与 CLI 不导入 Qt。
- 语言资源为 `rf_updater/locales/{zh-CN,zh-TW,en}.json`，扁平键值，约 340 键。zh-CN 是源语言真值。
- `t(key, **params)`：当前语言查找 → `str.format` 插值；缺失键回退 zh-CN；仍缺返回键名本身（可见但不致命）。
- 复数：值为 `{"one": ..., "other": ...}` 时按 `count` 参数选择（英文区分单复数，中文两形相同）。
- Qt 标准对话框（QFileDialog、QMessageBox 标准按钮）由 GUI 层加载 PySide6 自带的 `qtbase_{en,zh_CN,zh_TW}.qm`（QTranslator），与应用字符串体系互补。

## 键约定

- 命名空间：`engine.*`、`net.*`、`archive.*`、`storage.*`、`prefs.*`（引擎/CLI 错误与状态）、`gui.*`（窗口文本）、`task.*`（任务阶段与通知）、`dir.*`（目录页）、`cli.*`（命令行输出）。
- 语义化命名，如 `engine.game_running`、`task.install_done`、`dir.cleanup_accept`。
- 动态值一律作参数：路径、URL、ETag、SHA-256、数字、日期。模板用 `{name}`；字面花括号写 `{{}}`。
- 机器可读内容不翻译：`state.json`/receipt 字段、logbook 事件键、JSON 输出键、构建标识。
- 日期保持 `%Y-%m-%d %H:%M`，容量单位保持 B/KiB/MiB/GiB。
- 语言名用各自母语显示（简体中文 / 繁體中文 / English），不随界面语言变化。

## 语言检测与切换

- GUI 初始化：`settings.json` 的 `language`（`null`=跟随系统）→ `QLocale.system()`；繁体脚本或 TW/HK/MO → zh-TW，其余中文 → zh-CN，其他 → en。
- 跟随系统模式下每次启动重新检测；运行中 `QEvent.LocaleChange` 触发即时切换（手动固定语言时忽略）。
- CLI：`RF_UPDATER_LANG` > `LC_ALL` > `LC_MESSAGES` > `LANG`，均未设置 → zh-CN。
- 切换流程：`i18n.use` → 重载 qtbase 翻译器 → 按语言重选字体 → `App.retranslate()`（静态文本）+ `refresh()`（动态文本）→ 重建托盘菜单。无需重启。
- 已存在的任务通知保留产生时的语言，直到下次操作（历史消息语义）。
- 字体：zh-TW 优先 Microsoft JhengHei UI / PingFang TC / Noto Sans CJK TC；zh-CN 优先 Microsoft YaHei UI / PingFang SC / Noto Sans CJK SC；en 用系统默认。

## 新增语言步骤

1. 在 `rf_updater/i18n.py` 的 `LOCALES` 加入新目录 ID，并在 `match_name`/GUI 检测中补充映射。
2. 复制 `zh-CN.json` 为新目录文件，逐键翻译；保持键集合与模板参数完全一致。
3. `preferences.py` 的 language 合法值、`gui.py` 的 `LANGUAGE_NAMES` 与 qtbase 映射、`scripts/build.py` 的 qm 收集列表同步更新。
4. 运行 `python -m scripts.i18n_report` 确认无缺失键/参数差异；运行全量测试。
5. 在 `tests/test_i18n.py` 与 GUI 语言场景中补充新语言断言。

## 维护与测试

- `python -m scripts.i18n_report`：扫描源码中 `t("key")`、辅助函数键参数字面量与 f-string 动态前缀，对照三目录报告缺失/未用键与参数集合差异；缺键或参数不一致时退出码 1。
- `tests/test_i18n.py`：目录键/参数一致性、回退链、复数、插值安全、locale 映射、环境变量优先级、损坏目录不崩。
- `tests/test_cli.py`：子进程实测 CLI 语言选择。
- `tests/test_gui.py`：语言切换与持久化、初始化自动检测、LocaleChange 跟随、英文最小窗口布局、无原始键泄漏。
- 测试套件在 `tests/__init__.py` 钉住 zh-CN，GUI 测试另以设置固定语言，保证任何 CI 机器区域下断言稳定。

## 打包

- setuptools package-data 与 PyInstaller `--add-data` 均收集 `rf_updater/locales/*.json` 与三个 `qtbase_*.qm`（后者置于包内 `qt-translations/`）。
- 运行时目录加载优先 `importlib.resources`，回退 `Path(__file__)`；frozen 下 qtbase 从 `sys._MEIPASS/qt-translations` 加载。
