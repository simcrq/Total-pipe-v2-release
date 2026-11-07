# Codex lean-Story retry: Supplement Lane

## Model roles

- Driver / main Codex model: **`gpt-6-luna`**, reasoning **`max`**. Keep this for the run.
- Story Planner artifact: **`gpt-6.1-sol`**, reasoning **`high`**. Every Story submission and
  every `--inputs` model-selection file must use these exact values:
  `{"model":"gpt-6.1-sol","reasoning_effort":"high","selected_by_user":true}`.
  Do not let the pipeline generate a Story prompt with `gpt-6-luna`; select the Story model
  first, then read the generated `story_prompt.json`.
- Do not modify product code, schemas, docs, tests or git state. Write only under
  `codex-test/lean-*` and `codex-test/home-lean`.

## Why lean

The previous run never reached IR: RPA rejects pages whose `key_points` exceed category
slots, and two failed Story submissions exhaust the job's replan budget. This retry uses a
5-node, no-`key_points`, short-answer Story. If a job still hits `CAPACITY_EXCEEDED`,
report it and start a **fresh job** with shorter answers; do not burn the second attempt on
the same wording.

## Test A — `01-resistive-switching`, `supplement=pages`

Start:

```powershell
$env:PYTHONUTF8="1"
$env:TOTALPIPE_AGENT_HOME="F:\Workbuddy\Total-pipe-v2-release\codex-test\home-lean\A"
python -m agent start `
  --source ..\sample-papers\01-resistive-switching\workflow.json `
  --out-dir ..\codex-test\lean-A --language zh --presentation-type paper_presentation `
  --source-kind workflow --supplement pages `
  --requirements "面向研究生方法讲解：先补必要背景，再加一个构造算例；论文事实必须保留证据。"
```

Select the Story model:

```json
{"model":"gpt-6.1-sol","reasoning_effort":"high","selected_by_user":true}
```

Use this exact lean Story skeleton (you may polish wording, but keep the 5 nodes,
`answer` ≤ 45 Chinese characters, no `key_points`, and the EV assignments):

```json
{
  "planner": {"mode": "subagent", "model": "gpt-6.1-sol", "reasoning_effort": "high", "selected_by_user": true},
  "core_question": "这项界面器件研究用什么证据支持其开关结论？",
  "main_message": "界面 TiOx 层给出可测开关，但机制仍有歧义。",
  "story": [
    {"question": "界面结构给出了什么证据？", "answer": "截面 TEM 显示 3.5 nm 连续 TiOx 界面层。", "evidence": ["EV0006"], "next": "界面层已确认；电形成后是否出现可区分的电阻态？"},
    {"question": "电形成后电阻态如何变化？", "answer": "形成电压 2.8±0.2 V，阻态约 1.2×10^5→9.8×10^2 Ω。", "evidence": ["EV0001"], "next": "阻态差异已观察到；读出条件下能保持多久？"},
    {"question": "读出与循环稳定性如何？", "answer": "85 °C、0.1 V 下 ON/OFF>10^2 保持 10^4 s；500 次循环降幅≤12%。", "evidence": ["EV0002","EV0005"], "next": "稳定性已量化；哪些证据支持陷阱辅助传导？"},
    {"question": "导电机制证据是什么？", "answer": "300–400 K I–V 符合 Poole–Frenkel，活化能 0.18±0.02 eV。", "evidence": ["EV0003","EV0004","EV0007","EV0009"], "next": "机制仍有歧义；结论的适用范围是什么？"},
    {"question": "结论边界是什么？", "answer": "仅 n 型 Si、100 µm 结；未测 CMOS 与高频。", "evidence": ["EV0008"]}
  ],
  "ending": {"takeaway": "陷阱辅助解释相符，机制未唯一确定。", "limitation": "仅 n 型 Si、100 µm 结。"}
}
```

Every node should carry `explain` with `"must_show": []` and a short
`"prose_ok_reason"`; this keeps RPA out of narrow structural slots. Do not add
`key_points` or `form`.

After RPA, add supplement content to the IR:

- 2 standalone supplement pages:
  1. “先修：Schottky 与 Poole–Frenkel” — 2 blocks, `cover-hero`, `basis=supplement`,
     `kind=background`, source “标准固体物理教材”.
  2. “示意算例：势垒随电场下降” — `constructed: true`, visible 示意 label, a formula and
     1–2 short blocks; do not reuse a paper value or paper figure.
- 1 supplement block on a paper page (e.g. a one-sentence analogy under the mechanism page);
  keep the paper block and its EV on the same page.
- Paper pages keep their RPA evidence and numbers. Supplement pages have
  `semantic.evidence_refs: []`.

## Test B — `02-restarted-fista`, `supplement=inline`

Fresh job and home:

```powershell
$env:TOTALPIPE_AGENT_HOME="F:\Workbuddy\Total-pipe-v2-release\codex-test\home-lean\B"
python -m agent start `
  --source ..\sample-papers\02-restarted-fista\workflow.json `
  --out-dir ..\codex-test\lean-B --language zh --presentation-type paper_presentation `
  --source-kind workflow --supplement inline `
  --requirements "面向研究生方法讲解：补 proximal gradient 直觉和一个构造数值例子；论文数字必须保留证据。"
```

Use the same Story model selection and a 5-node lean Story (no `key_points`):

```json
{
  "planner": {"mode": "subagent", "model": "gpt-6.1-sol", "reasoning_effort": "high", "selected_by_user": true},
  "core_question": "restart 为什么能减少 FISTA 的迭代数？",
  "main_message": "restart 在良性条件下减少迭代，但高相干时收益下降。",
  "story": [
    {"question": "实验条件是什么？", "answer": "高斯矩阵、30 dB 噪声、100 次随机试验。", "evidence": ["EV0004","EV0006"], "next": "条件明确；近端步具体是什么？"},
    {"question": "近端步如何定义？", "answer": "soft-thresholding，步长 1/L，L 为梯度 Lipschitz 常数。", "evidence": ["EV0003"], "next": "单步操作明确；何时重启动量？"},
    {"question": "何时触发 restart？", "answer": "目标函数相对上一迭代上升时重置动量。", "evidence": ["EV0005"], "next": "触发条件明确；迭代收益有多大？"},
    {"question": "恢复结果如何？", "answer": "200 次迭代误差 1.2×10^-3；达 10^-3 少 1.8 倍迭代。", "evidence": ["EV0001","EV0002"], "next": "收益已量化；高相干时是否仍成立？"},
    {"question": "结论边界是什么？", "answer": "仅合成信号；高相干时增益降至 9%。", "evidence": ["EV0008","EV0007","EV0009"]}
  ],
  "ending": {"takeaway": "restart 降低迭代数，但依赖相干性。", "limitation": "仅合成信号。"}
}
```

Add **inline-only** supplement blocks on paper pages (no standalone pages):

- A short “soft-thresholding 直觉” block on the proximal-step page.
- A constructed two-step numeric example on the result page: label 示意, use numbers not
  present in the evidence (e.g. 3, 0.5, 2), no paper value/figure.
- If a standalone supplement page is present, the Agent must reject it with
  `SUPPLEMENT_PAGE_NOT_ENABLED`; do not keep it.

## Pipeline steps

For each test:

1. `agent start` → `model_selection`.
2. Write model JSON for `gpt-6.1-sol` / `high`; `agent advance --inputs`.
3. `story_prompt` → write `work/story_plan.json`; submit with
   `--artifact-kind story_plan --artifact-path work/story_plan.json`.
4. RPA → read `work/ir_prompt.json`; write `work/deck_ir.json` with the supplement
   content; submit.
5. Design → read `work/visual_prompt.json`; write `work/visual_proposal.json`; submit.
6. Build → OfficeCLI; inspect `build/qa_report.json`, `layout_feedback.json`,
   `derived/explanation_coverage.json`.
7. If a stage blocks, record exact code/message and whether a fresh job with a shorter
   Story fixes it. Do not claim success for a blocked job.

## Report

Write `codex-test/LEAN-REPORT.md` with:

- model choices (driver `gpt-6-luna` max; Story `gpt-6.1-sol` high);
- per test: status, candidate path, page count, supplement page/block count, QA counts,
  explanation coverage;
- the exact Story that was accepted (node count, key_points present or not);
- supplement content actually added;
- every blocker and the fresh-job result, if any;
- whether any paper number/figure leaked into a supplement block;
- a clear verdict on whether the lane was actually exercised.

The papers are synthetic; keep that label. Do not modify product code or commit.
