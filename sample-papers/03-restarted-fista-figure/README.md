# 03 — restarted FISTA with Figure 1

Synthetic fixture for the full TotalPipe pipeline with **text and a real embedded figure**.
The paper, curves, numbers and Figure 1 are illustrative fixtures, not real measurements.

## Files

- `paper.md` — synthetic paper text with `Figure 1` and a caption.
- `images/figure-1.png` — generated convergence plot (1185×674), clearly titled as synthetic.
- `workflow.json` — accepted PaperWorkflow-style evidence bundle:
  - EV0001–EV0009: text evidence;
  - EV0010: Figure 1 caption evidence;
  - `artifacts.figure_assets_metadata` points at `images/figure-1.png`.

## Full pipeline

```powershell
$env:PYTHONUTF8='1'
$env:TOTALPIPE_AGENT_HOME='<repo>\codex-test\home-subagent-figure'
Set-Location <repo>\Total-pipe
python -m agent start `
  --source ..\sample-papers\03-restarted-fista-figure\workflow.json `
  --out-dir ..\codex-test\subagent-figure `
  --language zh --presentation-type paper_presentation `
  --source-kind workflow --supplement both `
  --requirements "保留论文文字与 Figure 1；页面用文字加真实图片。"
```

Advance through `model_selection` → Story → RPA → Deck IR → Design → Build. In the IR, add a
`figure-parameters` page with:

```json
"assets": {
  "fig1": {
    "path": "<repo>/sample-papers/03-restarted-fista-figure/images/figure-1.png",
    "origin": "paper",
    "source_figure": "1"
  }
},
"figure_refs": [{
  "asset_id": "fig1", "source_figure": "1", "panel_count": 1,
  "caption": "Fig. 1. Synthetic convergence curves for standard and restarted FISTA; fixture data, not real measurements.",
  "alt": "合成收敛曲线"
}]
```

The page must keep EV0010 and at least one paper block. The embedded PNG appears in
`ppt/media/image.png`; the figure page carries `SCIENTIFIC_PANEL_REVIEW` as a REVIEW.
