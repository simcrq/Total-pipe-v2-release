# Codex test brief: Supplement Lane end-to-end

## Role

You are testing a feature branch of Total-pipe. Run the real Agent pipeline on the two
synthetic sample papers in `sample-papers/`, exercise the new supplement lane, inspect the
QA output and report what worked and what did not.

## Hard rules

- Do **not** modify product code, schemas, docs or tests. Do not commit, merge or push.
- Write every job, prompt, IR, build and report under `codex-test/` (inside the repo).
- The sample papers are synthetic. Keep that label in any report; never present their
  numbers as real literature.
- Paper facts must stay on `EV####`: never put a paper number, paper figure or long
  verbatim evidence passage into a supplement block.
- If a stage is blocked, report the exact `code`/`next_action` instead of inventing a
  workaround.
- The base pipeline is capacity-strict before the supplement lane is reached: keep each
  Story `answer` short (roughly ≤ 45 Chinese characters), and omit `key_points` unless a
  number must be visibly carried. Large `key_points` can make RPA return
  `CAPACITY_EXCEEDED` before any IR exists. If a Story submission is rejected twice, start
  a fresh job with a leaner Story instead of trying to extend the exhausted retry budget.

## Environment

- Repo: `F:\Workbuddy\Total-pipe-v2-release`
- Python entrypoint: run `python -m agent ...` from `F:\Workbuddy\Total-pipe-v2-release\Total-pipe`.
- Node / RPA and OfficeCLI are installed; OfficeCLI is on PATH.
- Use `$env:PYTHONUTF8="1"` and per-test `$env:TOTALPIPE_AGENT_HOME` under `codex-test/home`.
- The model selected by the user for this test is **`gpt-6-luna`**, reasoning **`max`**.
  Record that exact selection in `story_plan.json.planner`; do not choose a cheaper model.
- Read `Total-pipe/skills/total-pipe-deck/SKILL.md` before authoring Story, IR or Design.
  The Agent's `next_action` files contain the complete prompt/schema for each stage.

## Test matrix

### Test A — `01-resistive-switching`, `supplement=pages`

Start:

```powershell
python -m agent start `
  --source ..\sample-papers\01-resistive-switching\workflow.json `
  --out-dir ..\codex-test\A-resistive `
  --language zh --presentation-type paper_presentation `
  --source-kind workflow --supplement pages `
  --requirements "面向研究生方法讲解：先补必要背景，再加一个简化算例；论文事实必须保留证据。"
```

Then advance model selection with:

```json
{"model":"gpt-6-luna","reasoning_effort":"max","selected_by_user":true}
```

Requirements for this deck:

- 5–6 paper Story nodes; every node cites `EV####`; `planner.mode=subagent`.
- At least **2 standalone supplement pages**:
  1. a prerequisite/background page (e.g. Schottky vs Poole–Frenkel conduction or a
     band-diagram intuition);
  2. a worked example or analogy page.
- At least **1 supplement block on a paper page** (mixed page).
- Supplement blocks: `basis=supplement`, `supplement.kind/source/constructed`; no
  `evidence_refs`. A constructed example must visibly say 示意/构造/简化/示例 and must not
  reuse a paper value.
- The mixed page must keep non-empty `semantic.evidence_refs` on its paper block.
- If useful, give a supplement page `semantic.explanation` with `basis=supplement`
  obligations and no `evidence_refs`.
- Keep every paper number/unit in a paper block with its EV. The deck is Chinese; preserve
  `10^2`, `10^4 s`, `0.18 ± 0.02 eV`, `2.8 ± 0.2 V` exactly.

### Test B — `02-restarted-fista`, `supplement=inline`

Start with `--supplement inline` and a fresh output dir:

```powershell
python -m agent start `
  --source ..\sample-papers\02-restarted-fista\workflow.json `
  --out-dir ..\codex-test\B-fista `
  --language zh --presentation-type paper_presentation `
  --source-kind workflow --supplement inline `
  --requirements "面向研究生方法讲解：补 proximal gradient 直觉和一个小数值例子；论文结论和数字必须保留证据。"
```

Requirements:

- 5–6 paper Story nodes, every node cites EV; `planner` as above.
- **No standalone supplement pages** (`inline` must reject them). Add at least **2
  supplement blocks on existing paper pages**:
  1. a short background/intuition block (e.g. why soft-thresholding is the proximal step);
  2. a constructed two-step numeric example (label it 示意, choose numbers not used by the
     paper, keep it in a supplement block).
- Paper blocks keep their EV; mixed pages keep non-empty `semantic.evidence_refs`.
- If the IR accidentally contains a standalone supplement page, the stage must fail with
  `SUPPLEMENT_PAGE_NOT_ENABLED`; record that in the report if you test the negative case,
  otherwise remove the page and continue.

## Pipeline steps in both tests

1. `agent start` → expect `stage: model_selection`.
2. `agent advance --job-id ... --inputs <model.json>`.
3. `story_prompt` → read `work/story_prompt.json`; write `work/story_plan.json`;
   `advance --artifact-kind story_plan --artifact-path work/story_plan.json`.
4. RPA component runs automatically. Read `work/ir_prompt.json`; write
   `work/deck_ir.json`; `advance --artifact-kind deck_ir`.
5. Design stage: read `work/visual_prompt.json`; write `work/visual_proposal.json`;
   `advance --artifact-kind visual_proposal`.
6. Build stage: `agent advance --job-id ...`; OfficeCLI writes the PPTX. If it fails,
   keep the QA/log and report the exact code.
7. Inspect `build/qa_report.json`, `build/layout_feedback.json` and
   `build/derived/explanation_coverage.json`. Count supplement pages/blocks from the IR.
8. Optional: open or inspect the PPTX with OfficeCLI (`officecli` on PATH) and confirm the
   supplement pages exist; do not claim visual quality beyond what you actually checked.

## Report

Write `codex-test/REPORT.md` with:

- environment (commit `bcaf33d` or current HEAD, model, OfficeCLI version);
- one row per test: status (`candidate` / `blocked`), deck path, page count, supplement
  page/block count, QA `FAIL/REVIEW/INFO` counts, explanation coverage summary;
- what supplement content the model actually added (2–4 bullets per deck);
- every blocked stage with its exact code/message;
- whether any paper number/figure leaked into a supplement block;
- a short verdict: does the supplement lane produce a more complete explanation without
  weakening paper evidence?

If a test cannot complete, report how far it got and why. Do not summarize a blocked test
as a success.
