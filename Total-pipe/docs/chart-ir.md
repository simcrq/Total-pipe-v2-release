# 数据图（chart）IR 契约 v1

状态：**C1/C2/C3（scatter、误差棒、图内标注）已实现**；双轴与逐点 evidence 比对仍待后续。
本文件定义字段、校验和渲染边界；`chart_layout.py`
负责 Schema 表达不了的规则，`schemas/chart-ir.schema.json` 是可执行的字段契约，
`examples/chart-ir.example.json` 是可校验的样例。

## 用来画什么，不画什么

- **不重画论文里已有的图。** 论文图继续走 `figure-reading`：原图、原图注、可溯源，重画只会失真。
- **画正文或表格里的数字。** 曲线/柱状图的价值在“数字散落在句子和表格里，图能把趋势一次性说清”。
- **画跨来源合成。** 多篇论文的同一指标放在同一坐标里，只有 chart 能做，figure 做不到。
- **画示意。** 没有数据、但结构需要一张曲线时，用 `basis=explain` + `illustrative=true`，
  渲染时必须带可见的“示意”标记，不能伪装成论文数据。

## 在 Deck IR 里的位置

```json
"composition": {
  "charts": [{"id": "window", "...": "..."}],
  "layout_tree": {"version": "1.2", "regions": {"body": {"type": "stack", "children": [
    {"id": "chart1", "type": "chart", "ref": "window"}
  ]}}}
}
```

- `composition.charts` 与 `graphics` / `tables` 平级，最多 4 个。
- `chart` 是 layout tree 的叶子，和 `graphic` / `table` 同一套规则：每个 chart 恰好被引用一次，
  未引用或重复引用都失败。
- 高度由树分配；chart 的 preferred 高度 320px，hard 260px，最小宽度 420px。

## 样例

```json
{
  "id": "window",
  "kind": "line",
  "basis": "evidence",
  "x": {"label": "Channel length L (nm)", "scale": "log", "values": [40, 100, 300, 1000]},
  "y": {"label": "Programming window", "scale": "linear", "unit": "V"},
  "series": [
    {"label": "t_cg = 40 nm", "values": [10.5, 14.2, 15.1, 12.0], "evidence_refs": ["EV0012"]}
  ],
  "source": "Nature Electronics (2026) · Fig. 4c"
}
```

`examples/chart-ir.example.json` 里的数值只用来演示形状，真实 deck 必须引用论文数字。

## 字段

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `id` | 是 | 1–64 位字母/数字/`-`/`_`，页内唯一 |
| `kind` | 是 | `line` / `bar` / `scatter` |
| `basis` | 是 | `evidence` 或 `explain` |
| `illustrative` | explain 必填 | 必须为 `true`；evidence 图不允许为 `true` |
| `x.label` | 是 | 坐标轴标题，≤80 字符 |
| `x.scale` | 否 | `linear`（默认）/ `log` |
| `x.values` | line/bar 必填 | 2–24 个有限数；line 要求严格递增；scatter 改用每组 series 的 `x_values` |
| `y.label` | 是 | 坐标轴标题（含单位或另填 `y.unit`） |
| `y.scale` | 否 | `linear`（默认）/ `log` |
| `y.unit` | 否 | ≤24 字符 |
| `series` | 是 | 1–4 组 |
| `series[].label` | 是 | 图例文字，≤60 字符 |
| `series[].values` | 是 | 长度必须等于 `x.values`（scatter 为 `x_values`） |
| `series[].x_values` | scatter 必填 | 每个点一个 x；line/bar 不允许 |
| `series[].y_error` | 否 | 对称误差棒，每个点一个非负数；log 轴下不得触到 0 |
| `annotations` | 否 | 最多 6 条；`{text, series, point, dx?, dy?}`，dx/dy 为像素偏移 |
| `series[].evidence_refs` | 是 | evidence 图必须非空，且是本页 `semantic.evidence_refs` 的子集 |
| `source` | evidence 必填 | 出处行，≤120 字符 |
| `note` | 否 | 一句话读法，≤160 字符 |

## 校验

Schema 负责：类型、枚举、长度上限、必填。

`chart_layout.validate_charts` 负责跨字段规则：

1. `series[].values` 长度与 `x.values` 一致（scatter 与 `x_values` 一致）；
2. line 的 x 严格递增；
3. log 轴的 x / y 数据必须为正；
4. scatter 每组 series 必须有 `x_values`，line/bar 不允许；
5. `y_error` 长度必须等于点数、非负，log 轴下 `value-error` 不得触到 0；
6. `annotations` 的 series/point 必须指向真实点，dx/dy 在 ±160/±120 px 内；
7. evidence 图每组 series 必须有 `evidence_refs`，且全部落在本页 `semantic.evidence_refs`；
8. explain 图必须 `illustrative=true`；
9. evidence 图必须有 `source`。

**数字与 evidence 原文的逐点比对**（`CHART_DATA_NOT_IN_EVIDENCE`）属于流水线检查，不进
编译器：编译器拿不到 evidence 正文，只有 design 阶段和 `check_ir` 的调用方有。C4 在
`agent/adapters.py` 里实现，规则与 design 的数字校验一致：x 与每个 y 值都要在所引 evidence
原文中出现；找不到就 FAIL 并指出是哪个点。

## 渲染契约

- 原生形状 + 文本框，不嵌图片、不生成 chart part，保证可编辑且能被现有几何/字号检查覆盖。
- 画布：左边距 96、右边距 24、上边距 46、下边距 104；y 轴标题横排放在绘图区上方，不做旋转。
- 刻度：x 4–5 个（log 轴按 10 的幂，并补轴两端），y 4 个；刻度标签 20px（15pt，`caption` 角色），
  轴标题 24px（18pt，`body` 角色）。
- 折线 2.5px、标记 6px；柱状图零基线，柱间距 30%。scatter 只画标记。
- 误差棒 1.5px，上下各一条 8px 端帽；数值为 0 的点不画。
- 图内标注：文字放点的 `dx/dy` 处并夹在画布内，引线从点到文本框边缘；最多 6 条。
- 图例放右上角，按 series 顺序从左到右；`source` 放右下角 20px。
- explain 图在左上角加“示意”徽标（与 supplement 的可见标记一致）。
- 放不下时返回 `CHART_CAPACITY`，由树把页拆开，绝不缩字号或裁刻度。

## 与设计 / IR 阶段

- 设计层新增形式 `chart-reading`（anchor `graphic`）：用于“数字在正文/表格、曲线能说明趋势”的页；
  论文图已经在页面上时仍用 `figure-reading`。
- 设计层不写数据点，只声明“这一页要用图说明趋势”；数据由 IR 阶段从 evidence 里填。
- IR 阶段：没找到具体数字就退回 `basis=explain` + `illustrative=true`，或退回文字页；
  不允许为了填满图而编造坐标。

## 分期

| 期 | 内容 |
| --- | --- |
| C1 | 字段契约 + Schema + `validate_charts` + 样例 + 测试（已完成） |
| C2 | `layout_tree` 叶子 `chart`、测量、line/bar 渲染、`CHART_CAPACITY`（已完成） |
| C3 | scatter、误差棒、图内标注（已完成）；双轴（待做） |
| C4 | 流水线逐点 evidence 校验与 `CHART_DATA_REVIEW` |

## 未决

- 双轴（右轴 + series 归属）；
- 同一张图混合 evidence 与 explain 系列（v1 先禁止，图级二选一）；
- 柱状图的类别轴与数值轴命名；
- 标注避让（目前只夹在画布内，不主动躲其他文字）。
