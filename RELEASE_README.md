# Total-pipe v2 release preparation bundle

This directory is a source snapshot for release preparation. It contains the complete v2 toolchain without local Git metadata, caches, paper inputs, generated OCR/output directories, virtual environments, or credential-bearing configuration.

## Contents

- `Total-pipe/`: canonical Deck IR, deterministic Deck Compiler v2, schemas, pwf2rpa, skills, tests, examples, documentation, and benchmarks.
- `Total-pipe/docs/officecli-backend.zh-CN.md`: OfficeCLI backend protocol and agent invocation. The cloned OfficeCLI source in the sibling workspace is not bundled as an executable in this release snapshot.
- `PaperWorkflow/`: PDF/Markdown evidence extraction source, integrations, and tests.
- `research-ppt-assistant/`: scientific content normalization, slide planning, layout library, preflight, and visual-quality source.
- `acceptance/Test3/`: release acceptance report, canonical Deck IR, Story/RPA plan, baseline final PPTX, revised `final_msyh.pptx` with 微软雅黑, the PowerPoint-polished `final_msyh_decorated.pptx` variant, PowerPoint native PDF, unified QA, metrics, state, and review acknowledgement.

## Security and privacy preparation

- `PaperWorkflow/config.yaml` was intentionally excluded because it contains a configured MinerU credential.
- `PaperWorkflow/iconfig.yaml` was not copied verbatim. `config.example.yaml` is generated from it with API keys, tokens, passwords, and secrets cleared.
- `.env*`, `.git/`, `node_modules/`, virtual environments, `INput/`, OCR caches, logs, and workflow output directories are excluded.
- The acceptance source paper is not included. Its SHA-256 remains recorded in `acceptance/Test3/acceptance_report.md` for reproducibility.

## Acceptance status

- Deck Compiler: 25 tests passed
- pwf2rpa: 68 tests passed
- Research PPT Assistant: 289 tests passed
- Final deck: 9 slides, 0 FAIL
- Revised deck typography: all 139 editable text script checks use 微软雅黑; output is `acceptance/Test3/build/final_msyh.pptx`
- Presentation-ready variant: `acceptance/Test3/build/final_msyh_decorated.pptx` keeps the same content and typography; slides 2, 8, and 9 replace the previous lower-half decoration with low-contrast evidence containers for parameter interpretation, extrapolation boundaries, and the conclusion loop. The canonical `final_msyh.pptx` remains unchanged as the rollback baseline.
- Visual review: the revised containers use the existing left alignment, a subtle `#F4F8FA` fill with `#D6E4EA` outline, evenly spaced `➢` evidence bullets, 21 pt headings, 18 pt body text, and 微软雅黑 throughout. Their bottom edge stays above the evidence footer, with no overlap with the existing metric rows.
- Reusable text flow: RPA now emits `text_flow.mode = distributed_arrow_list` and prioritizes `structured_text / distributed_list_panel` for eligible 3–5 point prose. Deck Compiler supports `text_flow: auto|plain|distributed_arrow_list`, renders equal-height `➢` rows inside a low-contrast rectangle, and records the decision in `adaptation_log`.
- Documentation audit: RPA and Total-pipe README/USAGE now match the current CLI, status contracts, RPA-to-Deck-IR text-flow handoff, M5 boundary, Test3 paths, and release directory layout.
- Package integrity: 0 findings
- Layout geometry: 0 findings and 0 warnings
- PowerPoint native rendering: the baseline acceptance PDF was reviewed page by page; the revised slides 2, 8, and 9 were re-rendered to PDF and checked for bounds and collisions.
- M5 cleanup: legacy SlideDSL, adapter, sidecar telemetry, wrapper, and Team orchestration paths removed

## Release preparation checklist

1. Review repository names, package versions, author metadata, and licensing in each component.
2. Decide whether the three source directories will ship together or as separate repositories/packages.
3. Update platform-specific setup instructions for the intended release target.
4. Run the test commands in `Total-pipe/README.md` on a clean machine.
5. Recreate a local `PaperWorkflow/config.yaml` from `config.example.yaml`; never commit credentials.
6. Review `SHA256SUMS` after any release-preparation edit and regenerate it before publishing.

## Canonical entry points

- Pipeline skill: `Total-pipe/skills/total-pipe-deck/SKILL.md`
- Compiler CLI: `python -m deck_compiler`
- Deck IR schema: `Total-pipe/schemas/deck-ir.schema.json`
- QA schema: `Total-pipe/schemas/qa-report.schema.json`
- PaperWorkflow: `PaperWorkflow/README.md`
- Research PPT Assistant: `research-ppt-assistant/README.md`

## OfficeCLI single-backend development

Deck Compiler now uses OfficeCLI as its only PPTX writer. `build --officecli <executable>`
checks OfficeCLI 1.0.152+ and the required PPTX schema, uses an atomic batch, validates the
candidate and byte-identical staging PPTX, incorporates `view issues` into unified QA, and
keeps PowerPoint native review as the release gate.
Agent instructions and the batch protocol are in
`Total-pipe/docs/officecli-backend.zh-CN.md`.

The compiler suite passes with local Windows fonts substituted for the macOS paths in the
sample IR (38 tests). A live OfficeCLI 1.0.152 build produced a structurally valid PPTX on
Windows with zero FAIL; PowerPoint native validation remains pending for that smoke build.
