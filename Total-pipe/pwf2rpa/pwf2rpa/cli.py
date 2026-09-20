"""Command line interface for the PaperWorkflow -> RPA bridge."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from . import __version__
from .capacity import CATEGORIES, LAYOUT_LIBRARY_VERSION
from .convert import convert, load_specs, write_output
from .errors import AdapterError
from .story import HIGH_REASONING_EFFORTS, build_story_prompt, load_story
from .workflow import Workflow

__all__ = ["main", "build_parser"]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pwf_to_rpa",
        description="Convert a PaperWorkflow v4 workflow.json into Research PPT Assistant "
                    "content-model input.",
        epilog="Use --story for the evidence-grounded path. Without --story or "
               "--briefs, a deterministic legacy fallback is used.",
    )
    parser.add_argument("workflow", nargs="?", help="path to workflow.json (schema_version 4)")
    parser.add_argument(
        "--refresh-capacity",
        metavar="RPA_ROOT",
        help="rebuild the bundled layout capacity table from an RPA checkout and exit "
             "(requires node; only needed when RPA's layout library changes)",
    )
    planning = parser.add_mutually_exclusive_group()
    planning.add_argument("--briefs", metavar="PATH", help="slide-brief spec array (JSON)")
    planning.add_argument(
        "--story",
        metavar="PATH",
        help="Story Planner JSON produced by a user-selected high-reasoning subagent",
    )
    parser.add_argument(
        "--make-story-prompt",
        metavar="PATH",
        help="write a prompt package for the selected Story subagent and exit",
    )
    parser.add_argument("--story-model", metavar="MODEL", help="exact model explicitly selected by the user")
    parser.add_argument(
        "--story-reasoning",
        choices=sorted(HIGH_REASONING_EFFORTS),
        default="high",
        help="reasoning effort for the Story subagent (default: high)",
    )
    parser.add_argument(
        "--model-selected-by-user",
        action="store_true",
        help="confirm that the user explicitly selected --story-model",
    )
    parser.add_argument("--out", metavar="PATH", help="output path (default: rpa_input.json next to the workflow)")
    parser.add_argument(
        "--no-strict-fit",
        action="store_true",
        help="skip the layout-capacity simulation entirely",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="treat warnings (bad category hint, oversized page) as failures",
    )
    parser.add_argument("--quiet", action="store_true", help="suppress the per-slide summary")
    parser.add_argument(
        "--list-categories",
        action="store_true",
        help="print the legal category_hint values and exit",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__} "
                                                              f"(layout library {LAYOUT_LIBRARY_VERSION})")
    return parser


def _print_categories() -> int:
    width = max(len(name) for name in CATEGORIES)
    print(f"# {len(CATEGORIES)} legal category_hint values (layout library {LAYOUT_LIBRARY_VERSION})")
    for name in sorted(CATEGORIES):
        category = CATEGORIES[name]
        roomiest = max(category.layouts, key=lambda profile: profile.text_chars)
        print(
            f"{name:<{width}}  {category.name_zh:<14} "
            f"text<={roomiest.text_chars:<4} images<={max(p.image_capacity for p in category.layouts)}  "
            f"roles={','.join(category.roles)}"
        )
    return 0


def _summarise(payload: dict, out_path: Path) -> None:
    briefs = payload["slide_briefs"]
    print(f"wrote {out_path}")
    print(f"  slides: {len(briefs)}")
    for index, brief in enumerate(briefs, start=1):
        print(
            f"  {index:>2}. {brief.get('category_hint', '-'):<16} "
            f"{brief['title'][:34]:<36} "
            f"text={brief.get('text_chars', 0):<4} img={brief.get('image_count', 0)} "
            f"ev={','.join(brief.get('evidence_ids', [])) or '-'}"
        )


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI. Returns a POSIX exit status."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.refresh_capacity:
        from .refresh import refresh
        try:
            written = refresh(args.refresh_capacity)
        except (FileNotFoundError, RuntimeError) as error:
            print(f"{error}", file=sys.stderr)
            return 2
        print(f"regenerated {written}")
        return 0
    if args.list_categories:
        return _print_categories()
    if not args.workflow:
        parser.error("workflow path is required (or use --list-categories)")
    if args.make_story_prompt and (args.story or args.briefs):
        parser.error("--make-story-prompt cannot be combined with --story or --briefs")

    try:
        workflow = Workflow.from_path(args.workflow)
        workflow.validate()
        if args.make_story_prompt:
            package = build_story_prompt(
                workflow,
                model=args.story_model or "",
                reasoning_effort=args.story_reasoning,
                selected_by_user=args.model_selected_by_user,
            )
            write_output(package, args.make_story_prompt)
            print(f"wrote {args.make_story_prompt}")
            return 0
        specs = load_specs(args.briefs) if args.briefs else None
        story = load_story(args.story) if args.story else None
        payload, warnings = convert(
            workflow,
            specs,
            story=story,
            strict_fit=not args.no_strict_fit,
        )
    except AdapterError as error:
        print(str(error), file=sys.stderr)
        return 2

    for warning in warnings:
        print(warning.render(), file=sys.stderr)
    if warnings and args.strict:
        print(f"--strict: {len(warnings)} warning(s) treated as failure; nothing written",
              file=sys.stderr)
        return 3

    out_path = Path(args.out) if args.out else Path(args.workflow).parent / "rpa_input.json"
    write_output(payload, out_path)
    if not args.quiet:
        _summarise(payload, out_path)
        if warnings:
            print(f"  warnings: {len(warnings)} (RPA will still plan, but expect a degraded layout)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
