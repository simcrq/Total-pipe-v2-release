# 原生可编辑流程图

Native Graphic v2（`feat/native-graphic-connectors`）支持独立的 `native-graphic` 页面：
3–4 个节点、相邻节点间的原生连接符，以及独立的标题和正文文本框。
`process` 现在支持横向链式、横向错位和纵向链式；节点可单独标 `tone` 强调。
图形区域使用现有页面 frame，内部由 `deck_compiler/graphic_layout.py` 确定性布局，
经现有 OfficeCLI 输出。没有新增渲染器或依赖。

**编辑边界：** 节点形状、文字、关系标签、T 端帽和层容器仍是独立对象，没有 `p:grpSp` 编组。
移动节点不会自动带走独立文字；连接符可能被 PowerPoint 重新布线。持久修改优先改 canonical IR
的结构、weights、gap 或 align 后重建。必须手改时选全相关对象、必要时自行组合，再检查文字与路由；
重建不会保留手改产物。原文件没有组，无需先解组。详见[复杂页维护说明](complex-page-qa.md#图形编辑与-provider-边界)。

`feat/native-graphic-dag-layout` 在同一入口增加显式的 `type: "dag"`，支持分支、
并行路径、汇合和跨层连接。`type: "process"` 的 v2 布局与输出命令保持不变。

## 直接运行

在 `Total-pipe` 目录执行：

```powershell
python -m deck_compiler build --ir examples/native-graphic.deck_ir.json --out builds/native-graphic-native --layout-provider packer
```

输出 `builds/native-graphic-native/candidate.pptx`、`native.pdf` 与 `qa_report.json`。
Windows/macOS 上安装 PowerPoint 后，完整构建会通过 PowerPoint 导出 PDF 并检查文字和字体；
只有实际生成 PDF 才记录 `checks.native=true`。没有 PowerPoint 时保留
`NATIVE_RENDER_UNAVAILABLE`。快速开发可显式传 `--skip-native`，此时只得到候选产物。
示例两页覆盖全部五种节点形状。普通编译入口和 MCP `totalpipe_compile` /
`totalpipe_build` 均可使用，无需新增工具。默认 packer 对没有普通内容单元的
图形页沿用编译器布局；原有页面照常打包。

## 在 Deck IR 中声明

保留普通页面的 `semantic` 和 `presentation`，将 `composition` 写成：

```json
{
  "archetype": "native-graphic",
  "blocks": [],
  "figure_refs": [],
  "graphics": [{
    "id": "method",
    "type": "process",
    "direction": "horizontal",
    "nodes": [
      {"id": "input", "shape": "ellipse", "title": "输入", "body": "原始数据"},
      {"id": "analyze", "shape": "rounded-rect", "title": "分析", "body": "提取特征"},
      {"id": "output", "shape": "hexagon", "title": "输出", "body": "汇总结果"}
    ],
    "edges": [
      {"from": "input", "to": "analyze"},
      {"from": "analyze", "to": "output"}
    ]
  }]
}
```

- `direction` 支持 `horizontal`（默认，从左到右）和 `vertical`（从上到下）；
  纵向链在正文区高度有限，3 步更稳，4 步请只用短标题或省略 `body`。
- `layout` 支持 `chain`（默认）、`staggered` 和 `compact`；`staggered` 只用于横向，
  相邻节点上下错开约 28 px，连接符使用三折弯头，便于在宽页上打破“一条直线”。
- `compact` 是“更多步骤、全方形”的横向布局：支持 3–8 个 `rect` 节点，
  节点边长最大 180 px、最小 96 px，按可用宽度等比缩小，整体居中；
  字号用 24 CSS px（18 pt）下限，标题保持短，`body` 尽量省略。
  它强制 `shape=rect`（可省略 `shape`），不接受 ellipse/diamond/hexagon。
- 节点按数组顺序排列；横向从左到右、纵向从上到下。必须显式连接每对相邻节点，
  且恰好一次；`kind` 可省略，当前只接受 `arrow`。不推断、补写或改变科学关系。
- `shape` 支持 `rect`、`rounded-rect`（默认）、`ellipse`、`diamond`、`hexagon`。
  `compact` 只用 `rect`；纵向链的 `hexagon` 使用最接近上/下顶点的连接点，
  不假装存在边中点。
- 节点可带 `tone: "default" | "emphasis"`；`emphasis` 只加深主题色 tint 并加粗描边，
  仍是同一套 theme，不是新的配色。用于标出结论步或关键分支。
- `title` 必填，最多 80 字符；`body` 可省略，最多 180 字符。
  实际可容纳字数取决于形状和文本宽度；菱形内部空间较小。
- 图形和节点 ID 使用 1–64 个英文字母、数字、连字符或下划线。
  节点 ID 在图内唯一；编译后对象名包含图形和节点 ID，可在选择窗格中定位。
- 字体继承 deck theme，描边与箭头使用 `theme.accent`。文字独立测量并居中，
  不低于 18 pt；装不下时返回 `SPLIT_REQUIRED`，保留原文。
- 不写 `x/y/w/h/bbox`。旧平面表示一页最多一张原生图形；独立页使用 `native-graphic`。
  `process-flow`、`figure-parameters` 可与 blocks 和论文图片混排，见下文。
  其他 archetype 下的非空 `graphics` 会明确报错，避免内容被忽略。

复合区域扩展允许把最多 8 项 canonical graphics 分配到不同子区域，并与公式、图片和正文混排。
此时使用 `composition.layout_tree`，每项恰好引用一次，绕过平面 archetype 的数量粗筛，但不绕过
原有图形尺寸和证据门禁。详见 [Layout Tree 1.0](composite-layouts.md)。

节点是 `p:sp` 预设形状，文字是独立文本框，边是 `p:cxnSp` 直线连接符。
布局器输出源/目标节点、端点和形状专属连接点索引；OfficeCLI 在所有节点创建后，
通过 `from/to` 解析实际的 PowerPoint 形状 ID，再写入 `a:stCxn` / `a:endCxn`。
箭头在目标端；在 PowerPoint 中移动节点，连接符随之调整。文字仍是独立对象，
分支与汇合使用下文的 DAG 类型；v5 的自由形状使用
[Path IR](native-components.md)，尚不提供 PowerPoint 编组或 SVG 导入。

连接点使用 DrawingML 的零基索引，见
[预设形状定义](https://github.com/apache/poi/blob/trunk/poi/src/main/resources/org/apache/poi/sl/draw/geom/presetShapeDefinitions.xml)：

| 形状 | 右侧 / 源端 | 左侧 / 目标端 |
|---|---:|---:|
| rect / roundRect / diamond | 3 | 1 |
| ellipse | 6 | 2 |
| hexagon | 0 | 3 |

原有 Graphic IR 不需要迁移。结构 QA 会拒绝缺失连接符、无效引用、错误节点或连接点、
反向箭头以及用浮动形状替代连接符。XML 通过仍需在 PowerPoint 中实际拖动节点，
确认连接符跟随，并单独修改文字验证可编辑性。

结构 QA 核对对象身份、数量、唯一形状 ID、连接关系、几何、预设形状、填充、描边和文字契约；
只有节点自身的背景与文字可以相互包含，其他相交仍按碰撞处理。
生成的流程图保留 `SCHEMATIC_REVIEW`：需要确认图示与科学解释一致。
使用 `--skip-native` 的输出是候选文件，不能据此声称已通过 PowerPoint 原生验收。

## DAG：分支、并行与汇合

完整示例包含线性回归页、三路分支、三路汇合，以及带跨层绕行的四层图：

```powershell
python -m deck_compiler build --ir examples/native-dag.deck_ir.json --out builds/native-dag --layout-provider packer
```

独立图形页继续使用 `native-graphic`，`blocks` 和 `figure_refs` 留空。只改变图形类型与
显式节点/边；不写布局坐标。例如：

```json
{
  "id": "experiment",
  "type": "dag",
  "direction": "horizontal",
  "nodes": [
    {"id": "input", "title": "输入", "shape": "ellipse"},
    {"id": "a", "title": "条件 A", "body": "独立测量"},
    {"id": "b", "title": "条件 B", "body": "对照测量"},
    {"id": "result", "title": "汇合", "shape": "hexagon"}
  ],
  "edges": [
    {"from": "input", "to": "a"},
    {"from": "input", "to": "b"},
    {"from": "a", "to": "result"},
    {"from": "b", "to": "result"}
  ]
}
```

先按显式边拓扑排序，以最长前驱路径分层，再以稳定的重心排序减少交叉。
层从左到右排列，层内纵向排布；输入节点顺序作为相同优先级的稳定顺序。
孤立节点、互不连接的并行路径不会自动增加边。循环、自环、重复边和失效引用
在 IR 校验阶段拒绝。

节点复用 v2 的五种形状、独立文字和形状专属连接点。DAG 按实际字体在 18 pt
下测量文字，计算不同的节点高度；正文最多四行、标题最多两行。原文完整保留，
装不下时返回 `GRAPHIC_TEXT_OVERFLOW` 或 `GRAPHIC_CAPACITY`，不会截断。

相邻层使用 `bentConnector3`，跨层绕行使用 `bentConnector5`，均为绑定真实节点 ID 的
`p:cxnSp`。编译器写出端点、折点、上下翻转和 DrawingML 调整值；OfficeCLI 输出后，
结构 QA 会从实际 OOXML 还原路径，再检查边界、节点碰撞、穿越节点和严重线段冲突。
共同源或共同目标允许共用可见主干；无共同节点的线段交叉/重合会阻断交付，避免形成
容易误读的连接关系。`SCHEMATIC_REVIEW` 始终保留。

本阶段限制：每图最多 16 节点、64 条显式边，一页一图，方向为从左到右。
实际容量由页面区域、形状内框和文字决定；过多层、过多同层节点，或有限路由通道内
无法避开的冲突会明确失败，需拆图或调整内容结构。路由不是任意图的全局最优求解器。
PowerPoint 手动移动节点后，连接符端点仍会跟随，但应用可能重新布线；跨层
`bentConnector5` 在编辑后可能穿过中间节点。编译器的避障检查只保证编译时的布局，
不保证手动编辑后自动避障；编辑后需重新检查并调整连线路径。
DAG 不支持循环；v5 机制组件可以显式声明返回前层的反馈边。
尚不提供 PowerPoint 编组、独立自由曲线编辑器或 SVG 导入。

## 科研页面混排

在已有 `process-flow` 或 `figure-parameters` 的 `composition` 中增加可选的
`graphics: [<同上 process 或 dag>]` 即可；原有 `blocks`、`figure_refs`、
`semantic.takeaway`、`evidence_refs`、`caveats` 和 `speaker_notes` 完整保留。
不含 `graphics` 的旧页及独立图形页保持原有行为。

页面编译器测量正文和图注，尝试上下文在视觉上方、上下文与证据同列，以及图形在
证据上方的有限区域方案。`figure-parameters` 优先保留原图在左的阅读顺序。
只分配整个图形的 bbox，再交给 `graphic_layout.py` / DAG 布局器计算内部节点和连线。
本版混排页由编译器直接排版，packer / 外部提供方不接管节点或覆盖混排区域；
`layout_provider.json` 记录 `COMPILER_OWNED` 与
`reason: native_graphic_composition`。普通页面仍使用已选布局提供方。

原图仍使用原来的 `assets` / `figure_refs` 来源契约、原始图片字节和最小 panel 尺寸，
图注不属于原生图形。原生节点和文字继续继承 theme、保持字号下限；连接线按线段检查，
不得穿越正文、原图或图注。图文无法共存时返回 `GRAPHIC_PAGE_CAPACITY` 及具体原因，
不能为了放下图形而缩小证据下限、截断文字或丢掉一项内容。普通 overflow repair
不会自动拆分含图形的页面，需显式重规划。

只把证据支持的实体、关系写入节点和边；节点详细文字可以替代原来的流程正文，
未进入节点的原始要点必须留在其他 blocks 或讲稿中。编译器不从正文推断关系，也不
自动将旧 `visual_intent` 转为图形；同一页不可同时声明这两种流程结构。
最多一张原生图形、4 个普通 blocks、1 张插图；实际容量由 frame、文字和原图比例决定。
生成图保留 `SCHEMATIC_REVIEW`，原始科研插图继续保留 `SCIENTIFIC_PANEL_REVIEW`。

`examples/native-research.deck_ir.json` 是可编译的混排开发示例，复用仓库生成的指标插图，
明确标为示意图，不作为真实论文证据或科学验收结果：

```powershell
python -m deck_compiler compile --ir examples/native-research.deck_ir.json --out builds/native-research --layout-provider packer
```

用于实际科研页面时保留已有论文 asset 和 `source_figure`，只加入显式的图形描述。
2026-10-23 已对该开发示例在 Windows PowerPoint 中逐页检查，并实际移动混排页节点，
确认连接符跟随、插图和图注保持独立。真实论文证据页面的全链路科学验收仍未执行。

## 科研组件和 Path IR

v5 在同一 `composition.graphics` 入口增加 `mechanism`、`architecture`、`funnel`、
`path` 和 `composite`。这些类型可用于独立页和上述科研混排页；原有 `process` / `dag`
接口保持兼容。组件参数、明确的关系语义、局部路径坐标及限制见
[native-components.md](native-components.md)。
