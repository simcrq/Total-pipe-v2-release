# Total-pipe AI 工程索引

按当前任务选一条入口。生成和修订任务按 `next_action` 读取指定的完整任务书、提示包和 Schema。
编写 IR 时可先检索样例库，再打开命中的单项。接口以当前源码、Schema 和 CLI 为准。

## 按任务阅读

| 任务 | 文档 |
| --- | --- |
| 浏览项目、看成品或开始使用 | [仓库首页](../README.md)、[快速开始](../QUICKSTART.md) |
| 了解全流程与阶段产物 | [完整流程与使用说明](../Total-pipe/docs/USAGE.zh-CN.md)、[组件入口](#独立组件) |
| Agent 端到端生成或修订 | [轻量接入 Skill](../Total-pipe/skills/total-pipe-agent/SKILL.md)、[四工具与恢复](../Total-pipe/docs/agent-adapter.md)；[完整规范](../Total-pipe/skills/total-pipe-deck/SKILL.md) |
| 从题目或问题生成可编辑 PPTX | [题目入口](../Total-pipe/docs/agent-adapter.md#从题目开始)、[PageScene 实现](../Total-pipe/docs/page-scene.md#题目模式) |
| Agent 接入层实施与评审 | [修订设计 v2](../Total-pipe/docs/agent-adapter-design.md) |
| 原子科学记录、两次源审读与观众表达（Story2.0 / 设计1.3） | [内容契约](../Total-pipe/docs/content-projection.md)、[原设计动机](audience-content-contract-design.md) |
| 旧内容契约1.2实现与回归（新协议见内容契约） | [验证记录](content-projection-validation.md) |
| AI 安装与宿主配置 | [一键安装](../INSTALL_FOR_AI.md) |
| 运行依赖、字体、平台和 MCP 服务启动 | [环境清单](../Total-pipe/环境清单.md)、[默认与 advanced profile](../Total-pipe/docs/agent-adapter.md#安装和-profile) |
| 从 canonical Deck IR 编译 | [编译器 README](../Total-pipe/README.md)、[Deck IR / 公式协议](../Total-pipe/docs/deck-compiler-v2.md) |
| 查当前组件与协议版本 | [版本来源](#版本来源) |
| 开发、检查或更新文档 | [开发与文档维护](development.md)、[文档同步 Skill](../Total-pipe/skills/total-pipe-doc-sync/SKILL.md) |

## 独立组件

| 组件 | 职责与入口 |
| --- | --- |
| Agent 接入层 | 调度任务、验证产物和恢复进度。[接入层协议](../Total-pipe/docs/agent-adapter.md) |
| PaperWorkflow | 接入论文、检索证据和导出资源。[组件手册](../PaperWorkflow/README.md) |
| pwf2rpa | 校验 Story 并将内容与来源转为 RPA 输入。[组件手册](../Total-pipe/pwf2rpa/README.md) |
| Research PPT Assistant | 为默认 Agent 链路规范化内容和传递引用，同时提供独立规划工具。[组件手册](../research-ppt-assistant/README.md)、[中文用法](../research-ppt-assistant/docs/USAGE.zh-CN.md)、[Skill](../research-ppt-assistant/skills/research-ppt-assistant/SKILL.md) |
| Deck Compiler 和 OfficeCLI | 测量与布局、生成 PPTX 并检查其结构。[编译器手册](../Total-pipe/README.md)、[写入与 QA](../Total-pipe/docs/officecli-backend.zh-CN.md) |
| WSL2 / DeepSeek Harness 的特定对接 | [对接说明](../PaperWorkflow/DeepSeek-Harness对接与使用.md)，只在该部署场景下阅读 |
| 本地项目 MCP 包装 | [local-project-mcp-bridge Skill](../Total-pipe/skills/local-project-mcp-bridge/SKILL.md)，不属于默认 PPT 生成流程 |

## Deck IR 与后端协议

| 能力 | 文档 |
| --- | --- |
| 整套 Design、提案和完整术语 | [科研视觉规划](../Total-pipe/docs/scientific-visual-planner.md) |
| PageScene：显式页面场景、job 接入、绑定门禁与页级原生预览 | [PageScene 集成](../Total-pipe/docs/page-scene.md) |
| 页面 recipe 最小闭环：无卡片、原生列表、行内公式 | [Page recipes pilot](../Total-pipe/docs/page-recipes.md) |
| 页面设计 1.1：Story 引用、绘图、排布与讲解走读 | [接入层：页面设计阶段](../Total-pipe/docs/agent-adapter.md#页面设计阶段page_design) |
| 页面设计 1.1 实际子代理样例与回归 | [验证记录](agent-page-design-validation.md) |
| 四工具候选后的 PowerPoint 导出、预览与真实 UI 复核 | [原生验收接入](../Total-pipe/docs/agent-adapter.md#原生-powerpoint-验收接入) |
| IR 编写过程的选页渲染与看图修订 | [选页渲染接口](../Total-pipe/docs/agent-adapter.md#ir-选页渲染与看图修订) |
| IR 选页预览回归与本机真实渲染记录 | [验证记录](agent-ir-preview-validation.md) |
| Story 可见结构、IR 义务与覆盖账本 | [讲解契约](explanation-contract.md) |
| 补充内容、构造示例与论文泄漏检查 | [Supplement content、basis 与论文泄漏检查](../Total-pipe/docs/deck-compiler-v2.md#supplement-content-basis-supplement) |
| 递归内容区域与 RPA 子布局 | [复合布局](../Total-pipe/docs/composite-layouts.md) |
| 边框、标题色带和 takeaway 框选 | [边框容器](../Total-pipe/docs/framed-containers.md) |
| 原生列表、标记样式 / 颜色和实测容量 | [原生列表](../Total-pipe/docs/native-lists.md) |
| 独立公式、矩阵与图片来源 | [Deck IR 协议](../Total-pipe/docs/deck-compiler-v2.md) |
| 文字与原生数学混排 | [行内公式](../Total-pipe/docs/inline-math.md) |
| 图片来源以及论文原图、示意图和参考裁图的归属 | [图片来源协议](../Total-pipe/docs/deck-compiler-v2.md#figure-provenance-paper-generated-and-reference-images) |
| 合并表头、公式格和行高 | [原生科研表格](../Total-pipe/docs/native-tables.md) |
| 流程、DAG、连接符与图文共存 | [原生流程图](../Total-pipe/docs/native-graphics.md) |
| 学术 / 商业 / 印刷风格包与稀疏页平衡 | [视觉风格包](../Total-pipe/docs/visual-style.md) |
| IR 阶段设备：强调、标签组、图注出处、目录、结论框 | [设计层设备清单](../Total-pipe/docs/art-direction.md) |
| 机制、架构、漏斗、Bézier 与 Path | [科研图形组件](../Total-pipe/docs/native-components.md) |
| 自动讲解图、空白检测、正文区重排与回退 | [ExplainViz 协议](../Total-pipe/docs/explain-viz.md)、[当前实现与验证](explain-viz-auto-layout.md)、[首版评估](explain-viz-evaluation.md)、[构建接入历史](explain-viz-build-integration.md) |
| 数据图（折线 / 柱状 / 散点、误差棒、图内标注）的字段、校验与渲染边界 | [Chart IR 契约](../Total-pipe/docs/chart-ir.md) |
| 外部布局建议和回退 | [布局提供方](../Total-pipe/docs/layout-provider.md) |
| OfficeCLI 写入与实际结构 QA | [OfficeCLI 后端](../Total-pipe/docs/officecli-backend.zh-CN.md) |
| 复杂页溢出提示、留白与候选逐项签收 | [复杂页 QA 与维护](../Total-pipe/docs/complex-page-qa.md) |
| 可选的启发式质量分析 | [质量指标](../Total-pipe/docs/QUALITY_METRICS.md)，不能替代真实验收 |
| 输入及上游反馈的机器契约 | [Deck IR Schema](../Total-pipe/schemas/deck-ir.schema.json)、[布局反馈 Schema](../Total-pipe/schemas/layout-feedback.schema.json) |

## 版本来源

插件、MCP 服务、组件包和文件协议各自版本化。部署时记录 Git commit，并从实际安装源码查询能力。在 `Total-pipe/` 运行 `python -m deck_compiler capabilities` 可查看编译器支持的协议和对象。

| 对象 | 版本声明 |
| --- | --- |
| Total-pipe 插件、Agent 服务和编译器 | [插件清单](../Total-pipe/.codex-plugin/plugin.json)、[Agent 版本](../Total-pipe/agent/__init__.py)、[低层 MCP](../Total-pipe/deck_compiler/mcp_server.py)、[编译器模块](../Total-pipe/deck_compiler/__init__.py) |
| PaperWorkflow 插件、MCP 服务和 Python 包 | [插件清单](../PaperWorkflow/.codex-plugin/plugin.json)、[MCP 服务](../PaperWorkflow/mcp_server.py)、[pyproject.toml](../PaperWorkflow/pyproject.toml) |
| pwf2rpa | [模块版本](../Total-pipe/pwf2rpa/pwf2rpa/__init__.py) |
| Research PPT Assistant | [package.json](../research-ppt-assistant/package.json)、[插件清单](../research-ppt-assistant/.codex-plugin/plugin.json) |
| 文件协议 | [题目页面设计](../Total-pipe/agent/schemas/topic-page-design.schema.json)、[PWF 产物](../PaperWorkflow/README.md)、[论文 Story 和页面设计](../Total-pipe/docs/content-projection.md)、[Deck IR](../Total-pipe/schemas/deck-ir.schema.json)、[Chart IR](../Total-pipe/schemas/chart-ir.schema.json)、[布局树](../Total-pipe/docs/composite-layouts.md) |

## 样例和展示图

- [可检索的 Deck IR 脚本库](../Total-pipe/examples/library/README.md) 含按关键词选择、查看和构建单项示例的命令。
- [从真实 PPTX 批量提炼示例页](../Total-pipe/examples/library/FROM_PPTX.md)涵盖选页、读图和对象提取、原生重建与入库检查。
- [复杂混排单页](../Total-pipe/examples/complex-mixed/README.zh-CN.md)：PPTX、Deck IR、参考素材及检查记录。
- [空白检测与讲解标注三页](../Total-pipe/examples/explain-viz/whitespace-filled/README.md)：填充前后 IR、可编辑 PPTX、PowerPoint 原生预览与审计。
- [行内公式样例](../Total-pipe/examples/inline-math.deck_ir.json)、[矩阵推导样例](../Total-pipe/examples/matrix-derivation.deck_ir.json)。
- [原生表格](../Total-pipe/examples/native-table.deck_ir.json)、[边框容器](../Total-pipe/examples/framed-containers.deck_ir.json)、[原生图形](../Total-pipe/examples/native-components.deck_ir.json)。
- [README 展示图来源与隐私检查](images/README.md)。

## 历史资料

[统一归档索引](archive/README.md)记录旧 Agent 指南、开发总结、v26 实验和旧发布清单的去向。
旧文档索引已换成当前索引入口；旧完整正文仍在归档。默认 `rg` 排除归档，历史检索使用：

```bash
rg --no-ignore '要查的历史主题' docs/archive
```
