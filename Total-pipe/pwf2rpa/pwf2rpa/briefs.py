"""Turn compact slide-brief specs into RPA SLIDE_BRIEF objects.

This is the half of the bridge RPA cannot do for you.  ``normalize_content``
adapts ``paperworkflow_v4`` into Source/Citation/Evidence natively, but it
never invents slides: without ``slide_briefs`` there is nothing to plan.

The builder enforces the four rules that RPA punishes silently or loudly:

1. ``evidence_ids`` must resolve to real ``EV####`` entries, else
   normalize-content reports "does not resolve to Evidence".
2. ``category_hint`` must be one of the 40 real layout category ids.  A free
   string (a narrative label, say) is not an error -- it is worse: RPA relaxes
   to a whole-library search and picks a mismatched layout.
3. Every text item must fit some slot of that category, or slot binding raises
   ``SLOT_CAPACITY_EXCEEDED``.
4. Output must be byte-identical for identical input: no clocks, no uuids, no
   set iteration order.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from . import fit
from .errors import BriefError, Problem
from .workflow import Workflow

__all__ = ["build_briefs", "SPEC_FIELDS", "DEFAULT_VISUAL_TYPE"]

DEFAULT_VISUAL_TYPE = "visual_evidence"

#: Fields a spec may set. Anything else is a typo worth reporting, since RPA
#: silently drops unknown keys and the author never learns their hint was lost.
SPEC_FIELDS = frozenset(
    {
        "slide_type", "category_hint", "title", "goal", "claims", "takeaway",
        "question", "notes", "narrative_job", "evidence_ids", "citation_ids",
        "body", "evidence_texts",
        "visuals", "comparison_dimensions", "process_steps", "timeline_events",
        "experiment_groups", "data_series", "content_roles", "image_count",
        "text_chars", "title_chars", "table_count", "chart_count",
        "process_step_count", "duration_weight", "viewing_mode",
        "density_preference", "allow_auto_split", "metadata",
    }
)

#: Which brief fields become which slot-binding item types. Order matters: it
#: is the order collectContentItems emits them, and therefore the order slots
#: are consumed in.
_TEXT_FIELDS: tuple[tuple[str, tuple[str, ...], bool], ...] = (
    ("goal", ("text", "callout"), False),
    ("takeaway", ("callout", "text"), False),
    ("question", ("question", "text"), False),
    ("notes", ("text", "caption"), True),
    # body carries the page's full prose (the scientific argument), not a
    # 10-char callout label. It prefers a "text" slot and may be trimmed to
    # the slot's capacity, which is exactly what a long body paragraph needs.
    ("body", ("text",), True),
)

_VISUAL_KEYS = frozenset(
    {
        "visual_type", "panel_count", "has_embedded_text", "caption", "title",
        "description", "alt_text", "label", "figure_table_ref", "importance",
        "must_keep", "asset_uri", "uri", "visual_id", "evidence_ids",
        "citation_ids", "min_display_width", "visual_aspect_ratio",
    }
)


def _text(value: Any) -> str:
    return " ".join(value.split()) if isinstance(value, str) else ""


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, Sequence):
        return [item.strip() for item in value if isinstance(item, str) and item.strip()]
    return []


def _claim_text(value: Any) -> str:
    """Claims may be plain strings or objects; RPA reads text-ish keys."""
    if isinstance(value, str):
        return _text(value)
    if isinstance(value, Mapping):
        for key in ("text", "claim", "claim_text", "title", "label"):
            text = _text(value.get(key))
            if text:
                return text
    return ""


def _normalize_visual(raw: Any, path: str, problems: list[Problem]) -> dict[str, Any] | None:
    """Coerce one visual to the RPA VISUAL schema subset."""
    if isinstance(raw, str):
        raw = {"visual_type": DEFAULT_VISUAL_TYPE, "caption": raw}
    if not isinstance(raw, Mapping):
        problems.append(
            Problem("VISUAL_NOT_OBJECT", path, "visual must be an object or a caption string.",
                    actual=type(raw).__name__)
        )
        return None

    unknown = sorted(set(raw) - _VISUAL_KEYS)
    if unknown:
        problems.append(
            Problem("VISUAL_UNKNOWN_FIELD", path,
                    "RPA drops unknown visual fields; the hint would be lost silently.",
                    actual=unknown, expected=sorted(_VISUAL_KEYS),
                    hint="Remove the field or move it into `caption`.",
                    severity="warning")
        )

    visual: dict[str, Any] = {"visual_type": _text(raw.get("visual_type")) or DEFAULT_VISUAL_TYPE}

    panel_count = raw.get("panel_count", 1)
    if not isinstance(panel_count, int) or isinstance(panel_count, bool) or panel_count < 1:
        problems.append(
            Problem("VISUAL_PANEL_COUNT_INVALID", f"{path}.panel_count",
                    "panel_count must be an integer >= 1.", actual=panel_count, expected=">= 1")
        )
        panel_count = 1
    visual["panel_count"] = panel_count
    visual["has_embedded_text"] = bool(raw.get("has_embedded_text", False))

    for key in ("caption", "title", "description", "alt_text", "label", "figure_table_ref", "asset_uri", "uri", "visual_id"):
        text = _text(raw.get(key))
        if text:
            visual[key] = text
    for key in ("evidence_ids", "citation_ids"):
        values = _string_list(raw.get(key))
        if values:
            visual[key] = values
    if isinstance(raw.get("importance"), int) and not isinstance(raw.get("importance"), bool):
        visual["importance"] = raw["importance"]
    if "must_keep" in raw:
        visual["must_keep"] = bool(raw["must_keep"])
    for key in ("min_display_width", "visual_aspect_ratio"):
        value = raw.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
            visual[key] = value

    return visual


def _shape_for(brief: Mapping[str, Any], category: str) -> fit.PageShape:
    """Project a finished brief onto the fields RPA's capacity gates read."""
    items: list[fit.TextItem] = []
    for field, preferred, trimmable in _TEXT_FIELDS:
        text = brief.get(field, "")
        if text:
            items.append(fit.TextItem(field, text, preferred, trimmable))
    for index, claim in enumerate(brief.get("claims", [])):
        text = _claim_text(claim)
        if text:
            items.append(fit.TextItem(f"claims[{index}]", text, ("callout", "text"), False))

    visuals = tuple(
        fit.VisualItem(
            visual_type=visual.get("visual_type", DEFAULT_VISUAL_TYPE),
            panel_count=visual.get("panel_count", 1),
            has_embedded_text=bool(visual.get("has_embedded_text", False)),
        )
        for visual in brief.get("visuals", [])
    )
    return fit.PageShape(
        category=category,
        title=brief.get("title", ""),
        text_items=tuple(items),
        visuals=visuals,
        table_count=brief.get("table_count", 0),
        chart_count=brief.get("chart_count", 0),
        process_step_count=brief.get("process_step_count", 0),
    )


def _build_one(
    spec: Mapping[str, Any],
    index: int,
    workflow: Workflow,
    problems: list[Problem],
    *,
    strict_fit: bool,
) -> dict[str, Any]:
    """Assemble one SLIDE_BRIEF and record every contract breach found."""
    path = f"briefs[{index}]"

    if not isinstance(spec, Mapping):
        problems.append(
            Problem("BRIEF_NOT_OBJECT", path, "each slide brief must be a JSON object.",
                    actual=type(spec).__name__)
        )
        return {}

    unknown = sorted(set(spec) - SPEC_FIELDS)
    if unknown:
        problems.append(
            Problem("BRIEF_UNKNOWN_FIELD", path,
                    "unknown brief field; RPA would drop it without warning.",
                    actual=unknown,
                    hint="Check the spelling against the SLIDE_BRIEF contract.",
                    severity="warning")
        )

    title = _text(spec.get("title"))
    if not title:
        problems.append(
            Problem("BRIEF_TITLE_MISSING", f"{path}.title",
                    "title is the only required slide-brief field.",
                    hint="Give the page an assertion-style headline.")
        )

    # -- rule 2: category_hint must be a real layout category id ----------
    category = _text(spec.get("category_hint"))
    if not category:
        problems.append(
            Problem("CATEGORY_HINT_MISSING", f"{path}.category_hint",
                    "without a category hint RPA searches the whole library and misplaces the page.",
                    expected=fit.category_ids(),
                    hint="Pick the category matching this page's job, e.g. 'figure_text'.",
                    severity="warning")
        )
    elif not fit.is_known_category(category):
        suggestions = fit.suggest_categories(category)
        problems.append(
            Problem("CATEGORY_HINT_UNKNOWN", f"{path}.category_hint",
                    "not an RPA layout category; RPA would relax to a whole-library search.",
                    actual=category, expected=fit.category_ids(),
                    hint=f"Did you mean {', '.join(suggestions)}?" if suggestions
                         else "narrative_job-style labels are not category ids.",
                    severity="warning")
        )

    # -- rule 1: evidence_ids must resolve --------------------------------
    evidence_ids: list[str] = []
    for position, evidence_id in enumerate(_string_list(spec.get("evidence_ids"))):
        if evidence_id in evidence_ids:
            continue  # duplicates would fight over the same slot
        if not workflow.has_evidence(evidence_id):
            problems.append(
                Problem("UNKNOWN_EVIDENCE_ID", f"{path}.evidence_ids[{position}]",
                        "evidence_id does not exist in evidence_registry.",
                        actual=evidence_id, expected=workflow.evidence_ids,
                        hint="Cite an EV#### from this workflow, or drop the reference.")
            )
            continue
        evidence_ids.append(evidence_id)

    claims = [text for text in (_claim_text(claim) for claim in spec.get("claims", []) or []) if text]

    visuals: list[dict[str, Any]] = []
    for position, raw_visual in enumerate(spec.get("visuals", []) or []):
        visual = _normalize_visual(raw_visual, f"{path}.visuals[{position}]", problems)
        if visual is not None:
            visuals.append(visual)

    brief: dict[str, Any] = {
        "slide_type": _text(spec.get("slide_type")) or category or "custom",
        "title": title,
        "goal": _text(spec.get("goal")),
        "claims": claims,
        "process_steps": list(spec.get("process_steps", []) or []),
        "timeline_events": list(spec.get("timeline_events", []) or []),
        "comparison_dimensions": list(spec.get("comparison_dimensions", []) or []),
        "experiment_groups": list(spec.get("experiment_groups", []) or []),
        "data_series": list(spec.get("data_series", []) or []),
        "visuals": visuals,
        "citation_ids": _string_list(spec.get("citation_ids")),
        "evidence_ids": evidence_ids,
        "duration_weight": spec.get("duration_weight", 1),
    }
    if category:
        brief["category_hint"] = category

    for field in ("takeaway", "question", "notes", "narrative_job", "body"):
        text = _text(spec.get(field))
        if text:
            brief[field] = text

    # P0: carry the referenced evidence source text alongside the brief so a
    # downstream drafting role can expand it into full prose without
    # re-opening the workflow. The registry text is the paper's original
    # wording and is reference material, not page copy; page copy belongs in
    # ``body``. An explicit ``evidence_texts`` in the spec wins, otherwise the
    # registry text for each cited ``evidence_id`` is collected.
    supplied_evidence_texts = spec.get("evidence_texts")
    if isinstance(supplied_evidence_texts, Sequence) and not isinstance(supplied_evidence_texts, (str, bytes)):
        evidence_texts = supplied_evidence_texts
    else:
        evidence_texts = [
            {"evidence_id": evidence_id, "text": evidence.text}
            for evidence_id in evidence_ids
            for evidence in (workflow.get(evidence_id),)
            if evidence is not None and evidence.text
        ]
    if evidence_texts:
        brief["evidence_texts"] = evidence_texts

    # Counters RPA uses for retrieval. Deriving them from the actual content
    # keeps the query honest; an author-supplied value that contradicts the
    # content would make RPA shop for the wrong layout.
    brief["title_chars"] = len(title)
    brief["image_count"] = len(visuals)
    brief["text_chars"] = sum(
        len(text)
        for text in (
            [brief.get("goal", ""), brief.get("takeaway", ""), brief.get("question", ""), brief.get("notes", ""), brief.get("body", "")]
            + claims
        )
        if text
    )
    for field, default in (("table_count", 0), ("chart_count", 0)):
        value = spec.get(field, default)
        brief[field] = value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else default
    brief["process_step_count"] = len(brief["process_steps"])

    content_roles = _string_list(spec.get("content_roles"))
    if content_roles:
        brief["content_roles"] = content_roles

    for field in ("viewing_mode", "density_preference"):
        text = _text(spec.get(field))
        if text:
            brief[field] = text
    if "allow_auto_split" in spec:
        brief["allow_auto_split"] = bool(spec["allow_auto_split"])
    if isinstance(spec.get("metadata"), Mapping):
        brief["metadata"] = dict(spec["metadata"])

    # -- rule 3: everything must fit some layout of the category ----------
    if category and fit.is_known_category(category):
        report = fit.evaluate(_shape_for(brief, category))
        if not report.fits and strict_fit:
            limit = fit.max_claim_chars(category)
            problems.append(
                Problem("CAPACITY_EXCEEDED", path,
                        f"no layout in category {category!r} can hold this page: "
                        + "; ".join(report.reasons),
                        expected=report.limits,
                        hint=(f"Shorten claims to <= {limit} chars, cut a claim, or "
                              "move the overflow to a second page.") if limit else
                             "Shorten the page or split it in two.",
                        severity="warning")
            )

    return brief


def build_briefs(
    specs: Sequence[Mapping[str, Any]],
    workflow: Workflow,
    *,
    strict_fit: bool = True,
) -> tuple[list[dict[str, Any]], list[Problem]]:
    """Build RPA slide briefs from compact specs, validating against ``workflow``.

    Problems are split by severity, mirroring how RPA itself reacts:

    * ``error`` problems (an unresolvable evidence id, a missing title) abort,
      because RPA would refuse the input anyway.
    * ``warning`` problems (a bad category hint, an oversized page) are
      returned. RPA still emits a deck for these -- just a degraded one, with
      the category hint relaxed to a whole-library search -- so whether that
      is acceptable is the caller's call, not the adapter's.

    Args:
        specs: Slide-brief specs, one per page, in presentation order.
        workflow: The indexed PaperWorkflow the briefs must cite.
        strict_fit: Check each page against its category's layout capacity.
            Disable only to inspect a deliberately oversized draft.

    Returns:
        ``(briefs, warnings)``: briefs ready to place under ``slide_briefs``,
        and the non-blocking problems found along the way.

    Raises:
        BriefError: if any blocking problem was found.
    """
    if not isinstance(specs, Sequence) or isinstance(specs, (str, bytes)):
        raise BriefError(
            [Problem("BRIEFS_NOT_ARRAY", "briefs", "briefs file must contain a JSON array of specs.",
                     actual=type(specs).__name__)],
            summary="Unusable briefs file",
        )
    if not specs:
        raise BriefError(
            [Problem("BRIEFS_EMPTY", "briefs", "briefs file has no slides.",
                     hint="Write at least one brief, or omit --briefs to use the fallback.")],
            summary="Unusable briefs file",
        )
    if len(specs) > 40:
        raise BriefError(
            [Problem("BRIEFS_TOO_MANY", "briefs", "RPA plans at most 40 slides.",
                     actual=len(specs), expected="<= 40")],
            summary="Unusable briefs file",
        )

    problems: list[Problem] = []
    briefs = [
        _build_one(spec, index, workflow, problems, strict_fit=strict_fit)
        for index, spec in enumerate(specs)
    ]

    # Deck-level check. RPA feeds already-used layout ids back as exclude_ids,
    # so reusing one category across many pages pushes later pages onto ever
    # more cramped variants and finally off the category entirely. No
    # per-page check can see this.
    if strict_fit:
        used = [brief["category_hint"] for brief in briefs if brief.get("category_hint")]
        exhausted = fit.overused_categories(used)
        for category, count in sorted(exhausted.items()):
            problems.append(
                Problem("CATEGORY_EXHAUSTED", "briefs",
                        f"category {category!r} is used on {count} pages but the library has only "
                        f"{fit.LAYOUTS_PER_CATEGORY} layouts for it; RPA will run out and relax the hint.",
                        actual=count, expected=f"<= {fit.LAYOUTS_PER_CATEGORY}",
                        hint="Spread these pages across related categories.",
                        severity="warning")
            )
        shapes = [
            _shape_for(brief, brief["category_hint"])
            for brief in briefs
            if brief.get("category_hint")
        ]
        for index, category, available in fit.crowded_pages(shapes):
            # A page that fits no layout at all was already reported per-page
            # as CAPACITY_EXCEEDED; repeating it as contention is just noise.
            if category in exhausted or available == 0:
                continue
            problems.append(
                Problem("CATEGORY_CROWDED", f"briefs[{index}]",
                        f"only {available} layout(s) in category {category!r} can hold a page this "
                        "size, and earlier pages of the deck already need them; RPA excludes "
                        "already-used layouts, so this page will be pushed off its category.",
                        actual=available,
                        hint="Shorten this page so more layout variants fit, or use another category.",
                        severity="warning")
            )

    blocking = [problem for problem in problems if problem.severity == "error"]
    if blocking:
        raise BriefError(problems, summary=f"{len(blocking)} blocking slide-brief problem(s)")
    return briefs, [problem for problem in problems if problem.severity == "warning"]
