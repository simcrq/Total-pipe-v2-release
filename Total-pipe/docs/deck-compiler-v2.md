# Total-pipe Deck Compiler v2

Deck Compiler v2 is the deterministic middle and back end of Total-pipe. PaperWorkflow,
the evidence registry, Story Planner and RPA keep their scientific responsibilities. Their
output crosses one boundary into `deck_ir.json`; after that point no adapter may mutate page
semantics.

```text
Evidence -> Story -> RPA -> deck_ir.json
                           | semantic preflight
                           | deterministic layout + TextBoxContract
                           v
                       candidate.pptx (OfficeCLI)
                           | byte-identical staging copy
                           v
                        staging.pptx
                           | structural telemetry + PowerPoint PDF
                           v
                         qa_report.json
                           | hash-bound review acknowledgement
                           v
                          final.pptx
```

## Contracts

- `schemas/deck-ir.schema.json` separates semantic, composition and presentation data.
  Blocks and figures use component names and asset references. Final bounding boxes are
  compiler output and are rejected in Deck IR.
- `schemas/textbox-contract.schema.json` fixes font, line height, wrapping, autofit, insets,
  line limit, font floor and overflow policy. The compiler inserts measured line breaks;
  OfficeCLI writes the same values into DrawingML through typed properties and a narrow
  `raw-set` for the wrapping flag.
- `schemas/qa-report.schema.json` is the only QA result schema. Every finding identifies its
  detector, evidence source, confidence and diagnosis.

The initial catalog contains nine research presentation archetypes and seventeen components.
The layout compiler can select one `spacious` variant before returning `SPLIT_REQUIRED`; it
never keeps shrinking below the component font floor.

Blocks may set `text_flow` to `plain`, `auto`, or `distributed_arrow_list`. In `auto` mode,
the compiler recognizes three to five explicit prose/list rows (72 or more display units;
CJK characters count as two),
places them in one low-contrast panel, distributes equal-height rows vertically, and prefixes
each row with the outlined `➢` arrowhead. It does not split a single paragraph, tables, code,
or formula-like content into invented bullets. The applied choice is recorded in the slide's
`adaptation_log`; an explicit `distributed_arrow_list` request still has to contain two to six
rows and fit the component box above the font floor.

`examples/distributed-arrow-list.deck_ir.json` is the canonical model/compiler reference.
Models should emit explicit paragraph boundaries or `key_points`; the compiler will not infer
new scientific claims or split prose at punctuation merely to fill space.

## Lifecycle

Each output directory owns exactly one mutable candidate and staging file and one validated
final file. A lock rejects concurrent writers. Promotion rechecks the actual staging bytes and
requires matching IR, layout, structural QA and PowerPoint evidence hashes. `WARNING` does not
block promotion. `REVIEW` requires an acknowledgement tied to the artifact hash. `FAIL` always
blocks promotion.

OfficeCLI is the only PPTX writer. `build --officecli <executable>` checks version 1.0.152+
and the required PPTX schemas, maps compiled 96 dpi CSS px coordinates to OfficeCLI's `px`
dimensions, converts CSS px text sizes to points, atomically runs a JSON batch, and validates
the exported OpenXML. `candidate.pptx` and `staging.pptx` have identical bytes; a separate
read-only verifier checks the actual package.
See [OfficeCLI backend and agent calls](officecli-backend.zh-CN.md) for the full protocol.

```bash
PYTHON=/path/to/python
$PYTHON -m deck_compiler build \
  --ir examples/research.deck_ir.json \
  --out build/deck-v2 \
  --officecli /path/to/officecli

# Inspect every editable slide directly in PowerPoint (Normal or Reading view).
# Preview/PDF inspection does not satisfy this gate. Record the reviewed staging:
$PYTHON -m deck_compiler record-powerpoint-review \
  --out build/deck-v2 \
  --reviewer "reviewer name" \
  --slides all

# Export that same staging from PowerPoint and attach the exact native PDF:
$PYTHON -m deck_compiler validate-native \
  --out build/deck-v2 \
  --pdf build/deck-v2/native.pdf \
  --reviewer "reviewer name"

$PYTHON -m deck_compiler promote --out build/deck-v2
```

`--skip-native` is for compiler development. It deliberately produces a REVIEW and cannot
be promoted. LibreOffice and Keynote results are compatibility signals and cannot satisfy the
PowerPoint golden-render requirement.

## Derived files and ownership

`derived/deck_plan.json`, `visual_manifest.json`, `plan_to_layout.json` and
`qa_expectation.json` are read-only projections carrying the canonical IR hash. They exist for
debugging and legacy consumers; the compiler never reads them back.

M5 removed the legacy rendering and QA translation paths after the Test3 acceptance run.
All production rendering now starts from canonical Deck IR. New page-specific adapters must
not be added; extend the stable archetype/component catalog when a reusable composition is
missing.

## Benchmarking

`deck_compiler.baseline` freezes a reference PPTX and records only facts present in that file.
Unknown historical runtime, call counts and false-positive rates remain `null`. Every v2 build
writes `metrics.json` with rerender count, canonical truth count, adapter count and QA totals.
Measure false-positive rate and repair amplification during reviewed production runs rather
than estimating them from a synthetic fixture.
