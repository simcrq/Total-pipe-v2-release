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

首轮运行前先按论文主题写检索 `queries`，有定制问题时省略
`include_default_queries` 即只用定制问题；需要混用通用问题才显式设为 `true`。
主文提到补充材料而文件名无法自动配对时，在 PaperWorkflow 调用中传
`supplementary_paths` 的实际 PDF/Markdown 路径。此配对只证明来源在本地，
补充材料门禁仍为 `review`。先将其 OCR/Markdown 内容合并到分析输入，再设置
`supplementary_content_included=true`；不能只因文件存在就宣称完整证据审查通过。
分别检查 `quality_audit` 与 `synthesis_readiness` 六项门禁：前者表示 OCR/文本捕获，
不能用 `quality_audit.ready` 代替科学综合的 `synthesis_readiness.ready`。

## 2. Story Planner 硬门禁

拿到 `workflow.json` 后，必须先问用户选择当前可用的高能力模型。不得默认选择，
不得由主代理自行写 Story。用户选择后，用该模型的独立 subagent，reasoning 至少
`high`，生成 5–8 个节点的 `story_plan.json`。

先调用 `pwf2rpa_story_prompt` 生成证据约束的提示包。未传 `out_path` 时，工具在
`workflow.json` 旁写出 `workflow.story_prompt.json`；也可用绝对路径 `out_path`
指定本次输出目录。工具始终只返回小回执；子代理须读取
该文件中的完整 `instructions`、`evidence_store` 和 `output_shape`。调用时原样传入
用户选定的 `model`、`reasoning_effort` 与 `selected_by_user=true`。若当前 MCP
服务调用超时，则在 `pwf2rpa` 目录直接运行同一确定性生成器：

```bash
python -m pwf2rpa <workflow.json> \
  --make-story-prompt <story_prompt.json> \
  --story-model <用户选择> --story-reasoning <用户选择的强度> \
  --model-selected-by-user
```

提示包生成不调用模型；模型只在独立 Story Planner 子代理中使用。生成器代码位于本
工作区的 `pwf2rpa`，插件 MCP 若已启动，需重启该服务才能读取新的工具 schema。

每个节点保留以下四个必需字段：

```json
{"question":"...","answer":"...","evidence":["EV0001"],"next":"..."}
```

仅在一句 `answer` 会丢失必须保留的连续内容时，可选加 `key_points` 字符串数组；
不要求每个节点都有，也不限制条数。`answer` 是摘要，`key_points` 是要传给 RPA 的细节。

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
  --file <rpa_input.json> --detail-level full > <normalized_content.json>
node research-ppt-assistant/server/cli.mjs plan --file <rpa_input.json> \
  --presentation-type group_meeting --slide-count <N> --detail-level standard > <deck_plan.json>
node research-ppt-assistant/server/cli.mjs validate-deck --file <validation_input.json> \
  --detail-level compact
```

门禁分别要求 `normalize-content status=valid`、`pipeline_status=plan_complete`、
`plan status=success/adapted` 且 `unplanned_slide_briefs` 为空，以及
`validate-deck status=valid`。`adapted` 时逐条检查 `adaptation_log`，正文、
`key_points`、结论和限制不得出现 `truncate_text`。RPA 负责科学页面规划与视觉意图，
不输出最终 bbox。
`validation_input.json` 必须包含本轮计划的 `slides` 和未被修订覆盖的
`normalized_content.json`（作为 `content_model`）。`KEY_POINTS_LOST` 是错误，
需要恢复原文及顺序，不能通过修改或删去源 `content_model` 来消除。MCP 精简返回
会保留完整 `slides[].key_points`，但其摘要、截短的 slot 文本和设计意图不能代替
`rpa_input.json` 或完整的内容模型。每次 RPA 修订都从这些原始文件重新核对。
转换后先核对整套 Brief 标题的展示语言。pwf2rpa 会根据 Story 主体语言生成默认
结尾标题：英文 Story 用 `Conclusions and scope`，中文 Story 用 `结论与边界`；
`title_chars` 自动按实际标题计算。若语言仍不符合演示要求，先修订 Story 并重跑转换，
不要只手改 `rpa_input.json` 的标题而留下旧字符数。

`SOURCE_TEXT_NOT_BOUND` 表示原始 `body` 或要点未完整进入 Slot Binding，是硬错误。
总结页仍须使用 summary 版式；容量不足时应保持 `needs_replan`，由 Story/RPA
拆页或调整内容结构，不能回退到 literature 等错误类别来凑齐页数。
`max_chars` 与总 `text_chars` 只是按码点计算的粗筛，不区分英文单词、字宽和真实
换行。RPA 会按槽宽、字号及中英文字符宽度估计换行并报告 `SLOT_WRAP_RISK`；
该估计也不能代替实际渲染检查。`ROLE_MISMATCH` 只比较版式展示角色，
不把 Evidence 的 `primary_claim / primary_evidence` 当作版式角色。

长多段正文应在 Slide Brief 中保留为 `key_points` / `secondary_messages`，或在
`body` 中保留明确换行。`evidence_texts` 保持为原始证据，不自动充当正文。
RPA 的 Design Compiler 会在无主视觉、显示长度合适时输出
`design_ir.text_flow.mode=distributed_arrow_list`，并优先选择
`structured_text / distributed_list_panel`。Story Planner 不决定该版式。

## 4. Canonical Deck IR

把通过的 Story/RPA 规划映射到 `schemas/deck-ir.schema.json`。Deck IR 分为：

- `semantic`：title、purpose、takeaway、evidence_refs、caveats、speaker_notes。
- `composition`：archetype、blocks、figure_refs。
- `presentation`：theme tokens 与稳定组件变体。

整套先选择同一 frame：可在 Deck IR 顶层写 `presentation.frame_variant` 为 `default`
或 `spacious`。若省略，只要某页请求 spacious，编译器整套采用 spacious；不要让短中文
内容触发逐页随意切换。将 RPA 的同级步骤按阅读顺序放入 `figure-parameters` 的 3–4 个
blocks，并配一张 figure；这一 archetype 与顺序就是轻量的节奏契约，不需要模型写 bbox。
v26 会将组内间距校正为 24 px，容量允许时等高；若文字较长则保持等距并分配足够高度。
图注置于图像下方 12 px，所有校正后重新执行容量与碰撞检查。实际 frame 与逐页
`MODEL_PROPOSAL / PACKING_FALLBACK / COMPILER_FALLBACK` 在 `layout.json`、
`layout_provider.json` 和 `derived/plan_to_layout.json` 中查看。

从 RPA 映射到 Deck IR 时，保留这些段落边界，并把
`design_ir.text_flow.mode` 复制到对应 block 的 `text_flow`。block 也可使用 `auto`：
编译器只把 3–5 个明确段落、总显示长度不少于 72 单位且单段不超过 120 单位的正文
排为浅色矩形容器中的等高 `➢` 条目（汉字按 2 单位计）。单个长段落、公式、表格、
图注和参考文献保持原样；用 `plain` 禁止转换，用 `distributed_arrow_list` 显式请求。
实际触发结果写入编译后 slide 的 `adaptation_log`。

映射前逐条核对 `rpa_input.json` 中的 `key_points`。对应科学内容必须按原顺序
进入 Deck IR 的 `composition.blocks[].text` 或 `semantic.speaker_notes`，不能只留下
`takeaway`、缩写后的 slot 文本或 `design_ir.message.secondary`。如果一页容量不足，
拆页并保留全部细节；改写科学内容需先明确修订 Story/Brief，再重新运行 RPA。

禁止在 IR 中写最终 `x/y/w/h`。首代目录只使用 `deck_compiler/catalog.py` 中的稳定
archetype/component；内容超出容量时由编译器返回 `SPLIT_REQUIRED`，再回 Story/RPA
拆页。不得无限缩字号。

## 5. Agent 直接调用 v3

在本实验目录运行；MCP 入口为 `deck_compiler/mcp_server.py`，配置见根目录 `.mcp.json`。
该服务复用 pwf2rpa 协议和原有工具，同时新增：

- `totalpipe_compile(ir, out, layout_provider="v26")`：编译布局，默认 v26；返回布局与 QA，不生成 PPTX。
- `totalpipe_build(ir, out, layout_provider="v26", officecli="officecli")`：通过 OfficeCLI 生成 PPTX 候选和 QA。
- `totalpipe_review(out, officecli="officecli")`：按需检查现有构建并导出逐页截图、schema 与 issues。

`ir` 和 `out` 使用绝对路径。默认使用 v26；模型不支持或候选不通过时由现有布局逻辑回退，详情见 `layout_provider.json`。模型只提议 bbox，不改写科研内容。

MCP 未加载时，使用 `.mcp.json` 中的 Python，工作目录为本项目根目录：

```powershell
python -m deck_compiler build --ir <absolute-deck_ir.json> --out <absolute-build-dir> --layout-provider v26 --officecli <officecli-path> --skip-native
```

一般生成任务完成于候选 PPTX 与 QA；返回 artifact 路径、FAIL/WARNING/REVIEW 和模型回退情况。FAIL 必须处理；不能把候选称作 final。不要默认反复渲染或制作额外验收报告。

用户要求正式 final 时，再按 `docs/deck-compiler-v2.md` 中原有原生验收与 promote 流程执行。OfficeCLI 截图不伪装为 PowerPoint UI 眼检。自动 issues 保留，不因截图观感而清零。

OfficeCLI `view issues` 的 `Text overflow` 判断不准确，可能误报或漏报。看到此项时
保留原始 issue，并查看实际 PPTX 页面或按需用 `totalpipe_review` 定位；正式验收
仍以 PowerPoint 逐页眼检为准。不要为了消除该提示而压缩、删改 `key_points`。
确认真实溢出后调整布局或拆页，再重新生成和检查。
