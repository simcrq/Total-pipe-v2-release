# Visual Quality Metrics System

## Overview

The quality metrics system provides comprehensive analysis of generated presentations across 6 dimensions: readability, consistency, completeness, visual balance, accessibility, and scientific rigor.

## Quick Start

```bash
# Analyze quality after generation
python totalpipe.py quality build/

# Get JSON output
python totalpipe.py quality build/ --json

# Detailed per-slide analysis
python totalpipe.py quality build/ --detailed
```

## Quality Dimensions

### 1. Readability (Weight: 25%)

**What it measures**: How easy the text is to read.

**Metrics**:
- **Font sizes**: Minimum, average, and maximum font sizes across all text
- **Line counts**: Number of lines per text block
- **Text density**: Characters per unit area

**Quality criteria**:
- ✅ Font size ≥ 18pt (minimum for accessibility)
- ✅ Font size ≥ 20pt (recommended for body text)
- ✅ Line count ≤ 10 per block (avoid text walls)
- ✅ Text density ≤ 0.5 (avoid cramped appearance)

**Issues detected**:
```
HIGH: Font size 16pt is too small (minimum 18pt for body text)
  Fix: Increase font size or reduce content to fit larger text

MEDIUM: Font size 18pt is small (recommended 20pt+ for body text)

MEDIUM: 12 lines of text exceeds recommended maximum (10 lines)
  Fix: Split content across multiple slides

LOW: High text density (may appear cramped)
```

**Example good readability**:
- Average font size: 24pt
- Maximum line count: 8
- Sparse text density

### 2. Consistency (Weight: 20%)

**What it measures**: Visual rhythm and uniformity across slides.

**Metrics**:
- **Vertical spacing**: Standard deviation of gaps between elements
- **Font sizes by role**: Consistency of title, body, caption sizes
- **Horizontal spacing**: Consistency of margins and padding

**Quality criteria**:
- ✅ Vertical gap std dev ≤ 20px (consistent spacing)
- ✅ ≤ 2 different font sizes per role (e.g., all titles use same size)

**Issues detected**:
```
MEDIUM: Inconsistent vertical spacing (std dev: 28.3px)
  Fix: Use consistent spacing between elements (e.g., 24px)

MEDIUM: Inconsistent font sizes for body: [18, 20, 22]pt
  Fix: Use consistent font size for all body elements
```

**Example good consistency**:
- Vertical spacing: 24px ± 5px
- All titles: 32pt
- All body text: 22pt

### 3. Completeness (Weight: 15%)

**What it measures**: Content coverage and scientific rigor.

**Metrics**:
- **Evidence coverage**: Percentage of slides with evidence citations
- **Takeaway quality**: Presence and length of takeaways
- **Speaker notes**: Presence of speaker notes
- **Caveats**: Inclusion of limitations/caveats

**Quality criteria**:
- ✅ Evidence coverage ≥ 80% (most slides cite sources)
- ✅ All slides have meaningful takeaways (≥ 10 chars)
- ✅ Speaker notes present

**Issues detected**:
```
MEDIUM: No evidence citations on this slide
  Fix: Add evidence_refs to support claims

HIGH: Missing or very short takeaway
  Fix: Add clear one-sentence takeaway for this slide
```

**Example good completeness**:
- 90% evidence coverage
- All slides have takeaways
- Speaker notes on complex slides

### 4. Visual Balance (Weight: 15%)

**What it measures**: Use of whitespace and element distribution.

**Metrics**:
- **Slide coverage**: Percentage of slide area covered by elements
- **Coverage distribution**: Min, max, average coverage

**Quality criteria**:
- ✅ Average coverage 40-70% (ideal balance)
- ✅ No slide > 80% coverage (too dense)
- ✅ No slide < 30% coverage (too sparse)

**Issues detected**:
```
MEDIUM: Slide is very dense (85% coverage)
  Fix: Reduce content or increase slide size

LOW: Slide appears sparse (28% coverage)
```

**Example good balance**:
- Average coverage: 55%
- Range: 45% to 68%
- Consistent whitespace

### 5. Accessibility (Weight: 10%)

**What it measures**: WCAG compliance for readability.

**Metrics**:
- **Color contrast ratio**: Foreground/background contrast
- **Minimum font sizes**: Count of elements below accessibility threshold

**Quality criteria**:
- ✅ Contrast ratio ≥ 4.5:1 (WCAG AA for normal text)
- ✅ Contrast ratio ≥ 7.0:1 (WCAG AAA standard)
- ✅ No text elements < 18pt

**Issues detected**:
```
HIGH: Insufficient color contrast: 3.2:1 (WCAG AA requires 4.5:1)
  Fix: Increase contrast between foreground and background colors

HIGH: 3 text elements below 18pt (accessibility minimum)
  Fix: Increase font sizes to at least 18pt for accessibility

LOW: Color contrast 5.1:1 meets AA but not AAA standard (7:1)
```

**Example good accessibility**:
- Contrast ratio: 15.3:1 (excellent)
- No fonts below 18pt
- Meets WCAG AAA standard

### 6. Scientific Rigor (Weight: 15%)

**What it measures**: Quality of scientific figures and citations.

**Metrics**:
- **Figure caption coverage**: Percentage of figures with captions
- **Panel labels**: Presence and readability of panel labels
- **Figure quality**: Resolution, size, clarity

**Quality criteria**:
- ✅ All figures have descriptive captions
- ✅ Caption coverage ≥ 90%
- ✅ Figures large enough to read panel labels (≥ 220px)

**Issues detected**:
```
MEDIUM: Figure missing caption
  Fix: Add descriptive caption with figure reference (e.g., Fig.1a)

HIGH: Scientific panel labels too small to read
  Fix: Verify scientific figure quality and panel labels in PowerPoint

MEDIUM: Figure too small (180px minimum dimension)
  Fix: Increase figure size to at least 220px
```

**Example good scientific rigor**:
- 100% caption coverage
- All panels labeled clearly
- Figures sized appropriately

## Score Calculation

### Formula

```
Overall Score = Σ(category_score × weight) / Σ(weight)

Where weights are:
- Readability: 0.25
- Consistency: 0.20
- Completeness: 0.15
- Balance: 0.15
- Scientific: 0.15
- Accessibility: 0.10
Total: 1.00
```

### Issue Penalties

Each issue reduces the category score:
- **CRITICAL**: -25 points
- **HIGH**: -15 points
- **MEDIUM**: -8 points
- **LOW**: -3 points

### Bonuses

Good practices add points:
- Average font size ≥ 22pt: +10 points (readability)
- Evidence coverage ≥ 80%: +10 points (completeness)
- Contrast ratio ≥ 7.0:1: +10 points (accessibility)
- Caption coverage ≥ 90%: +10 points (scientific)

### Pass/Fail Threshold

- **PASS**: Overall score ≥ 70.0 AND 0 critical issues
- **FAIL**: Overall score < 70.0 OR any critical issues present

## Score Interpretation

| Score Range | Grade | Meaning | Action |
|------------|-------|---------|--------|
| 90-100 | Excellent | Production ready | Present to audience |
| 80-89 | Good | Minor improvements recommended | Optional iteration |
| 70-79 | Acceptable | Some issues to address | Review issues |
| 60-69 | Poor | Significant issues | Major revision needed |
| < 60 | Fail | Major problems | Regenerate or redesign |

## Output Formats

### Human-Readable Summary

```
============================================================
PRESENTATION QUALITY REPORT
============================================================

Overall Score: 87.5/100 [PASS]
Slides: 8

Issues: 6 total
  [HIGH] 1
  [MEDIUM] 3
  [LOW] 2

Category Scores:
  [OK] Readability      95.0/100  (1 issues)
  [OK] Consistency      90.0/100  (2 issues)
  [WARN] Completeness   75.0/100  (2 issues)
  [OK] Balance          85.0/100  (1 issues)
  [OK] Accessibility   100.0/100  (0 issues)
  [OK] Scientific       88.0/100  (0 issues)

Critical & High Priority Issues:
  HIGH     [Slide 3] Font size 16pt is too small (minimum 18pt)
           -> Fix: Increase font size or reduce content

============================================================
```

### JSON Output

```json
{
  "overall_score": 87.5,
  "passes": true,
  "scores": {
    "readability": {
      "score": 95.0,
      "weight": 0.25,
      "issue_count": 1,
      "details": {
        "min_font_size": 18,
        "avg_font_size": 22.4,
        "max_line_count": 9,
        "avg_line_count": 5.2
      }
    },
    "consistency": {
      "score": 90.0,
      "weight": 0.20,
      "issue_count": 2,
      "details": {
        "vertical_gap_std": 12.3,
        "vertical_gap_avg": 24.0,
        "font_sizes_by_role": {
          "title": {"min": 32, "max": 32, "unique": 1},
          "body": {"min": 20, "max": 22, "unique": 2}
        }
      }
    },
    "accessibility": {
      "score": 100.0,
      "weight": 0.10,
      "issue_count": 0,
      "details": {
        "contrast_ratio": 15.31,
        "text_elements_below_18pt": 0
      }
    }
  },
  "slide_count": 8,
  "total_issues": 6,
  "critical_issues": 0,
  "high_issues": 1,
  "medium_issues": 3,
  "low_issues": 2,
  "pass_threshold": 70.0
}
```

## Usage in AI Workflows

### Basic Quality Check

```python
from deck_compiler.quality_metrics import analyze_quality

# After generating presentation
quality = analyze_quality(build_dir)

if quality.passes():
    print(f"✓ Quality score: {quality.overall_score:.1f}/100")
    present_to_user()
else:
    print(f"✗ Quality issues detected")
    explain_issues(quality.issues)
```

### Quality-Based Iteration

```python
# Generate
generate_presentation(deck_ir, build_dir)

# Analyze
quality = analyze_quality(build_dir)

# Iterate if needed
while quality.overall_score < 85 and iterations < 3:
    # Fix high-priority issues
    for issue in quality.scores['readability'].issues:
        if issue.severity in ['CRITICAL', 'HIGH']:
            apply_fix(issue)
    
    # Regenerate
    generate_presentation(deck_ir, build_dir)
    quality = analyze_quality(build_dir)
    iterations += 1
```

### Category-Specific Analysis

```python
quality = analyze_quality(build_dir)

# Check specific dimensions
if quality.scores['accessibility'].score < 80:
    print("Accessibility issues detected:")
    for issue in quality.scores['accessibility'].issues:
        print(f"  - {issue.message}")
        if issue.suggested_fix:
            print(f"    Fix: {issue.suggested_fix}")

# Get detailed metrics
readability = quality.scores['readability']
print(f"Average font size: {readability.details['avg_font_size']}pt")
print(f"Minimum font size: {readability.details['min_font_size']}pt")
```

### JSON Integration

```bash
# Get JSON report
python totalpipe.py quality build/ --json > quality.json

# Parse in AI workflow
quality_data = json.loads(open('quality.json').read())

if quality_data['overall_score'] >= 85:
    approve_presentation()
elif quality_data['critical_issues'] == 0:
    present_with_warnings()
else:
    reject_and_iterate()
```

## API Reference

### `analyze_quality(build_dir, detailed=False)`

Analyze presentation quality.

**Parameters**:
- `build_dir` (Path): Build directory containing qa_report.json, layout.json, deck_ir.json
- `detailed` (bool): Include detailed per-slide analysis (default: False)

**Returns**: `QualityReport` object

**Example**:
```python
from pathlib import Path
from deck_compiler.quality_metrics import analyze_quality

report = analyze_quality(Path('build/'), detailed=True)
print(report.overall_score)  # 87.5
print(report.passes())       # True
print(report.to_json())      # JSON string
```

### `QualityReport`

Container for quality analysis results.

**Attributes**:
- `overall_score` (float): Weighted average score (0-100)
- `scores` (dict): Category scores (readability, consistency, etc.)
- `slide_count` (int): Number of slides analyzed
- `total_issues` (int): Total number of issues found
- `critical_issues` (int): Number of CRITICAL severity issues
- `high_issues` (int): Number of HIGH severity issues
- `medium_issues` (int): Number of MEDIUM severity issues
- `low_issues` (int): Number of LOW severity issues
- `pass_threshold` (float): Minimum score to pass (default: 70.0)

**Methods**:
- `passes()` → bool: Check if presentation meets quality threshold
- `to_dict()` → dict: Convert to dictionary
- `to_json()` → str: Convert to JSON string
- `to_summary()` → str: Generate human-readable summary

### `QualityScore`

Score for a single quality dimension.

**Attributes**:
- `category` (str): Category name (readability, consistency, etc.)
- `score` (float): Score for this category (0-100)
- `weight` (float): Importance weight in overall score
- `issues` (list): List of QualityIssue objects
- `details` (dict): Detailed metrics for this category

### `QualityIssue`

A specific quality issue found.

**Attributes**:
- `category` (str): Quality dimension (readability, consistency, etc.)
- `severity` (str): CRITICAL, HIGH, MEDIUM, LOW, INFO
- `slide` (int): Slide number (None for overall issues)
- `shape` (str): Shape/element name (None if not specific)
- `message` (str): Human-readable description
- `metric_value` (float): Measured value (optional)
- `threshold` (float): Threshold value (optional)
- `suggested_fix` (str): How to fix this issue (optional)

### `calculate_contrast_ratio(color1, color2)`

Calculate WCAG contrast ratio between two colors.

**Parameters**:
- `color1` (str): Hex color (e.g., "#142735")
- `color2` (str): Hex color (e.g., "#FFFFFF")

**Returns**: float (contrast ratio, e.g., 4.5)

**Example**:
```python
from deck_compiler.quality_metrics import calculate_contrast_ratio

# Check if colors meet WCAG AA standard
contrast = calculate_contrast_ratio("#142735", "#FFFFFF")
if contrast >= 4.5:
    print(f"✓ Passes WCAG AA ({contrast:.1f}:1)")
else:
    print(f"✗ Fails WCAG AA ({contrast:.1f}:1, need 4.5:1)")
```

## Common Issues and Fixes

### Issue: Low Readability Score

**Symptoms**:
- Font sizes below 20pt
- Too many lines per text block
- High text density

**Fixes**:
1. Increase font sizes to 22pt or larger
2. Split long text blocks across multiple slides
3. Reduce content per slide
4. Use bullet points instead of paragraphs

### Issue: Low Consistency Score

**Symptoms**:
- Varying spacing between elements
- Mixed font sizes for same role
- Inconsistent margins

**Fixes**:
1. Use consistent 24px spacing between elements
2. Define font sizes per role and stick to them
3. Use grid-based layout

### Issue: Low Completeness Score

**Symptoms**:
- Missing evidence citations
- Empty or short takeaways
- No speaker notes

**Fixes**:
1. Add evidence_refs to all content slides
2. Write clear one-sentence takeaways
3. Add speaker notes for complex content

### Issue: Low Balance Score

**Symptoms**:
- Slides too dense (>80% coverage)
- Slides too sparse (<30% coverage)

**Fixes**:
1. Aim for 40-70% slide coverage
2. Add whitespace around elements
3. Split dense slides

### Issue: Low Accessibility Score

**Symptoms**:
- Low color contrast (<4.5:1)
- Fonts below 18pt

**Fixes**:
1. Increase contrast (dark on light or light on dark)
2. Test colors with WCAG calculator
3. Increase all font sizes to 18pt minimum

### Issue: Low Scientific Rigor Score

**Symptoms**:
- Figures without captions
- Figures too small
- Missing panel labels

**Fixes**:
1. Add descriptive captions to all figures
2. Increase figure size to at least 220px
3. Verify panel labels in source figures

## Best Practices

### For High-Quality Presentations

1. **Target 85+ overall score**
   - Aim for "Good" or "Excellent" grade
   - Zero critical issues

2. **Prioritize readability and accessibility**
   - Use 22pt+ font sizes
   - Ensure 7:1+ contrast ratio
   - Keep text blocks under 10 lines

3. **Maintain consistency**
   - Use 24px spacing throughout
   - Define 3-4 font sizes (title, heading, body, caption)
   - Keep margins consistent

4. **Include complete scientific context**
   - Cite evidence on every content slide
   - Write clear takeaways
   - Caption all figures

5. **Balance content and whitespace**
   - Aim for 50-60% slide coverage
   - Don't fear whitespace
   - Split dense content

### For AI Agents

1. **Always check quality after generation**
   ```python
   quality = analyze_quality(build_dir)
   if not quality.passes():
       handle_issues(quality.issues)
   ```

2. **Use quality scores to decide iteration**
   ```python
   if quality.overall_score < 85:
       fix_high_priority_issues()
       regenerate()
   ```

3. **Parse JSON for programmatic decisions**
   ```bash
   python totalpipe.py quality build/ --json | jq '.overall_score'
   ```

4. **Explain issues to users**
   ```python
   for issue in quality.scores['readability'].issues:
       if issue.severity in ['CRITICAL', 'HIGH']:
           print(f"⚠ {issue.message}")
           if issue.suggested_fix:
               print(f"  Fix: {issue.suggested_fix}")
   ```

## Limitations

### What Quality Metrics Cannot Detect

1. **Content accuracy**: Metrics don't verify scientific correctness
2. **Narrative flow**: Cannot assess storytelling quality
3. **Visual aesthetics**: Subjective design choices not measured
4. **Audience appropriateness**: Cannot judge if content fits audience level
5. **Real rendering**: Analysis is based on layout metadata, not actual PowerPoint rendering

### Known Issues

1. **OfficeCLI text overflow**: Overflow detection is heuristic and may have false positives/negatives
2. **Font measurement**: PIL font measurement differs slightly from PowerPoint rendering
3. **Figure quality**: Cannot verify actual figure resolution or clarity without rendering
4. **CJK text**: Character count may not accurately reflect visual density for Asian languages

### Recommendations

1. Always verify quality report with actual PowerPoint review
2. Use quality metrics as guidance, not absolute truth
3. Test presentations with target audience
4. Combine automated metrics with human review

---

## Examples

See `test_priority_features.py` for working examples of all quality metrics functions.

---

## Support

For issues or questions about quality metrics:
1. Check this documentation
2. Review `test_priority_features.py` examples
3. Examine `deck_compiler/quality_metrics.py` source code
4. Refer to WCAG 2.1 guidelines for accessibility standards
