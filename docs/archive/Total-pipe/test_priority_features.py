#!/usr/bin/env python3
"""
Test script for Priority 1 & 2 features.

Tests:
1. Font discovery
2. Input validation
3. Quality metrics
4. Unified CLI
"""

import json
import sys
from pathlib import Path

# Add to path
sys.path.insert(0, str(Path(__file__).parent / 'deck_compiler'))

from deck_compiler.fonts import discover_fonts, get_default_font, validate_font_path
from deck_compiler.unified_cli import validate_inputs
from deck_compiler.quality_metrics import analyze_quality, calculate_contrast_ratio


def test_font_discovery():
    """Test font discovery on current platform."""
    print("=" * 60)
    print("TEST 1: Font Discovery")
    print("=" * 60)

    fonts = discover_fonts()
    print(f"Discovered {len(fonts)} font families")

    for family in list(fonts.keys())[:3]:
        print(f"  {family}:")
        for variant, path in fonts[family].items():
            print(f"    {variant}: {path}")

    regular, bold = get_default_font()
    print(f"\nDefault font:")
    print(f"  Regular: {regular}")
    print(f"  Bold: {bold}")

    assert regular != 'FONT_NOT_FOUND', "Should find at least one font"
    print("\n[OK] Font discovery passed\n")


def test_validation():
    """Test input validation."""
    print("=" * 60)
    print("TEST 2: Input Validation")
    print("=" * 60)

    # Create minimal valid deck IR with Windows fonts
    regular, bold = get_default_font()

    test_deck_ir = {
        "schema_version": "2.0",
        "deck_id": "test-validation",
        "theme": {
            "font_family": "Arial",
            "font_file": regular,
            "bold_font_file": bold,
            "foreground": "#142735",
            "background": "#FFFFFF",
            "accent": "#137C8B"
        },
        "assets": {},
        "slides": [
            {
                "id": "slide1",
                "semantic": {
                    "title": "Test Slide",
                    "purpose": "Testing",
                    "takeaway": "This is a test slide.",
                    "evidence_refs": ["EV001"],
                    "caveats": [],
                    "speaker_notes": "Test notes"
                },
                "composition": {
                    "archetype": "evidence-hypothesis",
                    "blocks": [
                        {
                            "id": "b1",
                            "component": "direct-evidence",
                            "text": "Test evidence block with some text content."
                        }
                    ],
                    "figure_refs": []
                },
                "presentation": {}
            }
        ]
    }

    # Write test deck IR
    test_path = Path(__file__).parent / 'test_deck_ir.json'
    test_path.write_text(json.dumps(test_deck_ir, indent=2), encoding='utf-8')

    print(f"Created test deck IR: {test_path}")

    # Validate
    result = validate_inputs(test_path)

    print(f"Valid: {result['valid']}")
    print(f"Issues: {len(result['issues'])}")
    print(f"Warnings: {len(result['warnings'])}")
    print(f"Estimated slides: {result['estimated_slides']}")

    if result['issues']:
        print("\nIssues found:")
        for issue in result['issues']:
            print(f"  {issue['type']}: {issue['message']}")

    assert result['valid'], "Test deck IR should be valid"
    assert result['estimated_slides'] == 1, "Should estimate 1 slide"

    print("\n[OK] Validation passed\n")
    return test_path


def test_quality_metrics():
    """Test quality metrics calculation."""
    print("=" * 60)
    print("TEST 3: Quality Metrics")
    print("=" * 60)

    # Test contrast ratio calculation
    contrast1 = calculate_contrast_ratio("#142735", "#FFFFFF")
    print(f"Contrast ratio (dark on white): {contrast1:.2f}:1")
    assert contrast1 >= 4.5, "Should meet WCAG AA standard"

    contrast2 = calculate_contrast_ratio("#888888", "#FFFFFF")
    print(f"Contrast ratio (gray on white): {contrast2:.2f}:1")
    assert contrast2 < 4.5, "Gray should have lower contrast"

    print("\n[OK] Quality metrics passed\n")


def test_quality_analysis_mock():
    """Test quality analysis with mock data."""
    print("=" * 60)
    print("TEST 4: Quality Analysis (Mock Data)")
    print("=" * 60)

    # Create mock QA report
    mock_qa = {
        "status": "REVIEW",
        "counts": {"FAIL": 0, "WARNING": 2, "REVIEW": 1, "INFO": 5},
        "items": [
            {
                "rule": "OFFICECLI_FORMAT",
                "severity": "WARNING",
                "message": "text overflow: 3 lines at 20pt need 70pt, usable 60pt",
                "slide": 1
            },
            {
                "rule": "SCIENTIFIC_PANEL_REVIEW",
                "severity": "REVIEW",
                "message": "Scientific panel review recommended",
                "slide": 2
            }
        ]
    }

    # Create mock layout
    mock_layout = {
        "slides": [
            {
                "slide_number": 1,
                "elements": [
                    {
                        "kind": "text",
                        "role": "body",
                        "name": "body1",
                        "bbox": [50, 100, 400, 200],
                        "contract": {
                            "font_size": 22,
                            "text": "This is body text\nWith multiple lines\nOf content"
                        }
                    },
                    {
                        "kind": "text",
                        "role": "title",
                        "name": "title1",
                        "bbox": [50, 20, 860, 60],
                        "contract": {
                            "font_size": 32,
                            "text": "Test Title"
                        }
                    }
                ]
            },
            {
                "slide_number": 2,
                "elements": [
                    {
                        "kind": "text",
                        "role": "body",
                        "name": "body2",
                        "bbox": [50, 100, 400, 150],
                        "contract": {
                            "font_size": 20,
                            "text": "Another body text block"
                        }
                    }
                ]
            }
        ]
    }

    # Create mock deck IR
    regular, bold = get_default_font()
    mock_deck_ir = {
        "schema_version": "2.0",
        "theme": {
            "foreground": "#142735",
            "background": "#FFFFFF",
            "font_file": regular,
            "bold_font_file": bold
        },
        "slides": [
            {
                "id": "slide1",
                "semantic": {
                    "title": "First Slide",
                    "takeaway": "This is the main point",
                    "evidence_refs": ["EV001"]
                },
                "composition": {
                    "blocks": [{"id": "b1", "text": "Content"}],
                    "figure_refs": []
                }
            },
            {
                "id": "slide2",
                "semantic": {
                    "title": "Second Slide",
                    "takeaway": "Another point",
                    "evidence_refs": []
                },
                "composition": {
                    "blocks": [{"id": "b2", "text": "More content"}],
                    "figure_refs": []
                }
            }
        ]
    }

    # Create temp directory with mock files
    test_dir = Path(__file__).parent / 'test_quality_analysis'
    test_dir.mkdir(exist_ok=True)

    (test_dir / 'qa_report.json').write_text(json.dumps(mock_qa, indent=2), encoding='utf-8')
    (test_dir / 'layout.json').write_text(json.dumps(mock_layout, indent=2), encoding='utf-8')
    (test_dir / 'deck_ir.json').write_text(json.dumps(mock_deck_ir, indent=2), encoding='utf-8')

    # Analyze quality
    try:
        report = analyze_quality(test_dir, detailed=True)

        print(f"Overall Score: {report.overall_score:.1f}/100")
        print(f"Total Issues: {report.total_issues}")
        print(f"Passes: {report.passes()}")

        print("\nCategory Scores:")
        for cat, score in report.scores.items():
            print(f"  {cat:15} {score.score:5.1f}/100  ({len(score.issues)} issues)")

        print(f"\n{report.to_summary()}")

        assert report.overall_score > 0, "Should have non-zero score"
        assert report.slide_count == 2, "Should detect 2 slides"

        print("\n[OK] Quality analysis passed\n")

        return test_dir

    except Exception as e:
        print(f"[ERROR] Quality analysis failed: {e}")
        import traceback
        traceback.print_exc()
        return None


def main():
    """Run all tests."""
    print("\n" + "=" * 60)
    print("TOTALPIPE PRIORITY 1 & 2 FEATURES TEST SUITE")
    print("=" * 60 + "\n")

    try:
        test_font_discovery()
        test_path = test_validation()
        test_quality_metrics()
        test_dir = test_quality_analysis_mock()

        print("=" * 60)
        print("ALL TESTS PASSED")
        print("=" * 60)
        print("\nGenerated test files:")
        if test_path and test_path.exists():
            print(f"  - {test_path}")
        if test_dir and test_dir.exists():
            print(f"  - {test_dir}/")
        print("\nYou can test these with:")
        print(f"  python totalpipe.py validate {test_path}")
        if test_dir and test_dir.exists():
            print(f"  python totalpipe.py quality {test_dir}")
        print()

        return 0

    except AssertionError as e:
        print(f"\n[FAIL] Test failed: {e}")
        import traceback
        traceback.print_exc()
        return 1
    except Exception as e:
        print(f"\n[ERROR] Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return 2


if __name__ == '__main__':
    sys.exit(main())
