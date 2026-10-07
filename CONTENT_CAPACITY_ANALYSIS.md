# Content Capacity Problem Analysis

## Problem Statement

The Total-pipe v3 suite successfully generates evidence-based and correctly formatted PPTX presentations, but **fails to correctly place a sufficient amount of content and PPT slides as needed to make research group meeting presentations visually appealing**. The generated presentations have widespread text overflow issues that make them unsuitable for actual use.

## Current State Analysis

### Evidence from graphene-v26 Build

**QA Report Summary:**
- **16 WARNING** issues - all text overflow problems
- **0 FAIL** issues - structure is valid
- **7 REVIEW** issues - scientific panel reviews
- 9 slides generated with content

**Text Overflow Pattern:**
Every single slide (slides 1, 2, 4, 5, 6, 7, 8, 9) has at least one text overflow warning:
- Typical message: `"text overflow: 3 lines at 15.0pt need 56pt, usable 47pt"`
- Body text overflows: `"4 lines at 21.0pt need 105pt, usable 80pt"`
- The layout model (v26) provides bounding boxes that are **too small** for the actual content

### Root Causes

#### 1. **Layout Model (v26) Generates Insufficient Heights**

**Location:** `Total-pipe/deck_compiler/layout_provider.py` and `totalpipe_layout/`

The v26 diffusion model learns layout proposals from training data, but:
- It proposes bounding boxes based on **abstract features** (lines 84-94 in `contracts.py`)
- Features include normalized text length (`len(unit.get('text', ''))/600`) and estimated heights
- The model outputs **normalized coordinates** that are decoded to pixel boxes
- **The capacity estimation in training doesn't match OfficeCLI's actual text rendering**

**Key Issue:** Line 56-66 in `layout_provider.py`:
```python
chosen = min(valid, key=lambda b: quality(request, b)) if valid else teacher(request)
```

The model selects from 32 candidates, but even the "best" candidate frequently produces overflow because:
1. The training objective optimizes for **layout quality metrics**, not content capacity
2. The `check()` function (line 54) validates geometric constraints, not actual text fit
3. Font rendering differences between training estimation and OfficeCLI reality

#### 2. **Conservative Text Fitting with Fixed Font Floors**

**Location:** `Total-pipe/deck_compiler/layout.py:56-66`

```python
def fit_text(text, bbox, contract):
    inner_w = bbox[2] - contract.inset["left"] - contract.inset["right"]
    inner_h = bbox[3] - contract.inset["top"] - contract.inset["bottom"]
    for size in range(int(contract.font_size), int(contract.font_floor) - 1, -1):
        font = ImageFont.truetype(contract.font_file, size)
        lines = break_lines(text, font, inner_w)
        if (len(lines) <= contract.max_lines and len(lines) * size * contract.line_height <= inner_h
                and all(font.getlength(line) <= inner_w for line in lines)):
            return "\n".join(lines), replace(contract, font_size=size)
    raise ValueError("SPLIT_REQUIRED")
```

Problems:
- **Fixed font floor**: Body text tries 28pt → 24pt, then fails with `SPLIT_REQUIRED`
- **Hard max_lines limit**: Default 10 lines, but bboxes are often too short
- **No dynamic height adjustment**: The function shrinks font size but cannot request more vertical space
- The compiler uses PIL/ImageFont for estimation, OfficeCLI uses DrawingML rendering - slight differences accumulate

#### 3. **RPA Planning Doesn't Account for Real Rendering Constraints**

**Location:** `research-ppt-assistant/`

The Research PPT Assistant (RPA) performs content planning with:
- 320 layout templates with slot capacity constraints
- Character count estimation: `text_chars` and `max_chars` per slot
- But these are **code point counts**, not actual rendered width/height

**From README.md line 137-141:**
> RPA 的总 `text_chars` 与槽位 `max_chars` 是码点粗筛，不等于英文单词、字宽或实际换行数。绑定器优先选能完整容纳正文的槽；验收还会用槽宽和字号估计中英文换行，`SLOT_WRAP_RISK` 需要真实页面复核。

The pipeline warns about wrap risk but doesn't prevent overflow.

#### 4. **No Feedback Loop from OfficeCLI to Layout Selection**

The current pipeline is strictly forward:
```
Story → RPA planning → Deck IR → v26 proposals → Compiler → OfficeCLI → QA (warnings only)
```

Once OfficeCLI reports overflow, there's **no mechanism** to:
- Retry with larger bboxes
- Split content across additional slides
- Reduce content density automatically

The overflow warnings are recorded but don't trigger replanning.

## Why This Makes Presentations Unsuitable

1. **Text is cut off**: Content doesn't fully display in PowerPoint
2. **Visual density issues**: Attempting to cram too much into small spaces
3. **Poor readability**: Font sizes shrink to minimum but still overflow
4. **Inconsistent spacing**: Some slides use all available space well, others waste vertical room while overflowing horizontally
5. **Not presentation-ready**: Requires manual intervention to fix every slide

## Quantitative Impact

**graphene-v26 build:**
- 16 text overflow warnings across 8 of 9 slides (89% of content slides)
- Slide 8 used PACKING_FALLBACK (0 valid v26 candidates), yet still has 2 overflows
- Average: 1.78 overflow warnings per slide

This is a **systematic failure**, not isolated edge cases.

---

## Proposed Solutions

### Solution 1: Enhanced Layout Model with Capacity-Aware Training ⭐ **RECOMMENDED**

**Modify the v26 training objective to penalize text overflow:**

1. **Add capacity loss term** during training:
   - For each proposal, estimate actual text fit using the same PIL font metrics
   - Penalize candidates where `required_height > proposed_height`
   - Weight this loss higher than aesthetic layout quality

2. **Post-selection validation**:
   ```python
   # In layout_provider.py after line 56
   chosen = min(valid, key=lambda b: quality(request, b)) if valid else teacher(request)
   
   # NEW: Verify capacity and inflate if needed
   chosen = ensure_capacity(request, chosen)
   ```

3. **Capacity inflation function**:
   ```python
   def ensure_capacity(request, boxes):
       """Inflate bboxes to fit content, maintaining relative positions."""
       for unit, box in zip(request['units'], boxes):
           if unit['role'] != 'figure':
               req_h = required_height(unit, box[2], request)
               if req_h > box[3]:
                   scale = req_h / box[3]
                   box[3] = req_h  # Increase height
                   # Cascade: shift boxes below this one down
       return boxes
   ```

**Pros:**
- Addresses root cause
- Works for all content types
- Maintains learned layout aesthetics

**Cons:**
- Requires model retraining
- May reduce layout variety if capacity dominates
- More complex implementation

---

### Solution 2: Dynamic Content Splitting and Slide Addition ⭐ **MOST PRACTICAL**

**Add a post-compilation repair stage that automatically splits overflowing content:**

1. **Detection**: Parse OfficeCLI overflow warnings
2. **Decision**: When overflow exceeds threshold (e.g., >20% of bbox height)
3. **Action**: 
   - Split the overflowing text block into N parts
   - Clone the slide N times
   - Redistribute content across new slides
   - Preserve figures and other elements

**Implementation:**

```python
# New module: deck_compiler/overflow_repair.py

def repair_overflow(ir, layout, qa_report, base_path):
    """Split slides with severe text overflow into multiple slides."""
    overflows = [item for item in qa_report['items'] 
                 if item['severity'] == 'WARNING' and 'text overflow' in item['message']]
    
    slides_to_split = defaultdict(list)
    for overflow in overflows:
        slide_num = overflow['slide']
        shape_id = extract_shape_id(overflow['shape'])
        # Parse: "4 lines at 21.0pt need 105pt, usable 80pt"
        needed, usable = parse_overflow_message(overflow['message'])
        if (needed - usable) / usable > 0.20:  # >20% overflow
            slides_to_split[slide_num].append({
                'shape_id': shape_id,
                'needed': needed,
                'usable': usable,
                'overflow_ratio': (needed - usable) / usable
            })
    
    if not slides_to_split:
        return ir, layout, qa_report  # No severe overflow
    
    new_ir = copy.deepcopy(ir)
    for slide_num, overflows in slides_to_split.items():
        original_slide = ir['slides'][slide_num - 1]
        
        # Find the most overflowing text block
        worst = max(overflows, key=lambda x: x['overflow_ratio'])
        block_id = worst['shape_id']
        
        # Find block in composition
        block = next(b for b in original_slide['composition']['blocks'] 
                     if b['id'] == block_id)
        
        # Split text into chunks that fit
        chunks = split_text_to_fit(block['text'], worst['usable'], worst['needed'])
        
        if len(chunks) > 1:
            # Create additional slides
            for chunk_idx, chunk in enumerate(chunks):
                if chunk_idx == 0:
                    # Update original
                    block['text'] = chunk
                else:
                    # Clone slide with new content
                    new_slide = copy.deepcopy(original_slide)
                    new_slide['id'] = f"{original_slide['id']}-part{chunk_idx + 1}"
                    new_slide['semantic']['title'] = f"{original_slide['semantic']['title']} (part {chunk_idx + 1})"
                    
                    # Update the block content
                    new_block = next(b for b in new_slide['composition']['blocks'] 
                                   if b['id'] == block_id)
                    new_block['text'] = chunk
                    
                    # Insert after original
                    new_ir['slides'].insert(slide_num + chunk_idx, new_slide)
    
    return new_ir, None, None  # Trigger recompile

def split_text_to_fit(text, usable_height, needed_height):
    """Split text into chunks that fit within usable_height."""
    lines = text.split('\n')
    ratio = needed_height / usable_height
    chunks_needed = math.ceil(ratio)
    lines_per_chunk = len(lines) // chunks_needed
    
    chunks = []
    for i in range(chunks_needed):
        start = i * lines_per_chunk
        end = start + lines_per_chunk if i < chunks_needed - 1 else len(lines)
        chunks.append('\n'.join(lines[start:end]))
    
    return chunks
```

**Integration:**

```python
# In deck_compiler/pipeline.py build() function, after initial compile:

result, findings = compile_deck(ir, base, proposals=proposals)

# NEW: Detect and repair overflow
if any(f['severity'] == 'WARNING' and 'text overflow' in f.get('message', '') 
       for f in findings):
    repaired_ir, _, _ = repair_overflow(ir, result, 
                                       {'items': findings}, base)
    if repaired_ir != ir:
        # Recompile with split slides
        result, findings = compile_deck(repaired_ir, base, proposals=proposals)
```

**Pros:**
- Works with existing models
- Automatic - no manual intervention
- Adds slides as needed - directly solves "insufficient slides" problem
- Can be deployed immediately

**Cons:**
- May create slides with redundant titles
- Doesn't improve single-slide layouts
- Breaks continuity of presentation narrative

---

### Solution 3: Increase Font Floor Tolerance and Max Lines

**Simpler fallback: allow smaller fonts and more lines when needed.**

**Changes:**

```python
# In deck_compiler/contracts.py

@dataclass
class TextBoxContract:
    font_family: str
    font_size: float
    font_file: str
    font_weight: int = 400
    line_height: float = 1.25
    inset: dict = field(default_factory=lambda: {"left": 0, "right": 0, "top": 0, "bottom": 0})
    wrap: bool = True
    autofit: str = "none"
    vertical_anchor: str = "top"
    max_lines: int = 8  # INCREASE TO 12 or 15
    overflow_policy: str = "wrap_shrink_variant_split"
    font_floor: float = 24  # DECREASE TO 18 or 20 for body text
```

```python
# In deck_compiler/layout.py, line 144-151

def text(eid, content, bbox, role="body", size=28, floor=24, lines=10,
         anchor="top", color=None, flow=None):
    # CHANGE defaults:
    # - floor=20 for body (was 24)
    # - lines=15 for body (was 10)
```

**Pros:**
- Simple one-line changes
- Immediate improvement
- No model retraining

**Cons:**
- Smaller fonts hurt readability
- More lines create visual density
- Doesn't add slides - just crams more into existing space
- Band-aid solution

---

### Solution 4: Hybrid - Capacity Inflation + Content Summarization

**Combine layout adjustment with intelligent content reduction:**

1. **During v26 proposal generation:**
   - Detect when content exceeds reasonable capacity
   - Inflate bboxes by 15-20% to provide breathing room

2. **During Deck IR compilation:**
   - When inflation causes collisions or exceeds slide bounds
   - Trigger content summarization agent
   - Ask LLM: "Condense this body text to 70% length while preserving key scientific claims"
   - Update Deck IR with condensed text
   - Preserve original in speaker notes

3. **Final validation:**
   - If still overflows, apply Solution 2 (split slides)

**Pros:**
- Best of both worlds
- Maintains readability
- Preserves full content in notes
- Most "intelligent" solution

**Cons:**
- Most complex
- Requires LLM calls during compilation
- Content reduction may lose nuance
- Slower pipeline

---

## Recommended Implementation Plan

### Phase 1: Immediate Relief (Solution 3)
**Timeline: 1-2 days**

1. Increase `max_lines` from 8 → 12 for body text
2. Decrease `font_floor` from 24 → 20 for body text  
3. Test on graphene-v26 build
4. Measure reduction in overflow warnings

**Expected impact:** 30-50% reduction in overflow warnings

### Phase 2: Automatic Slide Addition (Solution 2)
**Timeline: 1 week**

1. Implement `overflow_repair.py` module
2. Add detection logic for severe overflows (>20% of bbox)
3. Implement text chunking and slide cloning
4. Integrate into build pipeline after initial compilation
5. Add QA validation for split slides

**Expected impact:** 80-90% reduction in overflow warnings, presentations become usable

### Phase 3: Layout Model Enhancement (Solution 1)
**Timeline: 2-3 weeks**

1. Add capacity loss term to v26 training objective
2. Retrain model on existing dataset with new loss
3. Implement `ensure_capacity()` post-selection validation
4. Test on multiple papers
5. Deploy new checkpoint as v27

**Expected impact:** 95%+ overflow-free layouts, optimal solution

---

## Success Metrics

**Before (Current State):**
- 16 overflow warnings / 9 slides = 1.78 warnings/slide
- 89% of content slides have overflow
- 0% presentation-ready rate

**After Phase 1:**
- Target: <1.0 warning/slide
- Target: <60% of slides have overflow

**After Phase 2:**
- Target: <0.3 warning/slide
- Target: <20% of slides have overflow  
- Target: 80%+ presentation-ready rate

**After Phase 3:**
- Target: <0.1 warning/slide
- Target: <5% of slides have overflow
- Target: 95%+ presentation-ready rate

---

## Files to Modify

### Phase 1 (Quick Fix):
- `Total-pipe/deck_compiler/contracts.py` (line 28-29)
- `Total-pipe/deck_compiler/layout.py` (line 144-151)

### Phase 2 (Slide Splitting):
- **NEW:** `Total-pipe/deck_compiler/overflow_repair.py`
- `Total-pipe/deck_compiler/pipeline.py` (integrate repair)
- `Total-pipe/deck_compiler/mcp_server.py` (expose repair via MCP)

### Phase 3 (Model Enhancement):
- `Total-pipe/totalpipe_layout/model.py` (training objective)
- `Total-pipe/deck_compiler/layout_provider.py` (post-selection validation)
- Training script (add capacity loss)

---

## Conclusion

The core problem is a **mismatch between layout model proposals and actual content capacity**. The v26 model generates aesthetically reasonable layouts, but systematically underestimates the vertical space required for text content.

**Solution 2 (automatic slide splitting) is recommended as the highest-impact, lowest-risk solution** that directly addresses both stated problems:
1. ✅ "Correctly place a sufficient amount of content" - by giving content more space
2. ✅ "PPT slides as needed" - by adding slides when single-slide layout fails

This should be implemented first, followed by the model enhancement for a permanent fix.
