# 历史文档归档

本目录保存已过时的发布说明、开发记录、旧 Agent 指南、实验命令和原始清单。**不是当前使用说明或能力承诺。**

当前入口为[仓库 README](../../README.md)和[当前文档索引](../README.md)。默认搜索通过根目录 `.ignore` 排除本目录；需要溯源时显式使用 `rg --no-ignore '历史主题' docs/archive`。

## 归档清单

目录保留原仓库的相对层级；原文日期和结论保留。Markdown 增加历史提示并修正可确定的相对链接，旧的失效路径和命令只作为历史文字保留。

| 原路径 | 归档文件 | 当前替代 |
| --- | --- | --- |
| `AI_USAGE_GUIDE.md` | [记录](AI_USAGE_GUIDE.md) | [当前文档索引](../README.md) |
| `CONTENT_CAPACITY_ANALYSIS.md` | [记录](CONTENT_CAPACITY_ANALYSIS.md) | [当前文档索引](../README.md) |
| `FIXES_SUMMARY.md` | [记录](FIXES_SUMMARY.md) | [当前文档索引](../README.md) |
| `IMPLEMENTATION_SUMMARY.md` | [记录](IMPLEMENTATION_SUMMARY.md) | [当前文档索引](../README.md) |
| `README_FINAL.md` | [记录](README_FINAL.md) | [当前文档索引](../README.md) |
| `RELEASE_README.md` | [记录](RELEASE_README.md) | [当前文档索引](../README.md) |
| `SOLUTION_COMPLETE.md` | [记录](SOLUTION_COMPLETE.md) | [当前文档索引](../README.md) |
| `TESTING_GUIDE.md` | [记录](TESTING_GUIDE.md) | [当前文档索引](../README.md) |
| `V3_EXPERIMENT_REPORT.md` | [记录](V3_EXPERIMENT_REPORT.md) | [当前文档索引](../README.md) |
| `VISUAL_SUMMARY.md` | [记录](VISUAL_SUMMARY.md) | [当前文档索引](../README.md) |
| `COMMIT_MESSAGE.txt` | [记录](COMMIT_MESSAGE.txt) | [当前文档索引](../README.md) |
| `V3_INTEGRATION_MANIFEST.json` | [记录](V3_INTEGRATION_MANIFEST.json) | [当前文档索引](../README.md) |
| `SHA256SUMS` | [记录](SHA256SUMS) | [当前文档索引](../README.md) |
| `Total-pipe/IMPLEMENTATION_COMPLETE.md` | [记录](Total-pipe/IMPLEMENTATION_COMPLETE.md) | [当前文档索引](../README.md) |
| `Total-pipe/PRIORITY_1_2_IMPLEMENTATION.md` | [记录](Total-pipe/PRIORITY_1_2_IMPLEMENTATION.md) | [当前文档索引](../README.md) |
| `Total-pipe/SUMMARY.md` | [记录](Total-pipe/SUMMARY.md) | [当前文档索引](../README.md) |
| `Total-pipe/DOCUMENTATION_INDEX.md` | [记录](Total-pipe/DOCUMENTATION_INDEX.md) | [当前文档](../../Total-pipe/DOCUMENTATION_INDEX.md) |
| `Total-pipe/docs/QUALITY_METRICS.md` | [记录](Total-pipe/docs/QUALITY_METRICS.md) | [当前文档](../../Total-pipe/docs/QUALITY_METRICS.md) |
| `Total-pipe/docs/composite-layout-development.md` | [记录](Total-pipe/docs/composite-layout-development.md) | [当前文档索引](../README.md) |
| `Total-pipe/docs/next-stage-tasks.md` | [记录](Total-pipe/docs/next-stage-tasks.md) | [当前文档索引](../README.md) |
| `Total-pipe/docs/v3-experiment.md` | [记录](Total-pipe/docs/v3-experiment.md) | [当前文档索引](../README.md) |

| `Total-pipe/docs/inline-math.md` | [记录](Total-pipe/docs/inline-math.md) | [当前文档](../../Total-pipe/docs/inline-math.md) |
| `Total-pipe/docs/layout-provider.md` | [记录](Total-pipe/docs/layout-provider.md) | [当前文档](../../Total-pipe/docs/layout-provider.md) |

## 追溯与清单

[catalog.json](catalog.json) 记录原路径、归档路径、整理前后 SHA-256 和替代文档。原始版本可从 `2d20361` 及其历史提交追溯。
原 `SHA256SUMS`、`V3_INTEGRATION_MANIFEST.json` 和旧提交说明按原字节保存，它们描述旧快照，不能用于校验当前仓库、部署当前模型或自动认定发布完成。

归档中的代码片段和 Agent 提示不构成现行指令；只在用户明确查询历史时读取。
