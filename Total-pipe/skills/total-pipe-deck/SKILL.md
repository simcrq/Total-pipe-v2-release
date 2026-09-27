---
name: total-pipe-deck
description: 从论文 PDF 到研究汇报 PPTX 的证据—故事—规划—编译—原生验收流水线。保留 PaperWorkflow、Story Planner、pwf2rpa 与 RPA 的科研职责，Deck IR 之后统一进入 Deck Compiler v3。
---

# Total-pipe Deck Compiler v3

主链固定为：

```text
PDF → PaperWorkflow → Story Planner subagent → pwf2rpa → RPA planning
    → canonical deck_ir.json → v26 layout proposals + compiler fallback → OfficeCLI
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

## 5. Agent 直接调用 v3

在本实验目录运行；MCP 入口为 `deck_compiler/mcp_server.py`，配置见根目录 `.mcp.json`。
该服务复用 pwf2rpa 协议和原有工具，同时新增：

- `totalpipe_compile(ir, out, layout_provider="v26")`：IR → layout + QA，不渲染。
- `totalpipe_build(ir, out, layout_provider="v26", officecli="officecli")`：IR → OfficeCLI → PPTX 候选及 QA。
- `totalpipe_review(out, officecli="officecli")`：需要看图时才导出逐页原生 PNG、schema 与 issues。

`ir` 和 `out` 使用绝对路径。默认使用 v26；模型不支持或候选不通过时由现有布局逻辑回退，详情见 `layout_provider.json`。模型只提议 bbox，不改写科研内容。

MCP 未加载时，使用 `.mcp.json` 中的 Python，工作目录为本项目根目录：

```powershell
python -m deck_compiler build --ir <absolute-deck_ir.json> --out <absolute-build-dir> --layout-provider v26 --officecli <officecli-path> --skip-native
```

一般生成任务完成于候选 PPTX 与 QA；返回 artifact 路径、FAIL/WARNING/REVIEW 和模型回退情况。FAIL 必须处理；不能把候选称作 final。不要默认反复渲染或制作额外验收报告。

用户要求正式 final 时，再按 `docs/deck-compiler-v2.md` 中原有原生验收与 promote 流程执行。OfficeCLI 截图不伪装为 PowerPoint UI 眼检。自动 issues 保留，不因截图观感而清零。
