# 行内公式与自动下标

Deck IR 2.0 可在同一个可编辑 PowerPoint 文本框或原生单元格内混排文字和公式。
标题、结论、普通正文、图注和表格文字格中的 `V_OUT`、`V_G`、`I_D`、`x_i` 或 `T_h-BN` 会自动排成可编辑的原生行内公式。`OUT`、`h-BN` 这样的下标作为整体排在基符号右下方。普通正文可以直接写 `当 V_G 增大时，读取 V_OUT`。

自动识别适用于单字母变量和简单下标，也接受 `V_{OUT}`。代码片段、网址、带扩展名的文件名、常见绝对或点开头的相对路径和 `source_id` 一类长标识符按文字保留。可用反引号标记需保留字面下划线的符号。
PageScene 的普通文字、图注、原生列表、带文字的形状和表格也支持自动下标。

## 显式公式

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

这三个字段属于 slide.semantic，其余必需语义字段照常提供。裸写下标会自动启用相关字段。
表格 `kind: "text"` 的单元格也可加 `inline_math: true`；`kind: "formula"` 继续表示原有完整公式格。
不要在 formula 块或 formula 格上叠加行内模式。

## 数学与兼容规则

- 支持现有 AST 的分式、根号、上下标、嵌套指数、函数及矩阵。每个数学区域不可拆成两个文字行。
- 显式行内公式字段中的字面美元符号写 `\$`（JSON：`"\\$"`）。
- 行内不接受 `$$…$$` 或 `\[…\]`。长推导和独立展示继续使用 `component: "formula"`。
- 空公式、未知宏、未配对分隔符明确返回 INLINE_MATH_SYNTAX，表格返回带单元格身份的 TABLE_INVALID。
  不把解析失败内容静默改为普通文字。每个文字字段最多 128 个数学区域。
- 开启后 auto 文本流按混排段落处理。Deck IR 显式原生列表、图形标签和 panel 标题继续使用各自的文字协议。
- 独立公式继续使用对应的公式块。`V_OUT = G V_IN` 这类式子可直接使用简写，复合或容易歧义的下标用 `{…}` 写明范围。
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
显式换行支持 LF、CRLF 和 CR，按断行控制处理而不送入字体字形测量；连续空行和末尾换行
均参与高度计算。原始 IR 文本保留不变，适用于 Pillow 13 / Raqm 对换行测量的严格行为。
旧式纯文本溢出自动拆页不会处理行内混排页，避免按 OfficeCLI 的统一行高估计切开公式或科学分组；
需要调整时将完整内容及当前反馈交回规划层。

## 能力与规划

先查询 totalpipe_capabilities。行内模式要求 native_equation 和 native_inline_equation；
表格另需 table 叶节点、native_table 与布局树 1.1 或 1.2。树中仍引用原有 block/table ID，不复制科学内容。
带框 takeaway 和 1.2 面板按扣除描边、内边距及可选标记后的宽度测量，详见 [边框容器](framed-containers.md)。
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

每次验收以当前构建的 QA 与原生渲染证据为准。早期开发样例的测试数量和构建记录见
[历史快照](../../docs/archive/Total-pipe/docs/inline-math.md)，不作为当前版本的验证结果。

PowerPoint 的 TextMath 支持正文中的 inline math zone，实际写入为 a:r 与 a14:m/m:oMath 交错，
独立公式继续使用 m:oMathPara。参见 [Microsoft TextMath 文档](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.office2010.drawing.textmath?view=openxml-3.0.1)。

当前数学片段使用 Cambria Math，正文仍按主题字体排版。Times New Roman 普通文字字体不能保证
完整替代专用数学字体；根号、可伸缩括号和矩阵等结构需要相应数学字体支持。修改公式字体时必须
同时核对度量与 PowerPoint 原生渲染，不能只替换字体名称并沿用已有容量结果。
