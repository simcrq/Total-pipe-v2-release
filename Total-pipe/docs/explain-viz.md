# ExplainViz：可选的原生讲解图

ExplainViz 在已有 canonical Deck IR 进入正式 compile/build 前，向**明确预留的图形区域**追加
原生路径与文字。默认 `off`；不改变 Story、页面设计、正文、原图、证据、讲稿或布局树，
不替代必做的整套 Design。没有新模型服务、新 PPTX 后端或新的 Deck IR 字段。

首版提供 `geometry/peel_angle@1`、`layer_stack@1`、`process_steps@1`。
命令准备候选页及严格 Schema，当前 Agent 编写决策与 VisualSpec，程序再生成原生形状。
普通 compile/build/generate 和默认四工具不会自动启用该步骤。

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

应用时先编译原 IR，再对每页事务调用同一 `compile_deck`，最后复核整套：

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
此处的编译检查是 IR/布局检查，OfficeCLI 写入、渲染、PowerPoint 实际效果和最终晋级仍走原流程，
不自动回退已经生成的 PPTX。

## 5. 开发状态

本轮按用户要求停止验证，新增回归用例及三页样例尚未运行；没有新增测试通过或原生验收声明。
评估、已知限制和基线状态见[实现评估](../../docs/explain-viz-evaluation.md)。
自动寻找空白区域、局部重排、更多模板、独立模型 API、外部事实接入和决策集评估均留待后续。
