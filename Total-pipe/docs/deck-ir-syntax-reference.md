# Deck IR 全功能实现与代码语法手册（Agent 速查）

> **阅读边界**：编写 `work/pages/<id>.json` 或 `work/deck_ir.json` 时，**无需翻阅编译器或 Agent 源码**——本手册已覆盖 Canonical Deck IR v2.0 的全部设计功能、字段枚举、互排约束与快捷写法。
> **必须保留的检索动作**：动手设计/写 IR 前，**仍必须通过 `example_lookup.command_prefix` 检索并查看示例库**（`search "<讲解关系/结构>" --limit 3` + `show <id>`），借鉴成熟的多区构图、空间占比（正文带目标覆盖 45%–75%，避免单列大留白）和视觉节奏；文案、数值与图源始终取自本任务批准内容。

---

## 1. 顶层结构与单页草稿骨架

无论是整套 `work/deck_ir.json` 还是单页联调/逐页提交的 `work/pages/<id>.json`（`slides` 恰好 1 页），顶层字段均为：

```json
{
  "schema_version": "2.0",
  "deck_id": "paper-short-id",
  "presentation": {
    "text_capacity_policy": "preserve-terms",
    "frame_variant": "default",
    "visual_style": {"pack": "academic"},
    "academic_design": {
      "style": "research-seminar",
      "title_treatment": "thin-rule",
      "density": "balanced",
      "figure_treatment": "ruled-caption",
      "decoration_policy": "minimal",
      "header_variant": "compact",
      "type_scale": "standard",
      "accent_color": "#1E3A8A"
    },
    "bullet_style": "large_square",
    "bullet_color": "#1E3A8A",
    "list_gap": 0.45,
    "page_numbers": true,
    "agenda": {"title": "目录"},
    "footer": "Lab / Paper Short Title"
  },
  "theme": {
    "font_family": "Noto Sans CJK SC",
    "font_file": "NotoSansCJK-Regular.ttc",
    "bold_font_file": "NotoSansCJK-Bold.ttc",
    "foreground": "#111827",
    "background": "#FFFFFF",
    "accent": "#1E3A8A"
  },
  "assets": {
    "fig1a": {
      "path": "images/fig1a.png",
      "origin": "paper",
      "source_figure": "1a"
    }
  },
  "slides": [
    {
      "id": "P1",
      "semantic": {
        "title": {"copy_ref": "c_title"},
        "purpose": "Explain key measurement",
        "takeaway": {"copy_ref": "c_take"},
        "inline_math": ["title", "takeaway"],
        "evidence_refs": ["EV0001"],
        "caveats": [],
        "speaker_notes": "Full scientific speaker notes."
      },
      "composition": {
        "archetype": "composite-research",
        "blocks": [],
        "figure_refs": [],
        "graphics": [],
        "tables": [],
        "charts": [],
        "layout_tree": {"version": "1.2", "regions": {"body": {"id": "root", "type": "stack", "children": []}}}
      },
      "presentation": {
        "section": "研究背景",
        "variant": "default",
        "page_number": true,
        "takeaway_frame": {"border": {"color": "#1E3A8A", "width": 1.5}, "fill": "#EFF6FF", "padding": "compact"},
        "takeaway_marker": {"style": "large_diamond", "color": "#1E3A8A"}
      }
    }
  ]
}
```

### 顶层关键约束
- **多页共享头一致**：使用 `deck_ir_page` 分批写页时，每页顶层 `deck_id`、`presentation`、`theme` 必须完全一致。
- **`assets` 来源规则**：
  - `origin: "paper"`（默认）：须配 `source_figure`（正则 `^S?[1-9][0-9]*[a-z]?$`，如 `"1a"`、`"S2"`）；可选 `crop: {"source_path": "...", "source_sha256": "<64hex>", "box": [x1,y1,x2,y2]}`。
  - `origin: "generated"`：须配 `generator`（如 `"make_schematic.py/v1"`），**禁止**写 `source_figure`。
  - `origin: "reference"`：须配 `reference_source`，**禁止**写 `source_figure`。
- **`copy_ref` 与快捷写法（Agent 自动展开）**：
  - 凡审定过的 `display_copy` 文案，可直接写 `{"copy_ref": "<copy_id>"}`（可用于 `title`、`takeaway`、`block.text`、`figure_refs[].caption`、表格单元格、图形节点标题/正文等），程序自动绑定真实文本与 `content_projection`。
  - **独立公式简写**：`{"id": "eq1", "latex": "E = mc^2"}` 自动补齐 `component: "formula"` 与 `text`。
  - **链式流程图简写**：`composition.diagram = {"id": "flow", "nodes": [{"id": "a", "title": "步骤1"}, ...]}` 自动展开为 `composition.graphics` 中的横向 `process` 链。
  - **行内公式**：在正文、标题、结论或表格中直接写 `$...$` 或 `\(...\)`，并设 `block.inline_math: true` 或 `semantic.inline_math: ["title", "takeaway"]`（纯文本中的 `2×10^5` / `10^6` 也会自动转为可测量行内数学）。
  - **句内强调**：`**核心短语**`（主题强调色加粗）与 `==关键符号==`（浅色高亮）；每句至多一处，不可跨越 `$...$`，仅用于 `text_flow: "plain"`（原生列表内会被剥离）。

---

## 2. 页面构图：13 种平面 Archetype vs `composite-research` + `layout_tree`

### 2.1 何时直接用 `composite-research` + `layout_tree`
**凡一页有 3+ 对象、图文/表/数据图混排、需要多列/分组标签卡片或方向贴靠说明，直接从一开始选 `archetype: "composite-research"` + `layout_tree`（`version: "1.2"`）。**

| Archetype | 适用场景 | 限制 |
| --- | --- | --- |
| `composite-research` | 任意多区混排、面板分组、表格、数据图、多原生图 | **必填 `layout_tree`**；禁止 `visual_plan`/`visual_intent` |
| `cover` | 封面页（1 块、0 图） | 仅封面 |
| `cover-hero` / `figure-parameters` | 1 论文图 + 2–4 文本块（右图/左图） | 可配合 `visual_plan` |
| `hero-dual-evidence` / `dual-demonstration` | 双图并排 + 2 文本块 | 2 图 |
| `metric-comparison` / `three-conclusions` / `three-limitations` | 3–4 列纯指标/结论/局限 | 0 图 |
| `equation-derivation` | 独立公式推导栈（最多 16 块） | 0 图 |
| `process-flow` / `native-graphic` | 单原生流程图或纯原生图形页 | `native-graphic` 要求 `blocks: []`、`figure_refs: []` |
| `evidence-hypothesis` | 证据—假设对照（最多 8 块） | 0 图 |

### 2.2 `layout_tree` 完整语法（v1.0 / v1.1 / v1.2）
- 版本能力：`1.0` 基础节点；`1.1` 支持 `table` 叶子；**`1.2` 支持 `panel.frame`（边框、底色与 `chip` 标签头）**——推荐默认写 `"version": "1.2"`。
- 深度上限 6，节点上限 64；除 `caption_for(position)` / `text_for` 外，每个 block/figure/graphic/table/chart **必须恰好在树中引用一次**。
- **注意叶子 `ref` 类型**：`figure` 的 `ref` 是 **0-based 整数索引**（如 `0` 指 `figure_refs[0]`）；`block` / `graphic` / `table` / `chart` 的 `ref` 是**字符串 `id`**！

```json
{
  "version": "1.2",
  "regions": {
    "body": {
      "id": "cols",
      "type": "columns",
      "weights": [1.3, 1.0],
      "fit": "stretch",
      "gap": "standard",
      "children": [
        {
          "id": "left_panel",
          "type": "panel",
          "title": "实验表征",
          "padding": "compact",
          "gap": "compact",
          "frame": {
            "border": {"color": "#CBD5E1", "width": 1},
            "fill": "#F8FAFC",
            "title_fill": "#1E3A8A",
            "title_color": "#FFFFFF",
            "title_align": "left",
            "title_band": "chip"
          },
          "body": {"id": "fig0", "type": "figure", "ref": 0}
        },
        {
          "id": "right_stack",
          "type": "stack",
          "align": "start",
          "gap": "compact",
          "children": [
            {"id": "b1_leaf", "type": "block", "ref": "b1"},
            {"id": "t1_leaf", "type": "table", "ref": "t1"}
          ]
        }
      ]
    }
  }
}
```

#### `layout_tree` 节点枚举与互排规则
- **`columns`**：`children` 1–4 项；`weights`（每项 `0.1–10`）；`fit: "stretch" | "hug"`；`gap: "compact" | "standard" | "spacious"`；**禁止 `align`**。
- **`stack`**：`children` 1–12 项；`weights` 可选（写 `weights` 时若写 `align` 只能为 `"start"`）；`align: "start" | "center" | "distribute"`；**禁止 `fit`**。
- **`panel`**：必填 `id`、`title`、`body`；`padding: "none" | "compact" | "standard"`；`frame`（仅 v1.2）支持 `border`（无外框但用 `title_band: "chip"` + 十六进制 `title_fill` 时可省略 `border`）、`fill`（`"none"` 或 `#RRGGBB`）、`title_fill`、`title_color`、`title_align: "left" | "center"`、`title_band: "strip" | "chip"`。
- **`image_grid`**：`columns: 1..4`，`children`: 1–12 个 `{"id": "...", "type": "figure", "ref": 0}`，`gap`。
- **叶子**：`{"id": "...", "type": "block"|"graphic"|"table"|"chart", "ref": "<id>"}` 或 `{"id": "...", "type": "figure", "ref": 0}`。

### 2.3 方向贴靠说明（`caption_for` / `text_for`）
需要把图注或解读文字精准贴在某个图/表/公式/数据图的上下左右时，**必须使用 `layout_tree`**，且**不要把贴靠块放进 `layout_tree`**（编译器自动围绕目标放置）：

```json
{"id": "cap1", "component": "caption", "text": "Fig. 1a: 300 K 实测响应曲线", "text_flow": "plain", "inline_math": false,
 "caption_for": {"kind": "figure", "ref": "0", "position": "bottom"}}
```
```json
{"id": "note1", "component": "body", "text": "高场区呈线性饱和。",
 "text_for": {"kind": "chart", "ref": "ch1", "position": "right"}}
```
- `kind`: `"figure" | "graphic" | "formula" | "table" | "chart"`；`position`: `"top" | "bottom" | "left" | "right"`。
- `component: "caption"` 必须有 `caption_for`，且 `text_flow` 为 `"plain"`、`inline_math` 为 `false`，禁止 `label`/`anchor`/`bullet_style`/`bullet_color`。

---

## 3. 正文块、原生列表、公式与补充内容（`composition.blocks`）

- **`component` 枚举（19 种）**：
  `"body"`, `"metric"`, `"parameter"`, `"process-step"`, `"direct-evidence"`, `"hypothesis"`, `"limitation"`, `"conclusion"`, `"callout"`, `"comparison"`, `"definition"`, `"observation"`, `"method"`, `"result"`, `"question"`, `"source"`, `"caveat"`, `"formula"`, `"caption"`。
- **原生列表（用 `\n` 分条）**：
  - 无序列表：`text_flow: "native_bullet_list"`；二选一指定 `bullet_style`（`"bullet" | "square" | "open_square" | "diamond" | "arrow" | "check" | "dash" | "large_square" | "large_diamond" | "arrowhead"`）**或**单字符 `bullet_icon`（如 `"▸"`，**不可与 `bullet_style` 同写**）；可选 `bullet_color: "#RRGGBB"`。
  - 有序列表：`text_flow: "native_numbered_list"` + 可选 `list_start: 1`（**禁止 `bullet_style`**）。
  - **硬约束**：原生列表块宽度 ≥ 240 px，且 **`inline_math` 必须为 `false`**（含行内公式的块用 `text_flow: "plain"`）；`metric` 配合 `type_scale: "statement"` 会放大至 88 px（仅用于整页核心单数字）。
- **独立公式块**：
  ```json
  {"id": "eq1", "component": "formula", "text": "G(V) = G_0 \\exp\\left(-\\frac{\\Phi_B - \\alpha V}{k_B T}\\right)", "anchor": "b1"}
  ```
  `anchor` 指向紧邻前置非公式块 `id`，保持说明与推导成组。
- **补充内容块（仅 `supplement != "off"` 时允许）**：
  ```json
  {"id": "sup1", "component": "body", "basis": "supplement",
   "supplement": {"kind": "analogy", "source": "Textbook Ch. 3", "constructed": true, "assumptions": ["1D simplified model"]},
   "text": "示意类比：……"}
  ```
  `supplement.kind`: `"background" | "analogy" | "example" | "derivation" | "diagram" | "comparison"`；**禁止写 `evidence_refs`**，不得泄漏论文具体实测数值或论文图。

---

## 4. 原生矢量图形（`composition.graphics`，最多 8 个）

### 4.1 `process`（线性流程）与 `dag`（分支/汇合有向图）
```json
{
  "id": "g_flow",
  "type": "process",
  "direction": "horizontal",
  "layout": "compact",
  "nodes": [
    {"id": "n1", "shape": "rect", "tone": "default", "title": "基底清洗", "body": "丙酮超声"},
    {"id": "n2", "shape": "rounded-rect", "tone": "emphasis", "title": "ALD 沉积", "body": "15 nm 势垒"},
    {"id": "n3", "shape": "rect", "tone": "default", "title": "电学测试"}
  ],
  "edges": [
    {"from": "n1", "to": "n2", "kind": "arrow"},
    {"from": "n2", "to": "n3", "kind": "arrow"}
  ]
}
```
- `process`：3–8 节点，2–7 边；`direction: "horizontal" | "vertical"`；`layout: "chain" | "staggered" | "compact"`（5–8 步长流程优先 `layout: "compact"` 且尽量省去 `body`）；节点 `shape`: `"rect" | "rounded-rect" | "ellipse" | "diamond" | "hexagon"`，`tone: "default" | "emphasis"`。
- `dag`：最多 16 节点、64 边；**`direction` 固定 `"horizontal"`，`layout` 固定 `"chain"`**。

### 4.2 `mechanism`（激活/抑制/反馈机制图）
```json
{
  "id": "g_mech",
  "type": "mechanism",
  "direction": "horizontal",
  "nodes": [
    {"id": "e", "title": "外加电场 E"},
    {"id": "b", "title": "有效势垒 Φ_B"},
    {"id": "g", "title": "电导 G(V)"}
  ],
  "edges": [
    {"from": "e", "to": "b", "kind": "inhibit", "basis": "evidence", "evidence_refs": ["EV0001"], "label": "降低势垒"},
    {"from": "b", "to": "g", "kind": "activate", "basis": "hypothesis", "feedback": false, "label": "指数增强"}
  ]
}
```
- `edge.kind`: `"activate" | "inhibit" | "associate"`；`basis`: `"evidence" | "hypothesis" | "explain"`（`basis="evidence"` **必须带非空 `evidence_refs`**）。

### 4.3 `architecture`（分层架构）与 `funnel`（筛选漏斗/金字塔）
```json
{
  "id": "g_arch",
  "type": "architecture",
  "direction": "horizontal",
  "layers": [
    {"id": "l1", "title": "传感层", "nodes": [{"id": "s1", "title": "光敏阵列"}, {"id": "s2", "title": "偏置电极"}]},
    {"id": "l2", "title": "计算层", "nodes": [{"id": "c1", "title": "原位乘加"}]}
  ],
  "edges": [{"from": "s1", "to": "c1", "kind": "arrow"}]
}
```
```json
{
  "id": "g_funnel",
  "type": "funnel",
  "variant": "funnel",
  "end_width": 0.35,
  "levels": [
    {"id": "f1", "title": "初筛候选 (1200)"},
    {"id": "f2", "title": "稳定相筛选 (84)"},
    {"id": "f3", "title": "实验验证 (6)"}
  ]
}
```
- `architecture`：1–4 层，每层 1–4 节点。`funnel`：2–8 层，`variant: "funnel" | "pyramid"`，`end_width`（funnel 需 `0.2–1.0`，pyramid 需 `0–1.0`）。

### 4.4 `path`（自定义贝塞尔曲线/能带/几何示意）与 `composite`（组合图形）
```json
{
  "id": "g_curve",
  "type": "path",
  "view_box": [0, 0, 400, 220],
  "paths": [
    {"id": "axis_x", "commands": [["M", 30, 180], ["L", 370, 180]], "stroke": "foreground", "line_width": 1.5},
    {"id": "band", "commands": [["M", 40, 150], ["C", 140, 40, 260, 40, 360, 140]], "stroke": "accent", "fill": "none", "line_width": 2.5}
  ],
  "labels": [
    {"id": "lbl1", "text": "示意能带势垒", "box": [120, 15, 160, 28]}
  ]
}
```
- `path`：仅局部坐标（在 `view_box: [x,y,w,h]` 内）；每条路径二选一写 `commands`（`["M",x,y]` / `["L",x,y]` / `["C",x1,y1,x2,y2,x,y]` / `["Q",x1,y1,x,y]` / `["Z"]`）或 SVG 字符串 `d`；颜色用 `"accent" | "foreground" | "background" | "none" | "#RRGGBB"`；示意图须标明“示意”。
- `composite`：`arrangement: "columns" | "rows"`，`weights`（2–4 项），`components`（2–4 个子图形，类型可为 `process`/`mechanism`/`architecture`/`funnel`/`path`）。

---

## 5. 原生数据图（`composition.charts`，最多 4 个）

```json
{
  "id": "ch1",
  "kind": "line",
  "basis": "evidence",
  "illustrative": false,
  "x": {"label": "Bias (V)", "scale": "linear", "values": [0, 0.5, 1.0, 1.5]},
  "y": {"label": "Response", "scale": "linear", "unit": "a.u."},
  "series": [
    {"label": "300 K", "values": [1.0, 2.0, 4.0, 4.2], "y_error": [0.1, 0.12, 0.15, 0.14], "evidence_refs": ["EV0001"]},
    {"label": "Control", "values": [1.0, 1.05, 1.02, 1.04], "evidence_refs": ["EV0002"]}
  ],
  "reference_lines": [
    {"axis": "y", "value": 3.5, "label": "Target 3.5", "style": "dashed"}
  ],
  "shaded_zones": [
    {"axis": "x", "low": 0.8, "high": 1.5, "label": "Saturation window"}
  ],
  "annotations": [
    {"text": "2x gain", "series": 0, "point": 2, "dx": 14, "dy": -20}
  ],
  "source": "Fig. 2b",
  "note": "Error bars show ±1 SD (n=3)."
}
```
- **`kind`（4 种）**：`"line" | "bar" | "hbar" | "scatter"`。
  - `line`：必填数值 `x.values`；`scatter`：共享 `x.values` 或在每个 `series` 写 `x_values`。
  - `bar`（纵向柱状图）与 `hbar`（横向排名/消融条形图）：支持数值 `x.values` **或** 字符串类别 `x.categories: ["Ours", "w/o Fusion", "Baseline"]`（不可同时填 `values` 与 `categories`）。
- **阈值参考线与高亮区间**：
  - `reference_lines`（最多 4 条）：`{"axis": "x"|"y", "value": 90.0, "label": "Threshold", "style": "dashed"|"solid", "color": "#RRGGBB"}`。
  - `shaded_zones`（最多 3 个）：`{"axis": "x"|"y", "low": 0.2, "high": 0.8, "label": "Operating zone", "color": "#E6F4F1"}`。
- **自动避障与双行图例**：图例超宽时自动换为右对齐双行并下移绘图区顶边；`annotations` 自动避让折线、柱体、误差棒及相邻标注框。
- `basis`: `"evidence"` 时 `illustrative` 必须为 `false` 且数值来自证据；`"explain"` 时 `illustrative` 必须为 `true`（仅示意趋势或题目模式算例）。
- 需由 `layout_tree` 的 `{"id": "...", "type": "chart", "ref": "ch1"}` 引用。

---

## 6. 原生科研表格（`composition.tables`，最多 4 个）

```json
{
  "id": "t1",
  "row_count": 3,
  "column_count": 3,
  "header_rows": 1,
  "column_weights": [1.2, 1.0, 1.0],
  "origin": "paper",
  "evidence_refs": ["EV0001"],
  "cells": [
    {"id": "c00", "row": 0, "column": 0, "text": "Condition", "align": "left"},
    {"id": "c01", "row": 0, "column": 1, "text": "Temp (K)", "align": "center"},
    {"id": "c02", "row": 0, "column": 2, "text": "Gain", "align": "right"},
    {"id": "c10", "row": 1, "column": 0, "text": "Barrier 15 nm", "align": "left"},
    {"id": "c11", "row": 1, "column": 1, "text": "300", "align": "center"},
    {"id": "c12", "row": 1, "column": 2, "text": "$2.0\\times$", "inline_math": true, "align": "right"},
    {"id": "c20", "row": 2, "column": 0, "text": "Control", "align": "left"},
    {"id": "c21", "row": 2, "column": 1, "text": "300", "align": "center"},
    {"id": "c22", "row": 2, "column": 2, "text": "$1.0\\times$", "inline_math": true, "align": "right"}
  ]
}
```
- 上限：32 行 × 12 列（≤384 单元格）；支持 `row_span` / `column_span`、`kind: "text" | "formula"`、`inline_math: true`；`layout_tree.version` 至少 `"1.1"`（推荐 `"1.2"`）。

---

## 7. 论文图（`composition.figure_refs`）、无损裁图、高亮框与视觉风格

- **`figure_refs` 字段**：`asset_id`、`caption`（≤320 字）、`source_label`（≤80 字，弱化出处前缀，如 `"Author et al., Fig. 1g"`）、`source_figure`（论文图必填，如 `"1g"` / `"S2"`）、可选 `alt`/`panel_count`/`min_panel_extent`/`caption_height`/`caption_font_size`/`caption_font_floor`、**`highlights`**（最多 6 个原图归一化高亮标注框）：
  ```json
  {
    "asset_id": "fig_01",
    "source_figure": "1g",
    "caption": "Fig. 1g 局部实测响应对比",
    "highlights": [
      {"box": [0.52, 0.14, 0.40, 0.65], "label": "① 峰值区", "color": "#C2410C"}
    ]
  }
  ```
  其中 `box: [rx, ry, rw, rh]` 为相对渲染图片左上角与宽高的 `[0..1]` 归一化比例，编译器自动叠加原生描边矩形与圆角标签且不触发碰撞误报。
- **拼版大图无损检视与裁切（`figure_crop`）**：遇到论文多子图（a–f）拼版大图时，不要手猜像素坐标，直接调用：
  - 检视标尺与候选子图框：`totalpipe_advance(job_id, figure_crop={"operation": "inspect", "source": "fig_03"})`（输出 100 px 坐标网格图 `grid_preview_path` 与自动分割候选框 `candidate_panels`）。
  - 无损裁切并生成 `assets` 条目：`totalpipe_advance(job_id, figure_crop={"operation": "crop", "source": "fig_03", "box": [left, top, right, bottom], "source_figure": "3a"})`，返回的 `asset_entry` 已通过 `crops.verified_source()` 逐像素校验，可直接填入 `deck_ir.assets`。
- **布局树弹性微调与逐节点高度分解**：`layout_tree` 高度轻微溢出（≤ `max(24 px, 6% 正文高)`）时编译器自动收紧容器间距（`ELASTIC_MICRO_FIT`，不缩字号、不删内容）；若仍超限，`layout_feedback.json` 的 `subtree_breakdown` 精确列出每个子节点的 `width_px` 与 `required_height_px`。
- **题目模式（`source_kind="topic", page_mode="deck_ir"`）**：每页 `semantic.evidence_refs` 写 `[]`；表格用 `origin: "generated"`；图表用 `basis: "explain", illustrative: true`；图片用 `origin: "reference"` 或 `"generated"`。
- **`presentation.visual_style.pack`**：
  - `"academic"`（科研汇报默认：直角节点、细线无填充）
  - `"commercial"`（浅色圆角卡片）
  - `"print"`（纯黑细线，适合打印）
- **无 `layout_tree` 时的 `slide.presentation.visual_plan`**（仅平面图文页使用，与 `layout_tree` 互斥）：
  - `visual_job`: `"measurement-evidence"`（配 `figure-left|figure-right|figure-top` + `figure_width_ratio: 0.35–0.75`）、`"mechanism-explanation"`（配 `graphic-left|graphic-right|graphic-top` + `graphic_width_ratio: 0.4–1.0`）、`"evidence-comparison"`（配 `evidence-columns|evidence-rows` + `evidence_order`）。
- **`semantic.explanation`**（当 brief 含 `story_explain` 时逐条承接）：
  每条 obligation 写 `id`、`kind`（`quantity|parallel_items|grouped_panels|comparison|ordered_steps|relation|curve|image_evidence`）、`required`、`content`、`evidence_refs`（`basis="supplement"` 时不写）、`carrier`（`inline_math|formula|native_list|table|layout_tree|process|dag|mechanism|path|figure`）、`status`（`bound|waived|unsupported`）。

---

## 8. 边设计边调试工作流（与示例库配合）

1. **先查示例库**：运行 `example_lookup.command_prefix search "<结构/关系关键词>" --limit 3` 与 `show <id>`，查看真实构图范本（含开篇立题漏斗、分层系统架构+水平消融图、多子图网格高亮导读、三支柱结论与边界矩阵等）。
2. **查阅本手册写单页草稿**：将复杂页写入 `work/pages/<id>.json`（`slides` 仅含该页）。
3. **实时测几何与看图**（在 `page_design`、`page_review`、`deck_ir` 均可用，不改任务状态、不占修订预算）：
   - 骨架/留白快检：`totalpipe_advance(job_id, preview={"artifact_path": ".../work/pages/P1.json", "slide_ids": ["P1"], "mode": "layout"})`
   - 渲染看图与像素自检：`totalpipe_advance(job_id, preview={"artifact_path": ".../work/pages/P1.json", "slide_ids": ["P1"], "mode": "render"})`（返回 `pixel_whitespace` 四象限墨迹率与 `visual_checklist` 孤字/图注避障/页脚净空检查）
   - 语义 + 几何全检：`totalpipe_advance(job_id, artifact_kind="deck_ir", artifact_path=".../work/pages/P1.json", preflight=True)`
4. **分批正式提交**：进入 `deck_ir` 后严格按 `page_authoring.parallel_authoring.batches` 分批（**最多 2 个 IR 子代理**），复用 `draft_exists: true` 的草稿并逐页提交 `deck_ir_page`。
