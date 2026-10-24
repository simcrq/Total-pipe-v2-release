# 原生项目符号、独立样式与颜色

Deck IR 继续使用 `schema_version: "2.0"`。无序列表由原生段落属性绘制；
科学术语保留策略不会删除列表标记。
项目符号是可选的：takeaway 只在声明 takeaway_marker 后加标记；正文可由 auto 识别，
也可显式要求列表或用 text_flow=plain 关闭。样式与颜色字段本身不强制把普通段落变成列表。

## 配置

以下局部字段合入已有 IR 的顶层 presentation：

```json
{"text_capacity_policy":"preserve-terms","bullet_style":"large_square","bullet_color":"#005A9C"}
```

单页 presentation 可给完整 semantic.takeaway 加一个独立标记：

```json
{"takeaway_marker":{"style":"large_diamond","color":"#000000"}}
```

takeaway 保留完整字符串；编译器按字形预留至少 42 px 标记槽，按剩余宽度换行，后续行对齐正文且不重复标记。
可与显式行内公式共存，混排行高仍逐行实测。不声明 takeaway_marker 时保持普通 takeaway。

正文 block 可独立配置列表样式与符号颜色：

```json
{
  "id":"projects","component":"body","text_flow":"distributed_arrow_list",
  "bullet_style":"arrowhead","bullet_color":"#C2410C",
  "text":"第一项保留完整的科学术语与限定条件。\n第二项保留数值、单位与研究边界。\n第三项保留需要进一步验证的问题。"
}
```

| 配置 | 优先级 / 默认值 |
| --- | --- |
| 列表样式 | block.bullet_style → 顶层 presentation.bullet_style → 原有语义默认 |
| 列表符号颜色 | block.bullet_color → 顶层 presentation.bullet_color → theme.accent → 内置强调色 |
| takeaway 标记 | 单页 presentation.takeaway_marker.style，独立于正文列表 |
| takeaway 符号颜色 | takeaway_marker.color → 正文 foreground |
| 正文颜色 | 沿用文字主题，bullet_color 不改变正文颜色 |

颜色接受 `#RRGGBB`。样式支持 `bullet / square / open_square / diamond / arrow / check / dash`。
另提供 `large_square / large_diamond / arrowhead` 原生大方形、大菱形与箭头形字形；
默认列表优先 large_square，步骤类优先 arrowhead。已有小方形和细箭头样式仍可显式选择。
大字形使用 Wingdings 原生项目符号，在正文字号下绘制，不写入项目符号的百分比或点数缩放。
缺少该字体时用 Unicode 字形回退并报告 BULLET_GLYPH_REVIEW。
符号字体选择可显示该字符的正文或系统符号字体；跨机器仍须检查实际字形和对比度。
旧样式在本机缺少对应 Unicode 字形时仍可退回圆点；需要稳定的大字形时优先声明上述原生样式并安装 Wingdings。
capabilities 的 `native_bullets` 声明原生列表能力。

## 内容与容量

- 显式 distributed_arrow_list 要求 2–6 个非空原文条目，以换行分隔，不按句号创造条目。
- auto 继续保守识别多段正文；block 样式 / 颜色只配置已选中的列表，不创造条目。
- 原生列表的组件区域至少为 **520 × 220 CSS px**。**572 × 226 px 满足门槛**，随后仍按完整条目、
  标记槽、标签、实际换行和间距检查真实容量。
- 显式列表区域不足报告 SPLIT_REQUIRED；递归区域宽度不足报告 INSUFFICIENT_LIST_SPACE，附所需 / 可用尺寸。
  不静默改成无标记正文。auto 在小区域仍可使用原有普通文本回退，记录 TEXT_FLOW_FALLBACK。
- 字号下限为 **24 CSS px（18 pt）**；标记的实际字形宽度、上下伸参与容量测量。项目间距默认是行高的 0.45，可用顶层 presentation.list_gap 调整。
  不均分剩余空间拉大空白。
- strict 下，条目超过四行或完整列表高度不足时报告 SPLIT_REQUIRED。
- preserve-terms 下，名义条目行数或高度不足时保留全文、标记、颜色及顺序，扩展高度并报告
  SCIENTIFIC_TEXT_OVERFLOW REVIEW；由此产生的越界 / 碰撞也保留审核项。

布局树按标记槽、标签、换行和间距测量显式列表，其最小宽高参与递归分配；
普通布局提供方把显式列表交由编译器执行。通用纯文本自动拆页不切开显式条目与样式。
超容量后应调整布局或拆页；带 REVIEW 的候选不代表视觉通过。

数值与负号属于正文，例如 `1.25 nm`、`-0.5 eV` 不作为行首前缀删除；明确的列表前缀可转成原生标记。
不改写科学术语和数据。独立公式及开启 inline_math 的正文块使用原有数学路径，暂不接受 block 列表样式 / 颜色；
带行内公式的 takeaway 可以独立加标记。

## 写入、检查与示例

每条列表是同一文本对象中的一个段落，标记写入 a:buChar / a:buClr / a:buFont，换行使用段内软换行。
结构 QA 比较符号、符号颜色、字体、缩进与完整原文；混排 takeaway 比较完整文本体 XML。
OfficeCLI 固定行高的溢出估计保留为线索，实际显示须在 PowerPoint 逐页检查。

[两页样例](../examples/native-bullets.deck_ir.json) 包括黑色菱形、蓝色方形、橙色箭头、
继承默认颜色的勾选符号，以及带原生公式的 takeaway：

```bash
python -m deck_compiler build --ir examples/native-bullets.deck_ir.json \
  --out build/native-bullets --officecli officecli --skip-native
```

正式交付按 [中文用法](USAGE.zh-CN.md#6-正式-finalpowerpoint-验收与晋级) 完成原生验收及审核。
