# 原生可编辑流程图

Native Graphic v2（`feat/native-graphic-connectors`）支持独立的 `native-graphic` 页面：
3–4 个横向节点、相邻节点间的原生连接符，
以及独立的标题和正文文本框。图形区域使用现有页面 frame，内部由
`deck_compiler/graphic_layout.py` 确定性布局，经现有 OfficeCLI 输出。
没有新增渲染器或依赖。

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

- 节点按数组顺序从左到右排列。必须显式连接每对相邻节点，且恰好一次；
  `kind` 可省略，当前只接受 `arrow`。不推断、补写或改变科学关系。
- `shape` 支持 `rect`、`rounded-rect`（默认）、`ellipse`、`diamond`、`hexagon`。
- `title` 必填，最多 80 字符；`body` 可省略，最多 180 字符。
  实际可容纳字数取决于形状和文本宽度；菱形内部空间较小。
- 图形和节点 ID 使用 1–64 个英文字母、数字、连字符或下划线。
  节点 ID 在图内唯一；编译后对象名包含图形和节点 ID，可在选择窗格中定位。
- 字体继承 deck theme，描边与箭头使用 `theme.accent`。文字独立测量并居中，
  不低于 18 pt；装不下时返回 `SPLIT_REQUIRED`，保留原文。
- 不写 `x/y/w/h/bbox`。首版一页一图，普通 blocks 和论文图片放在相邻页面。
  其他 archetype 下的非空 `graphics` 会明确报错，避免内容被忽略。

节点是 `p:sp` 预设形状，文字是独立文本框，边是 `p:cxnSp` 直线连接符。
布局器输出源/目标节点、端点和形状专属连接点索引；OfficeCLI 在所有节点创建后，
通过 `from/to` 解析实际的 PowerPoint 形状 ID，再写入 `a:stCxn` / `a:endCxn`。
箭头在目标端；在 PowerPoint 中移动节点，连接符随之调整。文字仍是独立对象，
分支与汇合使用下文的 DAG 类型；本版尚不提供编组、自由曲线或 SVG 路径导入。

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

页面继续使用 `native-graphic`，`blocks` 和 `figure_refs` 留空。只改变图形类型与
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
PowerPoint 手动编辑后会调整连接符；大幅移动后需要重新检查布局。
本版不提供循环图、编组、自由曲线编辑器或 SVG 导入。
