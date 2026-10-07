# Quick Start Guide: Testing Overflow Repair

## Verify Installation

```bash
cd Total-pipe

# Check Python syntax
python -m py_compile deck_compiler/overflow_repair.py
python -m py_compile deck_compiler/pipeline.py

# Run unit tests
python -m unittest tests.test_overflow_repair -v
```

## Test on Real Data

### Option 1: Rebuild graphene-v26 with Repair

```bash
cd Total-pipe

# Backup current build
cp -r ../builds/graphene-v26 ../builds/graphene-v26-backup

# Rebuild with overflow repair enabled (default)
python -m deck_compiler build \
  --ir ../builds/graphene-v26/deck_ir.json \
  --out ../builds/graphene-v26-repaired \
  --officecli /path/to/officecli \
  --skip-native
```

### Option 2: Quick Test via Python

```python
import sys
sys.path.insert(0, 'E:/pptx_re/total-pipe-v3-experiment/Total-pipe')

from pathlib import Path
import json
from deck_compiler.overflow_repair import repair_overflow, overflow_summary

# Load existing build artifacts
build_dir = Path('../builds/graphene-v26')
ir = json.loads((build_dir / 'deck_ir.json').read_text(encoding='utf-8'))
layout = json.loads((build_dir / 'layout.json').read_text(encoding='utf-8'))
qa_report = json.loads((build_dir / 'qa_report.json').read_text(encoding='utf-8'))

# Analyze current overflow
summary = overflow_summary(qa_report)
print(f"Current state:")
print(f"  Total overflows: {summary['total_overflows']}")
print(f"  Slides affected: {summary['slides_affected']}")
print(f"  Avg overflow: {summary['avg_overflow_ratio']:.1%}")
print(f"  Max overflow: {summary['max_overflow_ratio']:.1%}")
print(f"  Severe (>25%): {summary['severe_overflows']}")

# Attempt repair
repaired_ir, was_modified = repair_overflow(ir, layout, qa_report, overflow_threshold=0.25)

print(f"\nRepair result:")
print(f"  Modified: {was_modified}")
if was_modified:
    print(f"  Original slides: {len(ir['slides'])}")
    print(f"  Repaired slides: {len(repaired_ir['slides'])}")
    print(f"  Added slides: {len(repaired_ir['slides']) - len(ir['slides'])}")
    
    # Show which slides were split
    for slide in repaired_ir['slides']:
        if '-cont' in slide['id']:
            print(f"    → {slide['id']}: {slide['semantic']['title']}")
```

## Compare Results

### Before Repair
```bash
cd ../builds/graphene-v26
cat qa_report.json | grep -A3 "text overflow" | head -20
```

Expected: 16 warnings across 8 slides

### After Repair
```bash
cd ../builds/graphene-v26-repaired
cat qa_report.json | grep -A3 "text overflow" | head -20
cat qa_report.json | grep "OVERFLOW_REPAIR_APPLIED"
```

Expected: 
- 2-4 warnings (80% reduction)
- INFO message showing repair was applied
- Additional slides with "-cont1", "-cont2" suffixes

## Manual Inspection

Open the repaired PPTX:
```bash
cd ../builds/graphene-v26-repaired
start staging.pptx  # Windows
# or
open staging.pptx   # macOS
```

Check:
- [ ] Continuation slides have proper titles (part 2/3, etc.)
- [ ] Text is fully visible, no cutoff
- [ ] Figures are present on appropriate slides
- [ ] Visual spacing looks reasonable
- [ ] No orphaned slides with no content

## Disable Repair (if needed)

```python
# In deck_compiler/pipeline.py, line 48
def compile_input(ir_path, out, layout_options=None, enable_overflow_repair=False):
```

Or via API:
```python
from deck_compiler.pipeline import compile_input

ir, layout, qa = compile_input(
    ir_path,
    out_dir,
    layout_options={'name': 'v26'},
    enable_overflow_repair=False  # Disable repair
)
```

## Troubleshooting

### Test Fails: ModuleNotFoundError
```bash
cd Total-pipe
export PYTHONPATH=.
python -m unittest tests.test_overflow_repair -v
```

### Repair Not Applied
Check QA report:
```bash
cat qa_report.json | python -m json.tool | grep -A5 "OVERFLOW_REPAIR"
```

If no INFO item, check:
1. Was overflow threshold exceeded? (must be >25%)
2. Were overflows actually WARNING severity?
3. Check error logs for exceptions

### Too Many Slides Created
The repair caps at 4 chunks per original slide. If you're getting more:
1. Check overflow ratios - extremely high ratios indicate layout model issues
2. Consider adjusting threshold:
   ```python
   repair_overflow(ir, layout, qa_report, overflow_threshold=0.35)  # More conservative
   ```

### Content Not Split Properly
The splitter preserves paragraph boundaries. If content appears unbalanced:
1. Check source text has proper `\n` separators
2. Review `split_text_to_chunks()` logic
3. May need manual Story/RPA replanning for better content distribution

## Next Steps

Once repair is verified:
1. Update MCP tools to expose `enable_overflow_repair` parameter
2. Update SKILL.md to document the feature
3. Add configuration option to project settings
4. Consider adding UI option in Claude Desktop

## Metrics to Track

For each build, record:
- Original slide count
- Repaired slide count  
- Overflow warnings before/after
- Build time (may increase due to recompilation)
- Manual fixes still required (target: 0)
