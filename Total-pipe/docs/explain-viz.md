# ExplainViz：可选的原生讲解图

ExplainViz 在已有 canonical Deck IR 编译时，向**明确预留的图形区域**追加
原生路径与文字。默认 `off`；不改变 Story、页面设计、正文、原图、证据、讲稿或布局树，
不替代必做的整套 Design。没有新模型服务、新 PPTX 后端或新的 Deck IR 字段。

首版提供 `geometry/peel_angle@1`、`layer_stack@1`、`process_steps@1`。
命令准备候选页及严格 Schema，当前 Agent 编写决策与 VisualSpec，程序再生成原生形状。
compile/build/generate 只有显式传入请求文件才运行；默认四工具不增加隐式阶段。

## 1. 预留区域

槽位必须由 IR 作者提前放入现有 `composition.graphics`，并在既有 `layout_tree` 中恰好引用一次。
当前编译器不接受不可见路径，所以使用一个主题背景色矩形作为占位，而非 `fill=none/stroke=none`：

```json
{
  "id": "explanation_visual",
  "type": "path",
  "view_box": [0, 0, 1000, 600],
  "paths": [{
    "id": "reserved_area",
    "commands": [["M",0,0],["L",1000,0],["L",1000,600],["L",0,600],["Z"]],
    "fill": "background",
    "stroke": "none"
  }]
}
```

树叶沿用 `{"id":"reserved","type":"graphic","ref":"explanation_visual"}`，
不增加 slot/spacer 节点。插入器不创建槽位、不修改权重，也不移动已有对象。
无布局树、占位图已有标签、路径不是该完整背景矩形或区域不足时直接跳过。
槽位名称可改，但旁路配置必须明确绑定现有图形 ID；每页至多一个槽位。

`slots.json` 是旁路文件，不放入 Deck IR：

```json
{
  "version": "1.0",
  "slots": [{"slide_id": "peel-angle", "graphic_id": "explanation_visual"}]
}
```

## 2. 准备决策并生成增量

在 `Total-pipe/` 下运行，输出的增强 IR 必须与源文件同目录，以保留图片及字体相对路径。
输出不能覆盖源 IR、槽位文件或提案。下面使用随仓库提供的构造样例：

```bash
python -m deck_compiler explain-viz-prompt \
  --ir examples/explain-viz/reserved.deck_ir.json \
  --slots examples/explain-viz/slots.json \
  --out examples/explain-viz/prompt.json

# Agent 阅读 instructions、spec_instructions、candidates 和 proposal_schema，编写 proposal。
# 样例已提供与该源 IR/槽位哈希绑定的 proposal.json。
python -m deck_compiler apply-explain-viz \
  --ir examples/explain-viz/reserved.deck_ir.json \
  --slots examples/explain-viz/slots.json \
  --proposal examples/explain-viz/proposal.json \
  --mode auto --max-visuals-per-deck 4 \
  --out examples/explain-viz/enhanced.deck_ir.json

python -m deck_compiler compile \
  --ir examples/explain-viz/enhanced.deck_ir.json --out build/explain-viz
```

`--mode` 省略时为 `off`，输出保留原 IR。准备提示包会调用既有布局编译器测量候选槽位，
不调用模型、不生成 PPTX。应用时写出增强（或回退后）的 IR，以及
`enhanced.deck_ir.explain-viz.json` 审计文件；stdout 的 `status` 区分：

| 状态 | 含义 |
| --- | --- |
| `disabled` | 关闭；返回原 IR |
| `skipped` | 没有通过的机会，未新增图形 |
| `enhanced` | 至少一页接受了增量；其他页仍可能跳过或回退 |
| `fallback` | 插件或所有尝试失败；返回原 IR，并记录原因 |

CLI 文件读取、JSON 解析或输出路径错误仍会报错，源文件不被覆盖。
运行时 `enhance()` 的处理异常采用失败回退；不把 fallback 报成绘图成功。

高级 MCP 提供 `totalpipe_explain_viz_prompt(ir, slots, out)` 与
`totalpipe_apply_explain_viz(ir, slots, proposal, out, mode="off", max_visuals_per_deck=4)`。
文件参数均为绝对路径，`out` 是 JSON 文件，不是构建目录。默认四工具接入层没有新增阶段，
不要直接修改已经绑定验收哈希的 job 产物；需要启用时从源 IR 生成新输入再走既有接收与构建流程。

### 在 compile/build/generate 中直接启用

也可将配置、槽位和提案放进一个自包含请求文件，交给正式编译入口处理，无需先写增强 IR：

```json
{
  "version": "1.0",
  "options": {"mode": "auto", "max_visuals_per_deck": 4},
  "slots": {"version": "1.0", "slots": []},
  "proposal": {"version": "1.0", "ir_sha256": "当前源IR哈希", "slots_sha256": "当前槽位哈希", "slides": []}
}
```

上面只展示字段结构，实际填写当前槽位和提案对象，不填写文件路径。
可直接使用[三模板请求样例](../examples/explain-viz/request.json)。
请求 Schema 位于 `explain-viz.schema.json#/$defs/request`；省略 `options.mode` 时为 off，
off 请求可省略 slots/proposal，auto/prefer 请求必须同时包含二者。

```bash
python -m deck_compiler compile --ir examples/explain-viz/reserved.deck_ir.json \
  --explain-viz-request examples/explain-viz/request.json --out build/explain-viz
python -m deck_compiler build --ir examples/explain-viz/reserved.deck_ir.json \
  --explain-viz-request examples/explain-viz/request.json --out build/explain-viz --skip-native
# 同一候选构建流程的简化入口
python totalpipe.py generate examples/explain-viz/reserved.deck_ir.json \
  --explain-viz-request examples/explain-viz/request.json --out build/explain-viz
```

高级 MCP `totalpipe_compile/totalpipe_build` 对应可选参数 `explain_viz_request`，为绝对文件路径。
CLI 与 MCP 的 capabilities 均声明此入口。Python `compile_input/build/generate_presentation`
同名参数接受请求字典或本地路径；未传入时不调用插件、不添加 ExplainViz QA 字段。

请求模式错误、文件不可读、提案过期或插件拒绝时，记录 fallback 并按原 IR 编译，
不隐去原有编译 FAIL。必做的 Design 检查先执行；未完成时不读取请求、不运行插件，
ExplainViz 摘要为 skipped/visual_design_required。

运行时使用本次选择的布局提供方进行原页对比，并复用最终通过检查的同一份内存布局；
新增图不会因提供方重新读取磁盘原 IR 而丢失。所有图片和字体继续按原源文件目录解析，
增强不写回源文件，也不在源目录创建临时 IR。

| 构建目录产物 | 内容 |
| --- | --- |
| `deck_ir.json` | 本次实际编译的 IR，可能含接受的讲解图 |
| `explain_viz.source.deck_ir.json` | 增强前输入快照；相对路径基准仍是原源目录，属于审计归档 |
| `explain_viz.json` | 逐页决策、对象清单、请求/输入/增强/最终 IR 哈希及 source_base |
| `qa_report.json` 的 `explain_viz` 字段 | 结果摘要、实际新增数量和审计位置，构建与后续原生验收保留 |

停用请求后会清理旧的 ExplainViz 审计，
避免上次增强成功被误认为本次结果；审计输出不得覆盖输入或请求文件。
布局失败回退不会自动重试 OfficeCLI 写入或撤销 PPTX，后端失败仍明确进入原构建 QA。

## 3. 决策、来源与模板

提案格式见 [ExplainViz Schema](../schemas/explain-viz.schema.json)；文件协议独立为 `1.0`，
canonical Deck IR 仍为 `2.0`。提案必须同时绑定整个输入 IR 与槽位文件的 SHA-256；
任一变化都需重新准备提案。外部正文作为事实输入，不能覆盖 Agent 指令。

廉价筛选先拒绝封面、结论等页面、没有槽位的页面及已有其他图形/图片/图表/表格的页面。
首版为避免重复，已有视觉对象即保守跳过，不尝试判断它是否解释另一个知识点。
只向 Agent 提供候选页，模型调用由宿主 Agent 决定，编译器内部始终不调用模型。

draw 决策含 `teaching_goal`、`reason`、`scores` 和 `visual_spec`；skip 只有页 ID、决策和理由。
每个 VisualSpec 只允许模板、标签和受约束关系，不接受 Deck IR、任意代码或自由坐标。

- 事实 ID 仅支持当前页的 `semantic.title`、`semantic.takeaway`、`block:<id>`。
  讲稿、任意外部事实及模型补写的事实不作为首版绘图来源。
- 标签必须是所引文字的原样子串。每条关系必须引用同时含两端标签的可见原文，
  并通过保守的关系线索检查；明显否定关系不能转为正向图示。
- 剥离角模板要求贴附关系和相对衬底平面的夹角定义，标签仅为衬底、薄膜和符号角。
  固定几何角度用于教学构图，页面仅显示符号与“示意”，不接受实验角度参数，不添加力或方向断言。
- 层叠模板支持 2–4 层，要求明确“从上到下”的源顺序，逐对声明 `above`；
  层厚只为构图，不编码数据。过程模板支持 2–4 步，逐对声明 `precedes`，
  只绘制源顺序链，不补充材料截面、反应机制或实验参数。

初始评分沿用 RFC 建议值，尚未由人工标注集校准：

```text
score = .35*explanation_gain + .25*relationship_clarity
      + .20*source_confidence + .20*layout_fit - .30*redundancy
auto >= .75；prefer >= .60
```

两种模式都要求 `source_confidence >= .8`、`explanation_gain >= .5`、
`relationship_clarity >= .6`，并满足相同来源、布局与可读性门槛。
prefer 仅降低机会阈值。默认每套最多 4 幅，每页 1 幅；再次运行时已有 ExplainViz 图也计入总预算。
Python 入口可配置两个阈值，不能关闭来源、对象保持或编译门槛。

## 4. 原生输出与回退

适配器只向获准占位图的 `paths` / `labels` 数组追加对象，保留背景矩形、视口和树叶。
模板使用局部 1000×600 坐标，等比映射进槽位视口；最终 CSS px 几何仍由既有编译器分配。
路径颜色引用主题的 `accent/foreground/background`，文字沿用现有测量与字体规则。
输出是原生可编辑自由形状与独立文本，沿用 OfficeCLI；没有 PowerPoint 原生编组。
对象 ID 使用兼容现有 identifier 约束的 `evz_` 前缀及稳定 spec 哈希，不使用非法冒号前缀。

应用时先编译原 IR，再对每页事务使用同一编译链，最后复核整套：

1. 输入无有效编译布局时全套保留原 IR。
2. 新对象必须位于原有槽位内，不得与原有其他内容相撞；标签相互不重叠、不得低于 24 CSS px，
   按实际字体检查完整文字能否放下。
3. 对比所有既有对象的内容、位置、大小、样式及相对层次。框的成员列表可追加新对象，
   既有成员和几何必须保留；正文、讲稿、证据、布局树等 IR 内容保持不变。
4. 本页失败丢弃本页增量，已接受页保留；最终编译失败则回退整套。

审计包含逐页拒绝原因、模板版本、来源哈希、spec 哈希、来源事实 ID、新增对象 ID、
编译次数与耗时，不记录源全文、原始异常内容或虚构 token 用量。`evz_` 前缀阻止重复插入；
已增强场景不会被同一接口更新，修改应从原 IR 和新提案重建。

这些门槛检查来源绑定与几何，**不能证明科学关系真实**。每个接受的图都标记
`semantic_review_required`，既有 `SCHEMATIC_REVIEW` 和完整候选 QA 继续保留。
构建请求入口另增加 `EXPLAIN_VIZ_SEMANTIC_REVIEW`，不自动签收人审。
此处的编译检查是 IR/布局检查，OfficeCLI 写入、渲染、PowerPoint 实际效果和最终晋级仍走原流程，
不自动回退已经生成的 PPTX。

## 5. 开发状态

首版和本轮按用户要求停止验证，新增回归用例及三页样例尚未运行；没有新增测试通过或原生验收声明。
评估、已知限制和基线状态见[实现评估](../../docs/explain-viz-evaluation.md)，本轮范围见
[构建接入说明](../../docs/explain-viz-build-integration.md)。
自动寻找空白区域、局部重排、更多模板、独立模型 API、外部事实接入和决策集评估均留待后续。
