"""JSON bridge for the PaperWorkflow DeepSeek Harness plugin."""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any


# The project root is derived from this file's own location
# (integrations/deepseek-harness -> project root) and can be overridden with
# PAPERWORKFLOW_ROOT when the plugin is installed from a different checkout.
PROJECT_ROOT = Path(
    os.environ.get("PAPERWORKFLOW_ROOT")
    or Path(__file__).resolve().parent.parent.parent
).resolve()
INPUT_ROOT = PROJECT_ROOT / "INput"
sys.path.insert(0, str(PROJECT_ROOT))

from utils.agent_tools import get_document_outline, retrieve_evidence
from utils.literature_workflow import build_literature_workflow
from utils.literature_prompt import build_prompt_builder_result
from utils.paper_tools import source_fingerprint


def safe_project_path(value: Any, suffix: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("path must be a non-empty string")
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = PROJECT_ROOT / candidate
    path = candidate.resolve()
    try:
        path.relative_to(PROJECT_ROOT)
    except ValueError as error:
        raise ValueError("path must stay inside the PaperWorkflow directory") from error
    if path.suffix.lower() != suffix:
        raise ValueError("path must point to a " + suffix + " file")
    if not path.is_file():
        raise FileNotFoundError("file not found: " + str(path))
    return path


def safe_markdown_path(value: Any) -> Path:
    return safe_project_path(value, ".md")


def safe_pdf_path(value: Any) -> Path:
    return safe_project_path(value, ".pdf")


def safe_source_path(value: Any) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("source_path must be a non-empty string")
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = PROJECT_ROOT / candidate
    path = candidate.resolve()
    try:
        path.relative_to(PROJECT_ROOT)
    except ValueError as error:
        raise ValueError("source_path must stay inside the PaperWorkflow directory") from error
    if path.suffix.lower() not in {".pdf", ".md"}:
        raise ValueError("source_path must point to a .pdf or .md file")
    if not path.is_file():
        raise FileNotFoundError("file not found: " + str(path))
    return path


def safe_project_directory(value: Any) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("output_dir must be a non-empty string when provided")
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = PROJECT_ROOT / candidate
    path = candidate.resolve()
    try:
        path.relative_to(PROJECT_ROOT)
    except ValueError as error:
        raise ValueError("output_dir must stay inside the PaperWorkflow directory") from error
    if path.exists() and not path.is_dir():
        raise ValueError("output_dir must point to a directory")
    return path


def workflow_config() -> dict[str, Any]:
    try:
        import yaml
    except ModuleNotFoundError as error:
        raise RuntimeError(
            "PaperWorkflow Python dependencies are missing; install pyyaml, requests, and loguru in WSL"
        ) from error
    config_path = PROJECT_ROOT / "config.yaml"
    if not config_path.is_file():
        raise FileNotFoundError("config.yaml not found: " + str(config_path))
    with config_path.open("r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle) or {}
    paths = config.setdefault("paths", {})
    for key in ("input_dir", "output_dir", "merge_output_dir", "temp_dir"):
        value = paths.get(key)
        if isinstance(value, str) and value.strip() and not Path(value).expanduser().is_absolute():
            paths[key] = str((PROJECT_ROOT / value).resolve())
    return config


def cache_root_for(pdf_path: Path, config: dict[str, Any]) -> Path:
    temp_dir = Path(config.get("paths", {}).get("temp_dir", PROJECT_ROOT / "temp_markdowns")).expanduser()
    if not temp_dir.is_absolute():
        temp_dir = PROJECT_ROOT / temp_dir
    stat = pdf_path.stat()
    cache_key = hashlib.sha256(
        f"{pdf_path}\0{stat.st_size}\0{stat.st_mtime_ns}".encode("utf-8")
    ).hexdigest()[:16]
    return temp_dir.resolve() / cache_key


def markdown_roots(cache_root: Path, pdf_path: Path, config: dict[str, Any]) -> list[Path]:
    temp_dir = Path(config.get("paths", {}).get("temp_dir", PROJECT_ROOT / "temp_markdowns")).expanduser()
    if not temp_dir.is_absolute():
        temp_dir = PROJECT_ROOT / temp_dir
    return [cache_root, temp_dir.resolve() / pdf_path.stem]


def find_markdown(cache_root: Path, pdf_path: Path, config: dict[str, Any]) -> Path | None:
    file_stem = pdf_path.stem
    for root in markdown_roots(cache_root, pdf_path, config):
        candidates = [
            root / (file_stem + ".md"),
            root / "full.md",
            root / "auto" / (file_stem + ".md"),
            root / "hybrid_auto" / (file_stem + ".md"),
        ]
        for candidate in candidates:
            if candidate.is_file():
                return candidate.resolve()
        if root.is_dir():
            exact = sorted(root.rglob(file_stem + ".md"))
            if exact:
                return exact[0].resolve()
            any_markdown = sorted(root.rglob("*.md"))
            if any_markdown:
                return any_markdown[0].resolve()
    return None


def process_pdf(value: Any) -> dict[str, Any]:
    pdf_path = safe_pdf_path(value)
    config = workflow_config()
    try:
        from utils.pdf_handler import PDFProcessor
    except ModuleNotFoundError as error:
        raise RuntimeError(
            "PaperWorkflow Python dependencies are missing; install pyyaml, requests, and loguru in WSL"
        ) from error

    requested_cache_root = cache_root_for(pdf_path, config)
    before = find_markdown(requested_cache_root, pdf_path, config)
    processor = PDFProcessor(config)
    markdown = processor.convert_to_markdown(str(pdf_path))
    after = find_markdown(requested_cache_root, pdf_path, config)
    return {
        "source": str(pdf_path),
        "mineru_mode": processor.mode,
        "cache_dir": str(after.parent if after is not None else requested_cache_root),
        "requested_cache_dir": str(requested_cache_root),
        "cache_hit": before is not None,
        "markdown_path": str(after) if after is not None else None,
        "char_count": len(markdown),
        "message": "MinerU PDF-to-Markdown/OCR completed; no LLM summary was requested.",
    }


def literature_workflow(payload: dict[str, Any]) -> dict[str, Any]:
    source_path = safe_source_path(payload.get("source_path"))
    queries = payload.get("queries", [])
    if not isinstance(queries, list):
        raise ValueError("queries must be an array of strings")
    if len(queries) > 12:
        raise ValueError("queries accepts at most 12 custom questions")
    for query in queries:
        if not isinstance(query, str) or not query.strip():
            raise ValueError("each query must be a non-empty string")
        if len(query) > 2000:
            raise ValueError("each query must be at most 2000 characters")

    include_defaults = payload.get("include_default_queries", True)
    if not isinstance(include_defaults, bool):
        raise ValueError("include_default_queries must be a boolean")
    top_k = payload.get("top_k", 5)
    if not isinstance(top_k, int) or isinstance(top_k, bool) or not 1 <= top_k <= 20:
        raise ValueError("top_k must be an integer from 1 to 20")
    chunk_chars = payload.get("chunk_chars", 6000)
    if (
        not isinstance(chunk_chars, int)
        or isinstance(chunk_chars, bool)
        or not 500 <= chunk_chars <= 20000
    ):
        raise ValueError("chunk_chars must be an integer from 500 to 20000")

    ingestion: dict[str, Any] | None = None
    if source_path.suffix.lower() == ".pdf":
        ingestion = process_pdf(str(source_path))
        markdown_value = ingestion.get("markdown_path")
        if not isinstance(markdown_value, str) or not markdown_value:
            raise RuntimeError("MinerU completed without a discoverable Markdown output")
        markdown_path = safe_markdown_path(markdown_value)
    else:
        markdown_path = safe_markdown_path(str(source_path))

    output_value = payload.get("output_dir")
    if output_value is None:
        output_dir = PROJECT_ROOT / "output" / "workflows" / source_fingerprint(source_path)
    else:
        output_dir = safe_project_directory(output_value)

    return build_literature_workflow(
        markdown_path=markdown_path,
        source_path=source_path,
        project_root=PROJECT_ROOT,
        output_dir=output_dir,
        custom_queries=queries,
        include_default_queries=include_defaults,
        top_k=top_k,
        chunk_chars=chunk_chars,
        ingestion=ingestion,
    )


def prompt_builder(payload: dict[str, Any]) -> dict[str, Any]:
    selected_pdf = payload.get("selected_pdf")
    if selected_pdf is not None and not isinstance(selected_pdf, str):
        raise ValueError("selected_pdf must be a relative path or selection id")

    research_goal = payload.get("research_goal")
    if research_goal is not None:
        if not isinstance(research_goal, str) or not research_goal.strip():
            raise ValueError("research_goal must be a non-empty string")
        if len(research_goal) > 4000:
            raise ValueError("research_goal must be at most 4000 characters")

    focus_questions = payload.get("focus_questions")
    if focus_questions is not None:
        if not isinstance(focus_questions, list):
            raise ValueError("focus_questions must be an array of strings")
        if len(focus_questions) > 12:
            raise ValueError("focus_questions accepts at most 12 questions")
        for question in focus_questions:
            if not isinstance(question, str) or not question.strip():
                raise ValueError("each focus question must be a non-empty string")
            if len(question) > 1000:
                raise ValueError("each focus question must be at most 1000 characters")

    additional_context = payload.get("additional_context")
    if additional_context is not None:
        if not isinstance(additional_context, str) or not additional_context.strip():
            raise ValueError("additional_context must be a non-empty string")
        if len(additional_context) > 6000:
            raise ValueError("additional_context must be at most 6000 characters")

    return build_prompt_builder_result(
        INPUT_ROOT,
        selected_pdf=selected_pdf,
        research_goal=research_goal,
        focus_questions=focus_questions,
        additional_context=additional_context,
    )


def run(payload: dict[str, Any]) -> dict[str, Any]:
    operation = payload.get("operation")
    if operation == "literature_workflow":
        return literature_workflow(payload)
    if operation == "prompt_builder":
        return prompt_builder(payload)
    if operation == "outline":
        path = safe_markdown_path(payload.get("markdown_path"))
        chunk_chars = payload.get("chunk_chars", 6000)
        if not isinstance(chunk_chars, int) or isinstance(chunk_chars, bool):
            raise ValueError("chunk_chars must be an integer")
        return get_document_outline(str(path), chunk_chars=chunk_chars)
    if operation == "search_evidence":
        path = safe_markdown_path(payload.get("markdown_path"))
        query = payload.get("query")
        top_k = payload.get("top_k", 5)
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query must be a non-empty string")
        if not isinstance(top_k, int) or isinstance(top_k, bool):
            raise ValueError("top_k must be an integer")
        return retrieve_evidence(str(path), query=query, top_k=top_k)
    if operation == "process_pdf":
        return process_pdf(payload.get("pdf_path"))
    raise ValueError("unsupported operation: " + repr(operation))


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            raise ValueError("request must be a JSON object")
        result = run(payload)
        json.dump(result, sys.stdout, ensure_ascii=False)
        sys.stdout.write("\n")
        return 0
    except Exception as error:
        print("PaperWorkflow bridge error: " + str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
