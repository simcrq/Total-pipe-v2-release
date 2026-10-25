"""Evidence-grounded Story Planning contract.

The Story Planner is deliberately model-facing while this module stays fully
deterministic.  A high-capability subagent chooses and orders the evidence;
pwf2rpa then validates that choice and converts each reasoning node into a
slide-planning brief.  No model call is hidden inside the adapter.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import fit
from .errors import Problem, StoryError
from .workflow import Workflow

__all__ = [
    "CAPABILITY_CARD",
    "EXPLANATION_KINDS",
    "HIGH_REASONING_EFFORTS",
    "build_story_prompt",
    "load_story",
    "story_to_specs",
    "validate_story",
]

HIGH_REASONING_EFFORTS = frozenset({"high", "xhigh", "max", "ultra"})
_ROOT_FIELDS = frozenset({"planner", "core_question", "main_message", "story", "ending"})
# Explanation forms the Story Planner may declare.  Each one names what the reader
# needs to see, not which slide component to use: layout choice stays downstream.
# Only forms whose layout pool is text-only are mapped to a category here --
# figure-bound pools (figure_text, dual_figure, architecture) need visual assets
# this stage cannot promise, so those forms keep their intent in metadata for the
# Deck IR stage and fall back to the keyword rotation.
_FORMS = frozenset({"sequence", "compare", "branch", "relation", "evidence", "prose"})
_FORM_CATEGORY = {
    "sequence": "workflow",
    "compare": "table",
    "branch": "discussion",
}
_FORM_SLOTS = {"sequence": "process_steps", "compare": "comparison_dimensions"}
_SLOT_FIELDS = ("process_steps", "comparison_dimensions", "timeline_events")

# The closed vocabulary the reader-facing contract may name.  These are visible
# structures, not renderer components: a story says "four peers must be scanned
# together", and the downstream binder chooses a native list, a table or a panel.
EXPLANATION_KINDS = (
    "quantity",
    "parallel_items",
    "grouped_panels",
    "comparison",
    "ordered_steps",
    "relation",
    "curve",
    "image_evidence",
)

# A compact capability card for the story subagent.  It is intentionally small:
# the full Skill document is not available inside this prompt, and a card that
# drifts from the compiler is worse than no card.  The binder and the compiler
# still own the concrete carrier and the measured capacity.
CAPABILITY_CARD = {
    "version": "1",
    "contract": "totalpipe.explanation-contract",
    "moves": [
        {"kind": "quantity", "reader_task": "quantify",
         "carriers": ["inline_math", "formula"],
         "requires": "a number, unit, symbol or relation that must be read exactly",
         "limit": "native math baseline still needs a PowerPoint check",
         "fallback": "plain text with REVIEW"},
        {"kind": "parallel_items", "reader_task": "distinguish",
         "carriers": ["native_list", "table"],
         "requires": "2-6 peer items whose order does not carry meaning",
         "limit": "native list needs at least 520 px width",
         "fallback": "table or measured prose"},
        {"kind": "grouped_panels", "reader_task": "locate",
         "carriers": ["layout_tree"],
         "requires": "2-4 groups or levels that must stay visibly nested",
         "limit": "panel title band consumes height",
         "fallback": "stack / columns"},
        {"kind": "comparison", "reader_task": "compare",
         "carriers": ["table", "layout_tree"],
         "requires": "at least 2 objects over at least 2 shared dimensions",
         "limit": "native table is at most 32 rows x 12 columns",
         "fallback": "columns with one object each"},
        {"kind": "ordered_steps", "reader_task": "trace",
         "carriers": ["process", "dag"],
         "requires": "2-5 steps with a fixed order",
         "limit": "the process component holds 3-4 nodes",
         "fallback": "ordered list, or split the page"},
        {"kind": "relation", "reader_task": "explain",
         "carriers": ["mechanism", "dag"],
         "requires": "explicit nodes and directed edges with a basis",
         "limit": "edges must be evidence or hypothesis; no inferred mechanism",
         "fallback": "text plus REVIEW"},
        {"kind": "curve", "reader_task": "read",
         "carriers": ["path"],
         "requires": "a schematic trend or shape, not a measured curve",
         "limit": "labels stay inside view_box; caption says schematic",
         "fallback": "no drawn curve"},
        {"kind": "image_evidence", "reader_task": "read",
         "carriers": ["figure"],
         "requires": "one real source figure the reader must inspect",
         "limit": "source figure and caption remain bound",
         "fallback": "text plus REVIEW"},
    ],
    "traps": [
        {"archetype": "process-flow", "is_not": "a native process graphic"},
        {"archetype": "metric-comparison", "is_not": "a native table"},
        {"archetype": "figure-parameters", "is_not": "a visual_plan"},
    ],
}

_EXPLAIN_FIELDS = frozenset({"reader_task", "must_show", "must_not_lose", "prose_ok_reason"})
_OBLIGATION_FIELDS = frozenset({"id", "kind", "required", "primary", "content", "evidence", "source_quote"})

_PLANNER_FIELDS = frozenset({"mode", "model", "reasoning_effort", "selected_by_user"})
_NODE_FIELDS = frozenset({"title", "question", "answer", "key_points", "evidence", "next",
                        "form", "process_steps", "comparison_dimensions", "timeline_events",
                        "explain"})
_ENDING_FIELDS = frozenset({"takeaway", "limitation"})

_GENERIC_NEXT = re.compile(
    r"^(?:then|next|after that|additionally|furthermore|然后|接下来|此外|随后)"
    r"(?:\s*(?:看|讨论|介绍|作者|we|the authors))?",
    re.IGNORECASE,
)
_FIGURE_ONLY = re.compile(r"^(?:fig(?:ure)?\.?|图)\s*[0-9a-z]+\s*$", re.IGNORECASE)
_HAN = re.compile(r"[\u3400-\u9fff]")
_LATIN = re.compile(r"[A-Za-z]")
_EPISTEMIC_MARKERS = (
    "但是", "然而", "仍", "尚", "不足", "疑问", "验证", "排除", "解释", "机制", "能否", "是否",
    "如果", "因此需要", "为了", "but", "however", "remain", "unclear", "test", "verify", "rule out",
    "explain", "mechanism", "whether", "if this", "to determine",
)
_HEDGES = (
    " may ", " might ", " likely ", " suggest", " possibly ", " could ",
    "可能", "或许", "提示", "表明", "推测", "倾向于",
)
_STRONG_CAUSAL = (
    " causes ", " caused ", " leads to ", " drives ", " proves ", " demonstrates that ",
    "导致", "引起", "驱动", "证明", "确定为", "必然",
)


def _text(value: Any) -> str:
    return " ".join(value.split()) if isinstance(value, str) else ""


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [_text(item) for item in value if _text(item)]


def _unknown_fields(raw: Mapping[str, Any], allowed: frozenset[str], path: str) -> list[Problem]:
    unknown = sorted(set(raw) - allowed)
    if not unknown:
        return []
    return [
        Problem(
            "STORY_UNKNOWN_FIELD",
            path,
            "unknown Story Planner field; keep the intermediate contract intentionally small.",
            actual=unknown,
            expected=sorted(allowed),
            severity="warning",
        )
    ]


def _required_text(raw: Mapping[str, Any], key: str, path: str, problems: list[Problem]) -> str:
    value = _text(raw.get(key))
    if not value:
        problems.append(
            Problem(
                "STORY_TEXT_MISSING",
                f"{path}.{key}",
                f"{key} must be a non-empty string.",
            )
        )
    return value


def _content_errors(kind: str, content: Any) -> list[str]:
    """Validate the shape of one obligation's visible content.

    The contract is deliberately about content, not about a component name.  A
    story says what the reader must see; the binder and the compiler choose how
    to draw it.
    """
    if isinstance(content, str):
        content = {"text": content}
    if not isinstance(content, Mapping):
        return ["content must be an object"]
    errors: list[str] = []
    if kind == "quantity":
        if not (_text(content.get("latex")) or _text(content.get("text"))):
            errors.append("quantity content needs latex or text")
    elif kind in ("parallel_items", "ordered_steps"):
        maximum = 6 if kind == "parallel_items" else 5
        items = _string_list(content.get("items"))
        if not 2 <= len(items) <= maximum:
            errors.append(f"{kind} content.items needs 2-{maximum} non-empty strings")
    elif kind == "grouped_panels":
        groups = content.get("groups")
        if not isinstance(groups, list) or not 2 <= len(groups) <= 4:
            errors.append("grouped_panels content.groups needs 2-4 group objects")
        else:
            for position, group in enumerate(groups):
                if not isinstance(group, Mapping) or not _text(group.get("title")):
                    errors.append(f"groups[{position}] needs a title")
                    continue
                if not (_string_list(group.get("items")) or _text(group.get("text"))):
                    errors.append(f"groups[{position}] needs items or text")
    elif kind == "comparison":
        objects, dimensions = _string_list(content.get("objects")), _string_list(content.get("dimensions"))
        if len(objects) < 2:
            errors.append("comparison content.objects needs at least 2 objects")
        if len(dimensions) < 2:
            errors.append("comparison content.dimensions needs at least 2 dimensions")
    elif kind == "relation":
        nodes = content.get("nodes")
        node_ids: list[str] = []
        if isinstance(nodes, list):
            for node in nodes:
                if isinstance(node, Mapping):
                    node_id = _text(node.get("id"))
                else:
                    node_id = _text(node)
                if node_id:
                    node_ids.append(node_id)
        if len(node_ids) < 2:
            errors.append("relation content.nodes needs at least 2 node ids")
        edges = content.get("edges")
        if not isinstance(edges, list) or not edges:
            errors.append("relation content.edges needs at least one directed edge")
        else:
            for position, edge in enumerate(edges):
                if not isinstance(edge, Mapping):
                    errors.append(f"edges[{position}] must be an object")
                    continue
                source, target, relation = (_text(edge.get("from")), _text(edge.get("to")),
                                            _text(edge.get("kind")))
                if not source or not target or not relation:
                    errors.append(f"edges[{position}] needs from, to and kind")
                elif node_ids and (source not in node_ids or target not in node_ids):
                    errors.append(f"edges[{position}] references a node outside content.nodes")
    elif kind == "curve":
        if not _text(content.get("shape")):
            errors.append("curve content.shape is required (for example rise-then-plateau)")
    elif kind == "image_evidence":
        if not (_text(content.get("what_to_look_at")) or _text(content.get("text"))):
            errors.append("image_evidence content needs what_to_look_at")
    return errors


def _normalize_obligation(raw: Any, path: str, position: int, node_evidence: list[str],
                           workflow: Workflow, problems: list[Problem]) -> dict[str, Any] | None:
    if not isinstance(raw, Mapping):
        problems.append(Problem("STORY_EXPLAIN_OBLIGATION_NOT_OBJECT", path,
                                "each must_show entry must be an object."))
        return None
    problems.extend(_unknown_fields(raw, _OBLIGATION_FIELDS, path))
    kind = _text(raw.get("kind")).lower()
    if kind not in EXPLANATION_KINDS:
        problems.append(Problem("STORY_EXPLAIN_KIND_UNKNOWN", path,
                                "declare one of the visible explanation kinds.", actual=kind,
                                expected=list(EXPLANATION_KINDS)))
        return None
    content = raw.get("content")
    for message in _content_errors(kind, content):
        problems.append(Problem("STORY_EXPLAIN_CONTENT_INVALID", f"{path}.content", message))
    if not isinstance(content, Mapping):
        content = {"text": content} if isinstance(content, str) else {}
    if kind == "curve" and content.get("schematic") is not True:
        problems.append(Problem("STORY_EXPLAIN_CURVE_SCHEMATIC_UNMARKED", f"{path}.content",
                                "a curve drawn by the pipeline must declare schematic=true.",
                                severity="warning"))
    evidence = _string_list(raw.get("evidence"))
    if not evidence:
        problems.append(Problem("STORY_EXPLAIN_EVIDENCE_EMPTY", f"{path}.evidence",
                                "each visible obligation needs at least one Evidence id."))
    resolved: list[str] = []
    for evidence_id in evidence:
        if evidence_id in resolved:
            continue
        if not workflow.has_evidence(evidence_id):
            problems.append(Problem("STORY_EXPLAIN_UNKNOWN_EVIDENCE", f"{path}.evidence",
                                    "obligation cites an id outside this workflow's Evidence Store.",
                                    actual=evidence_id, expected=workflow.evidence_ids))
            continue
        if evidence_id not in node_evidence:
            problems.append(Problem("STORY_EXPLAIN_EVIDENCE_NOT_ON_NODE", f"{path}.evidence",
                                    "an obligation may only cite Evidence already listed on its node.",
                                    actual=evidence_id, expected=node_evidence))
            continue
        resolved.append(evidence_id)
    source_quote = _text(raw.get("source_quote"))
    if source_quote:
        corpus = " ".join(
            workflow.get(evidence_id).text
            for evidence_id in resolved
            if workflow.get(evidence_id) is not None
        )
        if " ".join(source_quote.split()).casefold() not in " ".join(corpus.split()).casefold():
            problems.append(Problem("STORY_EXPLAIN_QUOTE_NOT_FOUND", f"{path}.source_quote",
                                    "source_quote is not an exact substring of the cited evidence.",
                                    actual=source_quote[:120], severity="warning"))
    required = raw.get("required", True)
    if type(required) is not bool:
        problems.append(Problem("STORY_EXPLAIN_REQUIRED_INVALID", f"{path}.required",
                                "required must be boolean.", actual=required))
        required = True
    primary = raw.get("primary", False)
    if type(primary) is not bool:
        problems.append(Problem("STORY_EXPLAIN_PRIMARY_INVALID", f"{path}.primary",
                                "primary must be boolean.", actual=primary))
        primary = False
    obligation_id = _text(raw.get("id")) or f"ob-{position + 1}"
    return {
        "id": obligation_id,
        "kind": kind,
        "required": required,
        "primary": primary,
        "content": dict(content),
        "evidence": resolved,
        **({"source_quote": source_quote} if source_quote else {}),
    }


def _normalize_explain(raw: Any, path: str, node_evidence: list[str],
                       workflow: Workflow, problems: list[Problem]) -> dict[str, Any] | None:
    if not isinstance(raw, Mapping):
        problems.append(Problem("STORY_EXPLAIN_NOT_OBJECT", path,
                                "explain must be an object."))
        return None
    problems.extend(_unknown_fields(raw, _EXPLAIN_FIELDS, path))
    raw_obligations = raw.get("must_show", [])
    if not isinstance(raw_obligations, list):
        problems.append(Problem("STORY_EXPLAIN_MUST_SHOW_INVALID", f"{path}.must_show",
                                "must_show must be an array of obligation objects."))
        raw_obligations = []
    if len(raw_obligations) > 6:
        problems.append(Problem("STORY_EXPLAIN_TOO_MANY", f"{path}.must_show",
                                "keep at most six visible obligations on one page; move the rest to notes "
                                "or another node.", actual=len(raw_obligations), severity="warning"))
    obligations: list[dict[str, Any]] = []
    seen: set[str] = set()
    for position, item in enumerate(raw_obligations):
        obligation = _normalize_obligation(item, f"{path}.must_show[{position}]", position,
                                           node_evidence, workflow, problems)
        if obligation is None:
            continue
        if obligation["id"] in seen:
            problems.append(Problem("STORY_EXPLAIN_DUPLICATE_ID", f"{path}.must_show[{position}].id",
                                    "obligation ids must be unique within a node.",
                                    actual=obligation["id"]))
            continue
        seen.add(obligation["id"])
        obligations.append(obligation)
    primary = [item for item in obligations if item["primary"]]
    if len(primary) > 1:
        problems.append(Problem("STORY_EXPLAIN_MULTIPLE_PRIMARY", f"{path}.must_show",
                                "only one obligation may be primary; the first one is kept.",
                                actual=[item["id"] for item in primary], severity="warning"))
        for item in obligations:
            item["primary"] = False
        primary[0]["primary"] = True
    elif not primary and obligations:
        first_required = next((item for item in obligations if item["required"]), obligations[0])
        first_required["primary"] = True
    prose_ok_reason = _text(raw.get("prose_ok_reason"))
    if not obligations and not prose_ok_reason:
        problems.append(Problem("STORY_EXPLAIN_PROSE_REASON_MISSING", f"{path}.prose_ok_reason",
                                "when must_show is empty, say why continuous prose is the right form.",
                                severity="warning"))
    return {
        "reader_task": _text(raw.get("reader_task")),
        "must_show": obligations,
        "must_not_lose": _string_list(raw.get("must_not_lose")),
        "prose_ok_reason": prose_ok_reason,
    }


def _form_from_explain(explain: Mapping[str, Any] | None) -> tuple[str, dict[str, list[str]]]:
    """Derive the legacy RPA category form when the story only wrote explain."""
    if not isinstance(explain, Mapping):
        return "", {}
    for obligation in explain.get("must_show", []):
        if not isinstance(obligation, Mapping) or not obligation.get("required", True):
            continue
        content = obligation.get("content") if isinstance(obligation.get("content"), Mapping) else {}
        if obligation.get("kind") == "ordered_steps":
            return "sequence", {"process_steps": _string_list(content.get("items"))[:5]}
        if obligation.get("kind") == "comparison":
            return "compare", {"comparison_dimensions": _string_list(content.get("dimensions"))}
    return "", {}


def _first_obligation(explain: Mapping[str, Any] | None, kind: str) -> dict[str, Any] | None:
    if not isinstance(explain, Mapping):
        return None
    return next((item for item in explain.get("must_show", [])
                 if isinstance(item, Mapping) and item.get("kind") == kind), None)


def validate_story(raw: Any, workflow: Workflow) -> tuple[dict[str, Any], list[Problem]]:
    """Validate and normalize one Story Planner result.

    The provenance gate is intentional: a story is accepted only when the user
    selected the model and a high-reasoning subagent produced it.  This keeps a
    main orchestration agent from silently replacing the required planning step
    with a cheaper local summary.
    """
    if not isinstance(raw, Mapping):
        raise StoryError(
            [Problem("STORY_NOT_OBJECT", "story", "story plan must be a JSON object.", actual=type(raw).__name__)],
            summary="Unusable story plan",
        )

    problems: list[Problem] = []
    problems.extend(_unknown_fields(raw, _ROOT_FIELDS, "story"))

    planner_raw = raw.get("planner")
    planner: dict[str, Any] = {}
    if not isinstance(planner_raw, Mapping):
        problems.append(
            Problem(
                "STORY_PLANNER_PROVENANCE_MISSING",
                "story.planner",
                "planner provenance is required before Slide Planning.",
                hint="Ask the user to choose a high-capability model, delegate to that subagent, and record the choice.",
            )
        )
    else:
        problems.extend(_unknown_fields(planner_raw, _PLANNER_FIELDS, "story.planner"))
        mode = _text(planner_raw.get("mode"))
        model = _text(planner_raw.get("model"))
        effort = _text(planner_raw.get("reasoning_effort")).lower()
        selected = planner_raw.get("selected_by_user") is True
        planner = {
            "mode": mode,
            "model": model,
            "reasoning_effort": effort,
            "selected_by_user": selected,
        }
        if mode != "subagent":
            problems.append(
                Problem(
                    "STORY_SUBAGENT_REQUIRED",
                    "story.planner.mode",
                    "Story Planning must be performed by a delegated subagent.",
                    actual=mode,
                    expected="subagent",
                )
            )
        if not model:
            problems.append(
                Problem("STORY_MODEL_MISSING", "story.planner.model", "record the exact model selected by the user.")
            )
        if effort not in HIGH_REASONING_EFFORTS:
            problems.append(
                Problem(
                    "STORY_MODEL_NOT_HIGH_REASONING",
                    "story.planner.reasoning_effort",
                    "Story Planning requires high-or-stronger reasoning.",
                    actual=effort,
                    expected=sorted(HIGH_REASONING_EFFORTS),
                )
            )
        if not selected:
            problems.append(
                Problem(
                    "STORY_MODEL_NOT_USER_SELECTED",
                    "story.planner.selected_by_user",
                    "the user must explicitly choose which high-capability model the subagent uses.",
                    actual=planner_raw.get("selected_by_user"),
                    expected=True,
                )
            )

    core_question = _required_text(raw, "core_question", "story", problems)
    main_message = _required_text(raw, "main_message", "story", problems)

    nodes_raw = raw.get("story")
    if not isinstance(nodes_raw, list):
        problems.append(
            Problem("STORY_NODES_NOT_ARRAY", "story.story", "story must be an array of 4-10 reasoning nodes.")
        )
        nodes_raw = []
    elif not 4 <= len(nodes_raw) <= 10:
        problems.append(
            Problem(
                "STORY_NODE_COUNT_INVALID",
                "story.story",
                "a research talk needs 4-10 reasoning nodes; nodes are not figures or slides.",
                actual=len(nodes_raw),
                expected="4-10",
            )
        )

    nodes: list[dict[str, Any]] = []
    for index, node_raw in enumerate(nodes_raw):
        path = f"story.story[{index}]"
        if not isinstance(node_raw, Mapping):
            problems.append(
                Problem("STORY_NODE_NOT_OBJECT", path, "each story node must be an object.", actual=type(node_raw).__name__)
            )
            continue
        problems.extend(_unknown_fields(node_raw, _NODE_FIELDS, path))
        title = _text(node_raw.get("title"))
        question = _required_text(node_raw, "question", path, problems)
        answer = _required_text(node_raw, "answer", path, problems)
        # The last node closes the argument: it does not need a hand-off to a next question.
        # Every other node does, because that is what makes the chain a chain.
        next_question = _text(node_raw.get("next"))
        if not next_question and index < len(nodes_raw) - 1:
            problems.append(
                Problem(
                    "STORY_TEXT_MISSING",
                    f"{path}.next",
                    "next is required on every node except the last one.",
                )
            )
        raw_key_points = node_raw.get("key_points", [])
        if not isinstance(raw_key_points, list) or any(
            not isinstance(point, str) or not point.strip() for point in raw_key_points
        ):
            problems.append(
                Problem(
                    "STORY_KEY_POINTS_INVALID",
                    f"{path}.key_points",
                    "key_points must be an optional array of non-empty strings.",
                )
            )
            key_points = []
        else:
            key_points = list(raw_key_points)
        form = _text(node_raw.get("form")).lower()
        if form and form not in _FORMS:
            problems.append(
                Problem(
                    "STORY_FORM_UNKNOWN",
                    f"{path}.form",
                    "declare one of the explanation forms this pipeline can render, or omit form.",
                    actual=form,
                    expected=sorted(_FORMS),
                    severity="warning",
                )
            )
            form = ""
        slots: dict[str, list[str]] = {}
        for field in _SLOT_FIELDS:
            raw_list = node_raw.get(field)
            if raw_list is None:
                continue
            values = (
                [item.strip() for item in raw_list if isinstance(item, str) and item.strip()]
                if isinstance(raw_list, list)
                else []
            )
            if len(values) < 2:
                problems.append(
                    Problem(
                        "STORY_FORM_SLOTS_INVALID",
                        f"{path}.{field}",
                        f"{field} must be an array of at least 2 non-empty strings.",
                        severity="warning",
                    )
                )
                continue
            if field == "process_steps" and len(values) > 5:
                # process_step_count is a hard retrieval constraint and the widest
                # process layout holds 5 nodes; more than that drops the page off the
                # category. Say so here, where the planner can still merge steps.
                problems.append(
                    Problem(
                        "STORY_FORM_SLOTS_TOO_LONG",
                        f"{path}.{field}",
                        "a process strip holds at most 5 steps; merge the rest into the answer.",
                        actual=len(values),
                        expected="<= 5",
                        severity="warning",
                    )
                )
            slots[field] = values
        required_slot = _FORM_SLOTS.get(form)
        if required_slot and required_slot not in slots:
            problems.append(
                Problem(
                    "STORY_FORM_UNFILLED",
                    f"{path}.{required_slot}",
                    "this form needs its structure written out, or the page degrades to plain text.",
                    severity="warning",
                )
            )

        evidence_ids = _string_list(node_raw.get("evidence"))
        if not evidence_ids:
            problems.append(
                Problem("STORY_EVIDENCE_EMPTY", f"{path}.evidence", "each answer needs at least one Evidence id.")
            )
        resolved: list[str] = []
        for position, evidence_id in enumerate(evidence_ids):
            if evidence_id in resolved:
                continue
            if not workflow.has_evidence(evidence_id):
                problems.append(
                    Problem(
                        "UNKNOWN_EVIDENCE_ID",
                        f"{path}.evidence[{position}]",
                        "Story Planner cited an id outside this workflow's Evidence Store.",
                        actual=evidence_id,
                        expected=workflow.evidence_ids,
                    )
                )
                continue
            resolved.append(evidence_id)

        next_lower = f" {next_question.lower()} "
        if next_question and (
            _FIGURE_ONLY.match(next_question)
            or (_GENERIC_NEXT.match(next_question) and not any(marker in next_lower for marker in _EPISTEMIC_MARKERS))
        ):
            problems.append(
                Problem(
                    "STORY_NEXT_IS_SEQUENTIAL",
                    f"{path}.next",
                    "next must name an unresolved scientific question, not the paper's next section or figure.",
                    actual=next_question,
                    hint="State what remains uncertain and why another experiment or analysis is needed.",
                )
            )

        evidence_text = " ".join(
            workflow.get(evidence_id).text.lower()
            for evidence_id in resolved
            if workflow.get(evidence_id) is not None
        )
        answer_lower = f" {answer.lower()} "
        if evidence_text and any(token in f" {evidence_text} " for token in _HEDGES) \
                and any(token in answer_lower for token in _STRONG_CAUSAL):
            problems.append(
                Problem(
                    "STORY_CERTAINTY_ESCALATION_RISK",
                    f"{path}.answer",
                    "the answer appears more causal or certain than its hedged source evidence.",
                    actual=answer,
                    hint="Preserve may/likely/suggest/possibly language and avoid converting co-occurrence into causation.",
                    severity="warning",
                )
            )

        explain = None
        if "explain" in node_raw:
            explain = _normalize_explain(node_raw.get("explain"), f"{path}.explain",
                                         resolved, workflow, problems)

        node = {
            "question": question,
            "answer": answer,
            "evidence": resolved,
            "next": next_question,
        }
        if title:
            node["title"] = title
        if key_points:
            node["key_points"] = key_points
        if form:
            node["form"] = form
        if explain is not None:
            node["explain"] = explain
        node.update(slots)
        nodes.append(node)

    ending_raw = raw.get("ending")
    ending: dict[str, str] = {"takeaway": "", "limitation": ""}
    if not isinstance(ending_raw, Mapping):
        problems.append(Problem("STORY_ENDING_MISSING", "story.ending", "ending must contain takeaway and limitation."))
    else:
        problems.extend(_unknown_fields(ending_raw, _ENDING_FIELDS, "story.ending"))
        # limitation is optional. Forcing it produced closing pages about which PDFs this run
        # happened to have; the paper's own boundary should be written when there is one.
        ending = {
            "takeaway": _required_text(ending_raw, "takeaway", "story.ending", problems),
            "limitation": _text(ending_raw.get("limitation")),
        }

    errors = [problem for problem in problems if problem.severity == "error"]
    if errors:
        raise StoryError(problems, summary="Unusable story plan")

    normalized = {
        "planner": planner,
        "core_question": core_question,
        "main_message": main_message,
        "story": nodes,
        "ending": ending,
    }
    return normalized, [problem for problem in problems if problem.severity == "warning"]


def load_story(path: str | Path) -> Any:
    """Read a Story Planner JSON file; semantic validation happens separately."""
    path = Path(path)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise StoryError(
            [Problem("STORY_NOT_FOUND", str(path), "story plan file does not exist.")],
            summary=f"Cannot read {path}",
        ) from exc
    except json.JSONDecodeError as exc:
        raise StoryError(
            [Problem("STORY_NOT_JSON", f"{path}:{exc.lineno}:{exc.colno}", f"story plan is not valid JSON: {exc.msg}")],
            summary=f"Cannot parse {path}",
        ) from exc


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: max(1, limit - 1)].rstrip() + "…"


def _category_for(question: str, index: int, form: str = "") -> str:
    """Pick a layout category from the declared form first, then from keywords.

    The keyword branch is a fallback for nodes that did not declare a form.  It
    can only see question wording, so a page whose argument is a procedure or a
    comparison used to land on a text pool and lose the structure it needed.
    """
    if index == 0:
        return "question"
    mapped = _FORM_CATEGORY.get(form)
    if mapped:
        return mapped
    lower = question.lower()
    if any(token in lower for token in ("为什么", "机制", "原因", "解释", "why", "mechanism", "explain")):
        return "discussion"
    if any(token in lower for token in ("如何", "方法", "策略", "how", "method", "approach")):
        return "method_overview"
    if any(token in lower for token in ("局限", "边界", "不足", "limit", "boundary")):
        return "limitations"
    return ("case", "gap", "theory", "decision")[(index - 1) % 4]


def _ending_title(plan: Mapping[str, Any]) -> str:
    """Follow the Story's display language instead of forcing a Chinese title."""
    texts = [plan["core_question"], plan["main_message"], *plan["ending"].values()]
    texts.extend(text for node in plan["story"] for text in (node["question"], node["answer"]))
    chinese = sum(bool(_HAN.search(text)) for text in texts)
    english = sum(bool(_LATIN.search(text)) and not _HAN.search(text) for text in texts)
    return "结论与边界" if chinese > english else "Conclusions and scope"


def story_to_specs(raw: Any, workflow: Workflow) -> tuple[list[dict[str, Any]], list[Problem]]:
    """Turn Story nodes into semantic planning units for RPA.

    Nodes are not declared to be final pages.  ``allow_auto_split`` remains on,
    and RPA may split a dense reasoning unit while preserving its Evidence ids
    and transition metadata.
    """
    plan, warnings = validate_story(raw, workflow)
    planner = dict(plan["planner"])
    common = {
        "core_question": plan["core_question"],
        "main_message": plan["main_message"],
        "story_planner": planner,
    }
    first_evidence = list(plan["story"][0]["evidence"][:2]) if plan["story"] else []
    cover_limit = max((layout.title_chars or 0) for layout in fit.CATEGORIES["cover"].layouts) or 30
    specs: list[dict[str, Any]] = [
        {
            "slide_type": "cover",
            "category_hint": "cover",
            "title": _truncate(workflow.title, cover_limit),
            "evidence_ids": first_evidence,
            "content_roles": ["primary_claim"],
            "narrative_job": "cover",
            "allow_auto_split": False,
            "metadata": {**common, "story_role": "cover"},
        }
    ]

    for index, node in enumerate(plan["story"]):
        form = _text(node.get("form"))
        slots = {field: list(node[field]) for field in _SLOT_FIELDS if node.get(field)}
        explain = node.get("explain") if isinstance(node.get("explain"), Mapping) else None
        # A story that wrote only explain still has to reach the RPA category pools
        # that carry a process or a table.  Keep the explicit form when present;
        # derive it from the required obligation otherwise.
        if explain and not form:
            derived_form, derived_slots = _form_from_explain(explain)
            if derived_form:
                form = derived_form
                for field, values in derived_slots.items():
                    if values:
                        slots.setdefault(field, list(values))
        category = _category_for(node["question"], index, form)
        title_limit = max((layout.title_chars or 0) for layout in fit.CATEGORIES[category].layouts) or 34
        # The planner may write its own slide title. RPA still needs one that fits its slot, so the
        # brief carries the truncated form and the metadata keeps the full sentence for the Deck IR.
        title = node.get("title") or node["question"]
        spec = {
            "slide_type": "custom",
            "category_hint": category,
            "title": _truncate(title, title_limit),
            "takeaway": node["answer"],
            "evidence_ids": list(node["evidence"]),
            "content_roles": ["primary_claim", "primary_evidence"],
            "narrative_job": "story_reasoning",
            "allow_auto_split": True,
            "metadata": {
                **common,
                "story_role": "reasoning_node",
                "story_node_index": index + 1,
                "story_title": title,
                "story_question": node["question"],
                "story_answer": node["answer"],
                "story_next": node["next"],
            },
        }
        if node.get("key_points"):
            spec["key_points"] = list(node["key_points"])
        elif explain:
            parallel = _first_obligation(explain, "parallel_items")
            content = parallel.get("content") if isinstance(parallel, Mapping) else None
            items = _string_list(content.get("items")) if isinstance(content, Mapping) else []
            if items:
                spec["key_points"] = items
        # Structural slots go to RPA top-level: its planner derives process_step_count
        # and comparison_dimension_count from them, and those counts are what let a
        # layout with a process or table region be retrieved at all.
        for field, values in slots.items():
            if values:
                spec[field] = list(values)
        if form:
            spec["metadata"]["story_form"] = form
        if explain is not None:
            spec["metadata"]["story_explain"] = explain
        specs.append(spec)

    final_evidence = list(dict.fromkeys(
        evidence_id
        for node in plan["story"][-2:]
        for evidence_id in node["evidence"]
    ))
    summary = {
        "slide_type": "summary",
        "category_hint": "summary",
        "title": _ending_title(plan),
        "takeaway": plan["ending"]["takeaway"],
        "evidence_ids": final_evidence,
        "content_roles": ["primary_claim", "supporting_evidence"],
        "narrative_job": "summary",
        "allow_auto_split": True,
        "metadata": {**common, "story_role": "ending", **plan["ending"]},
    }
    if plan["ending"].get("limitation"):
        summary["body"] = plan["ending"]["limitation"]
    specs.append(summary)
    return specs, warnings


def build_story_prompt(
    workflow: Workflow,
    *,
    model: str,
    reasoning_effort: str,
    selected_by_user: bool,
) -> dict[str, Any]:
    """Build the exact evidence-bound prompt package for the chosen subagent."""
    model = _text(model)
    effort = _text(reasoning_effort).lower()
    problems: list[Problem] = []
    if not selected_by_user:
        problems.append(
            Problem(
                "STORY_MODEL_NOT_USER_SELECTED",
                "planner.selected_by_user",
                "ask the user which high-capability model to use before creating the Story prompt.",
                expected=True,
            )
        )
    if not model:
        problems.append(Problem("STORY_MODEL_MISSING", "planner.model", "the user must choose an exact model."))
    if effort not in HIGH_REASONING_EFFORTS:
        problems.append(
            Problem(
                "STORY_MODEL_NOT_HIGH_REASONING",
                "planner.reasoning_effort",
                "use high-or-stronger reasoning for the Story subagent.",
                actual=effort,
                expected=sorted(HIGH_REASONING_EFFORTS),
            )
        )
    if problems:
        raise StoryError(problems, summary="Story subagent is not authorized")

    evidence = [
        {
            "evidence_id": item.evidence_id,
            "text": item.text,
            "query_ids": list(item.query_ids),
            "modality": item.modality,
            "support_type": item.support_type,
        }
        for item in workflow.evidence.values()
    ]
    output_shape = {
        "planner": {
            "mode": "subagent",
            "model": model,
            "reasoning_effort": effort,
            "selected_by_user": True,
        },
        "core_question": "string",
        "main_message": "string",
        "story": [
            {"title": "string, optional", "question": "string", "answer": "string",
             "evidence": ["EV0001"], "next": "string, optional on the last node",
             "form": "sequence|compare|branch|relation|evidence, optional; derived from explain when omitted",
             "process_steps": ["one step per item, required when form=sequence"],
             "comparison_dimensions": ["one dimension per item, required when form=compare"],
             "explain": {
                 "reader_task": "quantify|compare|trace|locate|distinguish|read|explain, optional",
                 "must_show": [
                     {"id": "ob-1", "kind": "quantity|parallel_items|grouped_panels|comparison|"
                                        "ordered_steps|relation|curve|image_evidence",
                      "required": True, "primary": True,
                      "content": {"latex": "\\varepsilon_A \\approx 0.21"} or
                                 {"items": ["first peer", "second peer"]} or
                                 {"objects": ["A", "B"], "dimensions": ["BER", "rate"]},
                      "evidence": ["EV0001"],
                      "source_quote": "exact substring of the cited evidence, optional"}
                 ],
                 "must_not_lose": ["units", "uncertainty"],
                 "prose_ok_reason": "required when must_show is empty"
             }}
        ],
        "ending": {"takeaway": "string", "limitation": "string, optional"},
    }
    instructions = (
        "你不是在总结论文，也不是按 Figure 顺序写大纲。你要从 Evidence Store 中选择最重要的证据，"
        "把论文重构为听众理解问题的顺序。只输出一个 JSON 对象，不要 Markdown。\n\n"
        "结构：\n"
        "1. 输出 4-10 个 story nodes；每个 node 是科研推理的一步，不是一个 Figure。"
        "节点数量由论证需要决定，不要为凑页数增加节点。\n"
        "2. 每个 node 有 question 和 answer。question 是你这一步要回答的科学问题，"
        "answer 是回答，只能由列出的 Evidence id 支撑；不得创造事实、因果关系或确定性。\n"
        "3. title 可选，是这一页给听众看的话。它可以不是问句，可以比 question 长或短，"
        "由你决定怎样说清楚；不写就退回 question。"
        "不要把标题写成“主题：结论”的拼接，那通常是硬塞字数的结果。\n"
        "4. 原文的 may/likely/suggest/possibly/可能/提示/推测必须保留其不确定性。\n"
        "5. next 说明当前证据留下的疑问或待验证机制，除最后一个 node 外必填；"
        "最后一个 node 不需要为了形式补一句“下一步看什么”。不得写成‘然后看 Fig.4’。\n"
        "6. 允许删除重复、展示性或弱相关证据，目标是最短、最清晰的核心证据链。\n"
        "7. 每个 node 必须写 explain，说明听众必须看见什么；它不决定页数、版式、配色或裁图。\n"
        "8. 相邻节点应能用‘因此/但是/为了验证/为了排除/如果该解释成立’连接。\n\n"
        "关于 ending：takeaway 必填；limitation 可选，只写论文自身的边界（样本、条件、方法假设）。"
        "不要写你这次拿到了哪些文件、SI 是否取得或是否审阅——那是工作记录，不是科学结论。\n\n"
        "关于 explain：explain 不是版式，而是‘读者必须看见什么’。\n"
        "must_show 每条从这 8 类里选一个：quantity（必须精确读出或比较的量/公式）、"
        "parallel_items（2-6 条并列、顺序可换）、grouped_panels（2-4 组层级或分组）、"
        "comparison（≥2 个对象在同一组维度上并排）、ordered_steps（2-5 步有先后）、"
        "relation（显式节点与有向边，边要能标 evidence/hypothesis）、"
        "curve（示意曲线或趋势，content.schematic=true）、image_evidence（必须读一张实测图）。\n"
        "每条必须绑定本 node 的 evidence；content 写清 items/objects/dimensions/groups/nodes/edges；"
        "source_quote 可选，但必须是引用证据中的原文片段。一页最多一个 primary。"
        "没有结构需求时写 must_show: [] 和 prose_ok_reason，不要为用能力硬造结构。\n"
        "form 仍可选，只是 RPA 类别提示；写了 explain 就可以省略 form，"
        "下游会从 required 的 ordered_steps / comparison 推导。"
        "如果仍写 form，sequence 配 process_steps、compare 配 comparison_dimensions，规则同旧版。"
        "注意：form=relation 是旧的“公式/可测关系”含义；explain.kind=relation 指节点与有向边，两者不同。\n"
        "陷阱：process-flow archetype 不是原生流程图，metric-comparison 不是原生表格，"
        "figure-parameters 不是 visual_plan。不要因为选了这些名字就以为结构已经存在。\n\n"
        "当一句 answer 会抹掉必须保留的连续内容时，可在该 node 添加 key_points 字符串数组；"
        "逐条保留证据支持的细节，不要求每个 node 都添加，也不限制条数。\n\n"
        "自检：删掉任一 node 后，下一 node 是否仍只因为论文顺序而出现？如果是，重写链条。"
    )
    return {
        "status": "ready_for_high_capability_subagent",
        "delegation": {
            "required": True,
            "mode": "subagent",
            "model": model,
            "reasoning_effort": effort,
            "selected_by_user": True,
        },
        "instructions": instructions,
        "capability_card": CAPABILITY_CARD,
        "output_shape": output_shape,
        "paper": {"title": workflow.title, "source_fingerprint": workflow.fingerprint},
        "evidence_store": evidence,
    }
