# 当前文档索引

本索引只列当前入口、功能协议和可运行样例。组件版本见[仓库 README](../README.md#当前版本)，
行为以源码、Schema 和 CLI 为准。历史开发记录统一位于[归档目录](archive/README.md)，不作为 Agent 默认上下文。

## 按任务阅读

| 任务 | 文档 |
| --- | --- |
| 了解组件、版本和完整入口 | [仓库 README](../README.md)、[快速开始](../QUICKSTART.md) |
| Agent 端到端生成或修订 | [总调度 Skill](../Total-pipe/skills/total-pipe-deck/SKILL.md)、[中文使用说明](../Total-pipe/docs/USAGE.zh-CN.md) |
| 安装、环境、字体和平台要求 | [环境清单](../Total-pipe/环境清单.md) |
| 从 canonical Deck IR 编译 | [编译器 README](../Total-pipe/README.md)、[Deck IR / 公式协议](../Total-pipe/docs/deck-compiler-v2.md) |
| 开发、检查或更新文档 | [开发与文档维护](development.md)、[文档同步 Skill](../Total-pipe/skills/total-pipe-doc-sync/SKILL.md) |

## 独立组件

| 组件 | 当前手册 |
| --- | --- |
| PaperWorkflow | [README](../PaperWorkflow/README.md) |
| pwf2rpa | [README](../Total-pipe/pwf2rpa/README.md) |
| Research PPT Assistant | [README](../research-ppt-assistant/README.md)、[中文用法](../research-ppt-assistant/docs/USAGE.zh-CN.md)、[Skill](../research-ppt-assistant/skills/research-ppt-assistant/SKILL.md) |
| WSL2 / DeepSeek Harness 的特定对接 | [对接说明](../PaperWorkflow/DeepSeek-Harness对接与使用.md)，只在该部署场景下阅读 |
| 本地项目 MCP 包装 | [local-project-mcp-bridge Skill](../Total-pipe/skills/local-project-mcp-bridge/SKILL.md)，不属于默认 PPT 生成流程 |

## Deck IR 与后端协议

| 能力 | 文档 |
| --- | --- |
| 整套 Design、提案和完整术语 | [科研视觉规划](../Total-pipe/docs/scientific-visual-planner.md) |
| 递归内容区域与 RPA 子布局 | [复合布局](../Total-pipe/docs/composite-layouts.md) |
| 边框、标题色带和 takeaway 框选 | [边框容器](../Total-pipe/docs/framed-containers.md) |
| 原生列表、标记样式 / 颜色和实测容量 | [原生列表](../Total-pipe/docs/native-lists.md) |
| 独立公式、矩阵与图片来源 | [Deck IR 协议](../Total-pipe/docs/deck-compiler-v2.md) |
| 文字与原生数学混排 | [行内公式](../Total-pipe/docs/inline-math.md) |
| 合并表头、公式格和行高 | [原生科研表格](../Total-pipe/docs/native-tables.md) |
| 流程、DAG、连接符与图文共存 | [原生流程图](../Total-pipe/docs/native-graphics.md) |
| 机制、架构、漏斗、Bézier 与 Path | [科研图形组件](../Total-pipe/docs/native-components.md) |
| 外部布局建议和回退 | [布局提供方](../Total-pipe/docs/layout-provider.md) |
| OfficeCLI 写入与实际结构 QA | [OfficeCLI 后端](../Total-pipe/docs/officecli-backend.zh-CN.md) |
| 可选的启发式质量分析 | [质量指标](../Total-pipe/docs/QUALITY_METRICS.md)，不能替代真实验收 |
| 输入及上游反馈的机器契约 | [Deck IR Schema](../Total-pipe/schemas/deck-ir.schema.json)、[布局反馈 Schema](../Total-pipe/schemas/layout-feedback.schema.json) |

## 样例和展示图

- [复杂混排单页](../Total-pipe/examples/complex-mixed/README.zh-CN.md)：PPTX、Deck IR、参考素材及检查记录。
- [行内公式样例](../Total-pipe/examples/inline-math.deck_ir.json)、[矩阵推导样例](../Total-pipe/examples/matrix-derivation.deck_ir.json)。
- [原生表格](../Total-pipe/examples/native-table.deck_ir.json)、[边框容器](../Total-pipe/examples/framed-containers.deck_ir.json)、[原生图形](../Total-pipe/examples/native-components.deck_ir.json)。
- [README 展示图来源与隐私检查](images/README.md)。

## 历史资料

[统一归档索引](archive/README.md)记录旧 Agent 指南、开发总结、v26 实验和旧发布清单的去向。
旧文档索引已换成当前索引入口；旧完整正文仍在归档。默认 `rg` 排除归档，历史检索使用：

```bash
rg --no-ignore '要查的历史主题' docs/archive
```
