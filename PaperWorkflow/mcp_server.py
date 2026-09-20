#!/usr/bin/env python3
"""MCP server for PaperWorkflow — tool names follow the total-pipe-deck contract.

The contract lives in the ``total-pipe-deck`` skill (SKILL.md, stage 1) and is
the authority for tool naming; do not rename these tools without updating it.

    paperworkflow_prompt_builder        list INput PDFs, or build the stage-1 prompt
    paperworkflow_literature_workflow   markdown/pdf -> workflow.json + evidence.md
    paperworkflow_outline               section outline of a converted .md
    paperworkflow_search_evidence       line-addressable evidence passages
    paperworkflow_process_pdf           OCR only, no evidence registry
    paperworkflow_list_outputs          list generated artefacts
    paperworkflow_build_manifest        chunk + span manifest

Dependency policy: the retrieval path (``evidence_graph -> paper_tools ->
literature_workflow``) is standard library only, so every tool except
``_process_pdf`` (and the OCR branch of ``_literature_workflow``) works without
installing anything. Those two need ``loguru`` + the MinerU CLI and degrade to an
explicit, actionable error rather than crashing the server.

Protocol: JSON-RPC 2.0 over stdio. Accepts both newline-delimited JSON and
Content-Length framing. stdout is reserved for the protocol — all logging goes
to stderr or $PAPERWORKFLOW_LOG.
"""

from __future__ import annotations

import io
import json
import os
import sys
import threading
import traceback
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SERVER_INFO = {"name": "paperworkflow", "version": "0.2.0"}
PROTOCOL_VERSION = "2025-06-18"

DEFAULT_INPUT_DIR = ROOT / "INput"
DEFAULT_OUTPUT_ROOT = ROOT / "output"
DEFAULT_WORKFLOW_ROOT = DEFAULT_OUTPUT_ROOT / "workflows"
DEFAULT_MARKDOWN_ROOT = DEFAULT_OUTPUT_ROOT / "markdowns"

DEFAULT_TIMEOUT = float(os.environ.get("PAPERWORKFLOW_TOOL_TIMEOUT", "120"))
OCR_TIMEOUT = float(os.environ.get("PAPERWORKFLOW_OCR_TIMEOUT", "1800"))

_env_roots = os.environ.get("PAPERWORKFLOW_ROOTS")
ALLOWED_ROOTS = [
    Path(p).expanduser().resolve()
    for p in (_env_roots.split(os.pathsep) if _env_roots else [str(ROOT)])
]
for _extra in (DEFAULT_INPUT_DIR, DEFAULT_OUTPUT_ROOT):
    try:
        ALLOWED_ROOTS.append(_extra.resolve())
    except OSError:
        pass


def log(msg: str) -> None:
    target = os.environ.get("PAPERWORKFLOW_LOG")
    try:
        if target:
            with open(target, "a", encoding="utf-8") as fh:
                fh.write(msg + "\n")
        else:
            print(msg, file=sys.stderr)
    except OSError:
        pass


INSTRUCTIONS = (
    "PaperWorkflow stage 1 of the Total-pipe pipeline. Start with "
    "paperworkflow_prompt_builder with no arguments to list the PDFs in INput and let "
    "the user choose — never pick for them. Call it again with selected_pdf to build "
    "the prompt, then paperworkflow_literature_workflow to produce workflow.json. "
    "Gate on synthesis_readiness, not quality_audit. Take artefact paths from the "
    "return value; do not guess directories."
)


# --------------------------------------------------------------------------- #
# stdout isolation + timeouts (stdout is the protocol channel)
# --------------------------------------------------------------------------- #


class _Divert:
    """Write-only stream forwarding anything the library prints to stderr."""

    def __init__(self, sink: Any) -> None:
        self._sink = sink

    def write(self, data: Any) -> int:
        try:
            self._sink.write(data)
        except Exception:
            pass
        return len(data) if hasattr(data, "__len__") else 0

    def flush(self) -> None:
        try:
            self._sink.flush()
        except Exception:
            pass

    def isatty(self) -> bool:
        return False

    def fileno(self) -> int:
        raise io.UnsupportedOperation("stdout is reserved for JSON-RPC")


def run_callable(fn: Callable[[], Any], timeout: float = DEFAULT_TIMEOUT) -> Any:
    """Run a tool body off the protocol thread with a wall-clock cap."""
    box: dict[str, Any] = {}

    def target() -> None:
        saved = sys.stdout
        sys.stdout = _Divert(sys.stderr)
        try:
            box["value"] = fn()
        except BaseException as error:  # noqa: BLE001 - reported to the caller
            box["error"] = error
        finally:
            sys.stdout = saved

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    thread.join(timeout)
    if thread.is_alive():
        raise TimeoutError(f"tool exceeded {timeout:g}s; still running in background")
    if "error" in box:
        raise box["error"]
    return box.get("value")


# --------------------------------------------------------------------------- #
# Path safety
# --------------------------------------------------------------------------- #


def resolve_safe(raw: str) -> Path:
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = ROOT / path
    resolved = path.resolve()
    for root in ALLOWED_ROOTS:
        try:
            resolved.relative_to(root)
            return resolved
        except ValueError:
            continue
    raise PermissionError(
        f"Path outside allowed roots: {resolved}. "
        f"Allowed: {', '.join(str(r) for r in ALLOWED_ROOTS)}. "
        f"Set PAPERWORKFLOW_ROOTS to widen."
    )


def resolve_source(raw: str, *, suffix: str | None = None) -> Path:
    """Resolve a contract source path: INput-relative, project-relative or absolute."""
    raw = str(raw).strip().replace("\\", "/")
    if not raw:
        raise ValueError("path is required")
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        # Contract convention: bare paths are relative to INput.
        inline = DEFAULT_INPUT_DIR / raw
        resolved = inline if inline.exists() else ROOT / raw
    else:
        resolved = candidate
    path = resolve_safe(str(resolved))
    if not path.exists():
        raise FileNotFoundError(f"Not found: {path}")
    if suffix and path.suffix.casefold() != suffix:
        raise ValueError(f"Expected a {suffix} file, got {path.suffix or '<none>'}")
    return path


def load_config() -> dict[str, Any]:
    """config.yaml, or {} when pyyaml is unavailable (tools degrade, not crash)."""
    cfg_path = ROOT / "config.yaml"
    if not cfg_path.is_file():
        return {}
    try:
        import yaml  # type: ignore
    except ImportError:
        log("[config] pyyaml not installed; config.yaml paths/modes unavailable")
        return {}
    try:
        return yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    except Exception as exc:  # noqa: BLE001
        log(f"[config] parse failed: {exc}")
        return {}


def input_root() -> Path:
    cfg = load_config()
    raw = (cfg.get("paths") or {}).get("input_dir")
    base = Path(raw).expanduser() if raw else DEFAULT_INPUT_DIR
    if not base.is_absolute():
        base = ROOT / base
    return base.resolve()


def missing_ocr_deps() -> list[str]:
    missing = []
    try:
        import loguru  # noqa: F401
    except ImportError:
        missing.append("loguru")
    return missing


def blocked_ocr(what: str) -> dict[str, Any]:
    return {
        "status": "blocked",
        "reason": "missing_dependencies",
        "missing": missing_ocr_deps(),
        "detail": f"{what} needs PDF ingestion (MinerU).",
        "remedy": (
            "pip install loguru pyyaml requests into the interpreter that runs this "
            "server, then ensure the MinerU CLI configured in config.yaml "
            "(api.mineru.cli_command) is installed and MINERU_TOKEN is set. "
            "Everything except PDF ingestion works without this."
        ),
    }


# --------------------------------------------------------------------------- #
# Tools
# --------------------------------------------------------------------------- #


def tool_prompt_builder(args: dict[str, Any]) -> dict[str, Any]:
    """List INput PDFs (no args) or build the stage-1 prompt (with selected_pdf)."""
    from utils.literature_prompt import build_prompt_builder_result

    return build_prompt_builder_result(
        input_root(),
        selected_pdf=args.get("selected_pdf"),
        research_goal=args.get("research_goal"),
        focus_questions=args.get("focus_questions"),
        additional_context=args.get("additional_context"),
    )


def tool_literature_workflow(args: dict[str, Any]) -> dict[str, Any]:
    """Build workflow.json / document.manifest.json / evidence.md for one source."""
    from utils.literature_workflow import build_literature_workflow

    raw_source = args.get("source_path")
    if not raw_source:
        raise ValueError("source_path is required")

    source_path = resolve_source(raw_source)
    suffix = source_path.suffix.casefold()

    if suffix == ".md":
        markdown_path = source_path
        ingestion = None
    elif suffix == ".pdf":
        if missing_ocr_deps():
            return blocked_ocr("OCR for a PDF source")
        markdown_path = _ocr_to_markdown(source_path)
        ingestion = {"mode": _mineru_mode(), "engine": "mineru"}
    else:
        raise ValueError("source_path must be .pdf or .md")

    output_dir = args.get("output_dir")
    if output_dir:
        out = resolve_safe(output_dir)
    else:
        out = DEFAULT_WORKFLOW_ROOT / source_path.stem
    out.mkdir(parents=True, exist_ok=True)

    workflow = build_literature_workflow(
        markdown_path=markdown_path,
        source_path=source_path,
        project_root=ROOT,
        output_dir=out,
        custom_queries=args.get("queries") or (),
        include_default_queries=bool(args.get("include_default_queries", True)),
        top_k=int(args.get("top_k", 5)),
        chunk_chars=int(args.get("chunk_chars", 6000)),
        ingestion=ingestion,
    )

    readiness = workflow.get("synthesis_readiness") or {}
    return {
        "status": "completed",
        "schema_version": workflow.get("schema_version"),
        "workflow_id": workflow.get("workflow_id"),
        "source": {
            "input_path": workflow["source"]["input_path"],
            "markdown_path": workflow["source"]["markdown_path"],
            "input_type": workflow["source"]["input_type"],
        },
        "artifacts": workflow.get("artifacts"),
        "synthesis_readiness": readiness,
        "quality_audit": workflow.get("quality_audit"),
        "counts": {
            "chunks": workflow["outline"]["chunk_count"],
            "spans": workflow["outline"]["span_count"],
            "evidence": len(workflow.get("evidence_registry") or []),
            "queries": len(workflow.get("evidence") or []),
        },
        "note": (
            "Gate on synthesis_readiness, not quality_audit. Take artefact paths from "
            "artifacts above; do not guess directory names."
        ),
        "workflow": workflow,
    }


def _mineru_mode() -> str:
    return (load_config().get("api") or {}).get("mineru", {}).get("mode", "official_cli")


def _ocr_to_markdown(pdf_path: Path) -> Path:
    """OCR a PDF and persist the Markdown so downstream tools can address it."""
    from utils.pdf_handler import PDFProcessor

    config = load_config()
    paths = config.setdefault("paths", {})
    temp_dir = paths.get("temp_dir") or "./temp_markdowns"
    temp_path = Path(temp_dir)
    if not temp_path.is_absolute():
        temp_path = ROOT / temp_path
    paths["temp_dir"] = str(temp_path)
    config.setdefault("api", {}).setdefault("mineru", {}).setdefault("mode", "official_cli")

    markdown = PDFProcessor(config).convert_to_markdown(str(pdf_path))

    DEFAULT_MARKDOWN_ROOT.mkdir(parents=True, exist_ok=True)
    target = DEFAULT_MARKDOWN_ROOT / f"{pdf_path.stem}.md"
    target.write_text(markdown, encoding="utf-8")
    return target


def tool_process_pdf(args: dict[str, Any]) -> dict[str, Any]:
    """OCR a PDF to Markdown only — no evidence registry is built."""
    raw = args.get("pdf_path")
    if not raw:
        raise ValueError("pdf_path is required")
    pdf_path = resolve_source(raw, suffix=".pdf")
    if missing_ocr_deps():
        return blocked_ocr("paperworkflow_process_pdf")
    target = _ocr_to_markdown(pdf_path)
    text = target.read_text(encoding="utf-8", errors="replace")
    return {
        "status": "completed",
        "source_pdf": str(pdf_path),
        "markdown_path": str(target),
        "char_count": len(text),
        "note": "OCR only. No evidence registry produced — use "
                "paperworkflow_literature_workflow for that.",
    }


def tool_outline(args: dict[str, Any]) -> dict[str, Any]:
    from utils.agent_tools import get_document_outline

    path = resolve_source(args["markdown_path"], suffix=".md")
    return get_document_outline(str(path), chunk_chars=int(args.get("chunk_chars", 6000)))


def tool_search_evidence(args: dict[str, Any]) -> dict[str, Any]:
    from utils.agent_tools import retrieve_evidence

    path = resolve_source(args["markdown_path"], suffix=".md")
    query = args.get("query")
    if not query:
        raise ValueError("query is required")
    result = retrieve_evidence(str(path), query, top_k=int(args.get("top_k", 5)))
    result["hint"] = (
        "Zero hits usually means the query terms are absent or the document is in "
        "another language. Try document vocabulary, or call paperworkflow_outline first."
    )
    return result


def tool_build_manifest(args: dict[str, Any]) -> dict[str, Any]:
    from utils.paper_tools import document_manifest

    path = resolve_source(args["markdown_path"], suffix=".md")
    manifest = document_manifest(
        path.read_text(encoding="utf-8", errors="replace"),
        markdown_path=path,
        chunk_chars=int(args.get("chunk_chars", 6000)),
    )
    for chunk in manifest.get("chunks", []):
        chunk.pop("text", None)
    for span in manifest.get("spans", []):
        span.pop("text", None)
    manifest["_note"] = (
        "Chunk/span bodies stripped for transport; call "
        "paperworkflow_search_evidence to read passages."
    )
    return manifest


def tool_list_outputs(args: dict[str, Any]) -> dict[str, Any]:
    cfg = load_config()
    raw = args.get("output_dir") or (cfg.get("paths") or {}).get("output_dir") or str(DEFAULT_OUTPUT_ROOT)
    base = Path(raw).expanduser()
    if not base.is_absolute():
        base = ROOT / base
    base = resolve_safe(str(base))
    if not base.is_dir():
        return {"output_dir": str(base), "exists": False, "items": []}

    limit = int(args.get("limit", 200))
    items = []
    for path in sorted(base.rglob("*")):
        if path.is_file():
            name = path.name
            items.append({
                "path": str(path),
                "name": name,
                "size": path.stat().st_size,
                "kind": "manifest" if name.endswith(".manifest.json")
                        else "workflow" if name == "workflow.json"
                        else path.suffix.lstrip("."),
            })
            if len(items) >= limit:
                break
    return {"output_dir": str(base), "exists": True, "count": len(items), "items": items}


TOOLS: dict[str, dict[str, Any]] = {
    "paperworkflow_prompt_builder": {
        "description": (
            "Stage 1a/1c. With no arguments: list the PDFs under INput as a "
            "pdf_index of selection_id (P001…) + relative_path — show it to the user "
            "and let them choose, never pick for them. With selected_pdf: build the "
            "stage-1 workflow prompt. Standard library only."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "selected_pdf": {"type": "string", "description": "selection_id (P001) or an INput-relative path"},
                "research_goal": {"type": "string"},
                "focus_questions": {"type": "array", "items": {"type": "string"}},
                "additional_context": {"type": "string"},
            },
        },
        "timeout": 60,
        "handler": tool_prompt_builder,
    },
    "paperworkflow_literature_workflow": {
        "description": (
            "Stage 1b. Convert a .md (or .pdf via OCR) into the literature hand-off "
            "package: workflow.json, document.manifest.json and evidence.md. Returns "
            "synthesis_readiness (the hard gate) and the artefact paths. Slow for PDFs "
            "(OCR); do not re-run unnecessarily."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "source_path": {"type": "string", "description": "Required. INput-relative path or absolute path; .pdf or .md"},
                "queries": {"type": "array", "items": {"type": "string"}, "maxItems": 12, "description": "Research questions, each <=2000 chars"},
                "include_default_queries": {"type": "boolean", "default": True},
                "top_k": {"type": "integer", "minimum": 1, "maximum": 20, "default": 5},
                "chunk_chars": {"type": "integer", "minimum": 500, "maximum": 20000, "default": 6000},
                "output_dir": {"type": "string", "description": "Optional directory inside the project"},
            },
            "required": ["source_path"],
        },
        "timeout": OCR_TIMEOUT,
        "handler": tool_literature_workflow,
    },
    "paperworkflow_outline": {
        "description": (
            "Section outline of a converted Markdown file: chunk ids, headings, line "
            "ranges, modalities. Deterministic, local, no model call."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "markdown_path": {"type": "string", "description": "Required. Path to a .md file"},
                "chunk_chars": {"type": "integer", "default": 6000},
            },
            "required": ["markdown_path"],
        },
        "timeout": 60,
        "handler": tool_outline,
    },
    "paperworkflow_search_evidence": {
        "description": (
            "Ranked, line-addressable evidence passages for a query against a "
            "converted Markdown file. Local and deterministic; call before asking a "
            "model to synthesise."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "markdown_path": {"type": "string", "description": "Required. Path to a .md file"},
                "query": {"type": "string", "description": "Required."},
                "top_k": {"type": "integer", "default": 5},
            },
            "required": ["markdown_path", "query"],
        },
        "timeout": 60,
        "handler": tool_search_evidence,
    },
    "paperworkflow_process_pdf": {
        "description": (
            "OCR a PDF to Markdown only; does not build an evidence registry. Needs "
            "loguru plus the MinerU CLI, and returns an actionable error when absent."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "pdf_path": {"type": "string", "description": "Required. Path to a .pdf file"},
            },
            "required": ["pdf_path"],
        },
        "timeout": OCR_TIMEOUT,
        "handler": tool_process_pdf,
    },
    "paperworkflow_build_manifest": {
        "description": (
            "Raw-chunk + atomic-span manifest for a Markdown file. Passage bodies are "
            "stripped; use paperworkflow_search_evidence to read them."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "markdown_path": {"type": "string"},
                "chunk_chars": {"type": "integer", "default": 6000},
            },
            "required": ["markdown_path"],
        },
        "timeout": 60,
        "handler": tool_build_manifest,
    },
    "paperworkflow_list_outputs": {
        "description": "List generated artefacts (workflow.json, manifests, evidence.md) under the output directory.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "output_dir": {"type": "string"},
                "limit": {"type": "integer", "default": 200},
            },
        },
        "timeout": 60,
        "handler": tool_list_outputs,
    },
}


def tools_list_payload() -> list[dict[str, Any]]:
    return [
        {"name": name, "description": spec["description"], "inputSchema": spec["inputSchema"]}
        for name, spec in TOOLS.items()
    ]


def call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    spec = TOOLS.get(name)
    if spec is None:
        raise KeyError(f"Unknown tool: {name}")
    handler: Callable[[dict[str, Any]], dict[str, Any]] = spec["handler"]
    return run_callable(lambda: handler(arguments or {}), spec.get("timeout", DEFAULT_TIMEOUT))


# --------------------------------------------------------------------------- #
# JSON-RPC loop
# --------------------------------------------------------------------------- #


def respond(message: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(message, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def handle(request: dict[str, Any]) -> dict[str, Any] | None:
    method = request.get("method")
    req_id = request.get("id")
    params = request.get("params") or {}

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": SERVER_INFO,
                "instructions": INSTRUCTIONS,
            },
        }

    if method in ("notifications/initialized", "initialized"):
        return None

    if method == "ping":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}

    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": tools_list_payload()}}

    if method == "tools/call":
        name = params.get("name")
        try:
            result = call_tool(name, params.get("arguments") or {})
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=2)}],
                    "structuredContent": result,
                    "isError": False,
                },
            }
        except Exception as exc:  # noqa: BLE001
            log(f"[tools/call] {name} failed: {exc}\n{traceback.format_exc()}")
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": f"{type(exc).__name__}: {exc}"}],
                    "isError": True,
                },
            }

    # Empty implementations so clients probing these do not error out.
    if method in ("resources/list", "prompts/list"):
        return {"jsonrpc": "2.0", "id": req_id, "result": {method.split("/")[0]: []}}
    if method in ("resources/templates/list",):
        return {"jsonrpc": "2.0", "id": req_id, "result": {"resourceTemplates": []}}

    if method in ("shutdown", "exit"):
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}

    if req_id is None:
        return None
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


def read_message() -> dict[str, Any] | None:
    """Read one message, accepting newline-delimited JSON or Content-Length framing."""
    stream = sys.stdin.buffer
    first = stream.readline()
    if not first:
        return None
    if first.lstrip().lower().startswith(b"content-length"):
        length = 0
        line = first
        while line and line.strip() not in (b"", b"\r\n"):
            if line.lstrip().lower().startswith(b"content-length"):
                length = int(line.split(b":", 1)[1].strip())
            line = stream.readline()
        payload = stream.read(length) if length else b""
        if not payload:
            return None
        return json.loads(payload.decode("utf-8"))
    text = first.strip()
    if not text:
        return None
    return json.loads(text.decode("utf-8"))


def main() -> None:
    log(f"[paperworkflow-mcp] starting, root={ROOT}, python={sys.executable}")
    while True:
        try:
            request = read_message()
        except json.JSONDecodeError as exc:
            log(f"[protocol] bad JSON: {exc}")
            continue
        except (KeyboardInterrupt, SystemExit):
            return
        if request is None:
            return
        try:
            response = handle(request)
        except Exception as exc:  # noqa: BLE001
            log(f"[protocol] handler crash: {exc}\n{traceback.format_exc()}")
            response = {
                "jsonrpc": "2.0",
                "id": request.get("id"),
                "error": {"code": -32603, "message": str(exc)},
            }
        if response is not None:
            respond(response)


if __name__ == "__main__":
    main()
