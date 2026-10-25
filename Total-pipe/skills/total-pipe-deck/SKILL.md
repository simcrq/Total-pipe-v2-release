---
name: total-pipe-deck
description: 从论文 PDF 或已有研究规划生成可编辑研究汇报 PPTX；保留 PaperWorkflow 证据、Story 与 RPA 规划，执行整套视觉设计，再由 Deck Compiler 和 OfficeCLI 编译、验收。
---

# Total-pipe 研究汇报流水线

```text
PDF → PaperWorkflow → Story Planner → [DesignIntentPlanner] → pwf2rpa → RPA
    → canonical Deck IR → Scientific Visual Planner（design 阶段，默认必做）
    → 合入设计的 Deck IR → packer / compiler → OfficeCLI → candidate.pptx + QA
    → 用户要求正式 final 时：PowerPoint 原生验收 → 审核 → promote
```

从已有产物继续相应阶段，不重复 OCR 或重写已经通过的科学故事。科研内容只有一个真源：
Canonical Deck IR；`derived/` 中的计划、资源清单和 QA expectation 都是只读派生物。
用户本轮或此前已给出的模型、语言和汇报要求继续有效。

## 工作目录与入口

先定位实际仓库，不猜测安装缓存路径。本文路径相对仓库：

- Deck Compiler 命令在 `Total-pipe/` 运行；配置是 `Total-pipe/.mcp.json`。
- pwf2rpa 命令在 `Total-pipe/pwf2rpa/` 运行。
- RPA 命令在仓库根目录运行，入口为 `research-ppt-assistant/server/cli.mjs`。
- MCP 的 `ir`、`out`、`proposal` 等路径必须为绝对路径；CLI 可用相对路径。
- MCP 服务若尚未加载当前代码或新 schema，使用同一仓库的 CLI；运行中的旧服务需重载才能读取更新。

使用当前可用的 Python/Node/OfficeCLI；默认布局提供方是 `packer`，也可用 `compiler` 或
`module:factory`。旧 `v26` 扩散模型已移除，不再用 `--layout-provider v26`。

## 1. 证据：PaperWorkflow

先根据论文主题和汇报问题写检索 `queries`。有定制 queries 时省略
`include_default_queries` 即仅使用定制问题；要混用通用问题才传 `true`。
生成并读取 schema v4 的 `workflow.json`、`document.manifest.json`、`evidence.md`；
下游优先引用 `EV####`。

主文提到补充材料而文件名无法自动配对时，显式传实际 `supplementary_paths`。
文件存在只证明取得来源：先让补充材料 OCR/Markdown 内容进入分析输入，再设
`supplementary_content_included=true`。分别检查 `quality_audit` 和
`synthesis_readiness` 的六项门禁；文本捕获成功不能代替科学综合就绪。
`review/blocked` 的原因必须保留，不能用摘要消除。

## 2. 科学故事：Story Planner

尚未获得用户的模型选择时，先请用户选择可用的高能力模型与至少 `high` 的 reasoning。
模型已在本会话选定则沿用。Story 由该模型的独立 subagent 生成，主 Agent 不代写科学故事。
这项用户选择与 subagent provenance 是 pwf2rpa 的硬门禁。

先调用 `pwf2rpa_story_prompt`，原样传 `model`、`reasoning_effort`、
`selected_by_user=true`；子代理读取输出文件的完整 `instructions/evidence_store/output_shape`。
未传 `out_path` 时输出在 workflow 旁。CLI 回退：

```bash
python -m pwf2rpa <workflow.json> --make-story-prompt <story_prompt.json> \
  --story-model <用户选择> --story-reasoning <用户选择的强度> --model-selected-by-user
```

提示包生成器不调用模型。按论证需要安排 4–10 个节点，不凑页数：

```json
{"title":"可选展示标题","question":"...","answer":"...","evidence":["EV0001"],"next":"..."}
```

`question/answer/evidence` 必填，`next` 仅最后节点可省略。`title` 可独立于 question，
省略时取 question；不要为了标题形式硬拼“主题：结论”。摘要不足以保留科学细节时加
`key_points` 字符串数组，条数由内容决定。`ending.limitation` 仅记录论文边界，
输入是否取得、SI 是否审阅等放工作记录。

顶层记录真实 provenance：

```json
{"planner":{"mode":"subagent","model":"<用户选择>","reasoning_effort":"high","selected_by_user":true}}
```

校验不通过时把原证据和错误退回同一子代理修订。标题和正文保留完整、正确的科学术语、
化学态、单位和限定词，不为容量自造缩写或截断术语。

### 可选的 DesignIntentPlanner

只有恰好四条要点具有明确步骤关系时，单独声明上游科研流程语义：

```json
{"slides":[{"story_node_index":2,"relation":"process","orientation":"vertical","emphasis":4}]}
```

索引从 1 开始，emphasis 可省略。此步骤不改 Story、不写坐标；没有明确关系时省略。
它不替代第 5 节的全 Deck 视觉设计。

## 3. pwf2rpa 与 RPA

```bash
python -m pwf2rpa <workflow.json> --story <story_plan.json> \
  --story-model <用户选择> --story-reasoning <用户选择的强度> \
  --model-selected-by-user --strict --out <rpa_input.json>
```

有设计意图才同时加 `--design-intent <design_intent.json>`。MCP 的对应字段为
`story_path/design_intent_path`；设计意图不能脱离 Story 单独传。

在仓库根目录运行：

```bash
node research-ppt-assistant/server/cli.mjs normalize-content \
  --file <rpa_input.json> --detail-level full > <normalized_content.json>
node research-ppt-assistant/server/cli.mjs plan --file <rpa_input.json> \
  --presentation-type group_meeting --slide-count <N> --detail-level standard > <deck_plan.json>
node research-ppt-assistant/server/cli.mjs validate-deck \
  --file <validation_input.json> --detail-level compact
```

要求 normalize `status=valid`；规划 `pipeline_status=plan_complete`、
`status=success/adapted` 且 `unplanned_slide_briefs` 为空；validate `status=valid`。
逐项检查 adaptation，不接受正文或要点被 truncate。验证输入必须带本轮 slides 与原始完整
`normalized_content.json` 作为 `content_model`；`KEY_POINTS_LOST/SOURCE_TEXT_NOT_BOUND`
要恢复原文，不能删改 content_model 消除错误。MCP 摘要、slot 短文本和设计消息不能替代源 Brief。

RPA 负责 Layout/Slot/容量与 `layout_contract`，不输出最终页面 bbox。
硬流程组须保留四条原文、顺序及 Slot Binding，`VISUAL_INTENT_NOT_BOUND/GROUP_SPLIT`
需要重规划，不能自动拆散。总结页保留 summary 类别；不要为通过容量改成错误类别。
`max_chars` 只是粗筛，`SLOT_WRAP_RISK` 也不能代替实际渲染。

## 4. Canonical Deck IR：正文、图片、图形和公式

按 `Total-pipe/schemas/deck-ir.schema.json` 与 `deck_compiler/catalog.py` 映射：

- `semantic`：完整展示标题、purpose、takeaway、证据、论文边界、讲稿。
- `composition`：稳定 archetype、完整 blocks、原图 figure_refs、显式原生 graphics。
- `presentation`：整套 frame、文字策略与设计决策，不复制第二份科学内容。

映射时可先显式设顶层 `presentation.text_capacity_policy="preserve-terms"`，
让完整长标题和正文在进入设计提示包前也能保留，不等到样式合入后再处理字符预算。

标题优先取 `metadata.story_title` 中的完整 Story 标题，不使用 RPA 临时压缩的短标题。
逐条核对源 `key_points` 和正文：按原顺序进入 block、图形节点完整 title/body 或讲稿；
必要的展示内容仍须可见，不能全部藏到 notes。段落边界保持换行，按需复制
`design_ir.text_flow.mode` 到 block 的 `text_flow`；不要为了触发列表样式改写科研内容。
证据编号和运行记录进入备注，不放到面向听众的标题、结论或 caveat。

整套采用同一 frame（`default/spacious`）。有硬流程 layout_contract 时，映射实际 block ID：

```json
{"relation":"process","members":["b1","b2","b3","b4"],"orientation":"vertical","preserve_order":true,"emphasis":"b4"}
```

该对象放 `composition.visual_intent`；只支持四个无独立 label 的 block，有一张原图用
`figure-parameters`、无图用 `process-flow`。不得与 graphics 或视觉重排混用。

### 原生列表与单段标记

正文列表先明确条目换行，用 text_flow=distributed_arrow_list 保留原生无序列表。
读 `Total-pipe/docs/native-lists.md`：顶层 presentation.bullet_style/bullet_color 设默认，block 同名字段覆盖。
单页 presentation.takeaway_marker={style:large_diamond,color:#000000} 为完整 takeaway 加一个独立标记；
可与 takeaway 行内公式共存，符号颜色不改正文颜色。preserve-terms 不移除项目符号，
垂直超容量保留原文与 REVIEW；显式列表宽度至少 520 px，高度按完整内容实测，不使用固定高度门槛；
空间不足时回到布局规划或拆页。
不要为套入列表缩短术语，也不要把失败列表改成普通文本掩盖问题。
标记可选；plain 关闭正文列表，不配置 takeaway_marker 则无前导标记。优先选 large_square、
large_diamond、arrowhead 等饱满原生字形，不设置项目符号百分比 / 点数缩放；符号颜色独立配置。

### 原生图形

使用 `composition.graphics`，不写页面坐标、不从普通正文推断关系。按实际类型读取：

- 流程、DAG、分支/汇合及图文混排：`Total-pipe/docs/native-graphics.md`。
- mechanism、architecture、funnel、path、composite：`Total-pipe/docs/native-components.md`。

机制边须明确关系及 `evidence/hypothesis` 依据；证据引用绑定本页，假设保留虚线与标签。
图形与原图、完整正文/图注共存，生成图不能代替论文证据；`SCHEMATIC_REVIEW` 始终保留。
图像来源按实际区分：论文图用 `origin: paper` 和完整 `source_figure`；管线绘制的图用 `origin: generated`、`generator`
及“示意图”图注；从用户提供的幻灯片或图片裁切时用 `origin: reference` 和非空白的 `reference_source`，
不填写 `source_figure`、不强制加示意图图注；仍检查裁图来源、最小可读尺寸和 `REFERENCE_IMAGE_REVIEW`。
Path 仅接受局部 view_box 与绝对 M/L/C/Q/Z，输出原生 custGeom；不是 SVG 导入或页面坐标接口。

### 可选的复合内容区域

复杂混排需要子布局时，读 `Total-pipe/docs/composite-layouts.md`，先查询 totalpipe_capabilities
（CLI：`python -m deck_compiler capabilities`）。再用 RPA search_sublayouts/compose_sublayout 手工选择，
或 plan_sublayout 自动选型；整页规划可传 body_compositions[{slide_id, request}]。
request 提交完整 canonical groups/content_refs 和新查询的消费者能力；不从 compact 摘要恢复内容。
把 composition_patch 合入 canonical slide。缺少能力则沿用旧整页布局，不以 compact slot 文本重写正文。

composition.layout_tree 1.0/1.1/1.2 支持 columns/stack/panel/image_grid，最多 6 层、64 节点。
叶节点引用 block ID、figure_refs 零基索引、graphic ID，1.1 另支持 table ID；每项恰好一次。显式 anchor 的公式与解释
在同一 stack、解释在前。不写页面坐标，不裁剪原图，不缩小图形绕过字号下限。树页仍需要整套
academic_design，不再叠加 visual_plan/visual_intent。structure_planned 不能当成几何通过。

需要外框、标题色带或结论框时，读 `Total-pipe/docs/framed-containers.md`。在 canonical 映射阶段
为 panel 声明 frame.border（可选 fill/title_fill/title_color/title_align），并将树版本改为 1.2；
未声明 frame 的 panel 仍不绘制背景。单页 presentation.takeaway_frame 为完整结论独立加框，
可与可选 takeaway_marker 和 inline_math 共存。不用绝对坐标叠矩形；描边、内边距与标记槽都消耗容量。
保留完整术语导致边框增长时检查 FRAME_EXPANDED_FOR_TERMS 与碰撞 REVIEW，不据此省略完整 Design 或原生验收。

编译后读 layout_feedback.json 的 slide_id、component、所需/实际尺寸和 suggested_actions，带原始完整
内容回 RPA 调整结构。plan_sublayout 接收当前 ir_sha256 和 compiler_feedback，哈希必须绑定完整 IR，
并传 rejected_sublayout_ids 排除已失败结构。未知/重复 slide_id、过期反馈、无合法候选均需重规划。
最多自主修订三次；同一问题仍存在则保留失败并向用户说明所缺空间，不继续无界循环或删改科学内容。

原生科研表格读 `Total-pipe/docs/native-tables.md`。composition.tables 保存完整 cells，支持多级表头、
row_span/column_span 及 formula/矩阵格；每个逻辑位置必须恰好覆盖一次，不自动补零或推断数据。
paper 表格 evidence_refs 必须绑定本页。每页最多 4 表、每表最多 32 行/12 列；字体下限 18 pt。
纯文字表格超容量按 preserve-terms 保留 REVIEW；含公式表格尺寸不足需加宽或拆页。
始终保留 TABLE_CONTENT_REVIEW 与近似公式测量审核，原生 PPTX/PDF 必须检查合并表头、公式及单位。

### 公式：独立公式与显式行内模式

展示公式用 `component: "formula"`，`text` 保存 LaTeX 子集。普通文本默认不解析数学标记。
需要行内混排时读 `Total-pipe/docs/inline-math.md`：正文块或表格 text 格加 inline_math=true，
用 `$…$` 或 `\(…\)` 标记完整数学区域；semantic.inline_math 列出 title/takeaway 可开启相应字段。
先查询 native_inline_equation 与 native_equation 能力；RPA content_refs 传 block.inline_math /
table.has_inline_math。图注、图形标签和 panel 标题暂按原有文字处理。

混排宽度和高度按逐行片段、基线上下需求测量，不按 LaTeX 命令长度或固定正文行高估算。
公式保持完整单元；过宽改用独立公式或加宽，不缩到字号下限以下。标题/正文按 preserve-terms
保留全文及高度溢出 REVIEW；含行内数学的表格按公式表格执行真实容量门禁。
行内模式不使用 distributed_arrow_list；字面美元符号须转义。保留 INLINE_MATH_MEASUREMENT_REVIEW，
实际核对 PowerPoint 的基线、换行与表格边界。原有独立公式不变。JSON 必须转义反斜线：

```json
{"id":"equation","component":"formula","text":"\\sqrt{\\frac{1+e^{-t}}{1+x^{2}}}","anchor":"explanation"}
```

`anchor` 可省略；存在时指向本页前方的非公式 block。无标签公式默认贴在前一说明块下方，
有 label 时标签与公式并排。支持 `\frac`、`\sqrt{…}`、`\sqrt[3]{…}`、`^/_`、
嵌套分组、`\left/\right`、Greek、求和/积分、`\exp/\log/\ln`、常用三角函数、
`\text/\mathrm/\mathbf/\mathit`。多项底数和指数写完整分组，如 `{xy}^{a^{2}}`。

矩阵使用 `\begin{bmatrix}…\end{bmatrix}`，单元格以 `&` 分列、`\\` 分行；
支持 `matrix/pmatrix/bmatrix/Bmatrix/vmatrix/Vmatrix`，也可用 `\left/\right` 包住裸 matrix。
保留所有行列、空单元格、分数、根号、上下标与外部转置，不能用普通文本拼方括号。
例如 2×2 矩阵的 JSON 为 `"\\begin{bmatrix}1&2\\\\3&4\\end{bmatrix}"`。
矩阵按单元格和行列测量并写成原生 OMML，Office 的间距仍保留原生核对 REVIEW。

先核对 `FORMULA_SYNTAX` 的字符位置；不支持的宏、array/cases 等不能硬塞给写入器。
保留表达式的数学含义，使用支持的等价形式或回到规划调整，不把公式降成错误的 Unicode 文本或位图。
密集推导页使用 `equation-derivation`，保留完整公式及说明，编译器按实测行高尝试单双栏。
公式没有“每页两条”的数量门禁，也不把双栏公式高度相加当成单栏容量；字号仍不低于
24 CSS px（18 pt）。显式 anchor 的公式组留在同一栏；后续无 anchor 的连续公式可独立成行。
不拉高说明文本框吸收留白；查看 `formula_flow` 的实际列数、字号、阅读顺序和候选容量。
超出真实区域时再用宽槽或拆页，不删公式或压缩科学术语。
`preserve-terms` 下，说明文字容量不足也保留完整术语并标记 REVIEW；公式本身须满足真实宽高。
详见 `Total-pipe/docs/deck-compiler-v2.md` 的 Formulas，以及
`Total-pipe/examples/formula.deck_ir.json` 与 `Total-pipe/examples/matrix-derivation.deck_ir.json`。
数学表达式按 AST 测量并写成原生 OMML；近似测量保留 REVIEW。HTML 截图仅显示 fallback，
根号、分式线和指数的实际排版须在 PowerPoint 原生视图检查。

## 5. Design 阶段：Scientific Visual Planner（默认必做）

Canonical IR 完成后，由当前 Agent 读取完整内容并设计一次整套 Deck；不需要新模型服务。

1. 调 `totalpipe_visual_prompt(ir, out, requirements)`，或运行 `visual-prompt`。
2. 读取完整提示包的 `deck_ir/available_assets/planning_targets/schemas`，生成绑定
   `ir_sha256` 的提案；为整套选一个 `academic_design`，为每个支持的页面写 `visual_plan`。
3. 调 `totalpipe_apply_visual_plan(ir, proposal, out)`，或 `apply-visual-plan`，严格验证后合入。
4. 后续 compile/build 必须读取合入后的 IR。科学内容改变后重新检查设计，不沿用过期提案。

```bash
python -m deck_compiler visual-prompt --ir <deck_ir.json> --out <visual_prompt.json> \
  --requirements <科研汇报要求>
python -m deck_compiler apply-visual-plan --ir <deck_ir.json> \
  --proposal <visual_proposal.json> --out <designed.deck_ir.json>
```

`out` 在这两个工具中是 JSON 文件路径。源 IR 用相对资源路径时，新 IR 必须与源 IR 同目录。
提案只改变 presentation，不改 Story、正文、原图、数值、图注、讲稿和科学关系。
协议与示例读取 `Total-pipe/docs/scientific-visual-planner.md`。

支持的视觉任务：单图测量证据、既有机制图解释、双图证据比较。由科学阅读顺序决定主视觉、
左右/上下、占比及原文强调；全套统一字体层级、强调色与标题/图注处理。强调必须精确出现在
引用的可见原文中。保留克制的原生细线、科学标注，避免商业 KPI 卡片和无意义装饰。
`planning_targets` 会列出不支持的页面及原因，硬流程组保持原顺序；不为补设计虚构图或机制。
纯文字/公式 Deck 仍选择整套 academic_design，提案可为 `slides: []`。

默认 compile/build/generate 会用 `VISUAL_DESIGN_REQUIRED` 阻止漏做设计，返回完整提示包和缺失页。
补做提案并合入后重试；不要自动设置跳过标记。只有用户明确要求旧版构建时才用
`--skip-visual-design`（MCP：`skip_visual_design=true`）。直接低层 `compile_deck` 保持旧 IR 兼容。

默认 `text_capacity_policy=preserve-terms`：标题、正文超字符或槽位预算仍保留全文并生成候选，
记录 `SCIENTIFIC_TEXT_CAPACITY_REVIEW/SCIENTIFIC_TEXT_OVERFLOW`，不为容量破坏术语或科学含义。
先增行高、调整区域，溢出越界/碰撞保留 REVIEW；原图尺寸、公式/图形容量与科学关系仍是硬门禁。
`VISUAL_PLAN_UNSATISFIABLE` 修改设计，不能删科研内容、降低原图下限或静默忽略失败。

## 6. 编译、候选与正式验收

```bash
python -m deck_compiler build --ir <designed.deck_ir.json> --out <build-dir> \
  --layout-provider packer --officecli <officecli-path> --skip-native
```

MCP：`totalpipe_compile` 仅编译布局与 QA；`totalpipe_build` 生成候选与 QA；
`totalpipe_review` 按需检查现有构建并截图。提供方只建议几何，编译器执行真实字体、容量、
碰撞、原图下限与科学关系门禁，OfficeCLI 写 PPTX。`layout_provider.json` 的 `COMPILER_OWNED`
表示递归区域、视觉计划、公式、显式列表或图形等页面按设计由编译器布局；不要把 owned 当成提供方失败。
查看 packed / owned / fallback / rejected、coverage 及具体回退原因，
`layout.json/derived/plan_to_layout.json` 的 requested/selected 是否执行了设计决定。

普通生成任务交付 `candidate.pptx` 路径、FAIL/WARNING/REVIEW 数量及关键未解决项，
不把候选叫 final。`FORMULA_CONTENT_MISMATCH/FORMULA_MISSING` 等失败须修复；
公式不仅要存在，还须保留被开方项、根指数和所有上下标结构。
OfficeCLI 的 `Text overflow` 有误报/漏报：保留原 issue，检查实际页面，不据此压缩或删除科学内容。

只有用户要求正式 final 才执行 `Total-pipe/docs/deck-compiler-v2.md` 的完整验收与 promote：
直接在 PowerPoint 逐页检查当前 staging，记录绑定实际文件哈希的 UI review，再用该文件导出的
原生 PDF 验证。OfficeCLI/HTML/PDF 截图不能冒充 PowerPoint UI 眼检。
科学审核项需真实审核者接受，不能因观感良好清零；未完成平台验收必须如实注明。
