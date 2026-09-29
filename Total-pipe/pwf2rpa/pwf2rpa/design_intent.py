"""Optional, geometry-free visual intent between Story and RPA."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from .errors import Problem, StoryError

__all__ = ["apply_design_intent", "load_design_intent"]

_ROOT_FIELDS = frozenset({"slides"})
_SLIDE_FIELDS = frozenset({"story_node_index", "relation", "orientation", "emphasis"})
_GEOMETRY_FIELDS = frozenset({"bbox", "x", "y", "w", "h", "width", "height", "region", "box"})


def load_design_intent(path: str | Path) -> Any:
    """Read the optional intent JSON; validate it against the Story later."""
    path = Path(path)
    try:
        source = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise StoryError(
            [Problem("DESIGN_INTENT_READ_FAILED", str(path), f"cannot read design intent: {exc}")],
            summary="Unusable design intent",
        ) from exc
    try:
        return json.loads(source)
    except json.JSONDecodeError as exc:
        raise StoryError(
            [Problem("DESIGN_INTENT_NOT_JSON", f"{path}:{exc.lineno}:{exc.colno}",
                     f"design intent is not valid JSON: {exc.msg}")],
            summary="Unusable design intent",
        ) from exc


def apply_design_intent(specs: list[dict[str, Any]], raw: Any) -> None:
    """Attach only supported Story-node topology; never add content or geometry."""
    if not isinstance(raw, Mapping):
        raise StoryError(
            [Problem("DESIGN_INTENT_NOT_OBJECT", "design_intent",
                     "design intent must be an object with a slides array.")],
            summary="Unusable design intent",
        )

    problems: list[Problem] = []
    unknown_root = sorted(set(raw) - _ROOT_FIELDS)
    if unknown_root:
        problems.append(Problem("DESIGN_INTENT_UNKNOWN_FIELD", "design_intent",
                                "unknown design intent field.", actual=unknown_root))
    slides = raw.get("slides")
    if not isinstance(slides, list):
        problems.append(Problem("DESIGN_INTENT_SLIDES_NOT_ARRAY", "design_intent.slides",
                                "slides must be an array."))
        slides = []

    by_node = {
        spec["metadata"]["story_node_index"]: spec
        for spec in specs
        if isinstance(spec.get("metadata"), Mapping)
        and isinstance(spec["metadata"].get("story_node_index"), int)
    }
    seen: set[int] = set()
    assignments: list[tuple[dict[str, Any], int | None]] = []
    for position, entry in enumerate(slides):
        path = f"design_intent.slides[{position}]"
        if not isinstance(entry, Mapping):
            problems.append(Problem("DESIGN_INTENT_SLIDE_NOT_OBJECT", path,
                                    "each slide intent must be an object."))
            continue
        unknown = set(entry) - _SLIDE_FIELDS
        geometry = sorted(unknown & _GEOMETRY_FIELDS)
        if geometry:
            problems.append(Problem("DESIGN_INTENT_GEOMETRY_FORBIDDEN", path,
                                    "design intent cannot contain coordinates or boxes.",
                                    actual=geometry))
        other_unknown = sorted(unknown - _GEOMETRY_FIELDS)
        if other_unknown:
            problems.append(Problem("DESIGN_INTENT_UNKNOWN_FIELD", path,
                                    "unknown slide intent field.", actual=other_unknown))
        index = entry.get("story_node_index")
        if type(index) is not int or index not in by_node:
            problems.append(Problem("DESIGN_INTENT_NODE_INVALID", f"{path}.story_node_index",
                                    "story_node_index must identify a Story reasoning node.",
                                    actual=index, expected=sorted(by_node)))
            continue
        if index in seen:
            problems.append(Problem("DESIGN_INTENT_DUPLICATE_NODE", f"{path}.story_node_index",
                                    "each Story node can have only one design intent.",
                                    actual=index))
            continue
        seen.add(index)
        if entry.get("relation") != "process":
            problems.append(Problem("DESIGN_INTENT_RELATION_UNSUPPORTED", f"{path}.relation",
                                    "only process is supported.", actual=entry.get("relation"),
                                    expected="process"))
        if entry.get("orientation") != "vertical":
            problems.append(Problem("DESIGN_INTENT_ORIENTATION_UNSUPPORTED", f"{path}.orientation",
                                    "only vertical is supported.", actual=entry.get("orientation"),
                                    expected="vertical"))
        emphasis = entry.get("emphasis")
        if "emphasis" in entry and (type(emphasis) is not int or not 1 <= emphasis <= 4):
            problems.append(Problem("DESIGN_INTENT_EMPHASIS_INVALID", f"{path}.emphasis",
                                    "emphasis must be a 1-based key_points index from 1 to 4.",
                                    actual=emphasis, expected="1..4"))
        spec = by_node[index]
        if len(spec.get("key_points", [])) != 4:
            problems.append(Problem("DESIGN_INTENT_KEY_POINTS_REQUIRED", path,
                                    "process intent requires exactly four Story key_points.",
                                    actual=len(spec.get("key_points", [])), expected=4))
        assignments.append((spec, emphasis if "emphasis" in entry else None))

    if problems:
        raise StoryError(problems, summary="Unusable design intent")

    for spec, emphasis in assignments:
        visual_intent: dict[str, Any] = {
            "relation": "process",
            "source": "key_points",
            "member_count": 4,
            "orientation": "vertical",
            "preserve_order": True,
        }
        if emphasis is not None:
            visual_intent["emphasis_index"] = emphasis
        spec["metadata"]["visual_intent"] = visual_intent
        spec["allow_auto_split"] = False
