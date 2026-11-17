# 0.2 验证记录

日期：2026-11-16（Asia/Shanghai）。本机 Linux x86_64、Python 3.14.4、PySide6/Qt 6.12.0，构建使用 PyInstaller 6.22.3。

## 回归与界面验收

- **60 项回归通过**：原有 51 项核心测试，加 1 项 Qt 外部环境清理测试和 8 项桌面验收。完整输出：[qt/test-results.txt](qa/qt/test-results.txt)。
- QtTest 使用真实回环 HTTP 和合成压缩包，覆盖安装、更新、校验、回退、重新安装、确认取消、错误详情和修复重试。
- 检查请求被阻塞时，已安装游戏仍能发起启动；官方请求返回 503 后，启动按钮仍可用，重试检查可恢复。
- 下载时切换页面，任务区域仍可取消；取消后保留部分文件，重试实际发送 Range 请求并完成校验。进度按 10 Hz 合并，测试不会将首个写入块与首个非零显示样本强行同步。
- 检查、安装进行中关闭窗口，会等待线程结束；已有安装保持不变。结果必须匹配任务 ID，过期信号不覆盖当前状态。
- 工作对象在任务结束后返回 GUI 线程，再统一销毁并等待线程最终清理。验收期间发现并修复过后台析构竞态和无父对象计时器访问已销毁控件的问题，最终测试未出现相关异常。
- 默认 1120×760、最小 900×640；100%、150%、200% 缩放；中文、长路径、复制、Tab 焦点、窄窗口收起插画及滚动均通过。150% 和 200% 的完整场景分别记录在 [scale-150](qa/qt/scale-150/test-results.txt)、[scale-200](qa/qt/scale-200/test-results.txt)。
- 原生 X11 场景使用 Xvfb/xcb；结果见 [native-test-results.txt](qa/qt/native-test-results.txt)。无显示服务器的交互使用 offscreen，不能将其等同于对应系统的原生桌面验收。

界面截图位于 [qa/qt](qa/qt)。除特别说明外，安装日期、包大小和构建信息来自合成测试包，不表示真实官方游戏版本。200% 的标志另有原生绘制高分屏检查图 `scale-200/vector-logo.png`。

## 旧数据兼容

读取 0.1 实测保留的 `/tmp/rf-live-test` 安装记录，Qt 版正确显示已安装且可启动，无需迁移。

```text
旧 state.json SHA-256：f27411b5cb5fafb5dc3b9314b5df6bc37f8148b9df2a10e865ca383a24e380db
读取前后字节一致，schema 保持 1。
启动文件：RocketFoundry-Linux-x86_64/RocketFoundry.x86_64
```

截图：[existing-0.1-install.png](qa/qt/existing-0.1-install.png)。没有复制测试游戏到用户默认数据目录，没有修改游戏存档。

## 打包与平台限制

原生包保留公共 CA、Qt 桌面插件、许可与第三方归属说明。自定义收集策略排除不使用的图片/文档引擎插件；检查生成目录中无 WebEngine、QML、QtQuick、QtPdf 或 Tk 组件。完整包体积会明显大于 0.1 的 Tk 版本。

本机 glibc 为 2.43，因此本机构建不代表可以运行于旧版 Linux。三平台 CI 仍使用 Ubuntu 22.04、Windows 2022、macOS 15，现已配置依赖安装、Qt 场景、高分屏场景、打包与窗口冒烟检查。**本工作区没有上传或执行远程 CI，也没有在 Windows/macOS 实机运行。**

源码 GUI 的 macOS 最低基线为 14；PyInstaller 的实际 macOS 包兼容性还受构建机部署目标约束。没有进行 Windows 代码签名或 Apple 公证，没有创建公开 Release。

## 本地程序升级

使用 `python -m scripts.install_linux --launch` 校验本地包摘要、安装到用户级版本目录并更新命令行与菜单入口。旧版目录和游戏数据均保留。默认数据目录、CLI 命令和安装记录不变。

最终压缩包解压到新临时目录后的检查已通过：

- `--version` 返回 `0.2.0`；CLI 与原有数据目录可直接使用。
- 将系统 CA 文件与目录指向不存在的位置，独立包仍通过附带 CA 验证官方 HTTPS，检查结果为 `current`。
- 原生 Qt 窗口在 Xvfb/xcb 中正常显示并持续运行，见 [native-bundle.png](qa/qt/native-bundle.png)。截图捕获时自动检查仍在执行，没有将检查中状态当成检查成功。
- 从独立包通过原有 CLI 启动真实官方 Linux 游戏，观察到首次隐私选择界面，见 [real-game-startup.png](qa/qt/real-game-startup.png)。没有替玩家作隐私选择或执行游戏操作；测试只结束自己创建的进程。

上述检查不是 Windows/macOS 原生验收，也不代表已测试实际游玩、联机或存档迁移。
