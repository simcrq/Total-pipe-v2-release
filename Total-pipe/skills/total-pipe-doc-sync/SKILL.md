---
name: total-pipe-doc-sync
description: 在 Total-pipe 仓库开发、修复或修改接口后，同步 README、中文用法、环境需求与相关协议，清理过时说明，并在提交或合并前检查文档与源码是否一致。用于项目开发收尾；单次生成或编辑 PPTX 不触发。
---

# Total-pipe 开发后文档同步

把文档同步作为本次开发的收尾步骤，在已有授权范围内直接完成编辑。
先确认仓库根目录含 `Total-pipe/`、`PaperWorkflow/`、`research-ppt-assistant/`；
所有路径相对该根目录，不依赖某个本机 checkout 或插件缓存。

## 根据实际变更选择文档

检查本次 diff、暂存内容与新增文件；继续开发或合并时，也纳入本次尚未交付的相关提交。
用实际实现、CLI 参数、Schema、依赖清单和已有验证记录确认行为。

| 变更涉及 | 同步位置 |
| --- | --- |
| 组件职责、完整入口、当前能力、产品 / 协议版本 | `README.md`；编译器相关入口另同步 `Total-pipe/README.md` |
| 使用步骤、MCP / CLI、输入输出、Design、验收与失败修订 | `Total-pipe/docs/USAGE.zh-CN.md`；影响 Agent 操作时同步 `Total-pipe/skills/total-pipe-deck/SKILL.md` |
| Python / Node / OfficeCLI、字体、OCR、API 配置、平台要求 | `Total-pipe/环境清单.md` 和 README 的环境摘要；真实依赖仍以 requirements / pyproject / package.json 为准 |
| Deck IR、公式、复合布局、表格、原生图形或容量策略 | `Total-pipe/docs/` 中对应功能协议；必要时同步 Schema 与可运行示例 |
| PWF、pwf2rpa 或 RPA 的独立行为 | 对应组件 README；影响 RPA Agent 操作时另同步其 Skill |
| 顶层快速开始与新入口冲突 | `QUICKSTART.md`；保持精简并指向当前操作手册 |

只修改与本次行为有关的文档。历史报告保留其原始日期与性质，主入口明确它们是历史记录。
替换或删除过时段落，避免在旧说法后追加相互矛盾的新说明。

## 项目中容易写错的事实

- 完整入口是总调度 Skill；`totalpipe.py generate` 从已有 canonical Deck IR 开始。
- Story、RPA、Deck IR 后的 Scientific Visual Planner 各有职责；Design 是默认必做阶段。
  提示包工具只准备输入；RPA 计划到 canonical IR 的语义映射由 Agent 完成。
- RPA 规划相对结构；Deck Compiler 决定最终几何；OfficeCLI 写 PPTX。
- 产品插件、组件包、MCP 握手和文件协议的版本分开列出；从实际清单读取，
  不把旧 MCP 版本当成产品版本，也不为文档同步自行发版。
- 编译器依赖与完整 PWF 环境分开说明。候选生成、结构 QA、PowerPoint 原生验收和 final 晋级分开表述。
- 公式写明当前支持语法、启用方式和未支持范围；混排行高按实际测量解释，字符预算只作粗筛。
- 保留完整正确的科学术语。文字容量例外可带 REVIEW 保留全文；公式、图形、原图等真实空间门禁如实说明。

## 提交前核对与报告

检查本次文档中的本地链接、工作目录、命令参数、示例字段、版本和依赖是否与源码一致。
区分已运行的测试 / 原生验收和未执行项；不复制历史测试总数、性能比例或交付时长作为当前承诺。
文档检查不自动扩大为完整测试；按用户对本次实现的验证要求执行。

提交前完成相关文档编辑；若本次实现确实不影响文档，简短说明依据即可。
最终报告列出关键文档、实现与验证结论，只有实际完成后才报告 commit / merge / push。
本 Skill 提供 Agent 工作流提醒，自动选用依赖宿主加载；它不创建 Git hook 或定时任务。
