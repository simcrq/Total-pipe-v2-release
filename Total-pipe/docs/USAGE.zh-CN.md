# Total-pipe 使用说明

本文对应当前仓库的 PaperWorkflow、Story、RPA、Scientific Visual Planner 和 Deck Compiler。
从已有产物继续相应阶段；不重复提取证据或重写已经通过的科学故事。
组件与当前版本见 [仓库 README](../../README.md)，安装、运行时和平台需求见 [环境清单](../环境清单.md)。

## 1. 输入、工作目录与产物

```text
论文 PDF → PaperWorkflow workflow.json → Story Planner story_plan.json
  → [可选 DesignIntentPlanner design_intent.json] → pwf2rpa rpa_input.json
  → RPA 规划与验证 → canonical deck_ir.json
  → Scientific Visual Planner（design 阶段，默认必做）→ designed.deck_ir.json
  → Deck Compiler + packer → OfficeCLI → candidate.pptx / staging.pptx + QA
  → 需要正式 final 时：PowerPoint 原生验收 → REVIEW 审核 → promote
```

编译器直接接收 Canonical Deck IR（`schema_version: "2.0"`）。它是科学内容真源；
`derived/` 中的计划、资源清单和 QA expectation 是只读派生物。

| 操作 | 工作目录 |
| --- | --- |
| `python -m deck_compiler …`、`python totalpipe.py …` | `<repo>/Total-pipe` |
| `python -m pwf2rpa …` | `<repo>/Total-pipe/pwf2rpa` |
| `node research-ppt-assistant/server/cli.mjs …` | `<repo>` |

命令中的尖括号表示需替换的实际文件或参数。CLI 可用相对路径，MCP 的文件路径必须绝对。
MCP 配置在 [../.mcp.json](../.mcp.json)，入口为 `deck_compiler.mcp_server`；确认配置的
Python 和 cwd 指向当前副本。运行中的旧服务不会自动重读代码或工具 schema；重载前可用 CLI。

| 构建目录文件 | 含义 |
| --- | --- |
| `deck_ir.json` | 本次编译冻结的输入 |
| `visual_prompt.json` | 漏做设计时返回的完整 Agent 提示包 |
| `layout.json` | 实际几何、文本契约和 adaptation log |
| `layout_provider.json` | 逐页提供方与回退原因 |
| `candidate.pptx` | 生成成功后的可编辑候选 |
| `staging.pptx` | 与 candidate 字节一致的验收对象 |
| `candidate.officecli.batch.json` | OfficeCLI 命令记录，哈希写入 QA |
| `officecli_issues.json` | 原始 OfficeCLI issues，已汇入 QA |
| `qa_report.json` | FAIL/WARNING/REVIEW/INFO 及下一步动作 |
| `native.pdf`、`native.json`、`powerpoint_review.json` | 当前 staging 的原生验收证据 |
| `metrics.json`、`state.json` | 编译指标与生命周期状态 |
| `final.pptx` | 完成验收、审核并 promote 后生成 |

失败或尚未验收时并非所有文件都会存在；旧 final 不能当成本次候选的成功结果。

## 2. PaperWorkflow、Story 与 RPA

### 证据提取

首轮 PaperWorkflow 调用前按论文主题和汇报问题设置 `queries`。有定制问题且未设置
`include_default_queries` 时仅使用定制问题，要混用通用问题才显式设为 `true`。
文件名无法自动配对的补充 PDF/Markdown 传实际 `supplementary_paths`；显式配对只证明
文件存在。先将补充材料 OCR/Markdown 内容合入分析输入，再设
`supplementary_content_included=true`。

分别读取 `quality_audit` 和 `synthesis_readiness` 六项门禁。OCR 捕获成功不等于科学综合
就绪；`review/blocked` 的原因保留并补证据。下游优先引用 `EV####`。

### Story Planner

用户尚未选择模型时，请其选择可用的高能力模型与至少 `high` 的 reasoning；已有明确选择则沿用。
Story 必须由该模型的独立 subagent 生成，顶层保留真实的模型与用户选择 provenance：

```json
{"planner":{"mode":"subagent","model":"<用户选择>","reasoning_effort":"high","selected_by_user":true}}
```

调用 `pwf2rpa_story_prompt` 时传 `workflow_path/model/reasoning_effort/selected_by_user`。
工具返回小回执；子代理读取输出文件完整的 `instructions/evidence_store/output_shape`。
默认输出在 workflow 旁，也可用绝对路径 `out_path`。CLI 回退：

```bash
python -m pwf2rpa <workflow.json> --make-story-prompt <story_prompt.json> \
  --story-model <用户选择> --story-reasoning <用户选择的强度> --model-selected-by-user
```

提示包生成器只封装证据，不调用模型。Story 按论证需要安排 4–10 个节点：

```json
{
  "title": "可选的完整展示标题",
  "question": "为什么出现这一现象？",
  "answer": "结果支持机制 A，但不能排除机制 B。",
  "key_points": ["实验观察到……", "进一步分析显示……", "仍不能排除……"],
  "evidence": ["EV0012", "EV0013"],
  "next": "如何区分机制 A 和机制 B？"
}
```

`question/answer/evidence` 必填，`next` 仅最后节点可省略。`title` 和 `key_points` 可选；
摘要不足以保留科学细节时使用 key_points，条数由内容决定。标题和正文保留完整正确的术语、
化学态、单位与限定词，不为容量截断或强行缩写。`ending.limitation` 只记录论文边界；
输入文件是否取得、SI 是否审阅等进入工作记录。

### 可选的科研流程意图

恰好四条 key_points 存在明确步骤关系时，DesignIntentPlanner 可生成：

```json
{"slides":[{"story_node_index":2,"relation":"process","orientation":"vertical","emphasis":4}]}
```

索引从 1 开始，emphasis 可省略。它只声明上游流程关系，不写坐标、不改 Story，
不替代后续整套视觉设计。没有此关系则省略文件。

### 转换与页面规划

```bash
python -m pwf2rpa <workflow.json> --story <story_plan.json> \
  --story-model <用户选择> --story-reasoning <用户选择的强度> \
  --model-selected-by-user --strict --out <rpa_input.json>
```

有设计意图才加 `--design-intent <design_intent.json>`；MCP 对应字段是
`story_path/design_intent_path`，后者必须与 Story 同传。

切到仓库根目录运行 RPA：

```bash
node research-ppt-assistant/server/cli.mjs normalize-content \
  --file <rpa_input.json> --detail-level full > <normalized_content.json>
node research-ppt-assistant/server/cli.mjs plan --file <rpa_input.json> \
  --presentation-type group_meeting --slide-count <N> --detail-level standard > <deck_plan.json>
node research-ppt-assistant/server/cli.mjs validate-deck \
  --file <validation_input.json> --detail-level compact
```

要求 normalize `status=valid`；plan `pipeline_status=plan_complete`、
`status=success/adapted` 且 `unplanned_slide_briefs` 为空；validate `status=valid`。
验证输入包含当前 `slides` 与原始完整 normalized content 作为 `content_model`。

每次修订都对照源 Brief：`KEY_POINTS_LOST/SOURCE_TEXT_NOT_BOUND` 要恢复原文和顺序，
不能删改 content_model 消除错误。`adapted` 要逐条核对 adaptation；compact 摘要、slot 短文本
和设计消息不能代替完整正文。总结页容量不足应保留 `needs_replan`，不能改成错误类别凑页。
硬流程组的 `VISUAL_INTENT_NOT_BOUND/VISUAL_INTENT_GROUP_SPLIT` 需要重规划，不能自动拆散。
字符预算仅粗筛，`SLOT_WRAP_RISK` 仍需真实渲染复核。

## 3. 映射 Canonical Deck IR

按 [Schema](../schemas/deck-ir.schema.json) 和 [组件目录](../deck_compiler/catalog.py) 映射，
不复制 RPA 的最终 bbox：

- `semantic`：完整标题、purpose、takeaway、evidence_refs、caveats 和 speaker_notes。
- `composition`：完整 blocks、原图 figure_refs 与 assets 引用、显式原生 graphics。
- `presentation`：统一 frame、文字容量策略和后续视觉决策。

完整标题或正文较长时，在映射阶段显式设顶层
`presentation.text_capacity_policy="preserve-terms"`，使进入设计前的字符预算也不要求缩写科学术语。

标题优先使用 Brief `metadata.story_title` 的完整 Story 标题；不写独立 title 时取 question。
保留源 key_points 与正文顺序、段落边界和必要展示细节，不只留下摘要或把全部正文藏到 notes。
证据编号、输入情况和运行记录进入备注；页面 caveat 只保留论文自身边界。

整套使用同一 frame（`default/spacious`）；省略时由兼容逻辑统一解析，不能逐页随意换风格。
有 RPA 流程 layout_contract 时，四条原文落到四个无独立 label 的 block，并用实际 ID 写
`composition.visual_intent.members`。单图用 `figure-parameters`，无图用 `process-flow`；
不得与 graphics 或 visual_plan 同页重排。完整字段见 [流程协议](deck-compiler-v2.md)。

长多段正文保持换行，可复制 RPA 的 `text_flow.mode`。`auto` 仅把符合长度条件的 3–5 个明确
段落转换为可编辑原生列表；`plain` 禁止转换。公式不经过普通文本列表转换。

无序列表用顶层 `presentation.bullet_style / bullet_color` 设默认，正文 block 同名字段独立覆盖；
符号颜色不改变正文颜色。单页 `presentation.takeaway_marker={"style":"large_diamond","color":"#000000"}`
为完整 takeaway 加一个原生前导标记，换行和行内公式按剩余宽度实测。
preserve-terms 保留列表原文、符号和颜色，垂直超容量记录 REVIEW；显式列表宽度至少 520 CSS px，
高度按完整条目、标记槽、实际换行、标签、间距及内边距测量。区域不足时报告拆页 / 重规划，
不降级为无符号文本。
完整用法、优先级及两页样例见 [原生列表](native-lists.md)。
项目符号可选；plain 关闭正文列表，takeaway 未配置则不加标记。large_square / large_diamond /
arrowhead 选择较饱满的原生字形，不缩放项目符号，字形尺寸参与空间测量。

图片来源在 canonical IR 中区分 `paper`、`generated` 与 `reference`：论文图要求图号，管线自绘示意图要求
生成器和“示意图”图注；用户提供的参考页 / 图片裁图标记为 `reference` 并记录 `reference_source`，不伪装成论文图或
强制添加示意图图注。参考裁图保留来源说明，但不作为独立科研证据核验。
`reference_source` 不能留空白；图注可以为空，图片仍执行原图字节核对、等比包含和最小可读尺寸检查，
并保留 `REFERENCE_IMAGE_REVIEW` 供来源 / 裁图 / 可读性审核。字段示例见[图片来源协议](deck-compiler-v2.md#figure-provenance-paper-generated-and-reference-images)。

原生 process/DAG 与图文混排见 [native-graphics.md](native-graphics.md)；机制、架构、漏斗、
Path 和 composite 见 [native-components.md](native-components.md)。所有关系显式声明；
机制的实测与假设保留依据、不同线型及标签。生成示意图不能替代论文原图，保留 `SCHEMATIC_REVIEW`。

### 复合内容区域

现有整页框架可在 `composition.layout_tree` 中选用递归子布局，支持 `1.0/1.1/1.2`，外层 Deck IR 仍为 `2.0`。
支持 columns、stack、panel、image_grid；叶节点引用 block ID、figure_refs 零基索引、graphic ID，
或 1.1 的 table ID。已有 1.0 树保持兼容。
每项内容恰好引用一次，不复制正文或填写页面坐标。新混排页可用 `composite-research`。

先查询 `totalpipe_capabilities`（CLI：`python -m deck_compiler capabilities`），再让 RPA
`search_sublayouts/compose_sublayout` 手工组合，或用 `plan_sublayout` 自动选型。
自动接口提交完整 groups/content_refs/consumer_capabilities，可选 body_size_px 与组的实测尺寸需求；
只输出相对结构。整页 `create_deck_plan` 可通过 `body_compositions: [{slide_id, request}]`
接入自动选型，结果位于 slides[].body_layout；slide_id 使用规范化后的实际页面 ID。
整页版式库和原有证据/原文绑定门禁继续保留，结构规划成功仍需编译器实测。
最多 6 层、64 节点，公式与解释在同一 stack，图形和原图的尺寸下限不变。

树页仍执行整套 Design、保留 academic_design，不叠加分配同一区域的 visual_plan/visual_intent。
查看 `layout_feedback.json` 的组件路径、所需/实际尺寸和建议，容量不足交回 RPA 重规划。
向 plan_sublayout 传当前完整 IR 的 ir_sha256、compiler_feedback 及 rejected_sublayout_ids；
过期反馈会被拒绝，已失败候选不会重试。调用者控制最多三轮修订，编译器不自行调用 RPA。
不会自动缩小水平流程图或裁剪证据图；完整标题/正文超容量按 preserve-terms 保留 REVIEW。
详见 [复合区域协议与样例](composite-layouts.md)。

树版本 1.2 的 panel 可选 frame，配置原生边框、填充、标题色带和标题颜色。未声明时沿用原有无背景分组。
单页 presentation.takeaway_frame 独立框选完整结论，可与可选 takeaway_marker 和显式行内公式一起使用。
编译器扣除描边、内边距及标记槽后测量内容，并将正文移到结论框下；保留术语导致的增长与碰撞仍需 REVIEW。
不传页面坐标，不用悬浮矩形补框。字段、嵌套规则、容量与两页样例见 [边框容器](framed-containers.md)。

### 原生科研表格

`composition.tables` 支持原生可编辑表格、多级表头、跨行跨列和公式/矩阵单元格。
布局树使用 1.1，以 table 叶节点引用 ID。每页最多 4 表、每表最多 32 行/12 列；
cells 的 row/column 为零基索引，row_span/column_span 定义合并区域，每个逻辑位置恰好覆盖一次。
单元格 kind 为 text 或 formula；公式复用现有 AST，不用普通文本拼写根号与指数。
论文表格必须把 evidence_refs 绑定本页；缺失值、空格和单位由上游明确提供。

列宽使用相对 column_weights，行高由完整文字和数学结构实测；字体下限 18 pt。
纯文字表格按 preserve-terms 保留超容量全文和 REVIEW，含公式的表格尺寸不足需加宽或拆页。
保留 TABLE_CONTENT_REVIEW、近似公式测量及原生 PDF 文本差异的审核项。
详见 [表格协议](native-tables.md) 和 [两页开发示例](../examples/native-table.deck_ir.json)。

PWF 新增 `artifacts.figure_assets_metadata`，pwf2rpa 对显式匹配的资源引用补齐源图片像素尺寸、宽高比、
格式及裁剪策略，RPA 保留这些字段。旧 workflow 缺少元数据仍可转换。

### 公式插入

公式用独立的 `component: "formula"`，`text` 保存 LaTeX 子集。JSON 必须双写反斜线：

```json
{"id":"f1","component":"formula","text":"\\sqrt{\\frac{1+e^{-t}}{1+x^{2}}}","anchor":"explanation"}
```

anchor 可省略；显式 anchor 指向本页前方的非公式 block。无标签公式默认位于前一说明块下方，
有 label 时标签与公式并排。普通正文默认不解析 `$…$`；显式开启行内模式后按下节处理。

#### 行内公式与混排容量

正文块或表格 text 格加 `inline_math: true`，以 `$…$` 或 `\(…\)` 标记公式：

```json
{"id":"response", "component":"body", "inline_math":true,
 "text":"当 $x>0$ 时，响应为 $\\sqrt{1+x^{2}}$，完整说明保持可编辑。"}
```

标题/结论在 semantic.inline_math 中列出 title/takeaway；未列出的字段保持原样。
开启后字面美元符号写 `\$`（JSON：`"\\$"`），不接受显示公式分隔符或分布式项目列表。
图注、panel 标题和图形标签仍按原有文字处理。

容量改为逐行测量文字与公式宽度、最大上伸/下伸高度，再累计实际行高；高矩阵只影响所在行。
数学区域整体换行，不按 LaTeX 字符长度估算，不拆根号和指数。正文、树和表格复用混排测量，
字号下限与完整术语策略保持不变；公式过宽需加宽或改用独立公式，含数学的表格不足需拆页。
查询 native_inline_equation 能力；RPA content_refs 的 block.inline_math / table.has_inline_math 传递需求。
保留原生核对 REVIEW。完整协议与三页样例见 [行内公式](inline-math.md)。

#### 独立公式语法

支持分式、`\sqrt{…}` / `\sqrt[3]{…}`、上下标和嵌套分组、Greek、求和/积分、
`\left/\right`、`\exp/\log/\ln`、常用三角函数与 `\text/\mathrm/\mathbf/\mathit`。
底数和多项指数写清分组，例如 `{xy}^{a^{2}}`。公式块可带外层 `$…$/$$…$$/\(…\)/\[…\]`。
未知命令、空参数与缺失括号返回带字符位置的 `FORMULA_SYNTAX`；array/cases 等尚不支持。
不要用错误表达式、普通文本或截图掩盖解析失败。

矩阵支持 `matrix/pmatrix/bmatrix/Bmatrix/vmatrix/Vmatrix` 六种环境：`&` 分列，`\\` 分行。
JSON 示例：

```json
{"id":"matrix","component":"formula","text":"A=\\begin{bmatrix}1&2\\\\3&4\\end{bmatrix}"}
```

输出为原生 `m:m/m:mr/m:e` 结构，矩阵括号是原生 delimiter。保留空单元格、不自动补零；
各行列数须一致，支持单元格中的根号、分式、上下标和外部转置。裸 matrix 可由 `\left/\right`
加括号，`\quad/\qquad` 可分隔并列公式。矩阵尺寸按列宽最大值和实际行高计算，原生间距仍保留 REVIEW。
分式、根号和求和另计算原生展示公式的保守高度，避免把 mathtext 的较小排版尺寸直接当作 PowerPoint 尺寸。

AST 统一投影到尺寸、Unicode fallback 和 OMML；数学模式测量实际排版，原生结构保留根指数、
被开方项和所有上下标。公式不再按“每页两条”限制，字号不低于 24 CSS px（18 pt）。放不下返回
`FORMULA_CAPACITY`，先加宽或拆页；`FORMULA_MEASURE_APPROXIMATE` 保留 REVIEW。
HTML 截图仅显示 fallback，实际根号、分式线和指数用 PowerPoint 原生视图核对。
见 [公式协议](deck-compiler-v2.md#formulas-component-formula) 和 [可运行示例](../examples/formula.deck_ir.json)。

密集推导使用 `archetype: "equation-derivation"`，按阅读顺序保留 blocks。
编译器按完整内容的实测高度尝试单双栏，阅读顺序为左栏从上到下，再读右栏。
显式 anchor 的说明与公式成组，不能拆散；无 anchor 的连续公式分别保留，不会只输出第一条。
说明文本框与公式行保持实际内容高度，不吸收整列剩余留白；独立两栏的公式高度分别检查，
不相加套用单栏比例。实际列数、字号、阅读顺序与容量候选记入 `layout.json` 的 `formula_flow`。
启用 `preserve-terms` 时，说明文字仍超出真实容量也保留全文并标记 REVIEW；公式本身的真实宽高不足仍会报告失败。
原有页面的普通正文数量限制仍生效，公式由几何容量判断。见 [4×4 矩阵与密集推导示例](../examples/matrix-derivation.deck_ir.json)。

## 4. Design 阶段：默认执行视觉规划

Canonical IR 完成后，当前 Agent 进行一次整套 Scientific Visual Planner，不需要新增模型服务。

```bash
python -m deck_compiler visual-prompt --ir <deck_ir.json> --out <visual_prompt.json> \
  --requirements <科研汇报要求>
```

读取完整 `deck_ir/available_assets/planning_targets/schemas`，输出绑定当前完整 `ir_sha256`
的 `visual_proposal.json`：一份统一 academic_design，加全部支持页面的 visual_plan。
选择测量证据、既有机制图解释或双图证据比较构图，按科学阅读顺序决定位置、占比和原文强调。
不支持的页面在 planning_targets 中有原因；硬流程组保持原顺序，不为补设计凭空添加图或机制。
纯文字/公式 Deck 仍选 academic_design，提案允许 `slides: []`。

```bash
python -m deck_compiler apply-visual-plan --ir <deck_ir.json> \
  --proposal <visual_proposal.json> --out <designed.deck_ir.json>
```

提案只改变 presentation，不改正文、原图、图注、数值、讲稿或科学关系。源 IR 有相对资源路径时，
新 IR 必须与源 IR 同目录。MCP 对应 `totalpipe_visual_prompt/totalpipe_apply_visual_plan`，
这两个工具的 out 是 JSON 文件路径。协议与提案示例见 [scientific-visual-planner.md](scientific-visual-planner.md)。

默认 compile/build 和统一 generate 检查设计：漏做时返回 `VISUAL_DESIGN_REQUIRED`、
完整提示包与缺失页面，Agent 补做并合入后重试。只规划样例页不能代替全套设计。
显式复现旧版才用 `--skip-visual-design`（MCP：`skip_visual_design=true`）；
低层 `compile_deck` 继续兼容旧 IR。

有 academic_design 时默认 `text_capacity_policy=preserve-terms`；也可在顶层 presentation 显式启用。
标题和正文超字符/槽位预算仍保留全文、生成候选并记录
`SCIENTIFIC_TEXT_CAPACITY_REVIEW/SCIENTIFIC_TEXT_OVERFLOW`，不为容量破坏专业术语。
先调整区域与行高；文字越界和碰撞保留 REVIEW。公式/图形容量、原图最小尺寸和科学关系仍是硬门禁。
`VISUAL_PLAN_UNSATISFIABLE` 要调整设计，不能删改科学内容或静默忽略失败。

## 5. 编译与候选

在 `Total-pipe/` 中先做无 PPTX 的布局检查，或直接生成候选：

```bash
python -m deck_compiler compile --ir <designed.deck_ir.json> --out <build-dir>
python -m deck_compiler build --ir <designed.deck_ir.json> --out <build-dir> \
  --officecli <officecli-path> --skip-native
```

统一入口 `python totalpipe.py generate <designed.deck_ir.json> --out <build-dir>` 使用同一构建流程，
默认生成候选；需要尝试原生渲染才加 `--native`。MCP 的 `totalpipe_compile` 仅编译布局和 QA，
`totalpipe_build` 生成候选和 QA，`totalpipe_review` 按需检查现有构建并导出截图。

默认提供方 `packer` 只建议几何，编译器执行文字适配、容量、原图尺寸与碰撞门禁；建议不通过
时记录回退原因。有 visual_plan 的页由编译器执行设计候选，不能被提供方覆盖，也不静默回退。
用 `--layout-provider compiler` 只运行编译器，外部提供方用 `module:factory`；旧 v26 模型已移除。
查看 layout 的 requested/selected 和候选失败原因，确认设计决定进入实际区域。
详见 [布局提供方](layout-provider.md) 与 [OfficeCLI 后端](officecli-backend.zh-CN.md)。

候选可作为普通生成任务的交付结果，但须标明状态与未解决项，不能称为正式 final。
FAIL 必须处理；WARNING 保留；REVIEW 需要相应审核。OfficeCLI `Text overflow` 可能误报或漏报，
保留原 issue 并检查实际页面，不据此删改科研内容。`FORMULA_MISSING/FORMULA_CONTENT_MISMATCH`
表示原生公式缺失或结构改变，不能靠存在一个公式标签就当成功。

## 6. 正式 final：PowerPoint 验收与晋级

用户要求正式 final 时，验收对象始终为本次 `staging.pptx`：

1. 在 Microsoft PowerPoint 普通/阅读视图逐页检查文字、公式、原图与图注、panel、字体、越界和碰撞。
2. 记录当前 staging/layout 哈希绑定的 UI review；PDF/HTML/截图不代替 PowerPoint 中的直接眼检。
3. 在同一次控制流程中导出当前 staging 的 `native.pdf`，绑定该 PDF 并重新验证。

```bash
python -m deck_compiler record-powerpoint-review --out <build-dir> \
  --reviewer <实际审核者> --slides all
python -m deck_compiler validate-native --out <build-dir> \
  --pdf <build-dir/native.pdf> --reviewer <相同审核者>
```

macOS / Windows 可尝试自动 PowerPoint 导出，也可在 UI 检查后手动导出并 validate-native。自动导出不代替
直接 UI review。不同版本的 PDF 或眼检记录不得复用；未做的平台验收如实注明。
source_figure、原图引用和图注须匹配；科学 panel 默认最小有效尺寸 220 CSS px，按协议显式
声明的下限也参与门禁，不能为排版静默降低。

若报告含 REVIEW，真实审核后提供当前文件绑定的 acknowledgement：

```json
{"artifact_sha256":"<staging sha256>","reviewer":"<审核者>","accepted_review_ids":["<全部已接受的 REVIEW ID>"]}
```

```bash
python -m deck_compiler promote --out <build-dir> --ack <review_ack.json>
```

没有 REVIEW 时可省略 --ack。只有结构检查、PowerPoint 原生证据、直接 UI review 和所需
acknowledgement 全部对应当前文件，才生成 `final.pptx`。手改 staging 后旧 QA、PDF 与审核记录失效。
科学审核不能由“截图看起来正常”自动清零。

## 7. 开发回归

需要验证实现时，在 `Total-pipe/` 运行编译器测试，在 `Total-pipe/pwf2rpa/` 运行桥接测试：

```bash
python -m unittest discover -s tests -v
```

RPA 自身的变更在 `research-ppt-assistant/` 运行 `npm test`；布局库变更再运行
`npm run audit:layouts`。公式回归样例可直接构建：

```bash
python -m deck_compiler build --ir examples/formula.deck_ir.json \
  --out <formula-build-dir> --skip-native
```
