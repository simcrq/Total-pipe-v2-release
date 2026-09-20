"""Deterministic fallback briefs, used when no ``--briefs`` file is supplied.

The point is not to write a good talk -- only a human or an LLM can do that.
The point is to produce a *valid, plannable* deck from the evidence alone, so
the pipeline can be exercised end to end and the result can be edited into
shape instead of authored from nothing.

Strategy: group evidence by ``query_ids`` (PaperWorkflow's retrieval intents),
map each intent to the layout category that matches its narrative job, then
compress evidence text into claims short enough for that category's slots.
Everything is derived from registry order, so the output is reproducible.
"""

from __future__ import annotations

import re
from typing import Any, Mapping

from . import fit
from .workflow import Evidence, Workflow

__all__ = ["fallback_specs", "INTENT_CATEGORIES"]

#: PaperWorkflow query intent -> (layout category, page title, narrative job).
#: Intents come from the literature workflow's query set; unknown intents fall
#: back to a neutral evidence page rather than guessing.
INTENT_CATEGORIES: dict[str, tuple[str, str, str]] = {
    "objective": ("question", "研究目标与核心问题", "motivation"),
    "background": ("background", "研究背景", "context"),
    "methods": ("method_overview", "方法与实验设置", "method"),
    "results": ("chart_takeaway", "主要结果", "evidence"),
    "discussion": ("discussion", "讨论", "interpretation"),
    "limitations": ("limitations", "局限与边界", "limitations"),
    "conclusion": ("summary", "结论", "summary"),
    "future_work": ("next_steps", "后续工作", "next_steps"),
    "unassigned": ("background", "补充证据", "context"),
}

_FALLBACK_CATEGORY = ("background", "证据", "context")

#: Sentence-ish boundaries used to cut evidence text into claim-sized pieces.
_BOUNDARY = re.compile(r"(?<=[。！？；.;!?])\s*|(?<=,)\s+")


def _clauses(text: str) -> list[str]:
    """Split evidence prose into candidate claims, longest-first order kept."""
    parts = [part.strip() for part in _BOUNDARY.split(text) if part and part.strip()]
    return parts or ([text.strip()] if text.strip() else [])


def _claim_from(evidence: Evidence, limit: int) -> str:
    """Compress one evidence entry into a claim of at most ``limit`` chars.

    Prefers a whole clause that already fits; only falls back to a hard cut
    with an ellipsis when no clause is short enough, mirroring how RPA itself
    truncates deterministically.
    """
    candidates = _clauses(evidence.text)
    fitting = [clause for clause in candidates if len(clause) <= limit]
    if fitting:
        return max(fitting, key=len)
    head = candidates[0] if candidates else evidence.text
    if len(head) <= limit:
        return head
    if limit <= 3:
        return head[:limit]
    cut = head[: limit - 3].rstrip()
    return f"{cut}..."


def _title(base: str, limit: int) -> str:
    return base if len(base) <= limit else base[: max(1, limit - 1)] + "…"


def fallback_specs(workflow: Workflow) -> list[dict[str, Any]]:
    """Derive one brief spec per query intent, plus a cover and a summary.

    Args:
        workflow: The indexed workflow to mine.

    Returns:
        Brief specs in presentation order, ready for :func:`~pwf2rpa.briefs.build_briefs`.
        Every page is guaranteed to satisfy its category's capacity envelope.
    """
    grouped = workflow.by_query_id()
    specs: list[dict[str, Any]] = []

    cover_evidence = [evidence.evidence_id for evidence in list(workflow.evidence.values())[:2]]
    cover_title = _title(workflow.title, max((layout.title_chars or 0) for layout in fit.CATEGORIES["cover"].layouts) or 16)
    specs.append(
        {
            "slide_type": "cover",
            "category_hint": "cover",
            "title": cover_title,
            "evidence_ids": cover_evidence,
            "content_roles": ["primary_claim"],
            "narrative_job": "cover",
        }
    )

    # Sort intents by their position in INTENT_CATEGORIES so the deck follows a
    # sensible arc; unknown intents keep registry order at the end.
    order = list(INTENT_CATEGORIES)

    def intent_key(intent: str) -> tuple[int, str]:
        return (order.index(intent) if intent in order else len(order), intent)

    for intent in sorted(grouped, key=intent_key):
        entries = grouped[intent]
        category, title, narrative_job = INTENT_CATEGORIES.get(intent, _FALLBACK_CATEGORY)
        claim_limit = fit.max_claim_chars(category) or 32
        # Keep claims comfortably inside the roomiest slot so the page still
        # fits after RPA's own bookkeeping.
        claim_limit = max(12, min(claim_limit, 32))

        claims: list[str] = []
        evidence_ids: list[str] = []
        for evidence in entries:
            claim = _claim_from(evidence, claim_limit)
            if claim and claim not in claims:
                claims.append(claim)
            evidence_ids.append(evidence.evidence_id)

        spec: dict[str, Any] = {
            "slide_type": "custom",
            "category_hint": category,
            "title": _title(f"{title}", 26),
            "claims": claims,
            "evidence_ids": evidence_ids,
            "content_roles": ["primary_claim", "primary_evidence"],
            "narrative_job": narrative_job,
        }
        specs.append(_shrink_to_fit(spec, category))

    specs.append(
        {
            "slide_type": "summary",
            "category_hint": "summary",
            "title": "总结与讨论",
            "claims": [],
            "evidence_ids": cover_evidence,
            "content_roles": ["primary_claim"],
            "narrative_job": "summary",
        }
    )
    return specs


def _shrink_to_fit(spec: Mapping[str, Any], category: str) -> dict[str, Any]:
    """Drop trailing claims until the page fits its category.

    Evidence ids are never dropped: they are the traceability contract, and
    slot binding folds surplus ids into an existing reference slot rather than
    failing.  Claims are the elastic part.
    """
    result = dict(spec)
    claims = list(result.get("claims", []))
    while True:
        shape = fit.PageShape(
            category=category,
            title=result.get("title", ""),
            text_items=tuple(
                fit.TextItem(f"claims[{index}]", claim, ("callout", "text"), False)
                for index, claim in enumerate(claims)
            ),
            visuals=(),
        )
        if fit.evaluate(shape).fits or not claims:
            break
        claims.pop()
    result["claims"] = claims
    return result
