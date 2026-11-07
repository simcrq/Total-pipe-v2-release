# ExplainViz：自动讲解图、空白检测与正文区重排

ExplainViz 默认启用 `auto`。正常 compile/build/generate 和四工具候选构建都会评估机会，
先复用预留区域，再检测空白，最后尝试当前页正文区的有限重排。没有合适内容或安全布局时保留原页。
源文件不写回，正文、讲稿、证据、图片来源和科学含义不由插件改写；输出仍为现有 Deck IR 2.0。

## 默认行为与关闭

```bash
python -m deck_compiler build --ir designed.deck_ir.json --out build/deck --skip-native
# 显式关闭；请求文件即使不存在，也不会因关闭而读取它
python -m deck_compiler build --ir designed.deck_ir.json --out build/deck --skip-native --explain-viz-mode off
python totalpipe.py generate designed.deck_ir.json --out build/deck --explain-viz-mode off
```

高级 MCP compile/build 使用 `explain_viz_mode`；默认四工具的 start 也接受同名参数，默认 auto。
模式优先级为显式 mode 参数、请求内 options.mode、默认 auto。off 禁用；prefer 降低机会评分阈值，
不降低来源、可读性、碰撞和内容保持门槛。IR 草稿预览、逐页测量和修补预检关闭自动增强，正式候选才运行。
已有 job 缺少此字段时按 auto 兼容，不能通过恢复任务静默变更已有显式 off。

## 决策与来源

提供三个确定性模板：`geometry/peel_angle@1`、`layer_stack@1`、`process_steps@1`。
默认规则只从当前页可见文字提取明确关系：剥离角定义、明确从上到下的 2–4 层，
或由箭头明确连接的 2–4 步顺序。规则不能识别或事实不足时跳过，不补写科学关系。
可以继续通过 Agent 提案指定受约束 VisualSpec；运行时不隐式选择模型或调用模型服务。
审计以 `decision_origin` 区分 source_rules 与 agent_proposal，评分是策略输入，不是科学正确率。

每个标签必须是当前 `semantic.title`、`semantic.takeaway` 或 `block:<id>` 原文的子串；
每条关系必须引用同时包含两端标签的明确原文。讲稿和新生成事实不能充当来源。
明显否定关系不转成正向关系。剥离角只标符号，不传实验角度；层厚、几何及步骤间距只为示意。
中文标签使用“示意”，英文标签使用“Schematic”。生成图仍需科学人审。

封面、总结、无解释关系及已有其他图片/图形/图表/表格的页面保守跳过。
默认每套最多新增 4 幅、每页 1 幅；已有 ExplainViz 图计入总预算，重复运行不重复插入。
已增强场景不就地重画；改变定义或顺序后，应从原输入重新生成。

## 放置策略

1. **预留槽位**：复用现有 layout_tree 中完整主题背景矩形的 Path IR 场景。
   可由旁路 slots.json 明确指定，或自动识别；成功时只追加路径和文字。
2. **自动空白检测**：从真实编译布局的正文区域减去已有对象边界及 12 CSS px 间距，
   对空矩形裁切并去除包含项；最小区域 420×260 CSS px。
   使用现有 stack/columns/graphic 叶子把区域写成可重建的相对布局。
   只有新增图仍在原空白内、原对象几何变化不超过 0.1 CSS px 浮点容差时才认定为空白插入。
   有空白不代表相对布局一定能表达；失败继续尝试后续策略。
3. **局部重排**：只重新安排当前页正文区，在上下或左右方案中有限尝试。
   可调整正文对象框与换行，不能改正文源文字、证据、讲稿、原图、标题或 takeaway；
   不降低原字号，不改变原字体/字重，完整文字必须可读，新增图和已有对象不能碰撞。
   可将旧平面正文转换为已有 composite-research/layout_tree，不新增渲染引擎或绝对坐标语法。

默认每页最多 8 次放置尝试，整套尝试最多为图示预算乘以每页次数；没有无限搜索。
记录 `slot_source=reserved|detected|local_reflow`、布局变体、最终区域及原对象 before/after 框。
页面失败只丢弃本页增量，最后整套复核失败时回退全套；源文件始终保留。

## 配置与提案

可以用 `--explain-viz-request request.json` 提供选项、显式槽位或 Agent 提案；请求不再是启用条件：

```json
{
  "version": "1.0",
  "options": {
    "mode": "auto",
    "slot_policy": "detect_free_space",
    "allow_local_reflow": true,
    "max_visuals_per_deck": 4,
    "max_layout_attempts_per_slide": 8,
    "protected_slide_ids": []
  }
}
```

`slot_policy=reserved_only` 保留只使用预留场景的旧策略；`allow_local_reflow=false` 只允许预留或无位移的空白插入。
`protected_slide_ids` 禁止指定页上的任何新增或重排。显式空 slots 列表是空允许清单，不会自动放宽范围。
保护列表含未知页 ID 时整体回退，避免拼写错误使保护失效；已有 visual_intent 硬流程约束的页面直接跳过。
options、slots、proposal 的字段契约见 [Schema](../schemas/explain-viz.schema.json)。
人工提案仍必须绑定整个输入 IR 和槽位列表的 SHA-256，任一变化都需重做；默认规则使用当前输入即时决策。

```bash
python -m deck_compiler explain-viz-prompt --ir designed.deck_ir.json --out prompt.json
# 提示包含自动发现的 slots、候选页事实、可用区域和严格 proposal_schema
python -m deck_compiler apply-explain-viz --ir designed.deck_ir.json --proposal proposal.json --out enhanced.deck_ir.json
```

slots/proposal 参数均可省略；省略时用自动发现和保守规则。apply 输出必须与源 IR 同目录，
避免图片和字体相对路径失效；输出不得覆盖源文件、提案或槽位文件。
高级 MCP 对应 `totalpipe_explain_viz_prompt / totalpipe_apply_explain_viz`。
完整样例见 [examples/explain-viz](../examples/explain-viz/README.md)，无预留槽位样例为 `automatic.deck_ir.json`。

## 构建产物与验收

- `deck_ir.json`：实际编译 IR，包含接受的图示及相对布局调整。
- `explain_viz.source.deck_ir.json`：增强前原输入归档，相对路径仍以原目录为基准。
- `explain_viz.json`：来源/提案/最终 IR 哈希、逐页决策、图形清单、空白区域与布局变化。
- `qa_report.json` 的 explain_viz 字段：disabled/skipped/enhanced/fallback、实际新增数和审计位置。
  构建和绑定当前产物的原生验收更新保留此摘要。

源读取、输出目录等基础设施错误正常报错；配置错误或插件错误回退，不隐藏原有编译 FAIL。
Design 检查先执行，插件不能绕过科学审读或默认整套 Design。
运行时使用本次选定的布局提供方；增强在内存中编译，保留原图片/字体目录，不写源目录临时 IR。

结构、文字与布局检查不能证明科学关系真实。成功绘图继续保留 SCHEMATIC_REVIEW 及
EXPLAIN_VIZ_SEMANTIC_REVIEW，后续 OfficeCLI、截图与 PowerPoint 原生验收仍需完成。
原生对象为自由形状和独立文字，尚无 PowerPoint 自动编组。OfficeCLI/原生渲染失败正常进入原构建 QA，
没有自动覆盖源文件或撤销已有 PPTX 的操作。

本轮默认启用与自动布局的验证记录见 [开发与验证说明](../../docs/explain-viz-auto-layout.md)。
首版和上一轮“未执行验证”的历史记录不代表本轮验证结果。
