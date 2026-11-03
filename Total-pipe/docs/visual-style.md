# 视觉风格包（visual_style）

「学术风还是商业风」不是渲染器里的 if 分支，也不是每页手调的样式，而是一份可选、可覆盖的**风格包**。Deck IR 只声明内容与构图；风格包决定这些东西被画成什么样：节点是直角还是圆角、有没有底色、线多粗、标签多重。

```
presentation.visual_style = {"pack": "academic", "overrides": {"graphic.node.stroke_width": 1}}
```

- `pack`：`academic`（默认）、`commercial`、`print`。
- `overrides`：点号路径 token，只允许覆盖该包已存在的 token。
- 不写 `visual_style` 时使用 `academic`。要沿用旧版卡片风，显式写 `"pack": "commercial"`。

## 三个包

| 包 | 节点 | 描边 | 连线 | 页面留白 | 适用 |
| --- | --- | --- | --- | --- | --- |
| `academic` | 直角矩形、无填充、常规字重 | 前景色 1.25px | 中性灰 1.25px | 稀疏页垂直居中 | 研究组例会、答辩、期刊汇报 |
| `commercial` | 圆角矩形、主题浅色填充、粗体 | 主题色 2px | 主题色 2.5px | 内容顶对齐 | 产品/商业提案（旧默认） |
| `print` | 直角矩形、无填充 | 纯黑 1px | 纯黑 1px | 稀疏页垂直居中 | 讲义、纸质稿 |

`commercial` 保留的是本仓库此前的默认外观，因此既有 deck 只要显式声明该包，渲染结果不变。

## Token 一览

```jsonc
{
  "graphic": {
    "node":     {"shape": "rect", "fill": "none", "stroke": "foreground",
                 "stroke_width": 1.25, "title_size": 24, "body_size": 20,
                 "align": "center", "bold": false},
    "emphasis": {"fill": "none", "stroke": "accent", "stroke_width": 2.25},
    "edge":     {"color": "muted", "width": 1.25, "arrow": "triangle"}
  },
  "panel": {"fill": "none", "border": "#D8DEE6", "border_width": 1,
            "title_fill": "none", "radius": 0},
  "text":  {"emphasis": "accent", "highlight": "#FFF1A8"},
  "page":  {"sparse_balance": "center", "furniture": "rule", "footer_rule": "#D8DEE6",
            "footer_ink": "muted", "number_ink": "muted",
            "footer_size": 20, "number_size": 22}
}
```

- `fill`：`none`、`tint`、`tint-strong` 或 `#RRGGBB`。
- `stroke` / `edge.color`：`accent`、`foreground`、`muted`、`none` 或 `#RRGGBB`。
- `shape`：`rect`、`rounded-rect`、`ellipse`、`diamond`、`hexagon`、`parallelogram`、`trapezoid`。
- `page.sparse_balance`：`center` 或 `top`。
- `page.furniture`：`rule`（细线 + 页码 + 页脚）或 `none`（不画页脚家具）。
- `text.emphasis` / `text.highlight` / `text.citation`：句内强调、高亮的墨色与底色，以及引用/出处的弱化墨色
  （默认取主题色、浅黄与 muted；`[[…]]` 标记由编译器用于图注出处）。
- 节点自己声明了 `shape` 时，节点级声明优先于风格包。

覆盖示例：

```jsonc
{"pack": "academic",
 "overrides": {"graphic.node.stroke_width": 1,
               "graphic.edge.color": "foreground",
               "page.sparse_balance": "top"}}
```

非法 token、非法取值、未知包都会在 `deck_compiler validate` 阶段报 `VISUAL_STYLE_INVALID`，不会静默忽略。

## 与 academic_design 的分工

- `presentation.academic_design`：版面语言——标题处理、密度、页眉变体、字号档位、图表框处理。
- `presentation.visual_style`：图形语言——节点形状、填充、描边、连线、面板默认、稀疏页平衡。

两者正交：同一套版面可以画成学术风或商业风。

## 稀疏页的竖向构图

`page.sparse_balance = center` 时，编译器在分配区域**之前**先测量构图自然高度；若内容高度不足区域 85%，就把区域整体下移一小段（**最多 32 px**）再分配。因为下移发生在测量之前，面板、图、连线和表格的几何仍然互相一致，不会被推出页面边界。

上限是刻意的：把半格余量全部下移，会在标题与正文之间留出一个段落高的空洞，读起来像排版事故，而不是留白。空余空间留在页面底部才是「短页」，留在标题下面就是「断了」。真正的解决办法不是把内容推下去，而是换构图——纯文字页尤其如此（`SPARSE_TEXT_PAGE` 会提示）。

`stack` 的 `align` 也据此收紧：`distribute` 只把余量分到**行间**，不再把单行文本撑成 129 px 高的盒子；内容不足 30% 时它自动退回顶部排布，由稀疏页提示要求换构图，而不是把三行字摊到整页。

这个策略只影响 `layout_tree` 构图；旧式 archetype 页保持原样。被平衡的页会在 `layout.json` 的 `adaptation_log` 里留下 `vertical_balance`，并抑制对应的 `PAGE_UNDERFILL` 提示。

## 版式兜底规则

三条不依赖作者自觉的规则，全部在编译期生效：

1. **标题只有一个字号。** `type_sizes(design)['title']`（标准档 44 px = 33 pt）就是全篇标题的唯一字号。
   长标题不会缩到 40/38/36 pt，而是让页眉变高（最多 3 行）；超过 3 行报 `TITLE_TOO_LONG`，
   提示缩写标题或拆页。此前 `fit_text` 会把长标题压小，导致相邻页标题一大一小。

2. **多段文字竖排 → 无序列表。** 一个 block 的 `text` 里如果有 2–6 个自然段（换行分隔）、
   每段不超过 240 个显示宽度、且不含表格/代码/公式行，编译器自动改用原生列表（`text_flow`），
   保留原文与 evidence，不吞内容。作者显式写了 `text_flow` 或 `inline_math` 的块不参与兜底。
   入口：`deck_compiler/text_flow.py:fallback_list`，在 `compile_deck` 里对每个 block 生效。

3. **图注按实际行数占位。** 图注条的高度按测量行数计算，最多 320 字符；`caption` 角色最多
   15 pt 且不缩字号。此前图注被 `max_lines=2` 卡死，真实论文的 3–4 行图注只能删到 60–90 字符。

## 句内强调

均质的正文读起来像一段说明文，人写的 deck 会在句子里把**结论词**抬出来。强调不是另加一个文本框，而是写在文本里的标记：

```jsonc
{"id": "p3-cause", "component": "body",
 "text": "接触宽度 **W** 与势垒高度 G 通过 ==Φ_B== 耦合，而不是按面积平均。"}
```

- `**…**`：主题色 + 加粗，用于承载结论的词或短语。
- `==…==`：高亮底色，用于必须在投影上被认出的符号或短表达式。
- 转义写 `\*\*`、`\==`；未闭合的标记按字面输出并报 `EMPHASIS_UNCLOSED`，不会吞掉后文。
- 标记不跨 `$…$` 公式：真需要强调量，强调公式前后的词。
- 原生列表一项只有一种 run 样式：块里带标记时编译器保留原文、去掉标记并报 `EMPHASIS_IN_LIST`；
  要保留强调就把该块写成 `text_flow: "plain"`。

强调短语用**粗体字面**测量（不是用常规字重估宽），因此加粗带来的换行与缩号都会如实出现在
`BODY_SIZE_VARIANCE` 里：一页只该有一处强调，排版重了就该删，而不是把整页缩一号。

入口：`totalpipe_layout/inline_math.py`（`parse_inline` / `measure_inline` 的 `strong_font`）、
`deck_compiler/inline_text.py:paragraphs`（run 级 `b` / `solidFill` / `a:highlight`）。

## 页码与页脚

设计页默认带页脚家具：一条 1 px 细线（y=664）、左侧一行弱化文字、右下角页码（15–16 pt，弱化墨色）。
参考的真实组会 deck 全篇连续页码，这是最便宜的「完成度」信号。

```jsonc
"presentation": {
  "page_numbers": true,                       // 默认 true；false 关掉全篇页码
  "footer": "NbS2/MoS2 非对称接触 · 组会报告"    // 可选，一行，≤120 字符，左侧
}
```

- 单页要藏页码：`slides[i].presentation.page_number = false`。
- 页脚不放 evidence id——那些是溯源键，留在 speaker notes。
- 只在 `academic_design` 页面上生效；旧式 frame 页保持原样。

## 目录与章节

参考里的长报告有目录页（点线引导 + 页码）和章节标记；这两样都能从 deck 自己已有的信息里算出来，
不需要作者再写一遍内容：

```jsonc
"presentation": {"agenda": {"title": "目录"}, "footer": "…"},
"slides": [
  {"id": "p1", "presentation": {"section": "器件与背景"}, …},   // 章节起点
  {"id": "p2", …},                                              // 同章节继续
  {"id": "p3", "presentation": {"section": "器件性能"}, …}
]
```

- 编译器在**第 1 页之后**插入一页目录：章节序号（01、02…）、章节名、点线引导、该章起始页码。
- 目录页上的每一个字都来自 IR：标题来自 `agenda.title`，章节名来自 `presentation.section`；
  页码由编译器按最终页序计算，因此插入目录页会把后面的页码整体 +1，并且只在插入前算一次。
- 目录页与内容页共用同一套页眉、细线与页脚，不是另一套模板。
- `presentation.agenda` 需要 `academic_design`；`agenda` 只写 `true` 时标题用「目录」。
- 少于两个章节不生成目录页并报 `AGENDA_EMPTY`；超过 8 个章节只列前 8 个并报 `AGENDA_TRUNCATED`。
- `presentation.section` 一行 ≤24 字符；它不改内容、不占 Story 条目，只标记章节起点。

## 图注出处

论文图注只写「画的是什么」时，读者还得自己找来源。`figure_refs.source_label` 加一句出处
（作者、文献或图号），编译器把它设为图注前的弱化前缀：

```jsonc
{"asset_id": "f4c", "caption": "Fig. 4c | Programming window…", "source_label": "Xie et al., Nat. Electron."}
```

渲染结果是「Xie et al., Nat. Electron. · Fig. 4c | …」，前缀用 `text.citation` 墨色（默认 muted），
整段仍是一个可编辑的图注。前缀计入图注的测量行数与字符数，不会压到图片上；<=80 字符。

## 原生渲染需要完全权限

`NATIVE_RENDER_SKIPPED` 不是配置问题，是沙箱边界：workspace-write 下 PowerPoint COM 返回
`E_ACCESSDENIED`、Chrome headless 无法创建命名管道。两者在一次性 `danger-full-access` 下都能跑通
（已实测：PowerPoint 打开候选并导出 PDF 成功，Chrome headless 截屏成功）。需要原生验收时：

```powershell
$ppt = New-Object -ComObject PowerPoint.Application
$pres = $ppt.Presentations.Open('<candidate.pptx>', $true, $false, $false)
$pres.SaveAs('<out.pdf>', 32)   # ppSaveAsPDF
$pres.Close(); $ppt.Quit()
```

导出的 PDF 再用 LibreOffice Kit 转 PNG，就能看到 PowerPoint 真实排版——公式是 Cambria Math 的
真分式与上下标，而不是 LibreOffice 的纯文本 fallback。

## 代码位置

- `deck_compiler/style.py`：包定义、校验、解析、`capabilities()`、`text_styles()`、`page_furniture()`。
- `deck_compiler/text_flow.py`：`fallback_list()`，多段文字的无序列表兜底。
- `deck_compiler/inline_text.py`：run 级强调与高亮的 XML。
- `deck_compiler/layout.py`：`page_furniture_elements()`，页脚细线与页码。
- `deck_compiler/graphic_layout.py`：节点与连线按包绘制，节点框按标签实测收紧。
- `deck_compiler/layout_tree.py`：`balanced_region()` 与稀疏页平衡。
- `schemas/deck-ir.schema.json`：`$defs/visual-style`、`presentation.page_numbers` / `footer`。
- `tests/test_inline_emphasis.py`：标记解析、粗体测量、run 输出、页脚几何。
- `tests/test_visual_style.py`：包解析、覆盖校验、节点样式、稀疏页平衡。
