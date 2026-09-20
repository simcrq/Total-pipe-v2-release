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
    "HIGH_REASONING_EFFORTS",
    "build_story_prompt",
    "load_story",
    "story_to_specs",
    "validate_story",
]

HIGH_REASONING_EFFORTS = frozenset({"high", "xhigh", "max", "ultra"})
_ROOT_FIELDS = frozenset({"planner", "core_question", "main_message", "story", "ending"})
_PLANNER_FIELDS = frozenset({"mode", "model", "reasoning_effort", "selected_by_user"})
_NODE_FIELDS = frozenset({"question", "answer", "evidence", "next"})
_ENDING_FIELDS = frozenset({"takeaway", "limitation"})

_GENERIC_NEXT = re.compile(
    r"^(?:then|next|after that|additionally|furthermore|然后|接下来|此外|随后)"
    r"(?:\s*(?:看|讨论|介绍|作者|we|the authors))?",
    re.IGNORECASE,
)
_FIGURE_ONLY = re.compile(r"^(?:fig(?:ure)?\.?|图)\s*[0-9a-z]+\s*$", re.IGNORECASE)
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
            Problem("STORY_NODES_NOT_ARRAY", "story.story", "story must be an array of 5-8 reasoning nodes.")
        )
        nodes_raw = []
    elif not 5 <= len(nodes_raw) <= 8:
        problems.append(
            Problem(
                "STORY_NODE_COUNT_INVALID",
                "story.story",
                "a research talk needs 5-8 reasoning nodes; nodes are not figures or slides.",
                actual=len(nodes_raw),
                expected="5-8",
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
        question = _required_text(node_raw, "question", path, problems)
        answer = _required_text(node_raw, "answer", path, problems)
        next_question = _required_text(node_raw, "next", path, problems)
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

        nodes.append({
            "question": question,
            "answer": answer,
            "evidence": resolved,
            "next": next_question,
        })

    ending_raw = raw.get("ending")
    ending: dict[str, str] = {"takeaway": "", "limitation": ""}
    if not isinstance(ending_raw, Mapping):
        problems.append(Problem("STORY_ENDING_MISSING", "story.ending", "ending must contain takeaway and limitation."))
    else:
        problems.extend(_unknown_fields(ending_raw, _ENDING_FIELDS, "story.ending"))
        ending = {
            "takeaway": _required_text(ending_raw, "takeaway", "story.ending", problems),
            "limitation": _required_text(ending_raw, "limitation", "story.ending", problems),
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


def _category_for(question: str, index: int) -> str:
    lower = question.lower()
    if index == 0:
        return "question"
    if any(token in lower for token in ("为什么", "机制", "原因", "解释", "why", "mechanism", "explain")):
        return "discussion"
    if any(token in lower for token in ("如何", "方法", "策略", "how", "method", "approach")):
        return "method_overview"
    if any(token in lower for token in ("局限", "边界", "不足", "limit", "boundary")):
        return "limitations"
    return ("case", "gap", "theory", "decision")[(index - 1) % 4]


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
        category = _category_for(node["question"], index)
        title_limit = max((layout.title_chars or 0) for layout in fit.CATEGORIES[category].layouts) or 34
        specs.append(
            {
                "slide_type": "custom",
                "category_hint": category,
                "title": _truncate(node["question"], title_limit),
                "takeaway": node["answer"],
                "evidence_ids": list(node["evidence"]),
                "content_roles": ["primary_claim", "primary_evidence"],
                "narrative_job": "story_reasoning",
                "allow_auto_split": True,
                "metadata": {
                    **common,
                    "story_role": "reasoning_node",
                    "story_node_index": index + 1,
                    "story_question": node["question"],
                    "story_answer": node["answer"],
                    "story_next": node["next"],
                },
            }
        )

    final_evidence = list(dict.fromkeys(
        evidence_id
        for node in plan["story"][-2:]
        for evidence_id in node["evidence"]
    ))
    specs.append(
        {
            "slide_type": "summary",
            "category_hint": "summary",
            "title": "结论与边界",
            "takeaway": plan["ending"]["takeaway"],
            "body": plan["ending"]["limitation"],
            "evidence_ids": final_evidence,
            "content_roles": ["primary_claim", "supporting_evidence"],
            "narrative_job": "summary",
            "allow_auto_split": True,
            "metadata": {**common, "story_role": "ending", **plan["ending"]},
        }
    )
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
            {"question": "string", "answer": "string", "evidence": ["EV0001"], "next": "string"}
        ],
        "ending": {"takeaway": "string", "limitation": "string"},
    }
    instructions = (
        "你不是在总结论文，也不是按 Figure 顺序写大纲。你要从 Evidence Store 中选择最重要的证据，"
        "把论文重构为听众理解问题的顺序。只输出一个 JSON 对象，不要 Markdown。\n\n"
        "硬约束：\n"
        "1. 输出 5-8 个 story nodes；每个 node 是科研推理的一步，不是一个 Figure。\n"
        "2. 每个 node 必须是 Question → Answer → Evidence → Next Question。\n"
        "3. answer 只能由列出的 Evidence id 支撑；不得创造事实、因果关系或确定性。\n"
        "4. 原文的 may/likely/suggest/possibly/可能/提示/推测必须保留其不确定性。\n"
        "5. next 必须说明当前证据留下的疑问、缺口、待排除解释或待验证机制；不得写成‘然后看 Fig.4’。\n"
        "6. 允许删除重复、展示性或弱相关证据，目标是最短、最清晰的核心证据链。\n"
        "7. 不决定 PPT 页数、布局、配色、裁图或完整实验参数。\n"
        "8. 相邻节点应能用‘因此/但是/为了验证/为了排除/如果该解释成立’连接。\n\n"
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
        "output_shape": output_shape,
        "paper": {"title": workflow.title, "source_fingerprint": workflow.fingerprint},
        "evidence_store": evidence,
    }
