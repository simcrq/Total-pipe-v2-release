# Scientific Visual Planner (V6 MVP)

design 阶段在 Canonical Deck IR 后默认执行一次 Agent 视觉决策。它沿用 `schema_version: "2.0"`，
保留 Evidence、Story、RPA 和 v5 原生图形；没有新模型服务、Scene IR 或页面坐标接口。
编译器只读取合入后的 Deck IR。低层 `compile_deck` 对没有新字段的 IR 保持旧行为；
CLI/MCP 的 compile/build 和统一 generate 默认检查是否完成设计。

漏做时返回 `VISUAL_DESIGN_REQUIRED`，在构建目录写 `visual_prompt.json`，并在小回执的
`next_action` 列出提示包、输入 IR 和缺失页。Agent 读取提示包后生成提案，用
`apply-visual-plan` 合入，再把新 IR 交回生成入口。不会自动替 Agent 选择构图或直接套默认样式。
只有明确要求复现旧版时才用 `--skip-visual-design`；MCP 对应 `skip_visual_design=true`。

## 一次提案与严格合入

```bash
python -m deck_compiler visual-prompt \
  --ir /work/deck_ir.json --out /work/visual_prompt.json \
  --requirements '科研组会，突出原图和证据等级'
```

现有 Agent 读取整个提示包，输出 `visual_proposal.json`。提示包包含完整 Deck IR、原图尺寸、
文件哈希、`planning_targets`、`required_plan_slide_ids` 和两份严格 Schema；生成提示包本身不调用模型。
每个支持的页面均需有 visual_plan；不支持的页列出原因，不凭空添加图或机制。
纯文字/公式 Deck 仍需 academic_design，其提案允许 `slides: []`。
已有 composition.layout_tree 的页面由 RPA 子布局定义正文结构，同样选择整套 academic_design，
不叠加平面 visual_plan。它会作为已有复合结构列入规划目标，仍按真实几何与原生渲染检查。
`--slides slide-04 slide-06` 仅用于局部修订，不能让其余支持的页静默跳过设计。
下面是提案的单页节选，完整生成任务须覆盖全部支持的页：

```json
{
  "ir_sha256": "<提示包中的完整 IR SHA-256>",
  "academic_design": {
    "style": "research-seminar",
    "title_treatment": "thin-rule",
    "density": "balanced",
    "figure_treatment": "unframed",
    "decoration_policy": "minimal",
    "header_variant": "compact",
    "type_scale": "standard"
  },
  "slides": [{
    "slide_id": "slide-04",
    "visual_plan": {
      "visual_job": "measurement-evidence",
      "primary": {"kind": "figure", "index": 0},
      "composition": "figure-left",
      "figure_width_ratio": 0.64,
      "emphasis": {
        "source": "semantic.takeaway",
        "text": "2 Å",
        "treatment": "inline-callout"
      }
    }
  }]
}
```

```bash
python -m deck_compiler apply-visual-plan \
  --ir /work/deck_ir.json --proposal /work/visual_proposal.json --out /work/v6.deck_ir.json
python -m deck_compiler build \
  --ir /work/v6.deck_ir.json --out /work/v6-build --skip-native
```

提案只允许 `ir_sha256 / academic_design / slides`；每项只允许 `slide_id / visual_plan`。
过期哈希、重复或不存在的页、非法字段、错误图索引、原文中不存在的强调和每页风格覆盖均拒绝。
合入只修改 presentation，不修改 theme、assets、semantic 或 composition。
源 IR 使用相对资源路径时，新 IR 必须写在同一目录；验证失败不覆盖已有输出。

MCP 对应入口为 `totalpipe_visual_prompt`、`totalpipe_apply_visual_plan`，`out` 为 JSON
文件路径。加载旧服务的客户端需重启该 MCP 服务才能发现新工具。

## Deck 风格与视觉任务

`presentation.academic_design` 在整套 Deck 中生效，沿用原 theme 字体，选择统一字号层级与强调色。

| 字段 | 取值与行为 |
| --- | --- |
| style | `research-seminar` |
| title_treatment | `plain` / `thin-rule`，后者生成原生细分隔线 |
| density | `balanced` / `compact`，视觉规划文本组间距分别为 24 / 18 px |
| figure_treatment | `unframed` / `ruled-caption`，后者在图与图注之间生成原生细线 |
| decoration_policy | `minimal` / `none`；none 要求 plain + unframed |
| header_variant | `standard` / `compact`，默认 compact；科学长标题可自动增加行高 |
| type_scale | `standard` / `compact`；默认标题 44、正文 28、图注 22 px；compact 为 40 / 26 / 20 px |
| accent_color | 可选 `#RRGGBB`；省略时沿用 theme.accent |

`slides[].presentation.visual_plan` 决定主视觉和构图，不添加科学内容。

| visual_job | 资源要求 | composition |
| --- | --- | --- |
| measurement-evidence | 恰好一张原图，无 graphics | `figure-left` / `figure-right` / `figure-top` |
| mechanism-explanation | 一个既有 v5 mechanism，或含 mechanism 的 composite | `graphic-left` / `graphic-right` / `graphic-top` |
| evidence-comparison | 恰好两张原图，无 graphics | `evidence-columns` / `evidence-rows` |

`primary` 用 `kind: figure/graphic` 和从 0 开始的 `index` 引用现有资源。可选字段：

- `figure_width_ratio`：0.35–0.75，单图槽宽或双图列中主图占比；默认单图 0.64、比较 0.5。
- `graphic_width_ratio`：0.4–1，仅机制页；控制原生图形区域宽度。
- `evidence_order`：比较页上原始图索引的完整排列，主图必须在首位；对象身份、来源和图注不变。
- `context_placement`：带原图的机制左右构图可用 `above-visuals / with-evidence` 为既有候选排序。
- `emphasis`：仅 `inline-callout`，保持正常正文字号；不是商业 KPI 卡片。

强调来源只解析 `semantic.title`、`semantic.takeaway`、`composition.blocks.<id>.text`、
`composition.graphics.<id>.nodes.<id>.title/body`。强调文字必须精确存在于引用的可见原文中。
讲稿不能被用来绕过这一验证。V6 不接受未实现的每页 `theme_tokens/component_variants`。

页面带 `semantic.explanation` 时，required 义务是硬输入：`visual_plan` 只能在不遮挡、不丢失
现有载体的前提下选构图，不能把列表/嵌套/公式页改回纯文字。当前三种 `visual_job` 只覆盖
图、机制和双图；纯文字/列表/嵌套页由 IR 映射成 `layout_tree` 或原生列表，最终由
`derived/explanation_coverage.json` 验收，而不是由视觉提案声称完成。
硬 `composition.visual_intent` 流程组不与 visual_plan 混用。

## 容量与科学术语

标题与正文必须保留完整、正确的专业术语、化学态、单位和科学限定词。
不得为了字符数或槽位容量，强行截断、造缩写或将术语压成不正确的表达。
从 RPA 映射 Canonical IR 时，标题取完整 Story 标题（包括 `metadata.story_title`），
正文取完整原始内容；RPA 的短标题、响应摘要或缩略的 Slot 文本不作为科学文字真源。

V6 默认采用 `presentation.text_capacity_policy: "preserve-terms"`，也可在旧 IR 上显式启用。
标题 120、takeaway 180、正文 600 字符是名义预算；超过时保留全文、报告
`SCIENTIFIC_TEXT_CAPACITY_REVIEW` 并继续生成候选。标题优先增加行数及标题区高度。
正文槽位仍不足时，编译器在字体下限保留完整文字，记录原始槽位、实际高度与
`SCIENTIFIC_TEXT_OVERFLOW`。由这些文本引起的越界和碰撞保留为 REVIEW，允许候选生成，
以便在原生 PowerPoint 中继续编辑与检查；不会把已记录的溢出宣称为视觉验收通过。
该模式不自动拆分或改写正文。显式 `text_capacity_policy: "strict"` 可恢复硬文字预算。
没有 V6 字段且未选择此策略的旧 IR 仍使用 strict。

比例先尝试请求值，再尝试邻近值；不改变请求的左右/上下方向。复用 `graphic_page_regions()`、
`compile_graphic()`、`block()`、`figure()` 和 `fit_text()`。原图最小尺寸、图形容量、科学关系、
对象身份及其他几何硬门禁仍生效。文本容量例外之外，无候选满足要求时报告
`VISUAL_PLAN_UNSATISFIABLE`，不静默回退到其他构图或删减内容。

## 追踪与验收

`layout.json` 记录实际 academic_design 和逐页 `scientific_visual_plan` adaptation：
包含 requested、selected 区域、实际比例以及候选失败原因。
`derived/plan_to_layout.json` 同样携带决策追踪。packer 与外部提供方不能覆盖视觉规划页。
原生分隔线必须通过实际 OOXML 中的几何、填充、边界与碰撞检查，没有碰撞豁免。

改变同一页的 composition、图像比例或比较顺序，应在科学内容不变时改变实际布局。
`tests/test_scientific_visual.py` 覆盖这类行为、提案原子合入、旧 IR、科学术语容量例外、
原图哈希、图注对齐、假设虚线、科学 REVIEW、提供方边界和原生对象。

构建生成 candidate/staging；正式 final 仍需现有 PowerPoint UI、原生 PDF、科学审核和 promote。
自动结构检查不代替盲评，也不代表已完成 Windows PowerPoint 原生验收。
