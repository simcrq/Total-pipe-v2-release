---
name: total-pipe-deck
description: 从论文 PDF 到研究汇报 PPTX 的证据—故事—规划—编译—原生验收流水线。保留 PaperWorkflow、Story Planner、pwf2rpa 与 RPA 的科研职责，Deck IR 之后统一进入 Deck Compiler v2。
---

# Total-pipe Deck Compiler v2

主链固定为：

```text
PDF → PaperWorkflow → Story Planner subagent → pwf2rpa → RPA planning
    → canonical deck_ir.json → deterministic layout → artifact-tool
    → candidate.pptx → staging.pptx → structural QA + PowerPoint native PDF
    → qa_report.json → final.pptx
```

从 `deck_ir.json` 开始只有一个页面事实来源。`deck_plan.json`、
`visual_manifest.json`、`plan_to_layout.json` 与 QA expectation 只能由编译器派生，
下游不得回写或改变语义。禁止新增逐论文 adapter。

## 1. PaperWorkflow

对论文生成 schema v4 的 `workflow.json`、`document.manifest.json` 和
`evidence.md`。下游优先引用 `EV####`；当 `synthesis_readiness` 为 `review` 或
`blocked` 时，保留门禁原因，不能用摘要覆盖。

## 2. Story Planner 硬门禁

拿到 `workflow.json` 后，必须先问用户选择当前可用的高能力模型。不得默认选择，
不得由主代理自行写 Story。用户选择后，用该模型的独立 subagent，reasoning 至少
`high`，生成 5–8 个节点的 `story_plan.json`。

每个节点只允许：

```json
{"question":"...","answer":"...","evidence":["EV0001"],"next":"..."}
```

顶层必须记录：

```json
{"planner":{"mode":"subagent","model":"<用户选择>",
"reasoning_effort":"high","selected_by_user":true}}
```

若确定性校验失败，把错误和原证据退回同一个 subagent 修订；主代理不能静默改写
科学故事。

## 3. pwf2rpa 与 RPA 规划

用严格模式把 Story 转为 RPA 输入：

```bash
cd Total-pipe/pwf2rpa
PYTHONPATH=. python -m pwf2rpa <workflow.json> \
  --story <story_plan.json> \
  --story-model <用户选择> --story-reasoning high \
  --model-selected-by-user --strict --out <rpa_input.json>
```

随后运行 RPA：

```bash
node research-ppt-assistant/server/cli.mjs normalize-content \
  --file <rpa_input.json> --detail-level compact
node research-ppt-assistant/server/cli.mjs plan --file <rpa_input.json> \
  --presentation-type group_meeting --slide-count <N> --detail-level compact
node research-ppt-assistant/server/cli.mjs validate-deck --file <deck_plan.json> \
  --detail-level compact
```

门禁分别要求 `status=valid`、`pipeline_status=plan_complete` 和
`validate-deck status=valid`。RPA 负责科学页面规划与视觉意图，不输出最终 bbox。

长多段正文应在 Slide Brief 中保留为 3–5 个 `key_points` / `secondary_messages`，或在
`body` 中保留明确换行。RPA 的 Design Compiler 会在无主视觉、显示长度合适时输出
`design_ir.text_flow.mode=distributed_arrow_list`，并优先选择
`structured_text / distributed_list_panel`。Story Planner 不决定该版式。

## 4. Canonical Deck IR

把通过的 Story/RPA 规划映射到 `schemas/deck-ir.schema.json`。Deck IR 分为：

- `semantic`：title、purpose、takeaway、evidence_refs、caveats、speaker_notes。
- `composition`：archetype、blocks、figure_refs。
- `presentation`：theme tokens 与稳定组件变体。

从 RPA 映射到 Deck IR 时，保留这些段落边界，并把
`design_ir.text_flow.mode` 复制到对应 block 的 `text_flow`。block 也可使用 `auto`：
编译器只把 3–5 个明确段落、总显示长度不少于 72 单位且单段不超过 120 单位的正文
排为浅色矩形容器中的等高 `➢` 条目（汉字按 2 单位计）。单个长段落、公式、表格、
图注和参考文献保持原样；用 `plain` 禁止转换，用 `distributed_arrow_list` 显式请求。
实际触发结果写入编译后 slide 的 `adaptation_log`。

禁止在 IR 中写最终 `x/y/w/h`。首代目录只使用 `deck_compiler/catalog.py` 中的稳定
archetype/component；内容超出容量时由编译器返回 `SPLIT_REQUIRED`，再回 Story/RPA
拆页。不得无限缩字号。

## 5. 编译与原生验收

使用工作区提供的 Python、Node 和 artifact-tool，不安装替代依赖：

```bash
cd Total-pipe
python -m deck_compiler build --ir <deck_ir.json> --out <build_dir> --node <node>
```

编译器保持一个 mutable candidate、一个 staging 和一个 final。`--skip-native` 只用于
开发，不能晋级 final。

在 macOS 上必须直接控制 Microsoft PowerPoint 打开 `staging.pptx`，在普通视图或
阅读视图中逐页眼检可编辑幻灯片本身，检查文字、图像比例、论文图号与图注对应、
panel 标签、碰撞和字体。眼检与导出应在同一次 PowerPoint 控制流程中完成；不得先
导出 PDF、再以 Preview 或逐页渲染图代替 PowerPoint 眼检。

完成逐页 PowerPoint 眼检后，先把检查记录绑定到当前 staging 与 layout：

```bash
python -m deck_compiler record-powerpoint-review --out <build_dir> \
  --reviewer "<reviewer>" --slides all
```

然后在 PowerPoint 中导出 `native.pdf`，再绑定原生证据：

```bash
python -m deck_compiler validate-native --out <build_dir> \
  --pdf <build_dir>/native.pdf --reviewer "<reviewer>"
```

`powerpoint_review.json` 必须声明 `method=powerpoint-ui`，覆盖全部 slide id，并与
`staging.pptx` 和 `layout.json` 的哈希一致；否则 `validate-native` 与 `promote` 都拒绝继续。

每个论文图素材与 figure reference 都必须写 `source_figure`（如 `3e`）。编译器会把
asset、figure reference 和图注中的 `Fig.3e` 三方对齐；缺失或不一致均为 FAIL。
科学图面默认最小有效尺寸为 220 px，低于阈值时返回
`SCIENTIFIC_PANEL_TOO_SMALL` FAIL，必须换版式、拆页或精简内容，不能以人工
acknowledgement 放行。

统一报告为 `qa_report.json`：

- `FAIL` 阻断 final。
- `WARNING` 不阻断，但必须可追溯。
- `REVIEW` 需要与 staging SHA-256 绑定的 reviewer acknowledgement。
- `INFO` 仅记录。

逐页检查后创建 acknowledgement，包含 `artifact_sha256`、`reviewer` 和完整
`accepted_review_ids`，再晋级：

```bash
python -m deck_compiler promote --out <build_dir> --ack <review_ack.json>
```

`promote` 会重查 staging、IR、layout、PowerPoint PDF 与 acknowledgement 的哈希；
任一证据过期都拒绝生成 `final.pptx`。

## 6. 完成标准

- PaperWorkflow 证据可追溯，Story 由用户选定的高能力 subagent 生成。
- pwf2rpa strict 0 warning，RPA 三个规划门禁通过。
- canonical truth count = 1，new adapter count = 0。
- Deck Compiler 预检与结构 QA 为 0 FAIL。
- staging 已在 PowerPoint UI 中逐页目检；图号—图注—素材一致，科学图面尺寸过门禁。
- PowerPoint native PDF 页数一致并与同一 staging 哈希绑定。
- 所有 REVIEW 均有 artifact-bound acknowledgement。
- `state.json.phase=final`，最终只交付 `final.pptx`。

旧 SlideDSL、`deckplan2slide.py`、`design_land.py`、artifact sidecar、PPTX sidecar 和
旧 pipeline wrapper 已在 M5 删除，不再兼容或维护。
