# Research PPT Assistant 使用说明

本文对应 `research-ppt-assistant 0.6.3-rc1`。命令和字段以当前
`server/cli.mjs help`、MCP tool schema 和仓库内 JSON Schema 为准。

## 1. 能力边界

RPA 负责内容规范化、版式规划、Slot Binding、设计意图、渲染前检查和渲染后 QA。
它不会：

- 读取或 OCR 论文 PDF；
- 编造缺失的研究结论、数值或引用；
- 直接创建、打开或编辑 PPTX；
- 从图片顺序、邻近关系或 caption 猜测科研图区域；
- 用设计评分覆盖 Evidence、Capacity、Geometry 或 Renderer 硬失败。

需要从论文开始时，先用 PaperWorkflow 生成 Evidence；需要 PPTX 时，把 RPA 结果交给
Total-pipe Deck Compiler 或其他外部渲染器。

## 2. 环境与入口

要求 Node.js 22 或更高版本。插件运行时没有第三方 npm 依赖。

```bash
node --version
node server/cli.mjs help
node server/cli.mjs summary
```

三种入口使用同一核心逻辑：

- Codex Skill：`skills/research-ppt-assistant/SKILL.md`
- MCP stdio：`node server/mcp-server.mjs`
- CLI：`node server/cli.mjs <command>`

CLI 支持 `--file input.json`、`--json '<object>'` 和普通参数。CLI 默认
`detail_level: standard`，MCP 默认 `compact`；机器消费 MCP 输出时读取
`structuredContent`。

## 3. 推荐工作流

```text
Evidence / PaperWorkflow v4
  → normalize_content
  → create_deck_plan
  → validate_deck_plan
  → run_preflight
  → visual/group/figure preflight（按页面需要）
  → 外部渲染器生成 PPTX 和真实 telemetry
  → assemble_render_telemetry（使用 artifact-tool/Visual Manifest 时）
  → evaluate_visual_quality
  → validate_rendered_deck
```

### 3.1 规范化 Evidence 与 Slide Brief

输入示例：

```json
{
  "sources": [
    {
      "source_id": "SRC0001",
      "title": "Example Paper",
      "source_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    }
  ],
  "citations": [
    {
      "citation_id": "CIT0001",
      "source_id": "SRC0001",
      "span_id": "S0001",
      "chunk_id": "E001"
    }
  ],
  "evidence": [
    {
      "evidence_id": "EV0001",
      "evidence": "实验组的目标指标高于基线。",
      "citation_ids": ["CIT0001"],
      "content_role": "primary_evidence",
      "importance": 1,
      "must_keep": true
    }
  ],
  "slide_briefs": [
    {
      "slide_id": "SLIDE0001",
      "slide_type": "result",
      "category_hint": "chart_takeaway",
      "title": "目标指标优于基线",
      "goal": "展示主要实验结果",
      "body": "实验组在预先定义的指标上高于基线。",
      "evidence_ids": ["EV0001"],
      "citation_ids": ["CIT0001"]
    }
  ]
}
```

```bash
node server/cli.mjs normalize-content --file content-model-input.json
```

继续之前检查：

- `status === "valid"`；
- Source → Citation → Evidence 引用链完整；
- `violations` 为空；
- `coverage.orphan_must_keep_evidence` 为空；
- `adaptation_log` 只有预期的规范化记录。

PaperWorkflow v4 对象可放入 `paperworkflow_v4`。RPA 只消费 JSON 对象，不读取
PaperWorkflow 的文件路径。

### 3.2 生成整套规划

把规范化输出中的 `sources`、`citations`、`evidence`、
`slide_briefs` 与规划选项一起传入：

```json
{
  "presentation_type": "group_meeting",
  "theme_id": "paper_blue",
  "viewing_mode": "projector",
  "density_preference": "中",
  "allow_auto_split": true,
  "max_replan_attempts": 3,
  "sources": [],
  "citations": [],
  "evidence": [],
  "slide_briefs": []
}
```

```bash
node server/cli.mjs plan --file plan-input.json --detail-level full
node server/cli.mjs validate-deck --file deck-plan.json
```

只传带 Evidence ID 的 `slide_briefs` 而不传对应 Evidence/Citation 会导致引用无法解析。
每页至少检查：

- `layout_id`、`slot_specs`、`slot_assignments`；
- `binding_status` 与 `contract_valid`；
- `violations` 与 `adaptation_log`；
- `planning_decision` 和 `replan_context.rejected_layout_ids`；
- `design_ir`、`visual_treatment`、`decoration_profile`；
- `production_status` 与 `design_status`。

`slot_specs[].pptx_in` 是 PowerPoint 英寸坐标。显式 `slot_id` 必须存在且类型兼容，
不会回退到其他槽位。结构内容超过容量时，`allow_auto_split: true` 才允许确定性拆页。

## 4. 长多段正文与 text_flow

RPA 接受以下字段：

- `body`：完整正文，可包含明确换行；
- `key_points`：并列要点；
- `secondary_messages`：次级信息；
- `text_flow`：`auto | plain | distributed_arrow_list`。

示例：

```json
{
  "slide_id": "SLIDE0008",
  "slide_type": "discussion",
  "category_hint": "discussion",
  "title": "结果的适用边界",
  "goal": "说明证据覆盖范围",
  "key_points": [
    "实验覆盖给定材料和加工窗口。",
    "结果支持相关机制，但不能证明唯一因果路径。",
    "跨材料适用性需要新的对照实验。"
  ],
  "text_flow": "auto",
  "evidence_ids": [],
  "citation_ids": []
}
```

自动选择 `distributed_arrow_list` 的条件：

- 没有主视觉；
- 3–5 个明确条目；
- 总显示长度至少 72 单位；
- 单项最多 120 单位；
- 汉字按 2 个显示单位计；
- 页面不是参考文献、结果主图、结果比较或指标主导页。

RPA 会优先选择 `structured_text / distributed_list_panel`，但不会绘制容器和箭头。
下游若使用 Total-pipe，应：

1. 保留条目顺序和换行；
2. 将条目合并到对应 Deck IR block 的 `text`；
3. 将 `design_ir.text_flow.mode` 复制到 block 的 `text_flow`。

Deck Compiler 才会生成浅色矩形、等高纵向条目和 `➢` 标记。空间不足时编译器保持
普通正文，并记录 `TEXT_FLOW_FALLBACK` / `adaptation_log`。

## 5. 渲染前检查

基础结构检查：

```bash
node server/cli.mjs validate-slide +  --layout-id RM-DUAL_FIGURE-01 --text-chars 80 --image-count 2

node server/cli.mjs preflight --file preflight-input.json
```

`run_preflight` 输入同时包含 `renderer_inputs` 和完整 `deck_plan`。继续渲染前，
确认 `pipeline_status === "preflight_complete"` 且 `status !== "invalid"`。

科研图页面按需增加：

- `visual-fit-preflight`：检查单图与 inner visual slot；
- `group-fit-preflight`：检查有明确语义关系的多图组；
- `figure-placement`：先生成 renderer input，渲染后再回填 effective geometry。

这些工具不会自行决定 semantic crop。需要裁切时必须提供显式 Visual Intent 与
Source Region。

## 6. 外部渲染器边界

渲染器读取 `layout_id`、`slot_specs[].pptx_in` 和 `slot_assignments`，生成
PPTX，并输出真实渲染事实。

`validate_renderer_inputs` 可检查 slidep/tencent-pptx 输入。slidep 页面源使用唯一
`XX_slug.slide`；同 stem 的 `.slide` / `.jsx` 会被阻断。Windows 使用
`F:/project` 形式的绝对路径；macOS/Linux 使用 POSIX 绝对路径。

RPA 中的 renderer adapter 只转换 telemetry，不承担 Total-pipe Deck Compiler 的
PPTX 生成职责。

## 7. Render Evidence 与 Visual QA

使用 artifact-tool + Visual Manifest 时：

```bash
node server/cli.mjs assemble-render-telemetry --file render-evidence-sidecar.json
node server/cli.mjs visual-quality --file canonical-render-telemetry.json
node server/cli.mjs validate-rendered-deck --file rendered-deck.json
```

生产 Evidence 需要真实且一致的：

- `manifest_schema_version`、`producer_version`、`deck_id`；
- deck 内唯一的 `visual_key`；
- 素材 SHA-256；
- source region、container、allocation 和 display geometry；
- renderer profile 与不可用事实清单。

缺少关键事实时不能判定为 pass。fixture benchmark、仓库测试和 source hash 只能验证
代码与样例，不能代替最终 PPTX 渲染和人工检查。

## 8. 状态判读

| 字段 | 含义 |
|---|---|
| `pipeline_status` | 当前阶段是否完成 |
| `status` | 当前工具的领域结果 |
| `production_status` | Evidence/Capacity/Geometry/Renderer 硬门禁 |
| `design_status` | 层级、留白、焦点、重复和节奏 |
| `repair_plan` | 最多两轮的确定性修复动作 |

Visual QA 的 `warning`、`fail`、`not_evaluable` 必须结合具体 rule 判读。
`design_status` 不能把 production failure 改成通过。

## 9. 自检

```bash
npm test
npm run audit:layouts
npm run benchmark:ci
npm run benchmark:figures
npm run test:coverage
npm run check
```

若文档命令与运行结果冲突，以 `node server/cli.mjs help` 和 MCP 的实时 tool schema
为准，并把差异作为文档缺陷修复。
