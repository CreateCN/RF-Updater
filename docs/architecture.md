# 架构总览（0.5）

**中文** | [English](en/architecture.md)

本文描述当前代码结构与设计约束。0.2 改版时的原始设计决策见 [design.md](design.md)（历史文档）。

## 分层

```text
┌─────────────────────────────────────────────────────────┐
│ GUI（PySide6 Qt Widgets）                                │
│   gui.py            窗口组装、页面、语言切换、托盘、定时   │
│   ui/controller.py  QThread worker 任务模型、状态与通知    │
│   ui/widgets.py     面板/详情/任务区/绘图控件              │
│   ui/directories.py 目录页（选择/统计/清理）               │
│   ui/theme.py       设计令牌、按语言选字体                 │
├─────────────────────────────────────────────────────────┤
│ 引擎（纯标准库，CLI 共用，零 Qt 依赖）                    │
│   engine.py      锁、代际安装、校验、回退、启动、运行感知   │
│   network.py     HTTPS、探测、续传、摘要、重试异常类型      │
│   archive.py     受限解压（ZIP/TAR.GZ）                   │
│   storage.py     有界清点、切换、清理                     │
│   preferences.py 目录记忆与设置持久化                     │
│   models.py      Release/错误类型/原子 JSON              │
│   runtime.py     外部进程环境清理                        │
│   logbook.py     诊断日志（JSON 行、轮转）                │
│   i18n.py        三语言目录、t()、locale 检测             │
├─────────────────────────────────────────────────────────┤
│ 入口：__main__.py（CLI 七命令，延迟导入 GUI）             │
│       run_updater.py（PyInstaller 入口）                  │
└─────────────────────────────────────────────────────────┘
```

**核心约束**：引擎层不导入 Qt。CLI 在无显示器、无 PySide6 的环境下可用；GUI 只是引擎的一个消费者。翻译因此放在标准库 `i18n.py` 而非 Qt tr 体系。

## 数据与信任边界

- 安装记录 `state.json` 沿用 schema 1：`active`/`previous` 双指针，读取时全面校验（字段类型、代际目录合法性、路径不越界）。
- **代际事务安装**：每次安装写入独立 `installs/<构建标识>-<ID>/`；提交（原子替换 state.json）前失败则整代删除，提交开始后即使中断也保留完整新代。不完整代际永不被指针引用，也不自动删除（可能含可恢复数据）。
- **构建标识**：`Release.identity` = sha256(平台, URL, 证据, 大小)[:20]，证据优先官方 SHA-256，其次 ETag、修改时间；跨 CDN 重定向与签名 URL 过期保持稳定。ETag/修改时间不是游戏内版本号；无法比较时明确提示 `unknown`。
- **校验诚实**：有官方 SHA-256 才声称已核对；否则仅传输长度 + 压缩包完整性 + 本地摘要。本地摘要不等于发布者签名。
- **网络安全**：下载与重定向逐跳强制 HTTPS；frozen 包加载内置 Mozilla CA；续传用 Range + If-Range，206 响应严格核对 Content-Range；`Repr-Digest` 与 `Content-Digest` 区分（206 的 Content-Digest 只哈希区间）。
- **解压防御**：拒绝绝对路径/`..`/反斜杠/冒号/Windows 保留名/尾随点空格；win/mac 大小写折叠碰撞检测；文件先写、链接后建；符号链接创建前后双重越界检查；硬链接必须指向已校验文件；16 GiB / 10 万文件上限；显式读尽 gzip 尾部验证 CRC。
- **并发**：`.updater.lock` OS 锁（msvcrt/flock），进程死亡自动释放，永不删除锁文件。
- **用户数据**：旧安装与缓存不自动删除；清理需显式勾选，当前/回退版本硬保护，旧安装需备份确认；整批先验证再逐项删除，失败按项报告。扫描不跟随符号链接/junction，250,000 节点 / 2,000 项上限。
- **失联目录**：保存的位置不可用时提示连接磁盘或换位置，绝不重建到其他卷（诊断日志也遵守此约束）。

## 任务模型（GUI）

- QObject `Worker` 移入 QThread 执行引擎调用；结果/异常/进度经信号回主线程，进度约 10 Hz 合并。
- 检查任务与变更任务分轨：检查期间仍可启动游戏；安装/校验/回退/清理串行。
- 结果必须匹配当前任务 ID，过期信号丢弃；检查失败只清除远端信息，保留本地启动能力。
- 取消用 `threading.Event`，在下载/摘要/解压块之间检查；关闭时禁新任务、等待线程结束，不 terminate。
- Worker 结束时在自身线程内 `moveToThread` 回 GUI 线程，`thread.wait()` 后统一 `deleteLater`，规避 Shiboken 跨线程销毁竞态。

## 运行感知与韧性（0.4）

- `launch()` 写 `game-session.json`（PID、可执行路径、命令、代际）；`game_running()` 以进程存活 + 可执行路径匹配判定（Linux `/proc/<pid>/exe` 与 cmdline 兜底脚本包装器；Windows `QueryFullProcessImageNameW`；macOS `proc_pidpath`，`open -W` 以等待进程存活判定）。PID 复用不误判；镜像不可读时保守视为运行中。
- 运行中：引擎拒绝安装/回退，存储层拒绝清理旧安装，GUI 禁用相应按钮并显示“运行中”；GUI 每 2 秒轮询，退出后自动恢复。
- 下载重试：仅 `NetworkInterrupted`（连接错误、响应截断）触发 2s/8s/32s 可取消退避，最多 3 次；续传缓存保留进度。校验不符、HTTP 错误、构建变化保持致命。
- 诊断日志：`logbook.record()` 逐事件开关文件（无持久句柄，测试夹具安全），1 MB 轮转保留 3 份；根目录不存在即跳过。

## 本地化（0.5）

- `i18n.py`：`t(key, **params)` 当前语言 → 源语言（zh-CN）回退；复数按 `count` 选 one/other；损坏目录静默降级。
- 检测：GUI `QLocale.system()`（繁体脚本/TW/HK/MO → zh-TW，其余中文 → zh-CN，其他 → en）；CLI `RF_UPDATER_LANG` > `LC_ALL` > `LC_MESSAGES` > `LANG`，未设置 → zh-CN。
- 切换：`settings.json` 的 `language`（null=跟随系统）；跟随模式每次启动重检测 + `LocaleChange` 即时跟随；手动选择即时生效（`retranslate()` 静态文本 + 每帧 `t()` 动态文本 + qtbase 翻译器 + 字体 + 托盘菜单）。
- 详见 [本地化说明](localization.md)。

## 打包

- PyInstaller 6.22.3 onedir，仅 Qt Core/Gui/Widgets；自定义 QtGui hook 只保留桌面平台插件；排除 WebEngine/QML/QtQuick/QtPdf/Tk。
- 随包：Mozilla CA（certifi）、`rf_updater/locales/*.json`、`qtbase_{en,zh_CN,zh_TW}.qm`、第三方许可。
- 启动外部进程前恢复 `LD_LIBRARY_PATH`/DLL 搜索目录，仅剔除指向 `_MEIPASS` 的 Qt 插件路径。
- 禁止跨平台交叉编译；Linux 构建受构建机 glibc 限制。

## 测试结构

112 项测试 + 20 项 Qt 场景，全部使用回环 HTTP 与合成包（运行感知用本地 sleep 夹具），不触网、不运行真实游戏。套件钉住 zh-CN。详见 [测试与构建](testing.md)。
