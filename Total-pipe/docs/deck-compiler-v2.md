# Total-pipe Deck Compiler v2

Deck Compiler v2 is the deterministic middle and back end of Total-pipe. PaperWorkflow,
the evidence registry, Story Planner and RPA keep their scientific responsibilities. Their
output crosses one boundary into `deck_ir.json`; after that point no adapter may mutate page
semantics.

```text
Evidence -> Story -> [DesignIntentPlanner] -> RPA -> deck_ir.json
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

Optional [Layout Tree 1.0/1.1/1.2](composite-layouts.md) extends canonical v2 in place. A bounded
`composition.layout_tree.regions.body` recursively compiles columns, stacks, panels and image grids
without changing scientific content or the OfficeCLI protocol. RPA's separate sublayout search and
composition and automatic selection tools emit references only. Version 1.1 adds measured
[native tables](native-tables.md) with merged headers and formula/matrix cells. `layout_feedback.json` is SHA-bound planner feedback,
specified by `schemas/layout-feedback.schema.json`; it supplements the unified QA report.
Flat IR remains supported and tree pages still require deck-wide visual design.
Version 1.2 adds optional [native panel frames and title bands](framed-containers.md). Outline and padding
participate in child measurement; slide presentation.takeaway_frame reserves a measured independent box,
with optional markers and inline math. The compiler checks containment, external collisions and native layer order.

- `schemas/deck-ir.schema.json` separates semantic, composition and presentation data.
  Blocks and figures use component names and asset references. Final bounding boxes are
  compiler output and are rejected in Deck IR.
- `schemas/textbox-contract.schema.json` fixes font, line height, wrapping, autofit, insets,
  line limit, font floor and overflow policy. The compiler inserts measured line breaks;
  OfficeCLI writes the same values into DrawingML through typed properties and a narrow
  `raw-set` for the wrapping flag.
- `schemas/qa-report.schema.json` is the only QA result schema. Every finding identifies its
  detector, evidence source, confidence and diagnosis.

The optional v3.2 DesignIntentPlanner is a topology layer after Story. The current
contract supports one four-point vertical `process` relation with no bbox.
`pwf2rpa --story ... --design-intent ...` sends it as Brief metadata; RPA verifies
the complete group binding and emits `slide.layout_contract`. The mapping to Deck IR uses
the actual block IDs:

```json
"composition": {
  "archetype": "figure-parameters",
  "visual_intent": {
    "relation": "process",
    "members": ["b1", "b2", "b3", "b4"],
    "orientation": "vertical",
    "preserve_order": true,
    "emphasis": "b4"
  },
  "blocks": ["..."],
  "figure_refs": ["..."]
}
```

The example shows the relation fields; `blocks` and `figure_refs` require their
normal full objects. The compiler accepts four unlabeled blocks with members
matching block order exactly: use `figure-parameters` with one figure, or
`process-flow` with no figure. Otherwise
`VISUAL_INTENT_INVALID` blocks compilation. Its existing component-role inference
remains available when no explicit intent is supplied. A hard process group
cannot be split silently; insufficient capacity returns to planning.

| Decision | Owner |
|---|---|
| Scientific content, order and evidence | Story Planner |
| Process relation and optional emphasis | DesignIntentPlanner |
| Layout family/id, slots, capacity and `layout_contract` | RPA |
| Allowed macro geometry proposal | v26 |
| Text fit, equal spacing, connector coordinates and final validity | Deck Compiler |

The initial catalog contains nine research presentation archetypes and seventeen components.
The layout compiler can select one `spacious` variant before returning `SPLIT_REQUIRED`; it
never keeps shrinking below the component font floor.

The v3 integration uses one frame grid across a deck. Top-level
`presentation.frame_variant` selects `default` or `spacious`; if omitted, any slide requesting
`spacious` selects it for the deck. The compiled layout records the actual choice. For a
`figure-parameters` slide, ordered blocks beside a figure share a 24 px vertical rhythm.
The bundled packer proposes macro geometry only. The compiler snaps peer spacing and figure-caption slack, then repeats capacity and
collision checks. `derived/plan_to_layout.json` reports the provider status per slide.
For a four-step, unlabeled `figure-parameters` process whose roles progress from `method`
through `process-step` to `result`, the v3 compiler draws a numbered vertical rail beside
the original blocks and reserves its width during text fitting.

Blocks may set `text_flow` to `plain`, `auto`, or `distributed_arrow_list`. In `auto` mode,
the compiler recognizes three to five explicit prose/list rows (72 or more display units;
CJK characters count as two),
places them in one low-contrast panel as **one text object with one paragraph per row**, and lets
PowerPoint draw the marker: each paragraph carries `a:buChar` + `a:buClr` and a hanging indent, so
Tab changes the level and the bullet menu reflects the style. The deck picks a default marker style —
`presentation.bullet_color` (otherwise `theme.accent`) colours it, `presentation.bullet_style` selects it (`bullet`, `square`,
`open_square`, `diamond`, `arrow`, `check`, `dash`, `large_square`, `large_diamond`, `arrowhead`); the default is derived from the dominant row
semantics (procedure → arrowhead, claims → open square, otherwise large square). The large styles select
native Wingdings glyphs at the prose size, without percentage or point-size scaling. Item spacing is a fraction of
the line height (`0.45`, override with `presentation.list_gap`) rather than the leftover panel height,
and the card hugs the list instead of stretching across the body area; a row may wrap to four lines
before the page is asked to split. It does not split a single
paragraph, tables, code, or formula-like content into invented bullets. The applied choice is
recorded in the slide's `adaptation_log`; an explicit `distributed_arrow_list` request still has to
contain two to six rows and fit the component box above the font floor.

Blocks may override `bullet_style` and `bullet_color` independently; prose color remains unchanged.
Slide `presentation.takeaway_marker: {"style":"diamond","color":"#000000"}` gives the complete takeaway
one native leading marker, including on an inline-math takeaway, with continuation lines aligned to the prose.
Explicit lists need at least 520 × 220 px. `preserve-terms` retains full native list rows, markers and colors;
vertical overflow becomes REVIEW at the 18 pt floor, while strict mode requires replanning or splitting.
It never silently removes explicit bullets. See [native list styles and capacity](native-lists.md).

`examples/distributed-arrow-list.deck_ir.json` is the canonical model/compiler reference.
Models should emit explicit paragraph boundaries or `key_points`; the compiler will not infer
new scientific claims or split prose at punctuation merely to fill space.

### Drawn schematics (`origin: generated`)

A page with no usable paper figure may use a diagram drawn by `tools/make_schematic.py` (flow strip,
trend chart, or a mermaid source rendered through `mermaid-cli` when `mmdc` is installed). The asset
declares `origin: "generated"` and a `generator` string; the compiler then:

- forbids `source_figure` on both the asset and the figure reference (`FIGURE_PROVENANCE_FORBIDDEN`),
  so a drawn diagram can never borrow a paper figure number;
- requires the caption to say 示意图 / schematic / diagram (`SCHEMATIC_CAPTION_REQUIRED`);
- keeps the same size and caption gates, but reports `SCHEMATIC_TOO_SMALL` and `SCHEMATIC_REVIEW`
  instead of `SCIENTIFIC_PANEL_TOO_SMALL` / `SCIENTIFIC_PANEL_REVIEW`;
- writes `schematic.generator` onto the compiled image element, so `layout.json` and the QA report
  distinguish drawn material from evidence.

Schematic pages are laid out as a centred band, not as text-beside-figure: the context lines run
across the top (two short blocks share one row), the diagram is centred across the page width, and the
caption sits under it. A bbox provider cannot express that arrangement, so schematic pages report
`SCHEMATIC_REQUIRES_COMPILER` and stay with the compiler templates.

The spec file and the script are committed next to the PNG, which is what makes the picture
reproducible. `examples/schematic.deck_ir.json` is the reference page.

### Formulas (`component: "formula"`)

A block whose component is `formula` carries a LaTeX-subset expression in `text` instead of prose.
The compiler never typesets it as text:

- IR validation parses it and reports `FORMULA_SYNTAX` with the character offset of the offending
  token (`totalpipe_layout/formula.py`, the only place that knows the grammar);
- the AST is measured at 30/28/26/24 css px and the largest size that fits the box wins; a formula
  that cannot fit at 24 px (18 pt) returns `FORMULA_CAPACITY` rather than shrinking below the floor;
- the writer receives one `a:p` holding `mc:AlternateContent` → `a14:m` → `m:oMathPara` → `m:oMath`, plus an
  `mc:Fallback` run with the Unicode text, so a reader without OMML still sees the formula;
- structural verification rejects a shape without an OMML payload (`FORMULA_MISSING`) and a fallback
  that disagrees with the parsed formula (`FORMULA_FALLBACK_MISMATCH`), or changed roots, powers,
  operands and run properties (`FORMULA_CONTENT_MISMATCH`). Presence of a tag alone is insufficient.

Supported inputs include fractions, `\sqrt{…}` / `\sqrt[3]{…}`, grouped/nested `^` and `_`,
Greek, sums/integrals, `\left` / `\right`, `\exp` / `\log` / `\ln` and common trigonometric
functions, plus `\text` / `\mathrm` / `\mathbf` / `\mathit`. Optional outer `$…$`, `$$…$$`,
`\(…\)` and `\[…\]` are accepted on a **formula block**. Backslashes must be doubled in JSON.
Ordinary prose remains literal by default. Optional [inline math](inline-math.md) enables mixed native
prose/math for explicitly marked blocks, title/takeaway fields and table text cells. It measures atomic
formula widths and per-line baseline extents; the inline_layout line metrics override the base
TextBoxContract's ordinary fixed line spacing. Existing display math is unchanged.
Unknown commands, empty/missing operands and
unclosed groups return `FORMULA_SYNTAX`; `array` and `cases` remain unsupported.

Matrix environments `matrix/pmatrix/bmatrix/Bmatrix/vmatrix/Vmatrix` produce editable
`m:m` → `m:mr` → `m:e` structures, with native delimiters for the selected brackets.
Use `&` between cells and `\\` between rows (double each backslash again in JSON).
Rows must have equal column counts. Blank cells stay blank; no cell is silently padded or dropped.
Fractions, roots, scripts, nested matrices and external transposes retain their structure.
`\quad/\qquad` insert explicit space between parallel expressions. Matrix metrics use measured
cell widths, per-column maxima, row baselines and delimiter allowance, with native spacing REVIEW.
See [Office matrix structure](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.math.matrix?view=openxml-3.0.1).

Dense derivations may use `archetype: "equation-derivation"`. There is no two-equation count
limit or a global sum-of-heights percentage: actual column regions must fit every complete group
at the font floor. Ordinary context block limits still apply. The compiler tries shared formula
sizes of 30/28/26/24 CSS px and one/two columns, splitting only between groups. Explicit anchors
bind preceding explanations and equations in the same column. Consecutive unanchored equations
remain independent rows, preserving all content and allowing a column break.
Explanation boxes keep their measured height; spare space is not stretched between explanation
and equation. `formula_flow` adaptations record columns, font size, reading order, boxes and failed
capacity candidates. A real shortage reports `FORMULA_CAPACITY` with the measured diagnostics.
With `preserve-terms`, over-capacity prose is retained for REVIEW; equation geometry still must fit.
The [4×4 regression deck](../examples/matrix-derivation.deck_ir.json) covers matrix factors,
ten equations on one slide, and cell-local fractions/roots/scripts.

The measurement projection preserves braces around the entire script base and uses mathtext's
math mode (`$…$`), so it measures the typeset expression instead of the length of literal LaTeX.
Native display fractions, radicals and sums also use conservative structural bounds: PowerPoint
may render them taller than mathtext, especially full-size fractions in matrix cells and radicals
around sums. These bounds retain `FORMULA_MEASURE_APPROXIMATE` REVIEW for native inspection.
For example, a stacked `\frac{a}{b}` is narrow; a long source string is not automatically a wide equation.
`MathTextParser` height already includes depth; the compiler does not add the descent twice.
See [Matplotlib mathtext](https://matplotlib.org/stable/api/mathtext_api.html) and
[Office Math paragraph structure](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.math.paragraphproperties?view=openxml-3.0.1).

Measurement uses matplotlib's mathtext, the same offline metric source as the text layout. A formula
that carries CJK inside `\text{}` cannot be measured there, so it is measured heuristically and
reported as `FORMULA_MEASURE_APPROXIMATE` (REVIEW) instead of being silently trusted.

Bbox providers are not allowed to place formulas (`FORMULA_REQUIRES_COMPILER`): a formula's height
comes from the typeset math, not from character advances, so the page stays with the compiler's
templates. `examples/formula.deck_ir.json` is the reference deck. Note that
`officecli view screenshot --render html` shows the fallback text; use `--render native` to see the
typeset formula.

For text-only column slides with at least three blocks, geometric preflight estimates the
visible bottom of the laid-out text rather than treating the full reserved textbox as occupied.
When the empty lower band is at least 160 CSS px and 40% of the body area, it emits
`TEXT_ONLY_LOWER_WHITESPACE` as a slide-specific `WARNING` with measured bounds in
`qa_report.json`; the CLI also includes it in `design_notices` with the slide number. This is a
design notice, not an instruction to invent filler content or a
promotion blocker; PowerPoint visual review remains the final judgment.

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
