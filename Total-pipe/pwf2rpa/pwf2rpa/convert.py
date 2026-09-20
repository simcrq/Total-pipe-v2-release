"""Assemble the final ``normalize_content`` / ``create_deck_plan`` input."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from .briefs import build_briefs
from .errors import BriefError, Problem
from .fallback import fallback_specs
from .story import story_to_specs
from .workflow import Workflow

__all__ = ["convert", "write_output", "load_specs"]


def convert(
    workflow: Workflow,
    specs: Sequence[Mapping[str, Any]] | None = None,
    *,
    story: Any | None = None,
    strict_fit: bool = True,
) -> tuple[dict[str, Any], list[Problem]]:
    """Build the two-key payload RPA expects.

    ``paperworkflow_v4`` is passed through untouched -- RPA's own adapter turns
    the evidence registry into Source/Citation/Evidence, and re-deriving those
    here would only risk drift.  ``slide_briefs`` is the part RPA cannot infer.

    Args:
        workflow: A validated workflow.
        specs: Slide-brief specs; mutually exclusive with ``story``. When both
            are ``None`` a deterministic legacy fallback deck is derived.
        story: Validated Story Planner JSON produced by a user-selected,
            high-reasoning subagent. It is converted into semantic briefs.
        strict_fit: Check each page against its category's layout capacity.

    Returns:
        ``(payload, warnings)`` where payload is
        ``{"paperworkflow_v4": ..., "slide_briefs": [...]}``.

    Raises:
        BriefError: if the specs breach the slide-brief contract in a way RPA
            would reject.
    """
    if specs is not None and story is not None:
        raise BriefError(
            [Problem("STORY_AND_BRIEFS_CONFLICT", "$", "provide either story or briefs, not both.")],
            summary="Ambiguous planning input",
        )
    story_warnings: list[Problem] = []
    if story is not None:
        resolved, story_warnings = story_to_specs(story, workflow)
    else:
        resolved = fallback_specs(workflow) if specs is None else specs
    briefs, warnings = build_briefs(resolved, workflow, strict_fit=strict_fit)
    payload = {
        "paperworkflow_v4": workflow.document,
        "slide_briefs": briefs,
    }
    return payload, story_warnings + warnings


def load_specs(path: str | Path) -> list[Mapping[str, Any]]:
    """Read a briefs JSON file.

    Accepts either a bare array of specs or ``{"slide_briefs": [...]}`` so the
    adapter's own output can be fed back in during editing loops.
    """
    path = Path(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise BriefError(
            [Problem("BRIEFS_NOT_FOUND", str(path), "briefs file does not exist.")],
            summary=f"Cannot read {path}",
        ) from exc
    except json.JSONDecodeError as exc:
        raise BriefError(
            [Problem("BRIEFS_NOT_JSON", f"{path}:{exc.lineno}:{exc.colno}",
                     f"briefs file is not valid JSON: {exc.msg}")],
            summary=f"Cannot parse {path}",
        ) from exc

    if isinstance(raw, Mapping):
        for key in ("slide_briefs", "briefs"):
            if isinstance(raw.get(key), list):
                return raw[key]
        raise BriefError(
            [Problem("BRIEFS_NOT_ARRAY", str(path),
                     "expected an array of specs or an object with `slide_briefs`.",
                     actual=sorted(raw))],
            summary=f"Cannot use {path}",
        )
    if not isinstance(raw, list):
        raise BriefError(
            [Problem("BRIEFS_NOT_ARRAY", str(path), "expected a JSON array of specs.",
                     actual=type(raw).__name__)],
            summary=f"Cannot use {path}",
        )
    return raw


def write_output(payload: Mapping[str, Any], path: str | Path) -> Path:
    """Write ``payload`` deterministically.

    Byte-stability matters: the same workflow and briefs must produce the same
    file so downstream caches, diffs and CI comparisons stay meaningful. Hence
    fixed indentation, no sorting surprises, and a trailing newline.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False)
    path.write_text(text + "\n", encoding="utf-8")
    return path
