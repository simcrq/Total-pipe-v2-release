# 复合内容区域（Layout Tree 1.0）

RPA 选择分组和子布局，Deck Compiler 在现有框架内测量并分配区域，OfficeCLI 接收确定对象与坐标。
PWF、pwf2rpa 不做视觉排版。没有增加独立系统层或 HTML 渲染管线。

## 输入与兼容性

外层仍是 `schema_version: "2.0"`。`composition.layout_tree` 为可选扩展，自身版本是 `1.0`。
没有它时，旧平面表示继续使用原有布局与容量限制。已有 archetype 可采用区域树；新混排页可用
`composite-research`，该 archetype 必须带树。标题、takeaway、caveat、脚注仍用现有 frame / academic_design。

内容只在 canonical blocks、figure_refs、graphics 中保存。下面的对象放进 `composition.layout_tree`：

```json
{
  "version": "1.0",
  "regions": {
    "body": {
      "id": "two-panels", "type": "columns", "weights": [2, 1],
      "children": [
        {"id": "method-panel", "type": "panel", "title": "实验流程与完整条件",
         "body": {"id": "method-ref", "type": "graphic", "ref": "method"}},
        {"id": "math-panel", "type": "panel", "title": "矩阵与平方根表达式",
         "body": {"id": "math-stack", "type": "stack", "gap": "compact", "children": [
           {"id": "explanation-ref", "type": "block", "ref": "explanation"},
           {"id": "equation-ref", "type": "block", "ref": "equation"}
         ]}}
      ]
    }
  }
}
```

此例需要相应 canonical blocks 与 ID 为 `method` 的 graphic；公式仍写 `component: "formula"`。
完整三页样例：[composite-layout.deck_ir.json](../examples/composite-layout.deck_ir.json)。

| 类型 | 输入 | 分配方式 |
|---|---|---|
| columns | children，可选 weights | 扣除间距后按相对权重分宽 |
| stack | children，可选 weights | 默认贴合实测内容；显式权重控制相对行高 |
| panel | title、body，可选 padding | 测量完整标题，为正文留区域，不绘制卡片背景 |
| image_grid | columns、figure children | 按行测量图片及图注，原图等比 contain |
| block | ref 为 block ID | 原有正文或原生 OMML 公式 |
| figure | ref 为 figure_refs 零基索引 | 原图、图注与来源检查一起复用 |
| graphic | ref 为 graphic ID | 原有 process/DAG、机制、架构、漏斗、Path 或图形 composite |

节点 ID 全树唯一。间距 `compact/standard/spacious` 为 12/24/32 CSS px；panel 内边距
`none/compact/standard` 为 0/12/20 CSS px。不能传页面 bbox/x/y/w/h。Path IR 原有局部坐标不变。
最多 6 层、64 节点、4 列；单个 grid 最多 12 图；canonical graphics 最多 8 项。
每个 block、figure_ref、graphic 必须恰好引用一次。显式 anchor 的公式与解释是同一 stack 的兄弟节点，
解释在前。树页不同时使用分配正文区域的 visual_plan/visual_intent。

## RPA：保留整页版式，另选子布局

RPA 模板 ID 与编译器 archetype 是两个既有概念，不新增虚构的 research_standard。
先完成原有 Evidence、Story、整页规划与验证；映射 canonical 内容后显式选择子布局。
`create_deck_plan` 不会自动将全部页面改成布局树。

1. 在 Total-pipe 目录运行 `python -m deck_compiler capabilities`，或调 `totalpipe_capabilities`。
2. 将返回对象作为 consumer_capabilities 传给 RPA `search_sublayouts`。
3. 用 `compose_sublayout` 提交 sublayout_id、groups 和 content_refs。每组含 id/title/items；
   items 用 kind/ref 引用内容。content_refs 包含 blocks 的 id/component/anchor、figure_count、graphics 的 id/type。
4. 把返回的 composition_patch 合入同一 canonical slide，保留完整内容和整页框架。
5. 执行整套 Design 并编译。树页需要 deck academic_design，不再叠加平面 visual_plan。

RPA CLI 在仓库根目录运行：

```bash
node research-ppt-assistant/server/cli.mjs search-sublayouts --file sublayout-search.json
node research-ppt-assistant/server/cli.mjs compose-sublayout --file sublayout-request.json
```

支持 two-panels、three-panels、four-panels、vertical-stack、image-grid。响应 `structure_planned` 只证明
结构合法，geometry_status 明确为 requires_compiler_measurement。能力缺失返回 legacy_fallback_required
或 SUBLAYOUT_CAPABILITY_UNAVAILABLE，退回原有整页检索，不向旧消费者发送树。旧 MCP 服务需重载。

## 测量、反馈和容量

编译器自底向上测量需求、自顶向下分配矩形。公式按 AST 和 18 pt 下限测量，图片保持原有 panel 下限，
图形调用原有绘制器进行有界尺寸探测。测量需求和最终 bbox 分别记录于 layout.json 的
`adaptation_log[action=layout_tree].nodes`；最终对象携带 layout_component/layout_region。
树由 compiler 独占，平面 packer 不重新分配其叶节点。

三节点水平流程图最少需要 `3×200+2×64=728 px` 宽；均匀三栏无法容纳时返回 INSUFFICIENT_DRAWING_SPACE。
可以调整权重、放整行、换两栏或拆页，不缩小节点绕过下限。复杂表格尚无统一原生测量/写入契约，暂不声明支持。

每次 compile/build 写 layout_feedback.json，绑定完整 IR 哈希。协议见
[layout-feedback.schema.json](../schemas/layout-feedback.schema.json)。单条错误示例：

```json
{
  "code": "INSUFFICIENT_DRAWING_SPACE", "severity": "FAIL",
  "component": "body.children[0].body",
  "message": "Native graphic cannot reach its readable minimum width in this region.",
  "required_size_px": [728, 272], "available_size_px": [326.86, 450],
  "measurement": "conservative_minimum",
  "suggested_actions": ["switch_to_two_columns", "split_slide"]
}
```

失败页为 layout_failed，统一 QA 同时保留。尺寸单位是 CSS px，探测可能为保守界，不能声称所有原生字体都可精确预测。
局部测量或发射失败会撤销该页树对象并阻止候选构建。Skill/调用者依据反馈重规划；编译器不调用 RPA 或改写科学内容。
preserve-terms 下，完整正文/标题可超名义槽位并保留 REVIEW，不截断专业术语；公式、图像、图形仍须满足真实尺寸下限。
原生公式和图形仍需 PowerPoint 视觉核对。

## 图片元数据

PWF 的 artifacts.figure_assets_metadata 记录资源路径身份、SHA-256、格式、image_kind、默认 crop_allowed=false。
可读光栅图另记录 source_width_px/source_height_px 和 visual_aspect_ratio；SVG 可从 viewBox 得到比例，
不伪造像素分辨率。未知格式记录 metadata_status=unavailable。

pwf2rpa 原样保留 workflow，仅为显式匹配 source_asset_id/asset_uri/uri 的 visual 补齐元数据。
不按同名文件猜来源；冲突保留显式值并返回 warning。RPA 规范化后保留尺寸和裁剪策略。
本版树始终 contain，即使元数据允许裁剪也不会自动裁剪证据图。

## 开发样例

在 Total-pipe 目录中运行：

```bash
python -m deck_compiler build --ir examples/composite-layout.deck_ir.json \
  --out ../builds/composite-layout --layout-provider packer --skip-native
```

样例使用仓库已有模拟图片，不宣称论文证据。输出 candidate.pptx，不自动晋级 final。
