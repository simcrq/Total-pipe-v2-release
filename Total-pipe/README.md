# Total-pipe Deck Compiler v2

Total-pipe 是从论文证据到可验收 PPTX 的端到端编排项目。上游负责证据与科研叙事，
Research PPT Assistant 负责页面规划，Deck Compiler v2 从 canonical
`deck_ir.json` 开始确定性生成和验证 PPTX。

```text
PDF → PaperWorkflow → Story Planner → pwf2rpa → Research PPT Assistant
    → canonical deck_ir.json → Deck Compiler v2
    → candidate.pptx → staging.pptx
    → structural QA + PowerPoint PDF
    → qa_report.json → final.pptx
```

## 职责边界

- **PaperWorkflow**：从论文生成可追溯 Evidence。
- **Story Planner**：组织研究问题、回答、证据和叙事推进。
- **pwf2rpa**：验证 Story provenance，并转换为 RPA Slide Brief。
- **Research PPT Assistant**：选择 Layout、绑定 Slot、输出设计意图；不生成 PPTX。
- **Deck Compiler v2**：验证 Deck IR、求解几何、生成 PPTX、写入 OOXML 契约。
- **PowerPoint 验收**：以 PowerPoint 导出的 PDF 和人工逐页检查作为原生证据。

`deck_ir.json` 是编译阶段唯一可维护的页面真源。以下文件只能由编译器派生：

- `derived/deck_plan.json`
- `derived/visual_manifest.json`
- `derived/plan_to_layout.json`
- `derived/qa_expectation.json`

下游不得修改这些派生文件再回写语义。

## 当前目录

```text
Total-pipe/
├── deck_compiler/        # Deck IR → PPTX → unified QA
├── schemas/              # Deck IR / TextBoxContract / QA Report
├── examples/             # 可运行的内容无关示例
├── benchmarks/           # compiler smoke 与历史基线
├── pwf2rpa/              # Story → RPA input
├── skills/
│   ├── total-pipe-deck/
│   └── local-project-mcp-bridge/
├── docs/
└── tests/
```

M5 已从 Total-pipe 主链删除旧 SlideDSL、`deckplan2slide.py`、
`design_land.py`、`rpa_full_pipeline.py`、孪生 artifact telemetry、
PPTX sidecar 和旧 Team 编排。Research PPT Assistant 仍保留自己的 renderer
telemetry adapter；它们不属于 Deck Compiler 的 PPTX 生成路径。

## 环境

优先使用 Codex `load_workspace_dependencies` 返回的 Python、Node 和
artifact-tool。最低要求和 PowerPoint 说明见 [环境清单](环境清单.md)。

```bash
python -m unittest discover -s tests -v

cd pwf2rpa
PYTHONPATH=. python -m unittest discover -s tests -v
```

Research PPT Assistant 是同级项目，测试应在其目录运行：

```bash
cd ../research-ppt-assistant
npm test
npm run audit:layouts
```

## Deck Compiler 快速使用

只编译 Deck IR 和布局，不生成 PPTX：

```bash
cd Total-pipe
python -m deck_compiler compile +  --ir examples/research.deck_ir.json +  --out /tmp/total-pipe-compile
```

生成 `candidate.pptx` 和 `staging.pptx`：

```bash
python -m deck_compiler build +  --ir examples/research.deck_ir.json +  --out /tmp/total-pipe-build +  --node /absolute/path/to/node +  --skip-native
```

`--skip-native` 仅用于开发检查，会产生 `REVIEW`，不能晋级 final。正式流程不要使用
该参数。正式流程在 macOS 上必须直接在 PowerPoint 普通视图或阅读视图逐页眼检
`staging.pptx`；不得用导出后的 Preview/PDF 代替。确认图号—图注—素材、科学图面
尺寸、碰撞和字体后，记录与当前 staging 绑定的 UI 眼检：

```bash
python -m deck_compiler record-powerpoint-review --out /tmp/total-pipe-build \
  --reviewer "reviewer" --slides all
```

随后在同一次 PowerPoint 控制流程中导出 `native.pdf`，再绑定原生证据：

```bash
python -m deck_compiler validate-native +  --out /tmp/total-pipe-build +  --pdf /tmp/total-pipe-build/native.pdf +  --reviewer "reviewer"
```

论文图片还必须在 asset 与 figure reference 上声明相同的 `source_figure`（如 `3e`），
且图注显式包含 `Fig.3e`；三方不一致或有效图面小于默认 220 px 都会直接 FAIL。

若 `qa_report.json` 中存在 `REVIEW`，创建与当前 staging SHA-256 绑定的
`review_ack.json`，列出全部接受的 review ID，然后晋级：

```bash
python -m deck_compiler promote +  --out /tmp/total-pipe-build +  --ack /tmp/total-pipe-build/review_ack.json
```

完整端到端步骤见 [中文使用说明](docs/USAGE.zh-CN.md)，编译器契约见
[Deck Compiler v2](docs/deck-compiler-v2.md)。

## Deck IR 与 text_flow

Deck IR Schema 位于 [schemas/deck-ir.schema.json](schemas/deck-ir.schema.json)。
block 支持：

```json
{
  "id": "findings",
  "component": "body",
  "label": "关键发现",
  "text_flow": "auto",
  "text": "第一项内容……\n第二项内容……\n第三项内容……"
}
```

`text_flow` 可选值：

- `auto`：满足条件时使用等距箭头列表；
- `plain`：始终保持普通正文；
- `distributed_arrow_list`：显式请求等距箭头列表。

自动模式只处理 3–5 个明确段落，总显示长度至少 72 单位、单项最多 120 单位，
汉字按 2 单位计。编译器不会按标点拆分单个段落。实际触发写入
`adaptation_log`；组件框不足 520×220 CSS px 时保持普通正文并记录
`TEXT_FLOW_FALLBACK`。

可运行参考见
[examples/distributed-arrow-list.deck_ir.json](examples/distributed-arrow-list.deck_ir.json)。

## 状态与晋级规则

- `FAIL`：阻断 PPTX 生成或晋级。
- `WARNING`：记录风险，不单独阻断晋级。
- `REVIEW`：需要绑定当前 artifact SHA-256 的人工确认。
- `INFO`：记录确定性适配或非阻断事实。

`promote` 会重新验证 staging、Deck IR、layout、PowerPoint PDF 和 acknowledgement
的哈希。任何证据过期都会拒绝生成 `final.pptx`。

## Test3 验收基线

源工作区的验收证据位于：

```text
/Users/simcr/0_Project/pptx-maker/Test3/acceptance/build/
```

发布副本位于：

```text
Total-pipe-v2-release/acceptance/Test3/build/
```

发布副本包含 baseline final、微软雅黑版本、装饰修订版本、PowerPoint PDF、
QA 报告、metrics、state 和 review acknowledgement。当前人工装饰版不等同于
canonical Deck Compiler 输出；`final_msyh.pptx` 保留为回退基线。
