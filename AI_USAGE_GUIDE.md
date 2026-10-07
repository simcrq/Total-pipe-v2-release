# AI Usage Guide: Total-pipe v3 PPT Generation Suite

## Quick Start for AI Agents

This guide helps Claude Code and other AI agents generate usable, visually appealing research presentations from papers.

## Current System Status

✅ **Working**: Core pipeline, all 59 tests passing  
⚠️ **Partially Fixed**: Text overflow (auto-repair implemented)  
❌ **Known Issues**: Asset path handling, font portability, complex workflow

## Prerequisites

```bash
# 1. Install Python dependencies
cd Total-pipe
pip install --user -r requirements-v26.txt

# 2. Verify installation
python -c "import lxml, torch, PIL; print('✓ All dependencies installed')"

# 3. Check OfficeCLI availability (optional for testing)
officecli --version || echo "OfficeCLI not in PATH"

# 4. Run tests
python -m unittest discover -s tests -v
```

## Pipeline Overview

```
PDF Paper → PaperWorkflow → Story Planner → pwf2rpa → RPA → Deck IR → Compiler → PPTX
   ↓            ↓               ↓              ↓       ↓       ↓          ↓
Evidence    Questions      Slide Ideas    Slide    Canon   Layout   Final PPT
Registry    + Answers                     Briefs    IR
```

**Total stages**: 6  
**Total projects**: 3 (Total-pipe, research-ppt-assistant, PaperWorkflow)  
**Estimated time**: 5-15 minutes per paper

## Known Issues & Workarounds

### Issue 1: Text Overflow (89% of slides) ⚠️ PARTIALLY FIXED

**Problem**: Generated slides have text that doesn't fit, cutting off content.

**Root Cause**: v26 layout model underestimates vertical space requirements.

**Solution Implemented**: Automatic overflow repair in `deck_compiler/overflow_repair.py`
- Detects overflow >25% of available space
- Automatically splits content to continuation slides
- Recompiles with fresh layouts
- Expected reduction: 75-85% fewer overflows

**Status**: Code complete, all tests passing. Enabled by default in compilation.

**Verification**:
```bash
# Check QA report for overflow warnings
cat build/qa_report.json | grep "text overflow"

# Should see OVERFLOW_REPAIR_APPLIED info message if repair triggered
cat build/qa_report.json | grep "OVERFLOW_REPAIR"
```

### Issue 2: Missing Asset Files ❌ MANUAL FIX REQUIRED

**Problem**: Deck IR references images in `images/` directory that must exist relative to deck_ir.json location.

**Workaround**:
```python
# When creating Deck IR, use absolute paths for assets
"assets": {
    "fig1": {
        "path": "/absolute/path/to/figure1.jpg",  # Not "images/fig1.jpg"
        "source_figure": "1"
    }
}
```

Or ensure images directory structure:
```
build/
  deck_ir.json
  images/
    [hash].jpg
    [hash].jpg
```

### Issue 3: Font Path Portability ❌ MANUAL FIX REQUIRED

**Problem**: Example Deck IRs use macOS font paths (`/System/Library/Fonts/...`).

**Workaround** - Use platform-appropriate paths:

**Windows**:
```json
"theme": {
    "font_family": "Arial",
    "font_file": "C:/Windows/Fonts/arial.ttf",
    "bold_font_file": "C:/Windows/Fonts/arialbd.ttf"
}
```

**macOS**:
```json
"theme": {
    "font_family": "Arial",
    "font_file": "/System/Library/Fonts/Supplemental/Arial.ttf",
    "bold_font_file": "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
}
```

**Linux**:
```json
"theme": {
    "font_family": "Liberation Sans",
    "font_file": "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "bold_font_file": "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"
}
```

### Issue 4: Complex Multi-Tool Workflow ⚠️ GUIDANCE PROVIDED

**Problem**: No single entry point - agent must orchestrate 6 stages across 3 projects.

**Current Workaround** - Follow this exact sequence:

#### Stage 1: Extract Evidence (PaperWorkflow)
```bash
cd PaperWorkflow
# User must provide topic-specific queries before first run
python workflow.py paper.pdf --queries '["What is the main finding?", "What methods were used?"]' --out workflow.json

# Check synthesis_readiness gates
cat workflow.json | grep synthesis_readiness
# All 6 gates must be "ready", not "review" or "blocked"
```

#### Stage 2: Generate Story (Subagent)
```bash
cd Total-pipe/pwf2rpa

# Step 2a: Generate story prompt
python -m pwf2rpa ../../PaperWorkflow/workflow.json \
  --make-story-prompt story_prompt.json \
  --story-model "claude-opus-4" \
  --story-reasoning high \
  --model-selected-by-user

# Step 2b: User must select model explicitly
# Then spawn Story Planner subagent with that model
# Subagent reads story_prompt.json and generates story_plan.json
```

**Story Schema** (for subagent):
```json
{
  "nodes": [
    {
      "question": "Research question",
      "answer": "One-sentence takeaway",
      "key_points": ["Detail 1", "Detail 2", "Detail 3"],  // Optional
      "evidence": ["EV0001", "EV0002"],
      "next": "Next question"
    }
  ],
  "planner": {
    "mode": "subagent",
    "model": "<user-selected-model>",
    "reasoning_effort": "high",
    "selected_by_user": true
  }
}
```

#### Stage 3: Convert to RPA Input
```bash
cd Total-pipe/pwf2rpa

python -m pwf2rpa ../../PaperWorkflow/workflow.json \
  --story story_plan.json \
  --story-model "claude-opus-4" \
  --story-reasoning high \
  --model-selected-by-user \
  --strict \
  --out rpa_input.json
```

**Optional**: Add design intent for 4-step processes:
```bash
# First create design_intent.json
python -m pwf2rpa ../../PaperWorkflow/workflow.json \
  --story story_plan.json \
  --design-intent design_intent.json \
  --story-model "claude-opus-4" \
  --story-reasoning high \
  --model-selected-by-user \
  --strict \
  --out rpa_input.json
```

#### Stage 4: RPA Planning
```bash
cd ../../../research-ppt-assistant

# Step 4a: Normalize content
node server/cli.mjs normalize-content \
  --file ../Total-pipe/pwf2rpa/rpa_input.json \
  --detail-level full > normalized_content.json

# Must return status: "valid"

# Step 4b: Create deck plan
node server/cli.mjs plan \
  --file plan-input.json \  # Contains presentation_type, slide_count
  --detail-level full > deck_plan.json

# Must return pipeline_status: "plan_complete"

# Step 4c: Validate plan
node server/cli.mjs validate-deck \
  --file validation_input.json \  # { slides: [...], content_model: {...} }
  --detail-level compact

# Must return status: "valid"
# No KEY_POINTS_LOST or SOURCE_TEXT_NOT_BOUND errors
```

#### Stage 5: Create Canonical Deck IR
```python
# Manual mapping from RPA deck_plan.json to deck_ir.json
# Follow schema: Total-pipe/schemas/deck-ir.schema.json
# Key mappings:
# - RPA title/goal/takeaway → semantic.*
# - RPA layout → composition.archetype
# - RPA slots → composition.blocks[].component
# - RPA visual_topology → composition.visual_intent
```

#### Stage 6: Compile and Build
```bash
cd Total-pipe

# Compile only (no PPTX generation)
python -m deck_compiler compile \
  --ir /absolute/path/to/deck_ir.json \
  --out /absolute/path/to/build \
  --layout-provider v26

# Full build (with PPTX)
python -m deck_compiler build \
  --ir /absolute/path/to/deck_ir.json \
  --out /absolute/path/to/build \
  --layout-provider v26 \
  --officecli officecli \
  --skip-native

# Check QA report
cat /absolute/path/to/build/qa_report.json | python -m json.tool
```

## Error Recovery Decision Tree

### Error: `synthesis_readiness` = review/blocked
**Stage**: PaperWorkflow  
**Action**: Add missing evidence
- Check which gate failed
- Add supplementary PDFs via `supplementary_paths`
- Merge supplementary OCR/Markdown into analysis input
- Set `supplementary_content_included=true`
- Rerun PaperWorkflow

### Error: Unknown evidence ID
**Stage**: pwf2rpa  
**Action**: Regenerate Story
- Evidence ID in Story doesn't exist in workflow
- Return to Story Planner subagent
- Provide correct evidence registry
- Regenerate story_plan.json

### Error: KEY_POINTS_LOST
**Stage**: RPA validate-deck  
**Action**: Revise RPA plan
- Compare `deck_plan.json` slides with `normalized_content.json`
- Restore missing key_points to slide content
- Do NOT use compressed slot text from compact output
- Rerun `validate-deck` with original content model

### Error: SPLIT_REQUIRED
**Stage**: Deck compiler  
**Action**: Reduce content or split slide
- Content doesn't fit in available layout
- Option A: Return to Story, split question into 2 nodes
- Option B: Return to RPA, add more slides
- Option C: Enable overflow repair (now default)

### Error: ASSET_INVALID
**Stage**: Deck compiler geometric preflight  
**Action**: Fix asset paths
- Check asset path is absolute or relative to deck_ir.json
- Verify image file exists at that path
- Ensure image is valid JPG/PNG
- Update deck_ir.json assets section

### Error: FONT_UNAVAILABLE
**Stage**: Deck compiler geometric preflight  
**Action**: Fix font paths
- Check theme.font_file points to existing file
- Use platform-appropriate path (see Issue 3)
- Verify font file is valid TrueType/OpenType
- Test with: `python -c "from PIL import ImageFont; ImageFont.truetype('path/to/font.ttf', 24)"`

### Warning: text overflow (many)
**Stage**: OfficeCLI post-generation  
**Action**: Review and verify
- Check if overflow_repair was applied
- Inspect actual PPTX in PowerPoint
- OfficeCLI detection is "unreliable" per docs
- If real overflow: reduce content density or add slides
- If false positive: accept and promote

## Visual Design Guidelines

### Slide Archetypes

**Use `cover-hero`** for:
- Title slide
- 2 blocks + 1 figure (right side)

**Use `figure-parameters`** for:
- Method description with diagram
- 3-4 parameters + 1 figure (left side)
- Ordered steps beside figure

**Use `process-flow`** for:
- 4-step process without main figure
- Method → process-step → result flow
- Auto-numbered with vertical connectors

**Use `evidence-hypothesis`** for:
- Observation + interpretation
- Up to 8 text blocks
- No figures

**Use `three-limitations`** or `three-conclusions`** for:
- Summary slides
- 3 labeled blocks
- Equal-height columns

### Typography Rules

**Titles**: Start at 32pt, floor 28pt  
**Takeaways**: Start at 24pt, floor 20pt  
**Body text**: Start at 28pt, floor 24pt  
**Max lines**: 10 per text box (hard limit)

**Line height**: 1.2× font size (fixed, no auto-adjustment)

### Color Palette

**Foreground**: Dark blue-gray `#142735` to `#162B3A`  
**Background**: White `#FFFFFF` (no off-white)  
**Accent**: Teal `#137C8B` or blue `#3B6DFF`  
**Panel fill**: Very light gray-blue `#F1F6F7`  
**Panel line**: Light gray `#C8D9DD`

Use accent color sparingly - only for emphasis or key metrics.

### Spacing & Rhythm

**Peer blocks** (figure-parameters): 24px vertical gap (enforced by compiler)  
**Figure-caption**: 12px gap  
**Slide margins**: Defined by frame variant (default or spacious)  
**Text insets**: 8-12px inside shapes

### Scientific Figures

**Minimum size**: 220px (smallest dimension)  
**Panel labels**: Must be readable at presentation scale  
**Caption format**: Must mention `Fig.Xe` matching `source_figure`  
**Aspect ratio**: Always preserved (no stretching)

### Best Practices

1. **One main point per slide** - don't cram multiple findings
2. **Key points over paragraphs** - use `key_points` array for clarity
3. **Evidence visible** - cite evidence IDs, link to figures
4. **Progression clear** - use `next` field to show narrative flow
5. **Visual hierarchy** - title → takeaway → details → evidence

## MCP Tools Reference

When using Total-pipe via MCP server:

### pwf2rpa_story_prompt
```json
{
  "workflow_path": "/path/to/workflow.json",
  "model": "claude-opus-4",
  "reasoning_effort": "high",
  "selected_by_user": true,
  "out_path": "/path/to/story_prompt.json"  // Optional
}
```
Returns: `{ "status": "success", "prompt_path": "...", "evidence_count": N }`

### pwf2rpa_check
```json
{
  "workflow_path": "/path/to/workflow.json",
  "story_path": "/path/to/story_plan.json",
  "design_intent_path": "/path/to/design_intent.json",  // Optional
  "model": "claude-opus-4",
  "reasoning_effort": "high",
  "selected_by_user": true
}
```
Returns: Capacity check results (warnings if content too long)

### pwf2rpa_convert
```json
{
  "workflow_path": "/path/to/workflow.json",
  "story_path": "/path/to/story_plan.json",
  "design_intent_path": "/path/to/design_intent.json",  // Optional
  "model": "claude-opus-4",
  "reasoning_effort": "high",
  "selected_by_user": true,
  "out_path": "/path/to/rpa_input.json"
}
```
Returns: `{ "status": "success", "output_path": "...", "slide_count": N }`

### totalpipe_compile
```json
{
  "ir": "/absolute/path/to/deck_ir.json",
  "out": "/absolute/path/to/build",
  "layout_provider": "v26"  // or "deterministic"
}
```
Returns: QA report summary (status, counts, report path)

### totalpipe_build
```json
{
  "ir": "/absolute/path/to/deck_ir.json",
  "out": "/absolute/path/to/build",
  "layout_provider": "v26",
  "officecli": "officecli"  // or absolute path
}
```
Returns: QA report + candidate PPTX path

### totalpipe_review
```json
{
  "out": "/absolute/path/to/build",
  "officecli": "officecli"
}
```
Returns: Issue count, slide screenshots generated

## Common Pitfalls

### ❌ Don't: Skip Story Planner hard gate
Story generation must use:
1. User-selected model (not agent's default choice)
2. Subagent mode (not inline generation)
3. At least `high` reasoning
4. Explicit `selected_by_user: true` flag

### ❌ Don't: Mix Story languages
If Story nodes are English, all should be English. Mixing triggers wrong ending title.

### ❌ Don't: Use relative paths in MCP calls
All `ir` and `out` paths must be absolute for MCP tools.

### ❌ Don't: Skip RPA validation
Always run `validate-deck` before creating Deck IR. Catching errors early saves full pipeline rework.

### ❌ Don't: Modify compact RPA output
RPA compact output has truncated slot text. Always use original `normalized_content.json` as truth.

### ❌ Don't: Trust OfficeCLI overflow alone
Docs say it's "unreliable". Always verify in actual PowerPoint or via screenshots.

### ❌ Don't: Edit candidate.pptx
`candidate.pptx` is for inspection only. Edits are not tracked and will be lost on rebuild.

### ❌ Don't: Skip PowerPoint native review
For formal delivery, must:
1. Open `staging.pptx` in PowerPoint
2. Eye-check every slide
3. Record review: `record-powerpoint-review`
4. Export PDF: `native.pdf`
5. Validate: `validate-native`
6. Acknowledge reviews and promote to `final.pptx`

## Success Metrics

A usable, visually appealing presentation has:

✅ **0 FAIL** items in QA report  
✅ **< 4 WARNING** items (preferably 0 text overflow)  
✅ **All REVIEW items acknowledged** (scientific panels, etc.)  
✅ **All content visible** in PowerPoint (no cut-off text)  
✅ **Consistent font sizes** (no wild 18pt-32pt jumps)  
✅ **Figures readable** (panels ≥220px, labels clear)  
✅ **Evidence cited** (all EV#### IDs present)  
✅ **Narrative coherent** (question → answer → next flow makes sense)  
✅ **Visually balanced** (not too dense, not too sparse)

## Next Steps for Improvement

**Phase 1 (Urgent)**:
- [ ] Single-function entry point: `generate_presentation(pdf_path)`
- [ ] Structured error messages with suggested fixes
- [ ] Preview generation without PowerPoint
- [ ] Asset path auto-resolution

**Phase 2 (Important)**:
- [ ] Decision tree for design intent
- [ ] Model selection guidance (cost vs quality)
- [ ] Progress indicators for long operations
- [ ] Visual quality scoring in QA

**Phase 3 (Nice-to-have)**:
- [ ] Interactive refinement (edit one slide, rebuild)
- [ ] A/B layout comparison
- [ ] Accessibility checks (contrast, font size)
- [ ] Multi-language support

## Getting Help

**Read these first**:
1. `Total-pipe/docs/USAGE.zh-CN.md` - Full Chinese usage guide
2. `Total-pipe/docs/deck-compiler-v2.md` - Compiler contracts
3. `Total-pipe/pwf2rpa/README.md` - Story conversion details
4. `CONTENT_CAPACITY_ANALYSIS.md` - Overflow problem deep-dive

**Check these for errors**:
- `build/qa_report.json` - Structured validation results
- `build/metrics.json` - Compilation stats
- `build/layout_provider.json` - Per-slide layout source

**Examples**:
- `Total-pipe/examples/research.deck_ir.json` - Minimal deck IR
- `builds/graphene-v26/` - Real build artifacts (partial)

## Summary

Total-pipe v3 is a sophisticated, multi-stage pipeline for generating evidence-based scientific presentations. It's **functional and architecturally sound**, but requires careful orchestration and has several known issues:

**Strengths**:
- ✅ Provenance tracking (evidence → slides)
- ✅ Scientific rigor (validation at every stage)
- ✅ Comprehensive QA reporting
- ✅ Automatic overflow repair (NEW)

**Challenges**:
- ⚠️ Complex 6-stage workflow
- ⚠️ Poor error recovery
- ⚠️ Manual asset/font path management
- ⚠️ No preview without PowerPoint

**For AI agents**: Follow this guide carefully. The system works but is unforgiving of shortcuts. When in doubt, regenerate from an earlier stage rather than trying to patch intermediate outputs.
