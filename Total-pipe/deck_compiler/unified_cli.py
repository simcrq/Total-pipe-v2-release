#!/usr/bin/env python3
"""
Unified CLI for Total-pipe v3 - Single entry point for all operations.

This module provides a simplified interface for AI agents and users:
- totalpipe generate: Full pipeline from inputs to PPTX
- totalpipe validate: Pre-check inputs before generation
- totalpipe preview: Generate slide screenshots
- totalpipe quality: Analyze presentation quality

Priority 1 implementation for AI usability.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

from . import pipeline
from .contracts import issue
from .errors import RecoverableError, AssetError, FontError, CapacityError
from .quality_metrics import analyze_quality, QualityReport
from .fonts import discover_fonts, validate_font_path


def generate_presentation(
    deck_ir_path: Path,
    out_dir: Path,
    layout_provider: str = "v26",
    officecli: str = "officecli",
    skip_native: bool = True,
    enable_overflow_repair: bool = True
) -> Tuple[bool, Optional[Path], Dict[str, Any]]:
    """
    One-function pipeline: Deck IR → PPTX

    Args:
        deck_ir_path: Path to canonical deck_ir.json
        out_dir: Output directory for build artifacts
        layout_provider: "v26" or "deterministic"
        officecli: OfficeCLI executable path or command
        skip_native: Skip native PowerPoint validation (dev mode)
        enable_overflow_repair: Enable automatic overflow repair

    Returns:
        Tuple of (success: bool, pptx_path: Optional[Path], qa_report: dict)
    """
    try:
        # Validate inputs first
        if not deck_ir_path.exists():
            raise RecoverableError(
                f"Deck IR not found: {deck_ir_path}",
                suggested_fix="Provide valid path to deck_ir.json",
                can_retry=True
            )

        deck_ir_path = deck_ir_path.resolve()
        out_dir = out_dir.resolve()

        # Run build pipeline
        layout_options = {'name': layout_provider}
        qa = pipeline.build(
            deck_ir_path,
            out_dir,
            not skip_native,
            officecli,
            layout_options
        )

        # Check results
        success = qa['counts']['FAIL'] == 0
        pptx_path = out_dir / 'candidate.pptx' if (out_dir / 'candidate.pptx').exists() else None

        return success, pptx_path, qa

    except Exception as e:
        # Convert to structured error
        if not isinstance(e, RecoverableError):
            e = RecoverableError(
                str(e),
                suggested_fix="Check error message and input files",
                can_retry=False
            )
        raise


def validate_inputs(
    deck_ir_path: Path,
    check_assets: bool = True,
    check_fonts: bool = True,
    check_capacity: bool = True
) -> Dict[str, Any]:
    """
    Validate inputs before generation (dry-run).

    Returns validation report with:
    - valid: bool
    - issues: List of validation problems
    - warnings: List of potential issues
    - estimated_slides: int
    - estimated_time_seconds: int
    """
    issues = []
    warnings = []

    # Load and parse Deck IR
    try:
        ir = json.loads(deck_ir_path.read_text(encoding='utf-8'))
    except Exception as e:
        issues.append({
            'type': 'DECK_IR_INVALID',
            'severity': 'FAIL',
            'message': f"Cannot parse deck_ir.json: {e}",
            'suggested_fix': "Ensure valid JSON and correct schema"
        })
        return {
            'valid': False,
            'issues': issues,
            'warnings': [],
            'estimated_slides': 0,
            'estimated_time_seconds': 0
        }

    # Check schema version
    if ir.get('schema_version') != '2.0':
        warnings.append({
            'type': 'SCHEMA_VERSION',
            'message': f"Expected schema_version 2.0, got {ir.get('schema_version')}"
        })

    # Validate theme and fonts
    if check_fonts:
        theme = ir.get('theme', {})
        font_file = theme.get('font_file')
        bold_font_file = theme.get('bold_font_file')

        if font_file:
            font_path = Path(font_file)
            if not font_path.exists():
                issues.append({
                    'type': 'FONT_UNAVAILABLE',
                    'severity': 'FAIL',
                    'path': str(font_file),
                    'message': f"Font file not found: {font_file}",
                    'suggested_fix': validate_font_path(font_file)
                })
        else:
            issues.append({
                'type': 'FONT_MISSING',
                'severity': 'FAIL',
                'message': "theme.font_file not specified",
                'suggested_fix': "Add font_file path in theme section"
            })

    # Validate assets
    if check_assets:
        assets = ir.get('assets', {})
        base_path = deck_ir_path.parent

        for asset_id, asset_info in assets.items():
            asset_path_str = asset_info.get('path', '')
            asset_path = Path(asset_path_str)

            # Try absolute first, then relative to deck_ir
            if not asset_path.is_absolute():
                asset_path = base_path / asset_path

            if not asset_path.exists():
                issues.append({
                    'type': 'ASSET_INVALID',
                    'severity': 'FAIL',
                    'asset_id': asset_id,
                    'path': str(asset_path_str),
                    'message': f"Asset not found: {asset_id}",
                    'suggested_fix': (
                        f"Place {asset_path.name} in images/ directory relative to deck_ir.json, "
                        f"or use absolute path: {asset_path.resolve()}"
                    )
                })

    # Estimate capacity
    slides = ir.get('slides', [])
    estimated_slides = len(slides)

    if check_capacity:
        for i, slide in enumerate(slides, 1):
            blocks = slide.get('composition', {}).get('blocks', [])
            for block in blocks:
                text = block.get('text', '')
                # Rough capacity check: >600 chars may overflow
                if len(text) > 600:
                    warnings.append({
                        'type': 'CAPACITY_WARNING',
                        'slide': i,
                        'block_id': block.get('id'),
                        'message': f"Slide {i} block {block.get('id')} has {len(text)} chars (>600 may overflow)",
                        'suggested_fix': "Consider splitting content or using overflow repair"
                    })

    # Estimate generation time
    # v26: ~2-5s per slide, deterministic: ~0.5s per slide
    estimated_time_seconds = estimated_slides * 3  # Conservative estimate

    return {
        'valid': len(issues) == 0,
        'issues': issues,
        'warnings': warnings,
        'estimated_slides': estimated_slides,
        'estimated_time_seconds': estimated_time_seconds
    }


def generate_preview(
    build_dir: Path,
    officecli: str = "officecli",
    format: str = "png",
    output_dir: Optional[Path] = None
) -> Dict[str, Any]:
    """
    Generate slide preview images.

    Args:
        build_dir: Build directory containing candidate.pptx
        officecli: OfficeCLI executable
        format: Output format ("png" or "html")
        output_dir: Optional output directory (defaults to build_dir/previews)

    Returns:
        {
            'status': 'success' | 'error',
            'preview_count': int,
            'preview_dir': str,
            'previews': [{'slide': 1, 'path': '...'}]
        }
    """
    from .officecli_review import review

    output_dir = output_dir or build_dir / 'previews'
    output_dir.mkdir(exist_ok=True)

    try:
        result = review(build_dir, officecli, format)

        # Move/copy screenshots to preview directory
        previews = []
        for page in result.get('pages', []):
            slide_num = page.get('page')
            if format == 'png':
                src = build_dir / f"officecli-slide-{slide_num}.png"
                if src.exists():
                    dest = output_dir / f"slide-{slide_num}.png"
                    import shutil
                    shutil.copy2(src, dest)
                    previews.append({'slide': slide_num, 'path': str(dest)})

        return {
            'status': 'success',
            'preview_count': len(previews),
            'preview_dir': str(output_dir),
            'previews': previews
        }
    except Exception as e:
        return {
            'status': 'error',
            'error': str(e),
            'preview_count': 0
        }


def main():
    """Unified CLI entry point."""
    parser = argparse.ArgumentParser(
        description='Total-pipe v3 - Unified CLI for research presentation generation',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Generate presentation
  totalpipe generate deck_ir.json --out build/

  # Validate before generation (dry-run)
  totalpipe validate deck_ir.json

  # Generate preview images
  totalpipe preview build/

  # Analyze quality
  totalpipe quality build/
"""
    )

    subparsers = parser.add_subparsers(dest='command', required=True, help='Command to run')

    # Generate command
    gen = subparsers.add_parser('generate', help='Generate PPTX from Deck IR')
    gen.add_argument('deck_ir', type=Path, help='Path to deck_ir.json')
    gen.add_argument('--out', type=Path, required=True, help='Output directory')
    gen.add_argument('--layout-provider', choices=['v26', 'deterministic'], default='v26',
                     help='Layout provider (default: v26)')
    gen.add_argument('--officecli', default='officecli', help='OfficeCLI executable')
    gen.add_argument('--no-overflow-repair', action='store_true',
                     help='Disable automatic overflow repair')
    gen.add_argument('--native', action='store_true',
                     help='Include native PowerPoint validation (requires PowerPoint)')

    # Validate command
    val = subparsers.add_parser('validate', help='Validate inputs (dry-run)')
    val.add_argument('deck_ir', type=Path, help='Path to deck_ir.json')
    val.add_argument('--skip-assets', action='store_true', help='Skip asset validation')
    val.add_argument('--skip-fonts', action='store_true', help='Skip font validation')
    val.add_argument('--skip-capacity', action='store_true', help='Skip capacity estimation')
    val.add_argument('--json', action='store_true', help='Output as JSON')

    # Preview command
    prev = subparsers.add_parser('preview', help='Generate slide previews')
    prev.add_argument('build_dir', type=Path, help='Build directory')
    prev.add_argument('--officecli', default='officecli', help='OfficeCLI executable')
    prev.add_argument('--format', choices=['png', 'html'], default='png',
                      help='Preview format (default: png)')
    prev.add_argument('--output', type=Path, help='Output directory (default: build_dir/previews)')

    # Quality command
    qual = subparsers.add_parser('quality', help='Analyze presentation quality')
    qual.add_argument('build_dir', type=Path, help='Build directory')
    qual.add_argument('--json', action='store_true', help='Output as JSON')
    qual.add_argument('--detailed', action='store_true', help='Include detailed analysis')

    args = parser.parse_args()

    try:
        if args.command == 'generate':
            print(f"[*] Generating presentation from {args.deck_ir}")
            print(f"    Output: {args.out}")
            print(f"    Layout provider: {args.layout_provider}")

            success, pptx_path, qa = generate_presentation(
                args.deck_ir,
                args.out,
                layout_provider=args.layout_provider,
                officecli=args.officecli,
                skip_native=not args.native,
                enable_overflow_repair=not args.no_overflow_repair
            )

            status_icon = "[OK]" if success else "[FAIL]"
            print(f"\n{status_icon} Status: {qa['status']}")
            print(f"    FAIL: {qa['counts']['FAIL']}")
            print(f"    WARNING: {qa['counts']['WARNING']}")
            print(f"    REVIEW: {qa['counts']['REVIEW']}")

            if pptx_path:
                print(f"\n[FILE] Generated: {pptx_path}")

            print(f"[REPORT] QA Report: {args.out / 'qa_report.json'}")

            return 0 if success else 1

        elif args.command == 'validate':
            print(f"[*] Validating {args.deck_ir}")

            result = validate_inputs(
                args.deck_ir,
                check_assets=not args.skip_assets,
                check_fonts=not args.skip_fonts,
                check_capacity=not args.skip_capacity
            )

            if args.json:
                print(json.dumps(result, indent=2))
            else:
                valid_icon = "[OK]" if result['valid'] else "[FAIL]"
                print(f"\n{valid_icon} Valid: {result['valid']}")
                print(f"    Issues: {len(result['issues'])}")
                print(f"    Warnings: {len(result['warnings'])}")
                print(f"    Estimated slides: {result['estimated_slides']}")
                print(f"    Estimated time: ~{result['estimated_time_seconds']}s")

                if result['issues']:
                    print("\n[!] Issues:")
                    for issue in result['issues']:
                        print(f"    {issue['type']}: {issue['message']}")
                        if 'suggested_fix' in issue:
                            print(f"       -> Fix: {issue['suggested_fix']}")

                if result['warnings']:
                    print("\n[WARNING] Warnings:")
                    for warning in result['warnings']:
                        print(f"    {warning['type']}: {warning['message']}")

            return 0 if result['valid'] else 1

        elif args.command == 'preview':
            print(f"[*] Generating preview images from {args.build_dir}")

            result = generate_preview(
                args.build_dir,
                officecli=args.officecli,
                format=args.format,
                output_dir=args.output
            )

            if result['status'] == 'success':
                print(f"\n[OK] Generated {result['preview_count']} preview images")
                print(f"    Preview directory: {result['preview_dir']}")
                for preview in result['previews']:
                    print(f"    Slide {preview['slide']}: {preview['path']}")
                return 0
            else:
                print(f"\n[FAIL] Preview generation failed: {result.get('error')}")
                return 1

        elif args.command == 'quality':
            print(f"[*] Analyzing presentation quality in {args.build_dir}")

            report = analyze_quality(args.build_dir, detailed=args.detailed)

            if args.json:
                print(report.to_json())
            else:
                print(report.to_summary())

            return 0

    except RecoverableError as e:
        print(f"\n[ERROR] {e.message}", file=sys.stderr)
        if e.suggested_fix:
            print(f"    [FIX] {e.suggested_fix}", file=sys.stderr)
        if e.can_retry:
            print(f"    [INFO] This error can be fixed and retried", file=sys.stderr)
        return 2

    except Exception as e:
        print(f"\n[ERROR] Unexpected error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 2


if __name__ == '__main__':
    sys.exit(main())
