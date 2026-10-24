# 显式行内公式

Deck IR 2.0 可在同一个可编辑 PowerPoint 文本框或原生单元格内混排文字和公式。
默认关闭，已有正文中的美元符号、反斜线及旧独立公式保持原有行为。
它复用现有公式 AST，属于编译器的文字测量与写入扩展，没有增加系统层。

## 开启方式

正文块加 `inline_math: true`，用 `$…$` 或 `\(…\)` 标记数学区域。JSON 中反斜线必须双写：

```json
{
  "id": "response", "component": "body", "inline_math": true,
  "text": "当 $x>0$ 时，响应为 \\(q(x)=\\sqrt{1+x^{2}}\\)，保留完整说明。"
}
```

标题和 takeaway 按字段显式开启；只影响列出的字段，不影响 purpose 或备注：

```json
{
  "title": "行内公式：$x_i^2$ 与平方根",
  "takeaway": "文字与 $\\sqrt{x^2+y^2}$ 按实际行高混排。",
  "inline_math": ["title", "takeaway"]
}
```

这三个字段属于 slide.semantic，其余必需语义字段照常提供。
表格 `kind: "text"` 的单元格也可加 `inline_math: true`；`kind: "formula"` 继续表示原有完整公式格。
不要在 formula 块或 formula 格上叠加行内模式。

## 数学与兼容规则

- 支持现有 AST 的分式、根号、上下标、嵌套指数、函数及矩阵。每个数学区域不可拆成两个文字行。
- 普通文本行内模式关闭时完全按旧规则处理；开启后，字面美元符号写 `\$`（JSON：`"\\$"`）。
- 行内不接受 `$$…$$` 或 `\[…\]`。长推导和独立展示继续使用 `component: "formula"`。
- 空公式、未知宏、未配对分隔符明确返回 INLINE_MATH_SYNTAX，表格返回带单元格身份的 TABLE_INVALID。
  不把解析失败内容静默改为普通文字。每个文字字段最多 128 个数学区域。
- 开启后 auto 文本流按混排段落处理，不自动转成项目列表；显式 distributed_arrow_list 与行内模式不能同时使用。
- 首版覆盖正文、semantic.title/takeaway 和原生表格文字格；图注、图形标签及 panel 标题仍按原有文字协议。
- canonical text 保留原始完整内容；Unicode fallback 仅用于无数学支持的阅读器，不用来估算容量或恢复原文。

## 容量计算

行内公式使固定“字数 × 字号”和固定段落行高不再足够。编译器现在：

1. 用实际正文字体测量文字片段，用公式 AST 测量数学片段；公式是不可分割的换行单元。
2. 逐行累加片段宽度，保留中文行首标点规则。整条公式在字号下限仍过宽时，返回 INLINE_FORMULA_SPACE。
3. 每行分别取最大的基线上方需求与基线下方需求，再与普通文字最小行距比较。
   段落高度是这些实际行高之和；一行含高矩阵，不会把整段所有行都拉成矩阵高度。
4. TextBoxContract 继续声明基础字体、下限、内边距及普通行距；inline_layout.lines 保存混排的
   width/ascent/descent/height 和完整片段。实际 DrawingML 行距使用逐行 height，覆盖普通固定行距。
   结构检查核对整个混排文本体，覆盖文字、数学结构、fallback、换行及每行间距。
5. IR 字符粗筛对行内内容统计“正文字符 + 数学区域数”，不按 LaTeX 命令长度计算。
   这只用于前置筛查；数学是否能放下仍由实际宽高决定。

正文、树、图文混排和密集推导的解释块共用这套测量。含行内公式的正文由编译器分配，
不交给只理解纯文本字数的平面 packer。表格按各格混排高度分配行高和合并区域。
正文与公式的基准字号不低于 18 pt；数学内部上下标和分式保留 Office Math 自身的排版比例。

preserve-terms 下，正文或标题可保留超出名义区域的完整混排内容，扩展实测高度并保留 REVIEW；
公式宽度仍须满足下限。含行内数学区域的表格与公式表格一样须满足真实容量，空间不足需加宽或拆页。
不能截断专业术语、拆开根号或压低基准字号以放行。

数学与正文使用不同字体；部分结构采用保守测量，保留 INLINE_MATH_MEASUREMENT_REVIEW。
PowerPoint 原生视觉检查仍必需，尤其检查基线、列边界和高公式前后的实际行距。
旧式纯文本溢出自动拆页不会处理行内混排页，避免按 OfficeCLI 的统一行高估计切开公式或科学分组；
需要调整时将完整内容及当前反馈交回规划层。

## 能力与规划

先查询 totalpipe_capabilities。行内模式要求 native_equation 和 native_inline_equation；
表格另需 table 叶节点、native_table 与布局树 1.1。树中仍引用原有 block/table ID，不复制科学内容。
RPA 的 content_refs.blocks 可声明 inline_math；content_refs.tables 可声明 has_inline_math。
消费者缺少能力时明确重规划，不向旧消费者发送不能处理的混排引用。

RPA 的既有全文绑定和字符粗筛继续保留；不要把 compact 摘要或排版后的 Unicode fallback 当成科学原文。
语义分组交给 RPA，数学尺寸与最终几何交给 Deck Compiler。编译反馈仍绑定完整 IR 哈希。

## 样例与验收

[三页开发样例](../examples/inline-math.deck_ir.json) 覆盖标题/正文、行内矩阵与独立公式共存、
表格混排和未开启模式的旧正文。它是数学软件回归，不建立科研结论。

```bash
python -m deck_compiler build --ir examples/inline-math.deck_ir.json \
  --out ../builds/inline-math --skip-native
```

本轮 716 项通过、1 项因缺少原有 Li Markdown 样例跳过。
三页 PowerPoint 直接检查、同次原生 PDF 和独立 PNG 复核均通过；旧复合布局与表格的几何、XML 和内容逐项相同。
构建记录位于忽略目录 builds/inline-math/initial/。候选 QA 为 0 FAIL、2 WARNING、37 REVIEW；
OfficeCLI 的两条溢出估计和科学/数学/字体审核记录均保留，不自动晋级 final。

PowerPoint 的 TextMath 支持正文中的 inline math zone，实际写入为 a:r 与 a14:m/m:oMath 交错，
独立公式继续使用 m:oMathPara。参见 [Microsoft TextMath 文档](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.office2010.drawing.textmath?view=openxml-3.0.1)。
