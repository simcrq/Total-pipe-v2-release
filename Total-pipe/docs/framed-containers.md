# 随布局测量的原生边框容器

边框是 Deck Compiler 现有容器的可选样式。RPA / 调度 Agent 选择分组与样式；
编译器测量内容并分配最终矩形，OfficeCLI 写原生可编辑矩形、文字、图片、公式和图形。
不向 Agent 开放页面坐标，不增加独立系统层。

## 带边框的 panel：Layout Tree 1.2

外层继续使用 `schema_version: "2.0"`。含 panel.frame 的树声明 `version: "1.2"`。
原有 `1.0`、`1.1` 树继续编译；不声明 frame 的 panel 保持原有分组行为，不绘制背景。

下面的节点放在 `composition.layout_tree.regions.body` 或其子树中，body 仍引用 canonical 内容：

```json
{
  "id":"research-panel", "type":"panel", "title":"研究环境与完整科学说明",
  "padding":"compact", "gap":"compact",
  "frame":{
    "border":{"color":"#A7B5C5","width":1.5},
    "fill":"#FFFFFF", "title_fill":"#0755A3",
    "title_color":"#FFFFFF", "title_align":"center"
  },
  "body":{"id":"evidence-ref","type":"block","ref":"evidence"}
}
```

| 字段 | 行为 |
| --- | --- |
| frame.border.color | 必填，`#RRGGBB` |
| frame.border.width | 可选，默认 1，范围 0.5–6 CSS px；不是 PowerPoint 点数 |
| frame.fill | 可选，默认 none；接受 none 或 `#RRGGBB` |
| frame.title_fill | 可选，默认 none；为实测标题区绘制原生色带 |
| frame.title_color | 可选，默认沿用正文前景色 |
| frame.title_align | 可选，left / center，默认沿用左对齐 |
| panel.padding | none / compact / standard；带框时默认 compact，未带框时仍默认 none |
| panel.gap | 标题区与正文的间距，compact / standard / spacious |

内边距为 0/12/20 CSS px，间距为 12/24/32 CSS px。边框和内边距都从可用区域扣除后才测量子内容。
带框标题区上下各有一份内边距，正文保留左右和底部内边距；标题区宽度随完整容器宽度变化。
矩形的描边中心线向内收半个线宽，使完整描边留在分配区域内。

panel.body 可包含已有 columns、stack、image_grid，或 block、figure、graphic、table 叶节点。
可以嵌套 panel；仍受最多 6 层、64 节点等原有限制。1.2 同时支持 1.1 的原生表格。
图片保持 contain 及原有可读尺寸下限；公式、流程图、贝塞尔图、表格复用各自的测量和绘制器。
边框会消耗真实空间；原本接近下限的内容可能需要换布局或拆页。

## takeaway 独立框选

单页 `presentation.takeaway_frame` 给完整 semantic.takeaway 加框，不复制或改写文本：

```json
{
  "takeaway_frame":{
    "border":{"color":"#C4CED9","width":1},
    "fill":"#F8FAFC", "padding":"compact"
  },
  "takeaway_marker":{"style":"large_diamond","color":"#000000"}
}
```

两项独立可选；省略 takeaway_marker 就只有框、没有项目符号。
框选按扣除描边、内边距和可选标记槽后的宽度测量完整结论，使用现有 24 CSS px（18 pt）文字下限。
显式 inline_math 的根式、指数和矩阵继续按逐行数学尺寸测量；正文区域从实际框底加间距后开始。
新样式也支持未采用 academic_design 的旧 frame，但正式流程仍默认要求完整 Design 阶段。

takeaway 继续位于整页框架中，不作为 body 树的重复引用。此接口提供独立结论框和正文面板框，
尚不表达把整页 takeaway 与正文图片组包在同一个跨区域外框中。

## 容量、反馈与原生检查

- 严格模式下，标题或子内容达不到可读下限时返回结构化空间失败，不能裁切、去掉边框或缩写术语。
- preserve-terms 下仍完整保留文字；文字释放超容量时，框和标题色带随实际内容边界增长，
  记录 FRAME_EXPANDED_FOR_TERMS REVIEW。与邻区的碰撞及越界继续报告 REVIEW，候选并不因此自动通过视觉验收。
- 只有编译器记录的子对象可与自身边框重叠。无关对象仍受碰撞检查；流程图连接线也只豁免自己的容器。
- QA 检查 FRAME_CONTENT_OUT_OF_BOUNDS；PPTX 结构检查核对矩形几何、填充、描边颜色和线宽，
  并检查原生对象顺序 FRAME_LAYER_ORDER，避免后绘的背景盖住内容。
- layout.json 的 layout_tree adaptation 节点记录需求、分配 bbox、标题区、样式及最终 frame_bbox；
  takeaway_frame adaptation 单独记录完整结论的测量和内外矩形。失败反馈继续绑定 IR 哈希。

`capabilities` 的 layout tree 当前版本为 1.2，supported_versions 同时列出 1.0/1.1/1.2，
container_frames 明确声明 panel 与 takeaway 能力。RPA 接受新版消费者能力，现有子布局工具仍输出
兼容的 1.0 / 1.1 结构；需要边框时，调度 Agent 在 canonical 映射阶段加样式并把相应树升级为 1.2，
再做完整 Design 和编译。不可假定旧消费者支持新字段。

## 可运行样例

[framed-containers.deck_ir.json](../examples/framed-containers.deck_ir.json) 包括独立菱形结论框、
蓝色标题带、图片组、箭头列表、嵌套边框和行内原生根式 / 指数。图片是仓库已有模拟数据。

在 Total-pipe 目录运行：

```bash
python -m deck_compiler build --ir examples/framed-containers.deck_ir.json \
  --out ../builds/framed-containers --officecli officecli --skip-native
```

输出是开发候选。正式 final 仍按 [中文用法](USAGE.zh-CN.md#6-正式-finalpowerpoint-验收与晋级)
完成逐页 PowerPoint 检查、原生 PDF 检查及审核。
