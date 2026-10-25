# 科研图形组件与原生 Path IR

v5 继续使用 `composition.graphics`、OfficeCLI 和现有 QA。`native-graphic` 独立页、
`process-flow` / `figure-parameters` 混排页都可使用下列类型；旧 `process` / `dag`
布局和输出行为保持兼容。没有新增依赖、SVG 渲染器或第二套科学评分体系。

**编辑边界：** 这些组件输出独立的形状、文字、标签、端帽和容器，尚无 PowerPoint 编组。
移动节点时独立对象不会整体跟随，连接符也可能重新布线。优先在 canonical IR 调整结构、
weights、gap 或 align 后重建；手工微调应选全相关对象，必要时自行组合，之后复查路由。
不存在需要先解开的组；手改不会回写 IR。详见[复杂页 QA 与维护](complex-page-qa.md)。

内部组件接口位于 `deck_compiler/graphic_components.py`：

```python
render_process_graph(data, theme, bounds, font_paths=None)
render_mechanism_graph(data, theme, bounds, font_paths=None)
render_layered_architecture(data, theme, bounds, font_paths=None)
render_funnel(data, theme, bounds, font_paths=None)
render_component(data, theme, bounds, font_paths=None)
```

接口返回现有原生 shape/text/connector 协议，最终文字适配由页面编译器完成。
`bounds` 由编译器分配，AI 只写内容与参数。下面的示例均为 `graphics` 中的一个对象；
完整可编译示例是 `examples/native-components.deck_ir.json`，六页内容均为开发示意，
不对应真实论文或科学结果。

## 机制：明确区分关系、证据和假设

```json
{
  "id": "signals", "type": "mechanism",
  "nodes": [{"id":"A","title":"实体 A"},{"id":"B","title":"实体 B"}],
  "edges": [{"from":"A","to":"B","kind":"inhibit","basis":"hypothesis"}]
}
```

节点沿用五种形状和完整 title/body。`kind` 必须为 `activate`、`inhibit` 或 `associate`；
分别使用箭头、T 端帽、无箭头连线。`basis` 必须为 `evidence` 或 `hypothesis`。
证据关系必须给非空 `evidence_refs`，并全部绑定到本页 `semantic.evidence_refs`；
声明引用不等于编译器已验证科学结论。假设使用虚线并显示“假设”，可用 `label`
补充关系文字，最长 80 字符。标签不低于 18 pt，找不到不遮挡节点/连线的空间时明确失败。

普通边必须构成 DAG；只有明确写 `feedback: true` 的边允许从其后层返回前层。
先按明确的正向边分层，再为反馈分配外侧正交通道。一般循环、自环、重复边、失效端点
或无法避让的关系会被拒绝，不会自动重分类为反馈。连接符绑定真实节点及形状连接点。

T 端帽由独立原生小矩形表达，关系标签也是独立文本；它们没有 PowerPoint 的自动跟随
约束，手动移动节点后需要对齐。连接符本身有原生绑定。此限制与节点文字的独立编辑
语义一致，不应把 XML 校验当作交互编辑验收。

## 分层架构：明确成员的容器

```json
{
  "id":"system", "type":"architecture",
  "layers":[
    {"id":"input","title":"输入层","nodes":[{"id":"collect","title":"采集"}]},
    {"id":"compute","title":"计算层","nodes":[{"id":"analyze","title":"分析"}]}
  ],
  "edges":[{"from":"collect","to":"analyze"}]
}
```

1–4 层从左到右排列，每层 1–4 个节点，总计不超过 16 个。边只能指向明确声明的后层；
不因相邻或同容器而自动添加关系。复用 DAG 的文字测量与路由，层容器和层标题位于节点
背后。容器只能与自己的成员合法包含，不能借此豁免页面上的其他碰撞。
目前为独立原生对象，尚未创建 `p:grpSp` PowerPoint 编组。

## 漏斗、金字塔与层次

```json
{
  "id":"selection", "type":"funnel", "variant":"funnel", "end_width":0.35,
  "levels":[{"id":"all","title":"候选集合"},{"id":"selected","title":"筛选集合"}]
}
```

2–8 个 level，保留 id/title/可选 body；`variant` 可用 `funnel` 或 `pyramid`。
`end_width` 为最窄端相对宽度：漏斗范围 0.2–1，默认 0.35；金字塔范围 0–1，
默认 0 形成尖顶，并将顶部标签放入三角形的安全内框。多边形由原生自由形状构成，
标签独立测量。宽度只编码视觉层次，不能由此宣称样本数或筛选率。
层数、文字和可用高度超出容量时返回错误，不截断标签。

## Path IR：局部几何到原生自由形状

```json
{
  "id":"region", "type":"path", "view_box":[0,0,200,100],
  "paths":[{"id":"outline","d":"M 0 50 Q 50 0 100 50 C 130 90 170 10 200 50 L 200 100 L 0 100 Z",
            "fill":"background","stroke":"accent","line_width":2}],
  "labels":[{"id":"name","text":"曲线区域","box":[50,60,100,30]}]
}
```

每条路径使用 `d` 或 `commands` 二选一；后者例如
`[["M",0,0],["L",100,0],["Q",150,100,200,0],["Z"]]`。
支持绝对大写 `M/L/C/Q/Z`，二次贝塞尔 Q 转为等价三次 C。计算三次曲线的实际极值，
检查几何在 view_box 内，再保持比例放入组件区域，归一化到本地整数坐标。
水平/竖直开放路径也保留正的原生对象尺寸。

最多 32 条路径，每条最多 512 条命令或 32000 字符；坐标必须有限且绝对值不超过 1e9。
最多 32 个独立标签，每个 `box` 都是 view_box 内的局部坐标，文字最长 180 字符。
同一个 path 场景中显式声明的路径与标签允许重叠，区域外的边界和其他页面内容仍检查。
fill/stroke 只支持 `accent`、`foreground`、`background`、`none` 或 `#RRGGBB`，线宽 0.5–6 px。

OfficeCLI 先创建普通原生形状，再用现有 raw-set 将预设几何替换为生成的
[`a:custGeom`](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.drawing.customgeometry)
和其[路径列表](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.drawing.path)。
不接受用户原始 XML，不生成 SVG 图片。结构 QA 比较实际路径、对象身份、样式与预期几何，
不会仅凭外观相似判定通过。

首版不支持相对命令、A/H/V/S/T、渐变、滤镜、遮罩、复杂裁剪、任意 SVG 导入或独立曲线编辑器。

## 组合与既有流水线

`type: "composite"` 可声明 2–4 个非 composite 子组件，使用 `arrangement: "columns"`
或 `"rows"` 和可选的正 `weights`。子组件 id 必须唯一，输出对象名按父/子组件隔离；
默认等分区域，不推断跨组件关系。需要跨组件的科学连线时，应在一个图中显式声明关系。
组件容量不足仍明确失败，不缩字号或静默删减。

CLI 与 MCP 入口不变：

```powershell
python -m deck_compiler compile --ir examples/native-components.deck_ir.json --out builds/native-components --layout-provider packer
```

完整构建使用现有 `build`，不要加 `--skip-native`；逐页检查 PowerPoint 后再记录
`record-powerpoint-review` 并执行 `validate-native`。
2026-10-23 已在 Windows PowerPoint 对六页组件示例逐页检查，实际移动机制图和架构图
节点，并用“编辑顶点”修改自由路径与漏斗多边形。连接符绑定通过；独立文字、关系标签、
T 端帽及容器尚未编组，不能自动整体跟随。手动移动后仍需检查路由，见
[原生图形限制](native-graphics.md)。
所有生成图保留 `SCHEMATIC_REVIEW`，结构通过不能替代科学正确性或交互编辑验收。
