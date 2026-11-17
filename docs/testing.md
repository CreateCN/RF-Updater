# 测试与构建

**中文** | [English](en/testing.md)

## 环境准备

```sh
python -m venv .venv
# 激活 .venv
python -m pip install -e . -r requirements-build.txt
```

- Python 3.11+（本机验证使用 3.14.4）；运行依赖 `PySide6==6.12.0`；构建依赖 `pyinstaller==6.22.3`、`certifi==2026.10.23`。
- Linux 桌面测试需要 Qt 平台插件系统库：Debian/Ubuntu 安装 `libxcb-cursor0 libxkbcommon-x11-0 libegl1 libopengl0 libgl1 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-render-util0 fonts-noto-cjk`；真实 X11 窗口测试需要 `xvfb-run`。
- Windows PowerShell 用 `$env:QT_QPA_PLATFORM='offscreen'` 设置环境变量。

## 测试哲学

- **不触网、不运行真实游戏**：全部测试使用回环 HTTP 服务器（`tests/support.py` 的 `Server`）与微型合成 ZIP/TAR.GZ 包。运行感知测试使用本地 `sleep 30` 夹具进程，结束只终止自己创建的进程。
- **语言钉住**：`tests/__init__.py` 将 i18n 固定为 zh-CN，GUI 测试另以设置固定语言，任何 CI 机器区域下断言稳定。
- **真实控件验收**：Qt 场景通过 QTest 点击真实可见控件、等待真实线程与信号，不用 sleep 猜测时序（`wait_until` 轮询条件）。
- 截图与测试输出中的日期、包大小、摘要均来自合成安装，不代表官方版本。

## 运行测试

```sh
# 全量单元 + 集成 + Qt 场景（无显示服务器）
QT_QPA_PLATFORM=offscreen python -m unittest discover -v

# 仅 Qt 桌面验收（20 场景）
QT_QPA_PLATFORM=offscreen python -m scripts.qa_gui

# Linux 真实 X11 窗口
xvfb-run -a env QT_QPA_PLATFORM=xcb python -m scripts.qa_gui --screenshots docs/qa/qt

# 高分屏验收
QT_QPA_PLATFORM=offscreen QT_SCALE_FACTOR=1.5 python -m scripts.qa_gui
QT_QPA_PLATFORM=offscreen QT_SCALE_FACTOR=2 python -m scripts.qa_gui

# 三语言目录键/参数一致性
python -m scripts.i18n_report

# 单个测试
QT_QPA_PLATFORM=offscreen python -m unittest tests.test_engine.EngineTests.test_full_install_update_verify_rollback -v
```

当前规模：**112 项测试**（archive 18、engine 19、gui 20、i18n 9、cli 5、logbook 4、network 17、runtime 4、storage 16），其中 20 项为 Qt 场景。

## 验收矩阵（每次发布前）

| 环境 | 命令 | 说明 |
| --- | --- | --- |
| offscreen | `unittest discover` | 全量，无窗口系统 |
| Xvfb/xcb | `scripts.qa_gui` | Linux 真实 X11 窗口 |
| 150% / 200% | `QT_SCALE_FACTOR` + `qa_gui` | 高分屏逻辑像素布局 |
| 独立包冒烟 | `scripts.smoke_native dist/RF-Updater/RF-Updater` | 打包窗口持续运行 |
| CLI 语言 | `RF_UPDATER_LANG=en/zh-TW … verify` | 独立包多语言输出 |
| 摘要 | `sha256sum -c dist/*.sha256` | 产物完整性 |

Windows/macOS 原生验收、代码签名与 macOS 公证必须在对应环境执行；offscreen 通过不等同于对应系统的原生桌面验收。

## 打包

```sh
python -m scripts.build
```

- 仅在当前操作系统构建（禁止交叉编译）：Linux → `dist/RF-Updater/` + `RF-Updater-linux-x64.tar.gz`；Windows → ZIP；macOS → `RF-Updater.app` + ditto ZIP。各附 `.sha256`。
- 收集：Qt 桌面插件（自定义 hook 剔除图片/文档查看器插件）、Mozilla CA 与许可、`rf_updater/locales/*.json`、`qtbase_{en,zh_CN,zh_TW}.qm`、第三方许可、README/LICENSE/docs。
- 排除：WebEngine、QML、QtQuick、QtPdf、Tk、UPX。
- Linux 本机安装：`python -m scripts.install_linux --launch`（核对摘要、保留旧版、更新 `~/.local/bin/rf-updater` 与菜单入口，不动游戏数据）。

## CI

[.github/workflows/ci.yml](../.github/workflows/ci.yml)：ubuntu-22.04 / windows-2022 / macos-15 三平台，Python 3.13：

1. 安装运行与构建依赖（Linux 另装 Qt 系统库与 Noto CJK 字体）
2. offscreen 全量测试
3. Linux Xvfb/xcb 交互检查
4. 150% / 200% 高分屏检查
5. 原生打包 + 程序窗口冒烟
6. 上传产物（不自动发布 Release）

Linux 用 Ubuntu 22.04 构建以保证较旧 glibc 基线；本机 glibc 2.43 构建仅在当前系统验收。

## 新增测试约定

- 引擎/存储测试放 `tests/test_<module>.py`，复用 `Server` 与合成包夹具；临时目录用 `tempfile.TemporaryDirectory` + `addCleanup`。
- GUI 场景加入 `tests/test_gui.py` 的 `GuiTests`：用 `open_window()`/`click()`/`idle()`/`wait_until()`，模态对话框用 `patch.object(window, "confirm", …)` 或 QTimer 检查真实对话框；截图用 `capture(name)`（`RF_QA_SCREENSHOTS` 环境变量启用）。
- 涉及用户可见文本的断言使用 zh-CN 文案（套件已钉住）；新增 i18n 键必须三语言同步并通过 `scripts.i18n_report`。
