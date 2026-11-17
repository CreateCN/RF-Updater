# 文档索引 / Documentation Index

## 当前文档 / Current documents

| 主题 Topic | 中文 | English |
| --- | --- | --- |
| 项目说明 Overview | [README.md](../README.md) | [README.en.md](../README.en.md) |
| 变更日志 Changelog | [CHANGELOG.md](../CHANGELOG.md)（双语 bilingual） | 同左 same |
| 架构总览 Architecture | [architecture.md](architecture.md) | [en/architecture.md](en/architecture.md) |
| 测试与构建 Testing & building | [testing.md](testing.md) | [en/testing.md](en/testing.md) |
| 本地化 Localization | [localization.md](localization.md) | [en/localization.md](en/localization.md) |
| 第三方许可 Third-party licenses | [third-party/README.md](third-party/README.md) | 同左 same |

## 历史记录 / Historical records

按版本归档的验证记录与截图，内容以当时版本为准，不随后续版本更新。
Version-archived verification records and screenshots; they describe the state at that version and are not updated afterwards.

| 版本 Version | 记录 Record | 截图 Screenshots |
| --- | --- | --- |
| 0.1（Tk） | [verification.md](verification.md) | [qa/](qa)（根目录图片 root images） |
| 0.2（Qt 改版 Qt redesign） | [verification-0.2.md](verification-0.2.md)、[design.md](design.md) | [qa/qt/](qa/qt) |
| 0.3（目录管理 directory management） | [verification-0.3.md](verification-0.3.md) | [qa/directories/](qa/directories) |
| 0.4（运行感知与韧性 running awareness & resilience） | [verification-0.4.md](verification-0.4.md) | 复用 qa/directories reuses qa/directories |
| 0.5（本地化 localization） | [verification-0.5.md](verification-0.5.md) | 合成夹具 synthetic fixtures |

其他参考 / Other references:

- [official-package-metadata.json](official-package-metadata.json) — 0.1 时期实测的官方三平台包元数据快照（历史证据，非运行时依赖）。Official package metadata snapshot measured during 0.1 (historical evidence, not a runtime dependency).
- 截图中的日期、包大小与摘要来自合成测试安装，不表示真实官方版本。Dates, sizes and digests in screenshots come from synthetic test installs, not real official versions.
