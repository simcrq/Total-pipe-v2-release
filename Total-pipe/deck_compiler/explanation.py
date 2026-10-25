"""Evidence-bound reader obligations carried by canonical Deck IR.

The Story Planner says what the audience must see.  This module checks that the
canonical IR actually carries that structure with a native object, and produces
the deterministic coverage ledger used by QA.  It never chooses a layout and it
never edits scientific content.
"""
from __future__ import annotations

import re

from .contracts import digest, issue


KINDS = (
    "quantity",
    "parallel_items",
    "grouped_panels",
    "comparison",
    "ordered_steps",
    "relation",
    "curve",
    "image_evidence",
)
CARRIERS = (
    "inline_math",
    "formula",
    "native_list",
    "table",
    "layout_tree",
    "process",
    "dag",
    "mechanism",
    "path",
    "figure",
)
STATUSES = ("bound", "waived", "unsupported")
KIND_CARRIERS = {
    "quantity": ("inline_math", "formula"),
    "parallel_items": ("native_list", "table", "layout_tree"),
    "grouped_panels": ("layout_tree",),
    "comparison": ("table", "layout_tree"),
    "ordered_steps": ("process", "dag", "native_list"),
    "relation": ("mechanism", "dag"),
    "curve": ("path",),
    "image_evidence": ("figure",),
}
_OBLIGATION_FIELDS = {"id", "kind", "required", "primary", "carrier", "status", "content",
                      "evidence_refs", "source_quote", "note"}
_EXPLANATION_FIELDS = {"reader_task", "must_not_lose", "obligations"}


def _text(value):
    return " ".join(value.split()) if isinstance(value, str) else ""


def _strings(value):
    if not isinstance(value, list):
        return []
    return [_text(item) for item in value if _text(item)]


def _graphic_types(graphic):
    if not isinstance(graphic, dict):
        return []
    kinds = [graphic.get("type")]
    for component in graphic.get("components", []) or []:
        kinds.extend(_graphic_types(component))
    return [kind for kind in kinds if isinstance(kind, str)]


def features(slide):
    """Native carriers actually present on one slide."""
    comp = slide.get("composition") if isinstance(slide.get("composition"), dict) else {}
    sem = slide.get("semantic") if isinstance(slide.get("semantic"), dict) else {}
    blocks = [block for block in comp.get("blocks", []) if isinstance(block, dict)]
    found = set()
    if sem.get("inline_math") or any(block.get("inline_math") is True for block in blocks):
        found.add("inline_math")
    if any(block.get("component") == "formula" for block in blocks):
        found.add("formula")
    if any(block.get("text_flow") == "distributed_arrow_list"
           and len([line for line in block.get("text", "").splitlines() if line.strip()]) >= 2
           for block in blocks):
        found.add("native_list")
    if comp.get("tables"):
        found.add("table")
    if comp.get("layout_tree"):
        found.add("layout_tree")
    for graphic in comp.get("graphics", []) or []:
        for kind in _graphic_types(graphic):
            if kind in ("process", "dag", "mechanism", "path"):
                found.add(kind)
    if comp.get("figure_refs"):
        found.add("figure")
    return found


def _collect_strings(value, result):
    if isinstance(value, str):
        if value.strip():
            result.append(value)
    elif isinstance(value, list):
        for item in value:
            _collect_strings(item, result)
    elif isinstance(value, dict):
        for key in ("text", "title", "body", "label", "caption", "alt", "cells", "content"):
            if key in value:
                _collect_strings(value[key], result)


def _visible_corpus(slide):
    sem = slide.get("semantic") if isinstance(slide.get("semantic"), dict) else {}
    comp = slide.get("composition") if isinstance(slide.get("composition"), dict) else {}
    result = []
    for key in ("title", "takeaway"):
        _collect_strings(sem.get(key), result)
    _collect_strings(sem.get("caveats"), result)
    for block in comp.get("blocks", []) or []:
        _collect_strings(block, result)
    for figure in comp.get("figure_refs", []) or []:
        _collect_strings(figure, result)
    _collect_strings(comp.get("tables"), result)
    for graphic in comp.get("graphics", []) or []:
        _collect_strings(graphic.get("nodes"), result)
        _collect_strings(graphic.get("labels"), result)
    return " ".join(result).casefold()


def _content_strings(kind, content):
    if not isinstance(content, dict):
        return []
    if kind in ("parallel_items", "ordered_steps"):
        return _strings(content.get("items"))
    if kind == "comparison":
        return _strings(content.get("objects")) + _strings(content.get("dimensions"))
    if kind == "grouped_panels":
        result = []
        for group in content.get("groups", []) or []:
            if isinstance(group, dict):
                result.extend(_strings([group.get("title")]))
                result.extend(_strings(group.get("items")))
        return result
    if kind == "relation":
        result = []
        for node in content.get("nodes", []) or []:
            if isinstance(node, dict):
                result.extend(_strings([node.get("title"), node.get("id")]))
            else:
                result.extend(_strings([node]))
        return result
    if kind == "quantity":
        return _strings([content.get("text")])
    return []


def _visible(strings, corpus):
    # Two-character Chinese labels (采集, 清洗) are complete visible terms; a
    # three-character floor would falsely mark a compact eight-step flow as missing.
    return any(_text(value).casefold() in corpus for value in strings if len(_text(value)) >= 2)


def validate_explanation(value, semantic, composition, slide_number=None):
    """Return semantic-preflight issues for one slide's explanation contract."""
    if value is None:
        return []
    problems = []
    if not isinstance(value, dict):
        return [issue("EXPLANATION_INVALID", "FAIL", "semantic.explanation must be an object",
                      slide_number, "semantic.explanation")]
    unknown = sorted(set(value) - _EXPLANATION_FIELDS)
    if unknown:
        problems.append(issue("EXPLANATION_INVALID", "FAIL",
                              f"semantic.explanation: unknown fields {unknown}",
                              slide_number, "semantic.explanation"))
    obligations = value.get("obligations")
    if not isinstance(obligations, list) or not 1 <= len(obligations) <= 6:
        problems.append(issue("EXPLANATION_INVALID", "FAIL",
                              "semantic.explanation.obligations must hold 1-6 obligations",
                              slide_number, "semantic.explanation.obligations"))
        return problems
    seen = set()
    primary_count = 0
    slide = {"semantic": semantic, "composition": composition}
    found = features(slide)
    corpus = _visible_corpus(slide)
    evidence_refs = semantic.get("evidence_refs") if isinstance(semantic.get("evidence_refs"), list) else []
    for position, obligation in enumerate(obligations):
        shape = f"semantic.explanation.obligations[{position}]"
        if not isinstance(obligation, dict):
            problems.append(issue("EXPLANATION_INVALID", "FAIL", f"{shape} must be an object",
                                  slide_number, shape))
            continue
        unknown = sorted(set(obligation) - _OBLIGATION_FIELDS)
        if unknown:
            problems.append(issue("EXPLANATION_INVALID", "FAIL",
                                  f"{shape}: unknown fields {unknown}", slide_number, shape))
        obligation_id = _text(obligation.get("id"))
        if not obligation_id or obligation_id in seen:
            problems.append(issue("EXPLANATION_INVALID", "FAIL",
                                  f"{shape}: a unique non-empty id is required",
                                  slide_number, shape))
        else:
            seen.add(obligation_id)
        kind = obligation.get("kind")
        if kind not in KINDS:
            problems.append(issue("EXPLANATION_INVALID", "FAIL",
                                  f"{shape}: kind must be one of {list(KINDS)}",
                                  slide_number, shape))
            continue
        required = obligation.get("required")
        if type(required) is not bool:
            problems.append(issue("EXPLANATION_INVALID", "FAIL",
                                  f"{shape}: required must be boolean", slide_number, shape))
            required = True
        primary = obligation.get("primary", False)
        if type(primary) is not bool:
            problems.append(issue("EXPLANATION_INVALID", "FAIL",
                                  f"{shape}: primary must be boolean", slide_number, shape))
            primary = False
        primary_count += int(primary)
        carrier = obligation.get("carrier")
        if carrier is not None and carrier not in CARRIERS:
            problems.append(issue("EXPLANATION_INVALID", "FAIL",
                                  f"{shape}: carrier must be one of {list(CARRIERS)}",
                                  slide_number, shape))
        status = obligation.get("status", "bound")
        if status not in STATUSES:
            problems.append(issue("EXPLANATION_INVALID", "FAIL",
                                  f"{shape}: status must be one of {list(STATUSES)}",
                                  slide_number, shape))
        content = obligation.get("content")
        if not isinstance(content, dict):
            problems.append(issue("EXPLANATION_INVALID", "FAIL",
                                  f"{shape}: content must be an object", slide_number, shape))
            content = {}
        refs = obligation.get("evidence_refs")
        if not isinstance(refs, list) or not refs or not all(isinstance(item, str) and item for item in refs):
            problems.append(issue("EXPLANATION_INVALID", "FAIL",
                                  f"{shape}: evidence_refs must be a non-empty list of ids",
                                  slide_number, shape))
            refs = []
        else:
            missing = [item for item in refs if item not in evidence_refs]
            if missing:
                problems.append(issue("EXPLANATION_EVIDENCE_INVALID", "FAIL",
                                      f"{shape}: evidence_refs must bind to semantic.evidence_refs; "
                                      f"missing {missing}", slide_number, shape))
        if status in ("waived", "unsupported") and not _text(obligation.get("note")):
            problems.append(issue("EXPLANATION_WAIVER_INVALID", "FAIL",
                                  f"{shape}: {status} requires a note explaining the decision",
                                  slide_number, shape))
        if status != "bound" or not required:
            continue
        acceptable = KIND_CARRIERS[kind]
        carried = found.intersection(acceptable)
        if not carried:
            problems.append(issue(
                "EXPLANATION_OBLIGATION_MISSING", "REVIEW",
                f"{shape}: required {kind} has no native carrier; expected {list(acceptable)} "
                f"but found {sorted(found)}",
                slide_number, shape,
                detector="explanation-preflight",
                suggestion=f"add {list(acceptable)} or record status=waived with a note",
            ))
            continue
        content_strings = _content_strings(kind, content)
        if content_strings and not _visible(content_strings, corpus):
            problems.append(issue(
                "EXPLANATION_CONTENT_NOT_VISIBLE", "REVIEW",
                f"{shape}: the declared {kind} content does not appear in visible slide text",
                slide_number, shape, detector="explanation-preflight",
                suggestion="copy the complete obligation content into a block, table or graphic",
            ))
    if primary_count > 1:
        problems.append(issue("EXPLANATION_PRIMARY_INVALID", "REVIEW",
                              "only one obligation may be primary", slide_number,
                              "semantic.explanation"))
    return problems


def coverage(ir):
    """Deterministic ledger: obligation -> declared carrier -> actual feature."""
    slides = []
    totals = {"total": 0, "satisfied": 0, "waived": 0, "unsupported": 0, "missing": 0}
    for number, slide in enumerate(ir.get("slides", []), 1):
        sem = slide.get("semantic") if isinstance(slide.get("semantic"), dict) else {}
        explanation = sem.get("explanation")
        if not isinstance(explanation, dict):
            continue
        found = features(slide)
        corpus = _visible_corpus(slide)
        entries = []
        for obligation in explanation.get("obligations", []) or []:
            if not isinstance(obligation, dict):
                continue
            kind = obligation.get("kind")
            required = obligation.get("required", True)
            declared = obligation.get("status", "bound")
            acceptable = KIND_CARRIERS.get(kind, ())
            carried = found.intersection(acceptable)
            if declared == "waived":
                state = "waived"
            elif declared == "unsupported":
                state = "unsupported"
            elif required and not carried:
                state = "missing"
            elif required and _content_strings(kind, obligation.get("content")) and not _visible(
                    _content_strings(kind, obligation.get("content")), corpus):
                state = "missing"
            else:
                state = "satisfied"
            totals["total"] += 1
            totals[state] += 1
            entries.append({
                "id": obligation.get("id"),
                "kind": kind,
                "required": required,
                "primary": obligation.get("primary", False),
                "declared_carrier": obligation.get("carrier"),
                "status": state,
                "found_carriers": sorted(carried),
                "note": obligation.get("note", ""),
            })
        slides.append({"slide_id": slide.get("id"), "reader_task": explanation.get("reader_task", ""),
                       "obligations": entries})
    return {"schema_version": "1.0", "derived_from": "deck_ir.json", "read_only": True,
            "ir_sha256": digest(ir), "slides": slides, "summary": totals}
