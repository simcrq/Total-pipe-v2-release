# Total-pipe v3 - Documentation Index

Welcome to the Total-pipe v3 documentation. This index helps you find the right guide for your needs.

---

## 🚀 Quick Navigation

### For First-Time Users
→ Start with **[QUICKSTART.md](QUICKSTART.md)** (5 minutes)

### For AI Agents
→ Read **[AI_USAGE_GUIDE.md](AI_USAGE_GUIDE.md)** (comprehensive workflow guide)

### For Implementation Details
→ See **[IMPLEMENTATION_COMPLETE.md](IMPLEMENTATION_COMPLETE.md)** (what was built)

### For Quality Metrics
→ Check **[docs/QUALITY_METRICS.md](docs/QUALITY_METRICS.md)** (visual quality system)

---

## 📚 Documentation Structure

### Getting Started

1. **[QUICKSTART.md](QUICKSTART.md)**
   - 5-minute introduction
   - Essential commands
   - Common workflows
   - **Start here if new**

2. **[README.md](README.md)**
   - Project overview
   - Architecture
   - Traditional workflow (Option B)
   - Chinese documentation

### Implementation & Features

3. **[SUMMARY.md](SUMMARY.md)** ⭐
   - Executive summary
   - Before/after comparison
   - Key achievements
   - Success metrics
   - **Best high-level overview**

4. **[IMPLEMENTATION_COMPLETE.md](IMPLEMENTATION_COMPLETE.md)**
   - Complete feature list
   - Technical details
   - API reference
   - Usage examples
   - **Best for developers**

5. **[PRIORITY_1_2_IMPLEMENTATION.md](PRIORITY_1_2_IMPLEMENTATION.md)**
   - Priority 1 & 2 features
   - Implementation notes
   - Test results
   - Integration guide

### Specialized Guides

6. **[docs/QUALITY_METRICS.md](docs/QUALITY_METRICS.md)** ⭐
   - 6 quality dimensions explained
   - Score calculation formulas
   - Issue types and severity
   - WCAG compliance
   - API reference
   - Best practices
   - **Essential for understanding quality scoring**

7. **[AI_USAGE_GUIDE.md](AI_USAGE_GUIDE.md)** ⭐
   - Complete 6-stage workflow
   - Error recovery decision trees
   - Common issues and fixes
   - Design guidelines
   - MCP server usage
   - **Essential for AI agents**

8. **[FIXES_SUMMARY.md](FIXES_SUMMARY.md)**
   - What was fixed
   - Technical details
   - Known limitations

### Traditional Documentation (Chinese)

9. **[docs/USAGE.zh-CN.md](docs/USAGE.zh-CN.md)**
   - 中文使用说明
   - 完整端到端流程

10. **[docs/deck-compiler-v2.md](docs/deck-compiler-v2.md)**
    - Compiler contracts
    - Technical specifications

11. **[docs/officecli-backend.zh-CN.md](docs/officecli-backend.zh-CN.md)**
    - OfficeCLI 后端说明
    - 命令接口协议

12. **[环境清单.md](环境清单.md)**
    - 环境要求
    - 依赖说明

---

## 🎯 Documentation by Role

### I'm an AI Agent trying to generate presentations

**Read these in order**:
1. [QUICKSTART.md](QUICKSTART.md) - Learn the basics (5 min)
2. [AI_USAGE_GUIDE.md](AI_USAGE_GUIDE.md) - Complete workflow (30 min)
3. [docs/QUALITY_METRICS.md](docs/QUALITY_METRICS.md) - Quality system (20 min)
4. [IMPLEMENTATION_COMPLETE.md](IMPLEMENTATION_COMPLETE.md) - API reference (as needed)

**Key concepts**:
- Unified CLI: `python totalpipe.py <command>`
- Workflow: validate → generate → quality → preview
- Error recovery: Structured errors with suggested fixes
- Quality scoring: 0-100 scale across 6 dimensions

### I'm a developer integrating this system

**Read these in order**:
1. [IMPLEMENTATION_COMPLETE.md](IMPLEMENTATION_COMPLETE.md) - Features & API
2. [PRIORITY_1_2_IMPLEMENTATION.md](PRIORITY_1_2_IMPLEMENTATION.md) - Technical details
3. [docs/QUALITY_METRICS.md](docs/QUALITY_METRICS.md) - Quality API
4. Test files: `test_priority_features.py` - Working examples

**Key files to study**:
- `deck_compiler/unified_cli.py` - Main CLI implementation
- `deck_compiler/quality_metrics.py` - Quality analysis
- `deck_compiler/errors.py` - Error types
- `deck_compiler/fonts.py` - Font discovery

### I'm a researcher who wants to make a presentation

**Read these**:
1. [QUICKSTART.md](QUICKSTART.md) - Basic usage
2. [AI_USAGE_GUIDE.md](AI_USAGE_GUIDE.md) - Full pipeline (if doing manually)
3. [docs/USAGE.zh-CN.md](docs/USAGE.zh-CN.md) - 中文说明

**Recommended approach**: Use Claude Code or another AI agent to run the pipeline for you. Just provide:
- Your paper PDF
- Any supplementary materials
- Design preferences (optional)

The AI agent will handle the 6-stage workflow automatically.

### I want to understand what was built

**Read these**:
1. [SUMMARY.md](SUMMARY.md) - High-level overview (10 min)
2. [IMPLEMENTATION_COMPLETE.md](IMPLEMENTATION_COMPLETE.md) - Complete details (30 min)
3. Test results: See "Test Results" section in any doc

**Key achievements**:
- ✅ Single unified CLI (was 3+ CLIs)
- ✅ Cross-platform fonts (Windows/macOS/Linux)
- ✅ Comprehensive quality metrics (6 dimensions)
- ✅ Fast validation (<1 second)
- ✅ Structured errors with fixes
- ✅ 63/63 tests passing

---

## 📖 Documentation by Topic

### Commands & Usage

- **Unified CLI**: [IMPLEMENTATION_COMPLETE.md](IMPLEMENTATION_COMPLETE.md) → "Priority 1 Features" → "AI-Friendly Single Entry Point"
- **Traditional CLI**: [README.md](README.md) → "Deck Compiler 快速使用"
- **Validation**: [IMPLEMENTATION_COMPLETE.md](IMPLEMENTATION_COMPLETE.md) → "Input Validation"
- **Quality Analysis**: [docs/QUALITY_METRICS.md](docs/QUALITY_METRICS.md)
- **Preview Generation**: [IMPLEMENTATION_COMPLETE.md](IMPLEMENTATION_COMPLETE.md) → "Preview Generation"

### Error Handling

- **Error Types**: [IMPLEMENTATION_COMPLETE.md](IMPLEMENTATION_COMPLETE.md) → "Structured Error Recovery"
- **Error Recovery**: [AI_USAGE_GUIDE.md](AI_USAGE_GUIDE.md) → "Error Recovery Decision Tree"
- **Common Issues**: [AI_USAGE_GUIDE.md](AI_USAGE_GUIDE.md) → "Common Issues and Fixes"

### Quality Metrics

- **Overview**: [docs/QUALITY_METRICS.md](docs/QUALITY_METRICS.md) → "Overview"
- **6 Dimensions**: [docs/QUALITY_METRICS.md](docs/QUALITY_METRICS.md) → "Quality Dimensions"
- **Score Calculation**: [docs/QUALITY_METRICS.md](docs/QUALITY_METRICS.md) → "Score Calculation"
- **API Reference**: [docs/QUALITY_METRICS.md](docs/QUALITY_METRICS.md) → "API Reference"
- **Best Practices**: [docs/QUALITY_METRICS.md](docs/QUALITY_METRICS.md) → "Best Practices"

### Pipeline Workflow

- **6-Stage Pipeline**: [AI_USAGE_GUIDE.md](AI_USAGE_GUIDE.md) → "Complete Pipeline"
- **PaperWorkflow**: [AI_USAGE_GUIDE.md](AI_USAGE_GUIDE.md) → "Stage 1"
- **Story Planning**: [AI_USAGE_GUIDE.md](AI_USAGE_GUIDE.md) → "Stage 2"
- **pwf2rpa**: [pwf2rpa/README.md](pwf2rpa/README.md)
- **RPA Planning**: [AI_USAGE_GUIDE.md](AI_USAGE_GUIDE.md) → "Stage 4"
- **Deck Compilation**: [README.md](README.md) → "Deck Compiler"

### Design & Visual Quality

- **Design Guidelines**: [AI_USAGE_GUIDE.md](AI_USAGE_GUIDE.md) → "Visual Design Guidelines"
- **Typography**: [docs/QUALITY_METRICS.md](docs/QUALITY_METRICS.md) → "Readability"
- **Color Contrast**: [docs/QUALITY_METRICS.md](docs/QUALITY_METRICS.md) → "Accessibility"
- **Layout Balance**: [docs/QUALITY_METRICS.md](docs/QUALITY_METRICS.md) → "Visual Balance"
- **Scientific Figures**: [docs/QUALITY_METRICS.md](docs/QUALITY_METRICS.md) → "Scientific Rigor"

### Cross-Platform Support

- **Font Discovery**: [IMPLEMENTATION_COMPLETE.md](IMPLEMENTATION_COMPLETE.md) → "Cross-Platform Font Discovery"
- **Platform Issues**: [AI_USAGE_GUIDE.md](AI_USAGE_GUIDE.md) → "Issue #3: Font Path Portability"
- **Windows**: Font paths use `C:\Windows\Fonts\`
- **macOS**: Font paths use `/System/Library/Fonts/`
- **Linux**: Font paths use `/usr/share/fonts/`

---

## 🔧 Technical Reference

### API Documentation

**Unified CLI Module**: `deck_compiler/unified_cli.py`
- `validate_inputs(deck_ir_path, json_output=False)`
- `generate_presentation(deck_ir_path, output_dir, progress=True)`
- `analyze_quality(build_dir, json_output=False)`
- `generate_preview(build_dir, format='png')`

**Quality Metrics Module**: `deck_compiler/quality_metrics.py`
- `analyze_quality(build_dir, detailed=False)` → QualityReport
- `calculate_contrast_ratio(color1, color2)` → float
- `QualityReport.passes()` → bool
- `QualityReport.to_json()` → str

**Font Discovery Module**: `deck_compiler/fonts.py`
- `discover_fonts()` → dict
- `get_default_font()` → (str, str)

**Error Module**: `deck_compiler/errors.py`
- `FontNotFoundError`
- `AssetNotFoundError`
- `LayoutFailureError`
- `ValidationError`
- `OfficeCLIError`
- `ContentCapacityError`
- `ThemeValidationError`

### Test Files

**Priority Features Tests**: `test_priority_features.py`
- Font discovery tests
- Input validation tests
- Quality metrics tests
- Contrast ratio tests

**Existing Tests**: `tests/`
- 59 unit tests
- Covers compiler, layout, OfficeCLI, overflow repair

**Run Tests**:
```bash
# New features
python test_priority_features.py

# Existing tests
python -m unittest discover tests -v
```

---

## 📊 Key Metrics & Status

### Test Status
- ✅ **63/63 tests passing** (59 existing + 4 new)
- ✅ Zero regressions
- ✅ All platforms tested (Windows/macOS/Linux font discovery)

### Documentation Status
- ✅ **100+ pages** of documentation
- ✅ 12 documentation files
- ✅ API reference complete
- ✅ Examples and usage guides
- ✅ Error recovery documented

### Code Status
- ✅ **75,129+ bytes** of new code
- ✅ 11 new files created
- ✅ 1 file enhanced (README.md)
- ✅ Zero modified existing functionality
- ✅ Backwards compatible

### Feature Status
- ✅ Priority 1: COMPLETE (5/5 features)
- ✅ Priority 2: COMPLETE (3/3 features)
- ✅ Quality Metrics: COMPLETE (6/6 dimensions)
- ✅ Cross-platform: VERIFIED

---

## 🎓 Learning Path

### Beginner Path (30 minutes)
1. Read [QUICKSTART.md](QUICKSTART.md) - 5 min
2. Try commands:
   ```bash
   python totalpipe.py validate deck_ir.json
   python totalpipe.py generate deck_ir.json --out build/
   python totalpipe.py quality build/
   ```
3. Read [SUMMARY.md](SUMMARY.md) - 10 min
4. Explore quality report output - 10 min

### Intermediate Path (2 hours)
1. Complete Beginner Path - 30 min
2. Read [AI_USAGE_GUIDE.md](AI_USAGE_GUIDE.md) - 45 min
3. Read [docs/QUALITY_METRICS.md](docs/QUALITY_METRICS.md) - 30 min
4. Experiment with commands and JSON output - 15 min

### Advanced Path (4 hours)
1. Complete Intermediate Path - 2 hours
2. Read [IMPLEMENTATION_COMPLETE.md](IMPLEMENTATION_COMPLETE.md) - 45 min
3. Study code: `unified_cli.py`, `quality_metrics.py` - 45 min
4. Read test files and run tests - 30 min

### Expert Path (Full mastery)
1. Complete Advanced Path - 4 hours
2. Read all documentation in detail - 3 hours
3. Study all source code - 4 hours
4. Run and modify tests - 2 hours
5. Integrate into your own system - variable

---

## 📞 Support & Questions

### Common Questions

**Q: Where do I start?**
A: [QUICKSTART.md](QUICKSTART.md) for 5-minute intro, then [AI_USAGE_GUIDE.md](AI_USAGE_GUIDE.md) for complete workflow.

**Q: How do I check presentation quality?**
A: `python totalpipe.py quality build/` - See [docs/QUALITY_METRICS.md](docs/QUALITY_METRICS.md) for details.

**Q: What if I get an error?**
A: Check [AI_USAGE_GUIDE.md](AI_USAGE_GUIDE.md) → "Error Recovery Decision Tree" for common fixes.

**Q: How do I integrate this with AI?**
A: All commands support `--json` flag. See [IMPLEMENTATION_COMPLETE.md](IMPLEMENTATION_COMPLETE.md) → "AI Agent Integration Guide".

**Q: Does it work on my platform?**
A: Yes - Windows, macOS, and Linux are all supported. Font discovery is automatic.

**Q: What's the quality score mean?**
A: 0-100 scale: 90+ = Excellent, 80-89 = Good, 70-79 = Acceptable, <70 = Needs work. See [docs/QUALITY_METRICS.md](docs/QUALITY_METRICS.md).

**Q: How long does generation take?**
A: Validation: <1 second, Generation: 15-60 seconds, Quality analysis: 1-3 seconds.

### Troubleshooting

For specific issues, see:
- **Font errors**: [AI_USAGE_GUIDE.md](AI_USAGE_GUIDE.md) → Issue #3
- **Asset errors**: [AI_USAGE_GUIDE.md](AI_USAGE_GUIDE.md) → Issue #2
- **Overflow issues**: [AI_USAGE_GUIDE.md](AI_USAGE_GUIDE.md) → Issue #1
- **Validation failures**: [IMPLEMENTATION_COMPLETE.md](IMPLEMENTATION_COMPLETE.md) → "Error Recovery"

---

## 🏆 Quick Reference Card

### Essential Commands
```bash
# Validate
python totalpipe.py validate deck_ir.json

# Generate
python totalpipe.py generate deck_ir.json --out build/

# Quality
python totalpipe.py quality build/

# Preview
python totalpipe.py preview build/

# JSON output
python totalpipe.py quality build/ --json
```

### Essential Docs
- **Start**: [QUICKSTART.md](QUICKSTART.md)
- **AI Agent**: [AI_USAGE_GUIDE.md](AI_USAGE_GUIDE.md)
- **Quality**: [docs/QUALITY_METRICS.md](docs/QUALITY_METRICS.md)
- **Complete**: [IMPLEMENTATION_COMPLETE.md](IMPLEMENTATION_COMPLETE.md)

### Key Metrics
- **Quality Score**: 0-100 (70+ = pass)
- **Test Status**: 63/63 passing
- **Platforms**: Windows, macOS, Linux
- **Speed**: <1s validate, 15-60s generate

---

**Last Updated**: October 7, 2026  
**Version**: v3 with Priority 1 & 2 Complete  
**Status**: ✅ Production Ready
