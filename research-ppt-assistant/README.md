# Research PPT Assistant

Research PPT Assistant 是离线科研演示规划与质量检查工具，当前版本为
`0.6.3-rc1`。它提供 320 个版式、40 个语义类别、16 套主题，以及 MCP、CLI
和 Codex Skill 三种入口。

它负责：

- 规范化 Source、Citation、Evidence 和 Slide Brief；
- 选择满足容量约束的 Layout，并生成 Slot Binding；
- 编译 `SlideDesignIR`，选择 Visual Treatment 与 Decoration Profile；
- 在渲染前检查结构容量、科研图适配和渲染器输入；
- 组装真实 Render Telemetry，执行渲染后 Visual QA；
- 输出有限轮次、可审计的修复建议。

它不读取论文 PDF、不执行 OCR、不生成科研结论，也不直接生成或编辑 PPTX。
PPTX 必须由 Total-pipe Deck Compiler、slidep、tencent-pptx 或其他外部渲染器生成。

## 在管线中的位置

```text
Paper / PaperWorkflow / Evidence
  → normalize_content
  → create_deck_plan
  → validate_deck_plan / run_preflight
  → 外部渲染器或 Total-pipe Deck Compiler
  → Render Telemetry
  → evaluate_visual_quality / validate_rendered_deck
```

RPA 输出的是规划和质量判断，不是最终页面几何。若使用 Total-pipe，需把 RPA 的
语义与设计意图映射到 canonical `deck_ir.json`，再由 Deck Compiler 生成 PPTX。

## 运行要求

- Node.js 22 或更高版本；
- 插件运行时没有第三方 npm 依赖；
- 需要渲染 PPTX 时，单独准备相应渲染器；
- 需要 PDF/OCR Evidence 时，先运行 PaperWorkflow 等上游工具。

检查环境和目录：

```bash
node --version
node server/cli.mjs summary
node server/cli.mjs audit-layouts
```

## 快速开始

有真实内容时，先规范化，再规划：

```bash
node server/cli.mjs normalize-content --file content-model-input.json
node server/cli.mjs plan --file plan-input.json --detail-level full
node server/cli.mjs validate-deck --file deck-plan.json
```

仅做版式检索：

```bash
node server/cli.mjs search +  --text-chars 80 --image-count 2 --k 5 --include-slots +  --detail-level standard
```

CLI 支持 `--file input.json`、`--json '<object>'` 和普通参数。Boolean 参数接受
`true / false / 1 / 0 / yes / no`；裸 flag 表示 `true`。CLI 默认返回
`detail_level: standard`，MCP 默认返回 `compact`。

## 常用 MCP / CLI 对照

| MCP 工具 | CLI 命令 | 作用 |
|---|---|---|
| `catalog_summary` | `summary` | 查看版式库、类别、主题和契约版本 |
| `audit_layout_library` | `audit-layouts` | 审计 320 个版式及 SVG 预览 |
| `normalize_content` | `normalize-content` | 规范化 Evidence 与 Slide Brief |
| `search_layouts` | `search` | 检索满足硬容量约束的 Top-K Layout |
| `get_layout` | `get` | 读取完整 Slot、坐标和容量 |
| `create_deck_plan` | `plan` | 生成逐页 Layout、设计候选和 Slot Binding |
| `validate_slide` | `validate-slide` | 检查单页结构容量 |
| `validate_deck_plan` | `validate-deck` | 检查整套规划 |
| `run_preflight` | `preflight` | 合并 Renderer Guard 与 Deck Contract 检查 |
| `validate_renderer_inputs` | `validate-renderer` | 检查渲染器页面源、路径和 watcher 风险 |
| `run_visual_fit_preflight` | `visual-fit-preflight` | 检查科研图与视觉槽的几何适配 |
| `run_group_fit_preflight` | `group-fit-preflight` | 检查相关科研图组的关系约束 |
| `run_figure_placement` | `figure-placement` | 生成并核对科研图放置事实 |
| `assemble_render_telemetry` | `assemble-render-telemetry` | 连接 Visual Manifest 与真实渲染事实 |
| `evaluate_visual_quality` | `visual-quality` | 执行统一渲染后视觉质量检查 |
| `validate_rendered_slide` | `validate-rendered-slide` | 检查单页渲染结果 |
| `validate_rendered_deck` | `validate-rendered-deck` | 汇总整套渲染结果 |

完整命令以当前 CLI 为准：

```bash
node server/cli.mjs help
```

## Slide Brief 与长多段正文

Slide Brief 支持 `body`、`claims`、`key_points`、
`secondary_messages` 和结构化集合。长多段正文可保留为 3–5 个
`key_points` / `secondary_messages`，或在 `body` 中使用明确换行：

```json
{
  "slide_id": "SLIDE0008",
  "slide_type": "discussion",
  "category_hint": "discussion",
  "title": "结果的适用边界",
  "goal": "区分已证实结论与外推限制",
  "key_points": [
    "现有实验覆盖给定材料和功率范围。",
    "观测结果支持相关机制，但尚不能证明唯一因果路径。",
    "跨材料适用性需要新的对照实验。"
  ],
  "text_flow": "auto",
  "evidence_ids": ["EV0012"],
  "citation_ids": ["CIT0004"]
}
```

Design Compiler 在以下条件满足时输出
`design_ir.text_flow.mode = distributed_arrow_list`：

- 没有主视觉；
- 存在 3–5 个明确条目；
- 总显示长度不少于 72 单位；
- 单项不超过 120 单位；
- 汉字按 2 个显示单位计算。

`text_flow: plain` 禁止转换；`distributed_arrow_list` 显式请求该意图。
RPA 只输出意图和候选，不绘制矩形或箭头。使用 Total-pipe 时，RPA→Deck IR 映射必须
保留条目边界，并把 `design_ir.text_flow.mode` 复制到对应 block 的
`text_flow`。

## 必须区分的状态

- `pipeline_status` 表示阶段是否完成，例如 `plan_complete`、
  `preflight_complete`、`render_qa_complete`。
- `status` 表示该阶段的领域结果，例如 `valid`、`warning`、`invalid`，
  或 `success`、`adapted`、`needs_replan`、`failed`。
- `production_status` 是 Evidence、Capacity、Geometry、Renderer 等硬门禁。
- `design_status` 是层级、留白、视觉焦点、重复和节奏等设计判断。

`design_status` 不能覆盖任何 production failure。缺少真实渲染事实时返回
`not_evaluable`、`blocked` 或人工复核状态，不能当作通过。

## Render Evidence 边界

`assemble_render_telemetry` 需要真实 Deck Builder 生成的 Visual Manifest 和未经
测试脚本补写的 renderer telemetry。生产通过还需要：

- 稳定唯一的 `visual_key`；
- 实际素材 SHA-256；
- 显式容器和 source-region lineage；
- 可验证的 allocation/display geometry；
- 最终 PPTX 渲染与目标页人工签核。

仓库测试、fixture benchmark 或 source hash 校验都不能替代真实 PPTX 验收。

## 工程检查

```bash
npm test
npm run audit:layouts
npm run benchmark:ci
npm run benchmark:figures
npm run test:coverage
npm run check
```

`npm run check` 包含 Node/版本检查、版式审计、稳定性 benchmark、Figure
benchmark 和覆盖率门禁。

详细流程和输入示例见 [中文使用说明](docs/USAGE.zh-CN.md)。模型使用约束见
[Skill](skills/research-ppt-assistant/SKILL.md)。
