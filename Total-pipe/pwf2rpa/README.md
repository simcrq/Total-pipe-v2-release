# pwf2rpa — PaperWorkflow v4 → Research PPT Assistant bridge

Converts a PaperWorkflow v4 `workflow.json` into the content-model input that
RPA's `normalize_content` and `create_deck_plan` consume.

Standard library only, Python 3.10+, deterministic validation and conversion.

The recommended path now inserts an evidence-grounded Story Planner before
slide briefs. The Story itself must be produced by a high-capability subagent
using a model explicitly selected by the user; pwf2rpa builds the prompt,
validates provenance and evidence references, then maps the reasoning chain to
RPA planning units.

```bash
python3 pwf_to_rpa.py workflow.json \
  --make-story-prompt story_prompt.json \
  --story-model <user-selected-model> \
  --story-reasoning high \
  --model-selected-by-user
# Delegate story_prompt.json to that model as a subagent and save its JSON as story_plan.json.
python3 pwf_to_rpa.py workflow.json --story story_plan.json --out rpa_input.json
cd ../../research-ppt-assistant
node server/cli.mjs normalize-content --file ../Total-pipe/pwf2rpa/rpa_input.json
# 将规范化内容与 `"presentation_type": "group_meeting"` 一并写入 plan-input.json。
# 使用 --file 时，业务参数必须位于该 JSON 中；命令行上的同名参数不会合并进去。
node server/cli.mjs plan --file plan-input.json --detail-level full
```

## What it does, and what it deliberately doesn't

RPA already understands PaperWorkflow: given `paperworkflow_v4`, its own
`adaptWorkflow` derives every Source, Citation and Evidence record. Re-deriving
them here would add nothing and drift the moment RPA changes.

So the adapter passes the workflow through **untouched**. Its recommended mode
validates a compact Story and converts it into the one thing RPA cannot infer —
`slide_briefs`:

```json
{ "paperworkflow_v4": { ...verbatim... }, "slide_briefs": [ ... ] }
```

## Story Planning is a hard intermediate gate

The full path is:

```text
PaperWorkflow Evidence
  -> high-capability Story subagent
  -> story_plan.json
  -> pwf2rpa validation/mapping
  -> slide_briefs
  -> RPA Slide Planning
```

Before creating the Story prompt, the orchestrator must ask the user which
currently available high-capability model to use. The main agent may not select
silently or write the Story itself. The output records:

```json
{
  "planner": {
    "mode": "subagent",
    "model": "<exact user choice>",
    "reasoning_effort": "high",
    "selected_by_user": true
  },
  "core_question": "...",
  "main_message": "...",
  "story": [
    {"question": "...", "answer": "...", "evidence": ["EV0001"], "next": "..."}
  ],
  "ending": {"takeaway": "...", "limitation": "..."}
}
```

Five to eight nodes are required. A node is a scientific reasoning step, not a
Figure and not necessarily one final slide. `allow_auto_split` remains enabled
for reasoning nodes so the downstream planner retains page-count authority.
The full machine-readable contract is in `schemas/story-plan.schema.json`.

The validator blocks when the model was not user-selected, execution was not a
subagent, reasoning is below `high`, an Evidence id does not resolve, or `next`
degenerates into a sequential transition such as “接下来作者介绍 Fig.4”. It also
warns when a hedged source appears to have been rewritten as a certain causal
claim; strict mode can promote that warning to failure.

## The four hard constraints

These are enforced because each one has bitten a real run.

| # | Rule | If violated | Severity |
|---|------|-------------|----------|
| 1 | `evidence_ids` must resolve to real `EV####` | `normalize_content` fails: *"does not resolve to Evidence"* | **error** — blocks |
| 2 | `category_hint` must be one of 40 real category ids | RPA silently relaxes to whole-library search, picks a mismatched layout | warning |
| 3 | Text must fit the category's slots | `SLOT_CAPACITY_EXCEEDED` | warning |
| 4 | Output must be reproducible | caches and diffs become meaningless | enforced by design |

**Errors block and write nothing** — RPA would reject the input anyway.
**Warnings are reported but still produce a file**, because RPA *does* produce a
deck in those cases, just a degraded one. Use `--strict` to make warnings fatal
in CI.

## Rule 3 is a simulation, not a guess

`fit.py` replays both of RPA's capacity gates offline against a table extracted
from RPA's own layout library (`capacity.py`, all 320 layouts):

- **retriever gate** — title chars, total text chars, image/table/chart counts,
  process steps, and the minimum display width each `visual_type` needs;
- **slot-binding gate** — text poured into slots in RPA's real order
  (priority desc, then reading order), with the same affinity rules.

This turns *"RPA picked a weird layout"* into an actionable message:

```
[WARNING][CAPACITY_EXCEEDED] briefs[0]: no layout in category 'cover' can hold
this page: goal is 35 chars but the subtitle slot holds 23
```

Capacity limits come from the committed RPA layout library. Regenerate them
whenever that library changes; do not rely on historical sample counts or
hard-coded boundary anecdotes in operational decisions.

### Deck-level contention

RPA never reuses a layout inside one deck — `createDeckPlan` feeds used ids
back as `exclude_ids`. Six short pages all asking for `figure_text` will push
the last ones off the category even though each fits in isolation. Since this
is a bipartite matching problem, not a counting one, the adapter solves it as
one (`crowded_pages`), which avoids false alarms.

### Known limits of the simulation

- RPA assigns layouts **greedily by score**, so it can strand a page even when
  a perfect matching exists. The adapter under-warns in that case (2/72 above).
  This is the safe direction: RPA still plans and warns itself.
- Slot ids and Chinese labels also contribute to binding affinity; ignoring
  them can only make the simulation *more* conservative, never falsely optimistic.
- The table reflects the `projector` viewing profile, RPA's default.

## Usage

### As a CLI

```bash
python3 pwf_to_rpa.py workflow.json --story story_plan.json --out rpa_input.json
python3 pwf_to_rpa.py workflow.json --briefs briefs.json --out rpa_input.json
python3 pwf_to_rpa.py workflow.json --out rpa_input.json   # fallback deck
python3 pwf_to_rpa.py --list-categories                    # the 40 legal ids
python3 pwf_to_rpa.py workflow.json --briefs b.json --strict   # CI mode
```

Exit codes: `0` ok · `2` blocking problem (nothing written) · `3` `--strict` and warnings.

### As a library

```python
from pwf2rpa import Workflow, convert, load_story, write_output

workflow = Workflow.from_path("workflow.json")
workflow.validate()
payload, warnings = convert(workflow, story=load_story("story_plan.json"))
write_output(payload, "rpa_input.json")
```

### Without `--story` or `--briefs`

This is a compatibility fallback, not a compliant full Total-pipe run.
Evidence is grouped by `query_ids` (PaperWorkflow's retrieval intents), each
intent mapped to a fitting category, and claims compressed to fit the slots.
Every evidence entry stays cited. The result plans cleanly — it is a starting
point to edit, not a talk.

## Brief spec format

Only `title` is required.

```json
{
  "category_hint": "figure_text",
  "title": "等双轴拉伸使 K1 光学声子快速软化",
  "claims": ["εA=0.205 时 K1 模显著下移", "εA=0.212 时 K1 模变为虚频"],
  "takeaway": "声子与能量扫描给出一致阈值。",
  "evidence_ids": ["EV0014", "EV0021"],
  "visuals": [{"visual_type": "dense_plot", "panel_count": 1,
               "has_embedded_text": true, "caption": "图 1：面内声子"}]
}
```

`text_chars`, `title_chars`, `image_count` and `process_step_count` are derived
from the actual content — a hand-written value that contradicts the content
would only make RPA shop for the wrong layout.

Unknown fields are reported rather than dropped silently, since a misspelled
key means the author's intent was lost.

## Maintenance

When RPA's layout library changes, regenerate the table:

```bash
python3 pwf_to_rpa.py --refresh-capacity /path/to/research-ppt-assistant
python3 -m unittest discover -s tests
```

This asks RPA's own readability module for the numbers rather than
reimplementing its typography maths, so the table cannot drift silently.
Verified to reproduce the committed table exactly.

## Layout

```
pwf_to_rpa.py         CLI entry point
pwf2rpa/
  workflow.py         indexed read-only view of workflow.json
  briefs.py           spec -> SLIDE_BRIEF, enforces the four rules
  fit.py              offline replay of RPA's two capacity gates
  fallback.py         deterministic briefs when none are supplied
  story.py            Story prompt, provenance/evidence validation, brief mapping
  convert.py          payload assembly and deterministic writing
  capacity.py         generated: 320 layouts x capacity envelope
  refresh.py          regenerates capacity.py from an RPA checkout
  errors.py           Problem records with severity
schemas/story-plan.schema.json  Story Planner interchange contract
tests/test_adapter.py           bridge regression tests
tests/test_story.py             Story/subagent hard-gate tests
```

## Tests

```bash
python3 -m unittest discover -s tests -v
```

Hermetic — they build their own miniature workflow rather than depending on
the archived graphene sample.
