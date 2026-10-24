# 可编辑科研表格

Deck IR 2.0 的 `composition.tables` 保存语义网格。布局树 1.1 用 `type: "table"`、
`ref: "表格ID"` 引用；表格可放入 panel、columns 或 stack。编译器测量列宽和行高，
OfficeCLI 建立原生 PowerPoint 表格并写入验证后的 DrawingML，不使用图片或分散文本框模拟。

## 最小输入

```json
{
  "id": "parameters", "row_count": 2, "column_count": 2,
  "header_rows": 1, "column_weights": [1, 2], "origin": "generated",
  "cells": [
    {"id":"h-name", "row":0, "column":0, "text":"物理量"},
    {"id":"h-expression", "row":0, "column":1, "text":"完整表达式与单位"},
    {"id":"name", "row":1, "column":0, "text":"根号与指数示例"},
    {"id":"expression", "row":1, "column":1, "kind":"formula", "text":"q(t)=\\sqrt{1+t^{2}}"}
  ]
}
```

将它放入 composition.tables，再用以下树引用：

```json
{"version":"1.1", "regions":{"body":{"id":"table-region", "type":"table", "ref":"parameters"}}}
```

## 网格与来源规则

- 每页最多 4 表；每表 1–32 行、1–12 列。row/column 为零基索引。
- cells 定义合并区域的左上角；row_span/column_span 默认为 1。所有逻辑位置必须恰好覆盖一次，
  重叠、越界、漏格和重复 ID 会失败；空白格显式写 text=""，不自动补值或补零。
- 多级表头通过 header_rows 与合并区域表示。默认 header_rows=1，可设为 0；表头加粗，
  填充和正文颜色来自当前主题。column_weights 只表达相对列宽，不接受页面坐标、行高或任意字号。
- cell.kind 为 text（默认）或 formula；align 为 left（默认）、center、right。
  同一格选择一种类型，带说明的复杂推导可分格或使用相邻正文块。
- formula 使用现有公式 AST，支持矩阵、根号、分式、上下标、嵌套指数等。
  未支持的 LaTeX 明确报错；不把失败公式变成普通文本。
- origin 必须为 paper 或 generated；paper 表格必须提供 evidence_refs，且全部绑定本页 semantic.evidence_refs。
  generated 不能用来冒充论文数据。编译器不推断缺失值、计算新结论或裁剪原始表格截图。

## 测量与容量

编译器尝试 28/26/24 CSS px（21/19.5/18 pt）。文字按实际字体完整换行；
`LDLᵀ` 等记号把上标与主体作为同一换行词元。公式按数学结构测量，合并单元格使用
合并后的宽高，跨行需求向被覆盖行分配。最终表格贴合实测行高，不拉伸填满剩余正文区。

纯文字表格在 preserve-terms 下可超名义区域生成候选并保留 SCIENTIFIC_TEXT_OVERFLOW REVIEW。
含公式表格的尺寸不足返回 INSUFFICIENT_TABLE_SPACE 与所需/实际尺寸，需加宽、减少同页并列项
或拆表/拆页；不能把公式缩到 18 pt 以下。保留全文不等于视觉已验收。

实际 PPTX 的表格名称、数量、坐标、每格内容、合并、公式和样式会与编译结果核对。
原生 PDF 检查单元格文本与页面边界；数学文本提取差异仍保留 REVIEW，需查看 PowerPoint 原生结果。
TABLE_CONTENT_REVIEW 始终要求核对科学术语、数值、单位及来源；近似公式测量也保持 REVIEW。

## 能力与示例

先查询 totalpipe_capabilities；tables 需要 layout_tree 1.1、table 叶节点及 native_table。
含公式的表格另需 native_equation。旧 1.0 消费者明确回退；旧树无需迁移。

[两页开发样例](../examples/native-table.deck_ir.json) 包含合并多级表头、Cholesky/LDLᵀ 分解矩阵，
以及双栏中含根号、分式和指数的原生公式表格。它是软件回归数学示例，不建立科研结论。

DrawingML 合并保留每个逻辑位置，并标记延续格；垂直对齐写入 tcPr.anchor。
对应规则见 [Microsoft 合并说明](https://learn.microsoft.com/en-us/openspecs/office_standards/ms-oe376/de4562ba-7901-48df-9803-414ded131f2b)
和 [原生单元格垂直对齐](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.drawing.tablecellproperties.anchor?view=openxml-3.0.1)。
