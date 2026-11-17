# 验证记录

验证日期：2026-11-16（Asia/Shanghai）。本地系统为 Linux x86_64，Python 3.14.4，Tk 8.6；打包使用 PyInstaller 6.22.3。没有将测试中成功启动解释为全功能游戏验收。

## 自动化与桌面流程

- `python3 -m unittest discover -v`：**51 项通过**。完整输出见 [qa/test-results.txt](qa/test-results.txt)。
- 本地 HTTP 测试覆盖 HEAD 回退、HTTPS 重定向策略、Range/If-Range、服务器忽略或错误返回 Range、构建变化、截断响应、取消恢复、摘要错误，以及部分响应摘要不能用于整包校验。
- 安装测试覆盖 ZIP/TAR.GZ、gzip 尾部 CRC 校验、提前拒绝超限 TAR 声明、Windows EXE/macOS bundle/Linux 可执行文件识别、路径与链接攻击、资源上限、跨进程锁竞争、校验损坏、更新与回退、提交失败和提交后中断。TAR 硬链接使用原生链接，避免复制导致磁盘放大。
- `scripts.qa_gui`：在真实 Tk 窗口执行检查 → 安装 → 文件校验 → 更新 → 回退 → HTTP 错误 → 重试 → 无缓存元数据的重新安装，全部通过。窗口 1120×760、920×680；小窗口保留可滚动内容与操作按钮。
- `scripts.smoke_native`：实际打开 PyInstaller Linux 更新器，窗口持续运行，自动检查取得官方最新构建元数据。见 [qa/native-bundle.png](qa/native-bundle.png)。
- 最终 TAR.GZ 解压到新目录后，重新检查原生窗口和真实游戏启动。将 `SSL_CERT_FILE`、`SSL_CERT_DIR` 指向不存在的位置，打包程序仍通过附带的公共 CA 完成官方 HTTPS 检查并返回 `current`；证书和主机名验证均保持启用。

截图 [qa/home.png](qa/home.png)、[qa/installed.png](qa/installed.png)、[qa/manage.png](qa/manage.png)、[qa/error.png](qa/error.png) 为合成测试安装的真实控件状态。它们不表示对应时间或摘要是官方版本信息；原生包截图和下面的真实包验证独立记录。

## 官方 Linux 包端到端验证

起初直连官网曾出现 TLS 错误；后续官方 API 读请求、完整下载安装均成功，没有跳过证书验证。

```text
官方下载：https://api.rocketfoundry.net/download/linux
Content-Length：563974010 bytes（约 537.8 MiB）
ETag："88bbe4729a4ad86249acf796f61a81bc-68"
Last-Modified：Sun, 15 Nov 2026 21:57:31 GMT
响应提供 SHA-256：否
本地包 SHA-256：bb6934a46abd01102f97b75c8c228c4936af71e7be73f2237cd1b421c503d94a
解压内容：1112254889 bytes
校验清单：226 个文件
启动文件：RocketFoundry-Linux-x86_64/RocketFoundry.x86_64
```

使用隔离目录 `/tmp/rf-live-test` 验证：

```sh
python3 -m rf_updater --root /tmp/rf-live-test install
python3 -m rf_updater --root /tmp/rf-live-test verify
python3 -m rf_updater --root /tmp/rf-live-test check
```

结果：成功下载、解压、切换 active；226 个文件校验通过；再次检查返回 `current`。安装包和游戏只保存在临时验收目录，没有纳入源码或构建产物。

分别从源码引擎和打包后的 Linux 更新器启动真实游戏。为游戏指定临时 XDG 数据、配置与缓存目录，在 Xvfb 中观察到游戏首次隐私选择界面。**没有选择允许、拒绝或进行游戏操作**。见 [qa/real-game-startup.png](qa/real-game-startup.png)。游戏输出报告 Godot 引擎和 Vulkan 初始化，说明进程、数据包和运行环境已加载。未测试实际游玩、联机、存档迁移或 GPU 性能。

```sh
xvfb-run -a -s '-screen 0 1280x900x24' python3 -m scripts.smoke_native \
  --game-root /tmp/rf-live-test \
  --launcher dist/RF-Updater/RF-Updater
```

验收脚本只关闭自己创建的进程组；游戏模态窗口未响应 SIGTERM 时会强制结束该测试进程，避免遗留游戏进程。这不属于更新器的正常关闭行为。游戏截图中的内容与商标归 Rocket Foundry 权利人所有。

## Windows 与 macOS

通过官方 HTTPS HEAD 与最多 1 MiB 的 ZIP 尾部 Range 请求实际确认：

| 平台 | 压缩大小 | ZIP 成员 | 启动文件 |
| --- | ---: | ---: | --- |
| Windows x64 | 573569754 bytes | 228 | `RocketFoundry.exe` |
| Apple Silicon macOS | 565222158 bytes | 230 | `Rocket Foundry.app/Contents/MacOS/Rocket Foundry` |

元数据见 [official-package-metadata.json](official-package-metadata.json)。两个响应都返回 ETag、Last-Modified，没有 SHA-256；Range 请求返回 206。它们的实际文件结构与当前发现逻辑一致。没有下载它们的完整压缩包，也没有在 Linux 上冒充完成 Windows/macOS 原生运行验收。

Windows 和 macOS 的合成包结构测试在本机通过。[CI](../.github/workflows/ci.yml) 已配置在 Windows x64、Linux x64、macOS ARM64 分别运行测试、打包和命令行冒烟检查；**尚未从此工作区上传或运行 GitHub Actions**。原生窗口、真实官方完整安装和启动仍应在对应系统验收。

## 可交付构建

Linux 独立应用位于 `dist/RF-Updater/`，压缩包 `dist/RF-Updater-linux-x64.tar.gz`，同名 `.sha256` 提供构建文件摘要。该包在本机实际启动并读取官方元数据。它依赖构建机 glibc（本机为 2.43），不代表能在 Ubuntu 22.04 上运行；CI 使用 Ubuntu 22.04 构建以降低 glibc 基线。

Windows/macOS 的构建与签名未在本机执行。程序没有公开发布，没有创建 Release，也没有官方背书或发布签名。将来公开分发时需执行目标平台原生验收与签名、公证流程。
