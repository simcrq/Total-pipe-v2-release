"""Relative PDF indexing and reusable Harness prompt generation."""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

INPUT_ROOT_LABEL = "INput"
DEFAULT_RESEARCH_GOAL = "系统提取论文的制备流程、物理图像、关键结果和局限性"
DEFAULT_FOCUS_QUESTIONS = (
    "样品、器件或计算模型如何制备或建立？",
    "实验装置、测量方法和关键参数是什么？",
    "论文对应的物理图像和作用机制是什么？",
    "最关键的实验结果和定量指标是什么？",
    "作者明确声明了哪些局限性？",
    "根据实验条件还能推导出哪些潜在限制？",
)


def _clean_inline(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip())


def index_input_pdfs(
    input_root: Path, *, root_label: str = INPUT_ROOT_LABEL
) -> list[dict[str, Any]]:
    """Recursively index PDFs while exposing paths relative to the input root."""

    root = input_root.expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError("input directory not found: " + str(root))

    candidates: list[tuple[str, Path]] = []
    for candidate in root.rglob("*"):
        if not candidate.is_file() or candidate.suffix.casefold() != ".pdf":
            continue
        resolved = candidate.resolve()
        try:
            relative = resolved.relative_to(root)
        except ValueError:
            continue
        candidates.append((relative.as_posix(), resolved))

    candidates.sort(key=lambda item: item[0].casefold())
    return [
        {
            "selection_id": f"P{index:03d}",
            "relative_path": relative_path,
            "source_path": str(resolved),
            "project_relative_path": f"{root_label}/{relative_path}",
            "folder": (
                Path(relative_path).parent.as_posix()
                if Path(relative_path).parent.as_posix() != "."
                else "."
            ),
            "filename": Path(relative_path).name,
            "size_bytes": resolved.stat().st_size,
        }
        for index, (relative_path, resolved) in enumerate(candidates, start=1)
    ]


def resolve_pdf_selection(
    input_root: Path,
    selected_pdf: str,
    *,
    root_label: str = INPUT_ROOT_LABEL,
) -> tuple[Path, str]:
    """Resolve one input-root-relative PDF selection without allowing traversal."""

    if not isinstance(selected_pdf, str) or not selected_pdf.strip():
        raise ValueError("selected_pdf must be a non-empty relative path")
    normalized = selected_pdf.strip().replace("\\", "/")
    label_prefix = root_label.rstrip("/") + "/"
    if normalized.casefold().startswith(label_prefix.casefold()):
        normalized = normalized[len(label_prefix) :]
    relative = Path(normalized)
    if relative.is_absolute() or ":" in normalized:
        raise ValueError("selected_pdf must be relative to source_dir")

    root = input_root.expanduser().resolve()
    candidate = (root / relative).resolve()
    try:
        resolved_relative = candidate.relative_to(root)
    except ValueError as error:
        raise ValueError("selected_pdf must stay inside INput/source_dir") from error
    if candidate.suffix.casefold() != ".pdf":
        raise ValueError("selected_pdf must point to a PDF")
    if not candidate.is_file():
        raise FileNotFoundError("PDF not found in source_dir: " + resolved_relative.as_posix())
    return candidate, resolved_relative.as_posix()


def normalize_focus_questions(
    questions: Iterable[str] | None,
) -> list[str]:
    if questions is None:
        return list(DEFAULT_FOCUS_QUESTIONS)
    normalized: list[str] = []
    for question in questions:
        clean = _clean_inline(question)
        if clean and clean not in normalized:
            normalized.append(clean)
    return normalized or list(DEFAULT_FOCUS_QUESTIONS)


def build_workflow_prompt(
    relative_pdf_path: str,
    *,
    source_display_path: str | None = None,
    research_goal: str | None = None,
    focus_questions: Iterable[str] | None = None,
    additional_context: str | None = None,
) -> str:
    """Create a strict but compact prompt for the unified literature workflow."""

    goal = _clean_inline(research_goal or DEFAULT_RESEARCH_GOAL)
    questions = normalize_focus_questions(focus_questions)
    project_relative_path = source_display_path or f"{INPUT_ROOT_LABEL}/{relative_pdf_path}"
    lines = [
        "请调用 paperworkflow_literature_workflow 处理：",
        project_relative_path,
        "",
        "研究目标：",
        goal,
    ]
    if additional_context and _clean_inline(additional_context):
        lines.extend(["", "补充背景：", _clean_inline(additional_context)])
    lines.extend(["", "重点回答："])
    lines.extend(f"{index}. {question}" for index, question in enumerate(questions, start=1))
    lines.extend(
        [
            "",
            "执行要求：",
            "1. 遵守 workflow.json 中的 claim_ledger_contract。",
            "2. 每个主要结论和数字必须引用 EV####，并保留 S####/E###、精确行号和字符偏移。",
            "3. 区分直接观察、测量、模拟、拟合、作者推断和二次推断。",
            "4. 区分材料合成、实验室制备、优化批次和连续化/R2R 工艺参数。",
            "5. 区分测试条件与实际结果；不同上下文中的数值范围不得合并。",
            "6. 局限性分为作者明确声明、合理推导和证据包限制。",
            "7. quality_audit 仅代表文本捕获质量；科学结论以硬门禁 synthesis_readiness 为准。",
            "8. 分别报告检索精度、流程覆盖率、阅读顺序和 chunk coherence，不得用一个总分替代。",
            "9. 补充材料被引用但本地不可用时，相关机制结论必须标记为“证据不完整”。",
            "",
            "输出内容：",
            "- 论文基本信息",
            "- 制备流程表",
            "- 物理图像与证据类型",
            "- 关键结果与定量指标",
            "- 分类后的局限性",
            "- EV#### 主张—证据台账及未覆盖流程",
            "- 主张—证据台账",
            "- 分维度质量审计",
            "- evidence.md、workflow.json、document.manifest.json、原始 Markdown 路径和门禁结论",
            "",
            "无法从证据确认的内容必须标记为“未确认”，不得自行补全。",
        ]
    )
    return "\n".join(lines)


def build_prompt_builder_result(
    input_root: Path,
    *,
    selected_pdf: str | None = None,
    research_goal: str | None = None,
    focus_questions: Iterable[str] | None = None,
    additional_context: str | None = None,
    root_label: str = INPUT_ROOT_LABEL,
) -> dict[str, Any]:
    """Return either a relative PDF selection index or a generated prompt."""

    root = input_root.expanduser().resolve()
    pdf_index = index_input_pdfs(root, root_label=root_label)
    if selected_pdf is None or not selected_pdf.strip():
        return {
            "mode": "selection_required",
            "input_root": str(root),
            "path_policy": "Selections are relative to source_dir; resolved source_path is included for MCP calls.",
            "pdf_count": len(pdf_index),
            "pdf_index": pdf_index,
            "next_action": (
                "Ask the user to choose a selection_id or relative_path, then call this "
                "tool again with selected_pdf and any known research information."
            ),
        }

    selection = selected_pdf.strip()
    matched_entry = next(
        (item for item in pdf_index if item["selection_id"].casefold() == selection.casefold()),
        None,
    )
    if matched_entry is not None:
        selection = matched_entry["relative_path"]

    selected_path, relative_path = resolve_pdf_selection(root, selection, root_label=root_label)
    return {
        "mode": "prompt_ready",
        "input_root": str(root),
        "selected_pdf": {
            "relative_path": relative_path,
            "source_path": str(selected_path),
            "project_relative_path": f"{root_label}/{relative_path}",
        },
        "research_goal": _clean_inline(research_goal or DEFAULT_RESEARCH_GOAL),
        "focus_questions": normalize_focus_questions(focus_questions),
        "prompt": build_workflow_prompt(
            relative_path,
            source_display_path=(
                f"{INPUT_ROOT_LABEL}/{relative_path}"
                if root_label == INPUT_ROOT_LABEL
                else str(selected_path)
            ),
            research_goal=research_goal,
            focus_questions=focus_questions,
            additional_context=additional_context,
        ),
        "next_action": (
            "Return the prompt to the user, or use it to call "
            "paperworkflow_literature_workflow when the user requested processing."
        ),
    }
