# Quick Start: Generate Research Presentations with AI

This is the **essential guide** for AI agents (Claude Code, etc.) to generate research presentations using Total-pipe v3.

## TL;DR

**What it does**: Converts research paper PDFs into PowerPoint presentations with proper evidence citations, scientific figures, and professional layouts.

**Current status**: ✅ Functional with guidance. Text overflow auto-repair enabled (reduces 89% overflow rate by 75-85%).

**Time required**: 5-15 minutes per paper (depends on paper length and model speed).

---

## Installation (One-Time Setup)

```bash
cd Total-pipe

# Install Python dependencies
pip install --user lxml torch pdfplumber Pillow pdfminer.six

# Verify installation
python -c "import lxml, torch, PIL; print('✓ Ready')"

# Run tests
python -m unittest discover -s tests -v
# Expected: Ran 59 tests in ~5s - OK (skipped=2)
```

---

## The 5-Minute Version

### Option A: Start from Deck IR (Recommended for Testing)

If you already have a canonical `deck_ir.json`:

```bash
cd Total-pipe

# Compile and build PPTX
python -m deck_compiler build \
  --ir /absolute/path/to/deck_ir.json \
  --out /absolute/path/to/build \
  --layout-provider v26 \
  --skip-native

# Check result
cat /absolute/path/to/build/qa_report.json | grep -E "(status|FAIL|WARNING)"

# View PPTX
open /absolute/path/to/build/candidate.pptx  # macOS
start /absolute/path/to/build/candidate.pptx  # Windows
```

**Success criteria**:
- `status: "REVIEW"` or `"PASS"` (not `"FAIL"`)
- 0 FAIL items
- Fewer than 4 WARNING items (overflow auto-repair should handle most)

### Option B: Full Pipeline (From Paper PDF)

**Warning**: Complex 6-stage workflow. Follow [`AI_USAGE_GUIDE.md`](./AI_USAGE_GUIDE.md) for complete instructions.

---

## Most Common Issues & Quick Fixes

### Issue 1: `ASSET_INVALID` - Can't find image files

**Fix**: Use absolute paths in deck_ir.json:

```json
{
  "assets": {
    "fig1": {
      "path": "/absolute/path/to/figure1.jpg",
      "source_figure": "1"
    }
  }
}
```

### Issue 2: `FONT_UNAVAILABLE` - Can't find font

**Fix**: Update deck_ir.json with correct font paths for your platform:

**Windows**:
```json
{
  "theme": {
    "font_family": "Arial",
    "font_file": "C:/Windows/Fonts/arial.ttf",
    "bold_font_file": "C:/Windows/Fonts/arialbd.ttf"
  }
}
```

**macOS**:
```json
{
  "theme": {
    "font_family": "Arial",
    "font_file": "/System/Library/Fonts/Supplemental/Arial.ttf",
    "bold_font_file": "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
  }
}
```

### Issue 3: Many text overflow warnings

**Status**: ✅ Auto-repair enabled by default

The system now automatically:
1. Detects overflow >25%
2. Splits content to continuation slides
3. Recompiles with fresh layouts

**Verification**:
```bash
# Should see this in QA report
cat build/qa_report.json | grep "OVERFLOW_REPAIR_APPLIED"
```

If overflow persists:
- Open actual PPTX in PowerPoint to verify (OfficeCLI detection is unreliable)
- Consider reducing content density or adding more slides

---

## Essential Files

### Input (Deck IR)

Minimal valid `deck_ir.json`:

```json
{
  "schema_version": "2.0",
  "deck_id": "my-presentation",
  "theme": {
    "font_family": "Arial",
    "font_file": "C:/Windows/Fonts/arial.ttf",
    "bold_font_file": "C:/Windows/Fonts/arialbd.ttf",
    "foreground": "#142735",
    "background": "#FFFFFF",
    "accent": "#137C8B"
  },
  "assets": {},
  "slides": [
    {
      "id": "slide1",
      "semantic": {
        "title": "My Research Finding",
        "purpose": "Present main result",
        "takeaway": "We discovered X using method Y.",
        "evidence_refs": [],
        "caveats": [],
        "speaker_notes": ""
      },
      "composition": {
        "archetype": "evidence-hypothesis",
        "blocks": [
          {
            "id": "b1",
            "component": "direct-evidence",
            "text": "Observation: We measured A and found B."
          },
          {
            "id": "b2",
            "component": "hypothesis",
            "text": "This suggests mechanism C may be involved."
          }
        ],
        "figure_refs": []
      },
      "presentation": {}
    }
  ]
}
```

### Output Files

After successful build in `build/`:

- `candidate.pptx` - Generated PowerPoint (for inspection)
- `staging.pptx` - Byte-identical copy (for formal review)
- `qa_report.json` - Validation results ⭐ **Check this first**
- `layout.json` - Compiled layout with text contracts
- `metrics.json` - Compilation statistics
- `state.json` - Build lifecycle state

---

## Decision Tree: When to Use Each Archetype

Choose the right slide layout:

### `cover-hero`
**Use for**: Title slide  
**Contains**: 2 text blocks + 1 figure (right side)  
**Example**: Paper title + author + hero image

### `figure-parameters`
**Use for**: Method with diagram  
**Contains**: 3-4 parameter blocks + 1 figure (left side)  
**Example**: Experimental setup, model parameters

### `process-flow`
**Use for**: Multi-step process  
**Contains**: 4 steps + small diagram  
**Auto-numbered**: ① → ② → ③ → ④ with vertical connector  
**Example**: Method → Processing → Analysis → Result

### `evidence-hypothesis`
**Use for**: Observation + interpretation  
**Contains**: Up to 8 text blocks  
**Example**: What we saw + what it means

### `three-limitations` / `three-conclusions`
**Use for**: Summary slides  
**Contains**: 3 labeled blocks in columns  
**Example**: Scope, Boundary, Uncertainty

---

## MCP Tools (If Using via Claude Code)

### Quick Build
```json
{
  "tool": "totalpipe_build",
  "params": {
    "ir": "/absolute/path/to/deck_ir.json",
    "out": "/absolute/path/to/build",
    "layout_provider": "v26",
    "officecli": "officecli"
  }
}
```

Returns:
```json
{
  "status": "REVIEW",
  "counts": {"FAIL": 0, "WARNING": 2, "REVIEW": 1, "INFO": 3},
  "report": "/path/to/build/qa_report.json",
  "candidate": "/path/to/build/candidate.pptx"
}
```

---

## Success Checklist

A good presentation has:

- [ ] **0 FAIL** in QA report
- [ ] **< 4 WARNING** (preferably 0 text overflow)
- [ ] **All content visible** in PowerPoint
- [ ] **Figures readable** (≥220px smallest dimension)
- [ ] **Consistent fonts** (no wild size variations)
- [ ] **Evidence cited** (all references present)
- [ ] **Clear narrative** (question → answer → next)

---

## When Things Go Wrong

### ❌ Compilation fails with `FAIL` status
1. Read QA report: `cat build/qa_report.json | grep -A5 FAIL`
2. Check rule ID (ASSET_INVALID, FONT_UNAVAILABLE, etc.)
3. See [`AI_USAGE_GUIDE.md`](./AI_USAGE_GUIDE.md) → "Error Recovery Decision Tree"

### ❌ Too many overflow warnings (>10)
1. Check if auto-repair ran: `grep OVERFLOW_REPAIR build/qa_report.json`
2. If not, check why (insufficient overflow ratio? disabled?)
3. If yes but still failing, content may be too dense
4. Solution: Reduce content per slide or add more slides

### ❌ Presentation looks bad in PowerPoint
1. Font too small? Check `layout.json` for actual font sizes
2. Text cut off? Check actual slide in PowerPoint (OfficeCLI warnings unreliable)
3. Figures too small? Check asset resolution and `source_figure` matching
4. Colors wrong? Verify theme in deck_ir.json

---

## Where to Get Help

**Start here**:
1. [`AI_USAGE_GUIDE.md`](./AI_USAGE_GUIDE.md) - Comprehensive guide
2. [`FIXES_SUMMARY.md`](./FIXES_SUMMARY.md) - What's been fixed
3. `build/qa_report.json` - Structured validation results

**Read next**:
- `Total-pipe/docs/USAGE.zh-CN.md` - Full Chinese guide
- `Total-pipe/docs/deck-compiler-v2.md` - Technical specs
- `Total-pipe/README.md` - Overview

**Examples**:
- `Total-pipe/examples/research.deck_ir.json` - Minimal example
- `builds/graphene-v26/` - Real build artifacts

**Problem analysis**:
- `CONTENT_CAPACITY_ANALYSIS.md` - Deep dive on overflow issue
- `IMPLEMENTATION_SUMMARY.md` - How auto-repair works

---

## Known Limitations

⚠️ **Complex workflow** - Full pipeline requires 6 stages across 3 projects  
⚠️ **Manual verification** - Must open PowerPoint to check final quality  
⚠️ **Asset management** - Images must be organized correctly  
⚠️ **Font discovery** - Must provide correct paths per platform  
⚠️ **No preview** - Can't see slides without PowerPoint (except via OfficeCLI screenshots)

But: **All have workarounds documented in `AI_USAGE_GUIDE.md`**

---

## Next Steps

1. **Test installation**: Run tests to verify setup
2. **Try example**: Compile `examples/research.deck_ir.json`
3. **Check output**: Review generated `qa_report.json`
4. **Read full guide**: [`AI_USAGE_GUIDE.md`](./AI_USAGE_GUIDE.md) for complete workflow

---

**Version**: v3.2 with overflow auto-repair  
**Status**: ✅ Ready for AI-assisted generation  
**Last Updated**: 2026-10-07
