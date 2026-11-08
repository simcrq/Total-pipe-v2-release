# PageScene：显式页面场景与原生页面验收

状态：**正式接入 Agent job（`page_mode=page_scene`）**。它仍然不是默认生成路径；默认
`page_mode=deck_ir` 保留完整 Deck Compiler / OfficeCLI 对象模型。

## 为什么加这一层

旧路径：

```
page_design(散文) -> Deck IR(layout_tree) -> compiler 分配区域 -> 整篇 QA
```

问题是页面设计只给意图，compiler 要猜几何；等整篇 candidate 出来才发现文字叠压。
PageScene 路径：

```
page_design -> PageScene(显式 bbox) -> python-pptx 原生渲染
            -> 单页 PowerPoint PNG -> 修改/接受 -> candidate -> native QA
```

PageScene 不重新决定科学内容。页面文案来自已批准的 `page_design.display_copy`；
Story 和证据仍然是科学权威。绑定器拒绝改写、遗漏批准文案、越权证据和未登记数字。

## 启动与阶段

```text
totalpipe_start(page_mode="page_scene", ...)
```

进入路径：

```text
intake -> queries -> evidence -> model_selection -> story_prompt -> story
       -> scientific_review -> rpa -> page_design -> page_review
       -> page_scene -> build -> candidate_ready
```

- `page_mode=page_scene` 跳过 `deck_ir`、`design`、`visual_design`。
- `page_mode=deck_ir`（默认）跳过 `page_scene`，原有流程和全部对象能力不变。
- `source_kind=deck_ir` 的导入任务不能使用 `page_scene`，否则会在创建任务前拒绝。

`page_scene` 是 agent artifact：`next_action` 给出
`work/page_scene_prompt.json`、`work/page_scene_task.md`、PageScene Schema 和输出路径
`work/page_scene.json`。最多 4 次不同稿件的修订额度，与旧 IR 的 3 次预算独立。

## 绑定门禁

接受 `page_scene` 时执行 `page_scene_binding.bind()`：

- 页数与页 ID/顺序必须与批准 `page_design` 一致；
- `title_ref` / `take_ref` 和对象 `copy_ref` 必须解析到 `copy_bindings`；
- 字面标题/结论必须与批准文本逐字一致，否则 `PAGE_SCENE_COPY_DRIFT`；
- `content_map` 标记为 visible 的 copy carrier 必须在页面上真正出现；
- `evidence_refs` 只能使用该设计页 Story item 已拥有的 EV；省略时自动继承；
- 正文/标题/结论中未在页面设计、Story 或证据库登记的阿拉伯数字会被拒绝；
- 图片路径相对提交文件解析，接受后固化为绝对路径并写入 checkpoint，源图变化会使旧页失效。

`work/page_scene_binding.json` 保存设计哈希、每页 required/used copy 与 evidence 绑定，
供后续审计；讲稿只写 `page.notes`，不进入投屏对象。

## 原生对象

页眉是统一的视觉系统：`section` 画成小标签，`title_ref`/`take_ref` 画标题与浅色结论带；
可选 `title_emphasis`/`take_emphasis` 给关键词加粗/强调色。正文对象不要重复画页眉。
`text` 支持 `emphasis`/`emphasis_color`，用于在批准文案内标出关键词，不改变文字内容。
视觉风格以浅色卡片、细强调线和小标签为主；深色只用于小标签/徽章，不用大面积深色横幅
或近黑卡片承载正文。

PageScene 0.1 当前支持：

- `text`：标题/正文/标签/图注/注释，支持 `copy_ref`、`emphasis`；正文中 `$...$` /
  `\(...\)` 会转成原生 OMML 行内公式（带 plain fallback），见 `inline-math.md`；
- `list`：**多级无序列表**，0–3 级、`bullet_style=dot|dash|square|arrow|none`、
  逐项字号/粗细/颜色、行内公式、原生段落；
- `group`：**嵌套容器**，子对象 box 相对 group，递归渲染；
- `image`：论文图/参考图，保持比例，支持 contain/cover；
- `shape` / `line`：矩形、圆角、椭圆、箭头、连接线；
- `table`：原生表格，表头（`header_fill` 可改表头色）、强调行、列宽；
- `path`：**原生 DrawingML 贝塞尔路径**，`view_box` + 绝对 `M/L/C/Q/Z` 命令；
- `formula`：**原生 OMML 公式**，`latex` 经现有 `totalpipe_layout.formula` 解析；
- `chart`：**原生可编辑数据图**，line/bar/column/scatter，带轴标题、图例和图内数据；
- `page.notes`：原生演讲者备注。

旧 `deck_ir` 路径继续保留 Bezier / Path IR、OMML、Chart IR、EViz、流程图、矩阵、
嵌套 container、边框设备和完整 OfficeCLI 对象模型。PageScene 不宣称已经覆盖 EViz
自动讲解图和完整 graphic component 编译器；这些复杂页继续使用默认 `deck_ir`。

## 页级原生预览

在 `page_scene` 阶段：

```json
{"job_id":"<job_id>","scene_preview":{
  "artifact_path":"/absolute/job/work/page_scene.json",
  "page_ids":["P5","P6"]
}}
```

CLI：

```powershell
python -m agent advance --job-id <job_id> --scene-preview request.json
```

它只渲染选中页，返回 PowerPoint PDF/PNG、`issues` 和 contact sheet；不写
`work/page_scene.json`、不推进阶段、不消耗修订额度、不改变 candidate。PNG/PDF 检查
不等于 PowerPoint UI 验收。

独立快速检查仍可用：

```powershell
python -m agent pagespec-check --spec work\page_scene.json
python -m agent pagespec-preview --spec work\page_scene.json --page P5 --out-dir work\previews\P5
```

## 构建与原生验收

`build` 在 `page_mode=page_scene` 下直接调用 PageScene renderer：

- 写出 `build/candidate.pptx`、`build/staging.pptx`；
- 写出 `build/page_scene.json`、兼容的 `build/layout.json`、`build/deck_ir.json`；
- `build/qa_report.json` 使用 `checks.backend=page_scene`；
- 结构 QA 检查 ZIP/XML、画布 1280×720 px、备注、背景、图片/表格/图表数量；
- 不使用 fake Deck IR layout 冒充编译器测量，也不要求 OfficeCLI。

候选后仍可用 `advance.native`：

```json
{"operation":"render","artifact_sha256":"...","layout_sha256":"..."}
```

PageScene native 分支用 PowerPoint 导出 PDF，再按 PageScene box 检查页数、文字越界、
正文区域文字、列表完整性和字体替换；生成 `native.pdf`、`native.json` 和逐页 PNG
contact sheet。`review` / `ingest` 仍要求实际 PowerPoint UI 审阅和显式 slide IDs。

## 密度门禁

`pagespec-check` / job 接受时检查：

- 标题 ≤28 字符，take ≤68（首页 110）；
- 每页扁平对象 ≤14；
- body 文本块 ≤4，body 字数 ≤260；
- 图片/表格/图表 ≤3；
- body ≥18 pt，label ≥11 pt，caption ≥8.5 pt，formula ≥14 pt；
- 所有 box 在页面内，正文文本不重叠；
- 图片存在，表格至少 2×2，图表 series/categories 一致。

它不做文字高度测量。真正的截断、重叠、字体替换和图片裁切由 `scene_preview` /
native PDF + 人工检查。

`page_scene_qa.expression_report()` 另外给出正向表达指标：`text_only_pages`、
`card_area`、`inline_math`、`list_styles`、`native_move_pages`。它用于 recipe pilot
和后续正门禁，不替代 scientific/content review；大面积填充形状会被计入 `card_area`，
所以“卡片化”不是靠提示词，而是可测量的。

## 18 页回归

`prototype/p0_scene/deck18.json` 仍是页面层回归样例：

- `pagespec-check`：18 页 PASS；
- `page_scene_build.build`：18 页 candidate，QA PASS；
- PowerPoint 原生导出：18 页；
- `officecli validate`：通过；
- P17 使用 native 多级无序列表 + nested group。

该样例是手写 PageScene，不冒充 job 的 page_design 绑定、科学审读或 PowerPoint UI 验收。

## Recipe pilot

`agent/page_recipes.py` 提供 6 个受约束 recipe（cover / contrast / figure_readout /
metrics / table_compare / closing）。设计方只填 slots，recipe 负责几何、原生列表、
行内公式、表格和无卡片布局。它是最小闭环，尚未接入 job 状态机；验收和指标见
`page-recipes.md` 与 `E:\ppt_x\AVDG_recipe_pilot\PILOT_QA.md`。

## 文件

| 文件 | 作用 |
|---|---|
| `agent/page_scene.py` | PageScene -> python-pptx 原生渲染器 |
| `agent/page_scene_qa.py` | 密度/几何门禁、页级 PowerPoint 预览 |
| `agent/page_scene_binding.py` | 批准文案/证据/数字绑定与 prompt |
| `agent/page_scene_build.py` | candidate/QA/layout/native PDF 检查 |
| `agent/schemas/page-scene.schema.json` | PageScene 0.1 |
| `agent/schemas/page-scene-preview.schema.json` | `scene_preview` 请求 |
| `tests/test_page_scene.py` | 对象、密度、预览回归 |
| `tests/test_page_scene_pipeline.py` | job 阶段、绑定、candidate、MCP 回归 |
| `prototype/p0_scene/` | 8 页 / 18 页独立试片 |

## 未做的

- PageScene 仍未覆盖 EViz 自动讲解图、完整 mechanism/funnel/architecture
  component 编译器和 Chart IR 的全部轴/误差棒/标注字段；这些继续走 `deck_ir`。
- `native` UI review 的真实人审不能由测试或自动导出代替。
- `promote/final` 仍是 CLI-only，且当前 final promotion 证据链按 OfficeCLI 构建校验；
  PageScene candidate 的正确边界是 candidate + native evidence，不冒充 final。
- 未做 PowerPoint UI 逐页人工签收；18 页只完成原生 PDF/PNG 检查。
