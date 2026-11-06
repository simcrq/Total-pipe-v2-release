# Total-pipe v3

从论文证据和科研叙事生成可编辑 PowerPoint 的模块化流水线。Agent 按 Skill 调度各组件，
默认 Agent 链路由 RPA 规范化内容、独立 page_design 决定页面表达；Deck Compiler 确定最终几何并检查容量，OfficeCLI 写入原生 PPTX。
IR 阶段可用 `advance(preflight=true)` 在提交前汇总全部验收问题并测量容量，不消耗修订次数；
拆页保留逐页证据锚点及节点级完整覆盖。PDF doctor 使用官方 CLI 验证现有 MinerU 登录，无需重复导出 token。
新任务使用科学记录与观众表达契约：Story 2.0 分离原子科学单元与叙事，先经主 Agent 科学源审读；page_design 1.3 忠实改写投屏文案，
区分唯一所有权与明确复用，再经页面源文案审读进入 IR。条件只跟随其直接限定的可见断言，旧协议可恢复。
逐页交 deck_ir_page 可自动绑定来源、测量容量并缓存通过页；齐全后整套复验。见[内容契约](Total-pipe/docs/content-projection.md)。
IR 编写中可用 `advance.preview` 选页生成 HTML 渲染 PNG，实际看图后改源 IR；未变页复用缓存。
这是编辑预览，最终候选仍整套构建，PowerPoint 原生验收仍须完成。见[选页渲染接口](Total-pipe/docs/agent-adapter.md#ir-选页渲染与看图修订)。

**默认入口：** [total-pipe-agent Skill](Total-pipe/skills/total-pipe-agent/SKILL.md) 与四工具接入层。
**完整流程规范：** [total-pipe-deck Skill](Total-pipe/skills/total-pipe-deck/SKILL.md)。
**操作手册：** [中文使用说明](Total-pipe/docs/USAGE.zh-CN.md)。
**环境与安装：** [环境清单](Total-pipe/环境清单.md)。
**按任务查文档：** [当前文档索引](docs/README.md)；Agent 阅读规则见 [AGENTS.md](AGENTS.md)。

## 生成效果

以下为实际生成的 PPTX 经 Microsoft PowerPoint 原生导出的幻灯片画面，均为软件功能示例。

**复杂科研混排：参考图片、测量边框、原生列表、矩阵、行内公式与可编辑 Bézier 图形。**

![复杂科研混排单页](docs/images/complex-mixed.png)

[下载可编辑 PPTX](Total-pipe/examples/complex-mixed/complex-mixed.pptx) · [源 IR 与重建说明](Total-pipe/examples/complex-mixed/README.zh-CN.md)

**原生科研表格：多级表头、跨行跨列、公式格与矩阵。**

![原生科研表格与矩阵](docs/images/native-table.png)

[表格源 IR](Total-pipe/examples/native-table.deck_ir.json) · [展示图来源与隐私检查](docs/images/README.md)

## 当前版本

以下为当前仓库声明的版本，核对日期为 **2026-11-04**。产品、组件与文件协议分别版本化；
复合布局、原生科研表格、行内公式、原生数据图与页面设计阶段已在当前源码中实现。

| 对象 | 当前声明 | 版本来源 |
| --- | --- | --- |
| Total-pipe 插件 | `3.3.0+codex.20261021203000` | [插件清单](Total-pipe/.codex-plugin/plugin.json) |
| Agent 接入层 / 默认 MCP | `1.0.1`；四工具 | [接入层](Total-pipe/agent/__init__.py)、[实施修订](Total-pipe/docs/agent-adapter-design.md) |
| Total-pipe 低层 MCP / Deck Compiler Python 模块 | `3.2.0` / `2.4.0` | [MCP 服务](Total-pipe/deck_compiler/mcp_server.py)、[模块版本](Total-pipe/deck_compiler/__init__.py) |
| PaperWorkflow 插件 / MCP / Python 项目 | `0.2.0+codex.20260928131752` / `0.3.0` / `0.1.0` | [插件清单](PaperWorkflow/.codex-plugin/plugin.json)、[MCP 服务](PaperWorkflow/mcp_server.py)、[pyproject.toml](PaperWorkflow/pyproject.toml) |
| pwf2rpa | `1.4.2` | [模块版本](Total-pipe/pwf2rpa/pwf2rpa/__init__.py) |
| Research PPT Assistant | `0.6.3-rc1`；插件构建 `0.6.3-rc1+codex.20260920125419` | [package.json](research-ppt-assistant/package.json)、[插件清单](research-ppt-assistant/.codex-plugin/plugin.json) |
| 文件协议 | PaperWorkflow schema `4`；Story content contract `2.0`（兼容 `1.0`）；page_design `1.3`（兼容 `1.0/1.1/1.2`）；Deck IR `2.0`；Chart IR `v1`；layout tree `1.0/1.1/1.2` | [内容契约](Total-pipe/docs/content-projection.md)、[Deck IR Schema](Total-pipe/schemas/deck-ir.schema.json)、[Chart IR Schema](Total-pipe/schemas/chart-ir.schema.json) |

仓库现有版本元数据尚未统一，服务握手可能返回上表中的组件版本。部署时同时记录 Git commit，
并查询 `python -m deck_compiler capabilities` 确认功能；插件版本号不能代替运行时能力检查。

## 实际组件与职责

| 组件 | 位置 / 入口 | 负责的内容与产物 |
| --- | --- | --- |
| 总调度 Skill | [Total-pipe/skills/total-pipe-deck/](Total-pipe/skills/total-pipe-deck/SKILL.md) | 调度证据、Story、RPA、页面设计、Design、编译与验收；组织失败后的修订 |
| Agent 接入层 | [Total-pipe/agent/](Total-pipe/agent/)、[轻量 Skill](Total-pipe/skills/total-pipe-agent/SKILL.md) | 以现有组件推进阶段、准备完整提示、验证与恢复 job；不编写科学内容 |
| PaperWorkflow（PWF） | [PaperWorkflow/](PaperWorkflow/README.md)；`mcp_server.py` | PDF OCR / Markdown 接入、证据检索、图片与尺寸元数据；产出 `workflow.json`、`evidence.md` 和可搬移资源包 |
| Story Planner | Skill 调度的独立 Agent 阶段；[提示包接口](Total-pipe/pwf2rpa/pwf2rpa/story.py) | 依据证据组织 `question / answer / evidence / next` 和可选 `key_points`，产出 `story_plan.json` |
| pwf2rpa | [Total-pipe/pwf2rpa/](Total-pipe/pwf2rpa/README.md) | 确定性校验、内容与元数据传输；把 Story 转成 RPA 输入，产出 `rpa_input.json` |
| Research PPT Assistant（RPA） | [research-ppt-assistant/](research-ppt-assistant/README.md) | 默认 Agent 仅使用内容规范化与引用传递；独立 CLI 仍提供模板规划、子布局和规划验证（320 个版式、40 类语义和 16 套主题） |
| 页面设计（page_design） | Skill 调度的独立 Agent 阶段；[内容契约](Total-pipe/docs/content-projection.md) | 1.3 独立改写观众文案，设计原图/自绘与讲解，明确所有权、再次出现和直接限定；不改变科学含义、不看编译器能力清单 |
| 源文案审读（page_review） | 主 Agent 实际检查，非自动签收 | 对照科学记录审读忠实性、限定范围和观众文案；绑定当前哈希，失败退回设计 |
| Scientific Visual Planner | 整套视觉提案阶段；[协议](Total-pipe/docs/scientific-visual-planner.md) | 选择整套科研风格及支持页面的视觉构图，生成提案并合入 Deck IR 的 `presentation` |
| Deck Compiler / Deck IR | [Total-pipe/deck_compiler/](Total-pipe/README.md) | 校验科学内容契约、递归分配区域、测量文本与公式、检查几何，生成确定坐标及 `layout_feedback.json` / `qa_report.json` |
| 布局提供方 | [totalpipe_layout/](Total-pipe/totalpipe_layout/)、[提供方接口](Total-pipe/docs/layout-provider.md) | 内置 `packer` 为受支持的平面正文提供确定性几何建议；复杂测量页由编译器布局，单独记录 owned；也可选 `compiler` 或外部 `module:factory` |
| OfficeCLI | 外部安装的命令行程序 | 按编译结果写入文字、图片、原生公式、表格、流程图、连接符与贝塞尔路径等 PowerPoint 对象 |
| Microsoft PowerPoint | macOS / Windows 桌面程序 | 逐页检查实际排版并导出原生 PDF，供正式交付验收 |

Story Planner、page_design 和 Scientific Visual Planner 是 Agent 工作阶段；提示包工具本身只准备输入和校验结果。
可选的 DesignIntentPlanner 在 Story 后声明四步流程关系，详见使用说明；它不替代整套 Design。

## 完整流程与入口

```text
论文 PDF / Markdown
  → PaperWorkflow：workflow.json + evidence.md + 原图
  → Story Planner：story_plan.json
  → scientific_review：实际审读原子科学记录、原文/SI必要条件与遗漏
  → [可选 DesignIntentPlanner：design_intent.json]
  → pwf2rpa：rpa_input.json
  → RPA：内容规范化与引用传递（默认 Agent 不重复做模板规划）
  → page_design 1.3：原子记录所有权 / 明确复用 + 观众文案 / 直接限定 + 视觉与走读
  → page_review：实际源文案审读（旧 1.0/1.1 跳过）
  → Agent 按 Schema 映射 canonical deck_ir.json
  → Scientific Visual Planner：整套 Design 提案 → 合入后的 Deck IR
  → [可选 ExplainViz：仅在明确预留区域追加原生讲解图，默认 off]
  → Deck Compiler + 布局提供方：几何、容量和结构化反馈
  → OfficeCLI：candidate.pptx / staging.pptx + QA
  → 需要正式 final 时：PowerPoint 逐页验收 + 原生 PDF + REVIEW 审核 → promote
```

### 1. 从论文开始：Agent + Skill

在完整仓库根目录执行 `python3.12 install.py --client codex`（Claude 使用 `--client claude`），
默认注册 `total_pipe`，只暴露 doctor / start / advance / status 四工具。
使用 [total-pipe-agent Skill](Total-pipe/skills/total-pipe-agent/SKILL.md)，按 next_action 提供 Agent 产物与用户选择。
已有 IR / workflow 可从对应阶段继续；安装、状态与恢复详见[接入层说明](Total-pipe/docs/agent-adapter.md)。例如：

接入层默认返回紧凑摘要，`totalpipe_status(detail="full")` 可读取完整请求与产物清单；状态查询只读。
`slide_count` 是最终论文页目标，与 Story 节点/brief 数量独立；本地执行区间与等待事件追加在
`logs/events.jsonl`，用于区分组件执行、返工与外部等待，不将它当作模型 token 或整链提速基准。
已有 canonical IR 可提交 `deck_ir_patch` 调整既有布局树或栅格图片路径；先用原编译器预检，失败保留
旧 IR/候选/QA，apply 通过后再执行完整构建与 QA。接口与图片人审边界见[局部修补](Total-pipe/docs/agent-adapter.md#局部修补与布局预检)。
候选后可用 `advance.native` 接入 PowerPoint 原生导出、全页预览和实际 UI 复核，直接更新 QA，
复用现有 PPTX；自动导出不代替眼检，正式 promote 仍用 CLI。见[原生验收接入](Total-pipe/docs/agent-adapter.md#原生-powerpoint-验收接入)。

```text
使用 total-pipe-agent，将 /absolute/path/paper.pdf 制作为中文研究汇报。
围绕研究问题、方法、关键结果和局限组织证据与故事，完成整套 Design。
保留完整科学术语、原图和原生公式，交付可编辑候选及 QA 报告。
```

Story 阶段需要记录用户选择的模型、reasoning 和真实 subagent provenance。
从已有证据、Story 或 Deck IR 继续时，按产物状态进入相应阶段。
RPA 之后先由独立子代理写观众表达和视觉讲解设计，主 Agent 实际源文案审读后，再按 Schema 映射
canonical Deck IR；Design 的视觉提案阶段随后执行。

### 2. 已有 Deck IR：编译 CLI

下面的命令均在 `<repo>/Total-pipe/` 运行：

```bash
# 查询协议与原生对象能力
python -m deck_compiler capabilities

# 准备完整 Design 提示包；Agent 阅读后编写 visual_proposal.json
python -m deck_compiler visual-prompt --ir deck_ir.json --out visual_prompt.json
python -m deck_compiler apply-visual-plan --ir deck_ir.json \
  --proposal visual_proposal.json --out designed.deck_ir.json

# 只编译布局和 QA
python -m deck_compiler compile --ir designed.deck_ir.json --out build/my-deck

# 生成可编辑候选，开发阶段暂不导出 PowerPoint PDF
python -m deck_compiler build --ir designed.deck_ir.json --out build/my-deck \
  --officecli officecli --skip-native
```

有相对资源路径时，合入设计后的 IR 与源 IR 保存在同一目录。已包含完整设计的 IR 可直接编译。
`python totalpipe.py generate designed.deck_ir.json --out build/my-deck` 是同一编译阶段的简化入口，
输入同样是已有 Deck IR。漏做 Design 时，默认返回 `VISUAL_DESIGN_REQUIRED` 及完整提示包。

普通生成任务交付候选并报告未解决项；正式 `final.pptx` 还须完成
[PowerPoint 原生验收与晋级](Total-pipe/docs/USAGE.zh-CN.md#6-正式-finalpowerpoint-验收与晋级)。
`--skip-native` 的构建须补做原生验收后才能晋级。

### 3. MCP 服务入口

默认服务在 `<repo>/Total-pipe` 执行 `python -m agent.mcp_server`，配置为
[Total-pipe/.mcp.json](Total-pipe/.mcp.json)。原低层三服务保留在
[.mcp.advanced.json](Total-pipe/.mcp.advanced.json)，用 `install.py --profile advanced` 注册，
以下是各低层服务的独立启动方式：

| 服务 | 服务进程的工作目录 | 启动命令 | 配置 |
| --- | --- | --- | --- |
| `paperworkflow` | `<repo>/PaperWorkflow` | `python mcp_server.py` | [PaperWorkflow/.mcp.json](PaperWorkflow/.mcp.json) |
| `research_ppt` | `<repo>/research-ppt-assistant` | `node server/mcp-server.mjs` | [research-ppt-assistant/.mcp.json](research-ppt-assistant/.mcp.json) |
| `total_pipe_v3` | `<repo>/Total-pipe` | `python -m deck_compiler.mcp_server` | [Total-pipe/.mcp.advanced.json](Total-pipe/.mcp.advanced.json) |

advanced 客户端将相对 cwd 解析到对应组件目录；手动配置时填写实际绝对路径，
Python 指向已安装依赖的虚拟环境。Total-pipe 服务包含 pwf2rpa 的五个工具，以及
`totalpipe_capabilities / totalpipe_visual_prompt / totalpipe_apply_visual_plan / totalpipe_compile / totalpipe_build / totalpipe_review`，
以及候选复审工具 `totalpipe_qa / totalpipe_ack_review`；可选讲解图使用
`totalpipe_explain_viz_prompt / totalpipe_apply_explain_viz`，不增加默认四工具阶段。
MCP 文件参数使用绝对路径。更新源码后重载服务。

## 环境需求

| 环境 / 依赖 | 要求与适用阶段 |
| --- | --- |
| Python | **完整流水线使用 3.12+**，来自 PaperWorkflow 的 `requires-python`；在虚拟环境安装依赖 |
| Node.js | **22+**，用于 RPA；当前 RPA 运行时无第三方 npm 依赖 |
| 编译器 Python 依赖 | `Pillow>=10`、`lxml>=5`、`pdfplumber>=0.11`，见 [requirements.txt](Total-pipe/requirements.txt) |
| PaperWorkflow Python 依赖 | 以 [pyproject.toml](PaperWorkflow/pyproject.toml) 为准；完整 PDF / 批处理环境需安装其声明的依赖 |
| OfficeCLI | **1.0.152+** 可执行文件；生成 PPTX 时还检查所需对象属性 Schema。放入 PATH 或传 `--officecli` 绝对路径 |
| OCR | PDF 输入默认调用 **MinerU 官方 `mineru-open-api` CLI**，需安装并认证；已有 Markdown / 证据包可从对应阶段继续 |
| 字体 | 安装主题所需字体、使用语言的字形和 PowerPoint 数学字体；公式使用 Cambria Math。额外字体目录用 `TOTALPIPE_FONT_DIR` 指定 |
| 原生验收 | **macOS 或 Windows + Microsoft PowerPoint**；Linux / WSL 可执行规划、编译和结构检查，正式晋级还需 PowerPoint 原生证据 |
| 可选 IR 编辑预览 | OfficeCLI screenshot/html + 可启动的 Chrome/Edge/Chromium/Firefox 或其支持的 Playwright 浏览器；不能代替 PowerPoint 原生验收 |
| 可选测量依赖 | `matplotlib` 提供数学字体度量；未安装或遇到不支持的数学结构时使用保守估计并保留 REVIEW。无需本地 LaTeX 或 torch |
| 模型与网络 | Story / Design 使用 Agent 模型；默认 MinerU 云 OCR 需要网络与认证。仅从本地 Deck IR 编译不要求模型 API Key |

最小编译环境与完整依赖安装命令见 [环境清单](Total-pipe/环境清单.md)。
`PAPERWORKFLOW_CONFIG` 可指向外部 YAML；`MINERU_TOKEN` 用于 OCR 认证。
旧批处理若调用 DeepSeek / OpenAI 兼容 API，还需对应密钥；MCP 的证据检索和编译器不要求这些密钥。
主题字体先从 IR 所在目录、额外字体目录及系统字体目录解析；替代字体会进入 QA。

## 当前能力与容量规则

可直接打开[复杂混排单页 PPTX](Total-pipe/examples/complex-mixed/complex-mixed.pptx)，
对应 [Deck IR、资源与重建说明](Total-pipe/examples/complex-mixed/README.zh-CN.md) 一并版本管理。
该样例同时展示参考图片、测量边框、原生项目符号、矩阵、行内根式 / 指数以及原生 Bézier 光子芯片图案。

- **原生数学内容**：分式、根号、上下标、嵌套指数、六种矩阵环境；密集多步推导按实际单双栏区域测量。
- **显式行内公式**：正文、标题 / takeaway、表格文字格可选开启；文字与数学片段按逐行宽度、上伸和下伸高度计算容量。图注、图形标签和 panel 标题暂不解析行内公式。
- **复合区域与表格**：`columns / stack / panel / image_grid` 递归布局；layout tree `1.1` 增加原生表格，含合并表头、跨行跨列和公式格；保留旧平面 IR 与 `1.0` 树。
- **原生科研图形**：流程、DAG、机制、分层架构、漏斗和贝塞尔路径；`process` 支持横向、纵向、错位和 3–8 步全方形紧凑布局，节点可单独强调；关系由上游显式声明，编译器分配区域。
- **可选 ExplainViz**：默认关闭；Agent 提交绑定源 IR 和预留槽位的讲解图计划，确定性模板追加剥离角、层叠或过程原生对象。无槽位、来源不足、编译失败或原有对象变化时跳过/回退；不替代页面设计或科学人审。本轮按要求未运行验证，见[协议](Total-pipe/docs/explain-viz.md)与[评估](docs/explain-viz-evaluation.md)。
- **原生列表**：整套或 block 独立设置符号样式与颜色，takeaway 可单独加前导标记；最低宽度 520 CSS px，高度按完整条目实测，术语保留策略不删除项目符号。见 [列表协议](Total-pipe/docs/native-lists.md)。
- **讲解契约**：Story 的 `explain` 逐条绑定证据，声明读者必须看见的量、并列项、分组、对照、顺序、关系或示意曲线；IR 带进 `semantic.explanation`，编译生成 `derived/explanation_coverage.json`。required 义务缺原生载体时保留 REVIEW，不静默当纯文字页。见 [讲解契约](docs/explanation-contract.md)。
- **补充内容旁路**：`basis: supplement` 允许无论文 EV 的背景、类比、构造示例、推导说明或示意图；论文块仍强制 EV，补充块可选来源、构造示例须可见标注，Agent 检查论文数值/图/长引用泄漏；默认关闭，`supplement=inline|pages|both` 显式开启。见 [Deck IR 协议](Total-pipe/docs/deck-compiler-v2.md#supplement-content-basis-supplement)。
- **图片来源**：区分论文图 `paper`、自绘示意图 `generated` 和用户参考裁图 `reference`；参考裁图保留 `reference_source`，不要求论文图号或“示意图”图注。见 [来源协议](Total-pipe/docs/deck-compiler-v2.md#figure-provenance-paper-generated-and-reference-images)。
- **可测量边框容器**：layout tree `1.2` 为 panel 增加原生边框与标题色带；takeaway 可独立框选。描边、内边距和完整内容参与容量计算，支持嵌套并保留旧树。见 [容器协议](Total-pipe/docs/framed-containers.md)。
- **原生数据图**：`composition.charts` + layout tree 的 `chart` 叶子；折线 / 柱状 / 散点，线性 / 对数轴，误差棒与图内标注。`basis: evidence` 的图必须绑 EV 与出处，`basis: explain` 的示意曲线须标“示意”。论文已有图时用 `figure-reading`，不重画。见 [Chart IR 契约](Total-pipe/docs/chart-ir.md)。
- **机制图关系边**：流程 / 机制图的边上可写标签，`basis` 区分 `evidence`（须引用）、`hypothesis`（未证实）与 `explain`（补充说明，点线、无引用；标签含数字时仍须引用）。见 [科研图形组件](Total-pipe/docs/native-components.md)。
- **页面设计阶段**：RPA 之后、IR 之前，独立子代理只读 Story、briefs、证据、图和场合，以 content_refs 引用内容、以自由 design 交代绘图、排布与走读；不重写 Story，**不需要知道编译器能画什么**。场合分五档（组会 / 会议答辩 / 文献分享 / 讲课 / 商业路演），写进 `setting`，决定密度与页面形态。设计者选择视觉形式，IR 作者选择实现能力。见 [接入层契约](Total-pipe/docs/agent-adapter.md#页面设计阶段page_design)。
- **类型尺度**：一页一个 body 字号（28 px / 21 pt），标题 44 px、注释 22 px、页脚 20 px。`metric` 默认比正文高一档；整页只讲一个数字时可设 `presentation.academic_design.type_scale="statement"`，把它提到 88 px，其余角色不变。
- **垂直分配**：平面文字栏、公式流、图侧文字栈和 packer 栏在保持实测字号/换行的前提下分配剩余高度；stack 平台在间隙超过 48 px 时不再均分间隙，改为整组居中（上限 56 px），避免“三行字浮在版面上”。表注仍允许低于 18 pt，其余投屏文字守住 18 pt 下限。
- **可追溯反馈**：`layout_feedback.json` 给出组件路径、所需 / 可用尺寸与建议，供上游用完整内容重规划。
- **复杂页复审**：stack 保留默认贴合内容，可显式居中或分配余量，留白超过 15% 时给出 REVIEW 与相对权重建议；候选支持逐项签收和待复核视图，内容 / 几何变化后相关记录失效。见[复杂页 QA](Total-pipe/docs/complex-page-qa.md)。
- **科学术语优先**：`preserve-terms` 保留长标题与正文，超预算可带 REVIEW 生成候选；公式真实宽高、图形可读性和原图尺寸仍执行容量门禁。

编译阶段只维护 canonical Deck IR；`layout.json`、`derived/` 和后端 batch 都由编译器派生。
OfficeCLI 的 `Text overflow` 警告估计在 QA 中记为 INFO，保留原始 issue，再以实际 PowerPoint 页面核对。
正式晋级要求零 FAIL、当前文件绑定的原生验收，以及全部 REVIEW 的真实审核记录。

## 文档导航

| 文档 | 内容 |
| --- | --- |
| [中文使用说明](Total-pipe/docs/USAGE.zh-CN.md) | 从证据到候选 / final 的完整操作、门禁和修订流程 |
| [Agent 接入层](Total-pipe/docs/agent-adapter.md) / [修订设计](Total-pipe/docs/agent-adapter-design.md) | 默认四工具、安装、恢复、页面设计阶段（场合 / shape / marks）与设计评审 |
| [环境清单](Total-pipe/环境清单.md) | 安装、配置、平台范围与服务启动 |
| [编译器入口](Total-pipe/README.md) | Deck IR 编译命令与产物 |
| [Scientific Visual Planner](Total-pipe/docs/scientific-visual-planner.md) | 必做 Design、视觉提案及术语容量策略 |
| [讲解契约](docs/explanation-contract.md) | Story 可见结构、IR 义务、覆盖账本与责任边界 |
| [复合区域](Total-pipe/docs/composite-layouts.md) / [原生表格](Total-pipe/docs/native-tables.md) | 子布局规划、递归几何与尺寸反馈 |
| [Chart IR](Total-pipe/docs/chart-ir.md) / [科研图形组件](Total-pipe/docs/native-components.md) | 数据图与机制图的字段、证据绑定和渲染边界 |
| [设计层设备](Total-pipe/docs/art-direction.md) | IR 阶段的强调、标签组、图注出处、结论框与篇级设备清单 |
| [行内公式](Total-pipe/docs/inline-math.md) / [Deck IR 协议](Total-pipe/docs/deck-compiler-v2.md) | 数学语法、混排测量和完整 IR 约束 |
| [原生图形](Total-pipe/docs/native-graphics.md) / [科研组件与路径](Total-pipe/docs/native-components.md) | 可编辑流程、机制、架构与贝塞尔图形 |
| [开发后文档同步 Skill](Total-pipe/skills/total-pipe-doc-sync/SKILL.md) | 开发收尾时核对 README、中文用法、环境与协议，提交前清理过时说明 |

过时开发总结、旧 Agent 指南、v26 实验和旧发布清单已统一移入[历史归档](docs/archive/README.md)，
保留原文和原路径索引；默认检索不包含归档。安装和运行以本 README、当前使用说明及源码为准。
