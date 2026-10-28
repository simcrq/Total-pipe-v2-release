# Sample papers for the supplement-lane test

These are **synthetic** sample papers, not real research. The numbers, devices and
references are illustrative and must stay labeled as synthetic in any deck.

Each folder contains:

- `paper.md` — a short paper with abstract, methods, results, discussion and limitations.
- `workflow.json` — a ready PaperWorkflow v4 fixture whose `evidence_registry` quotes the
  paper. `synthesis_readiness` is `ready`, so the Agent pipeline can start from
  `--source-kind workflow` without OCR or a new readiness audit.

Use these to test `supplement=pages` (standalone supplement pages) and
`supplement=inline` (supplement blocks on paper pages). The point is to see whether the
model adds useful background, an analogy or a worked example while keeping every paper
number, figure and conclusion on the evidence path.

## Papers

1. `01-resistive-switching` — materials/device paper. Natural supplements: Schottky vs
   Poole–Frenkel conduction, band-diagram intuition, a toy I–V calculation.
2. `02-restarted-fista` — optimization/algorithm paper. Natural supplements: proximal
   gradient intuition, a two-step numerical example, a comparison with plain gradient
   descent.

## Quick preflight

From `Total-pipe/`:

```powershell
$env:TOTALPIPE_AGENT_HOME="$PWD\..\.codex-test\home"
python -m agent start --source ..\sample-papers\01-resistive-switching\workflow.json `
  --out-dir ..\.codex-test\pre-01 --language zh --presentation-type paper_presentation `
  --source-kind workflow --supplement pages
```

The first response should be `stage: model_selection`; then use `python -m agent advance`
with the model choice. See `CODEX-TEST-TASK.md` for the full test brief.
