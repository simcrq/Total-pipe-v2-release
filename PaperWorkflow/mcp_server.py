#!/usr/bin/env python3
"""MCP server for PaperWorkflow — tool names follow the total-pipe-deck contract.

The contract lives in the ``total-pipe-deck`` skill (SKILL.md, stage 1) and is
the authority for tool naming; do not rename these tools without updating it.

    paperworkflow_prompt_builder        list PDFs in any directory / build a prompt
    paperworkflow_literature_workflow   PDF/Markdown -> self-contained Total-pipe bundle
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
from collections.abc import Callable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SERVER_INFO = {"name": "paperworkflow", "version": "0.3.0"}
PROTOCOL_VERSION = "2025-06-18"

DEFAULT_INPUT_DIR = ROOT / "INput"
DEFAULT_OUTPUT_ROOT = ROOT / "output"
DEFAULT_WORKFLOW_ROOT = DEFAULT_OUTPUT_ROOT / "workflows"
DEFAULT_TIMEOUT = float(os.environ.get("PAPERWORKFLOW_TOOL_TIMEOUT", "120"))
OCR_TIMEOUT = float(os.environ.get("PAPERWORKFLOW_OCR_TIMEOUT", "1800"))


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
    "PaperWorkflow stage 1 of the Total-pipe pipeline. Sources may be anywhere on "
    "the local filesystem. paperworkflow_literature_workflow produces a self-contained "
    "bundle with workflow.json, evidence.md, paper.md, document.manifest.json, figure "
    "assets and bundle.manifest.json. "
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
# Path resolution
# --------------------------------------------------------------------------- #


def resolve_path(raw: str, *, must_exist: bool = False) -> Path:
    """Resolve a local path without the historical project-root sandbox."""

    value = str(raw).strip()
    if not value:
        raise ValueError("path is required")
    path = Path(value).expanduser()
    candidates = (
        [path] if path.is_absolute() else [Path.cwd() / path, ROOT / path, input_root() / path]
    )
    resolved = next(
        (candidate.resolve() for candidate in candidates if candidate.exists()),
        candidates[0].resolve(),
    )
    if must_exist and not resolved.exists():
        raise FileNotFoundError(f"Not found: {resolved}")
    return resolved


def resolve_source(raw: str, *, suffix: str | None = None) -> Path:
    """Resolve a contract source path: INput-relative, project-relative or absolute."""
    raw = str(raw).strip().replace("\\", "/")
    if not raw:
        raise ValueError("path is required")
    path = resolve_path(raw, must_exist=True)
    if not path.is_file():
        raise ValueError(f"Expected a file, got: {path}")
    if suffix and path.suffix.casefold() != suffix:
        raise ValueError(f"Expected a {suffix} file, got {path.suffix or '<none>'}")
    return path


def config_candidates() -> list[Path]:
    """Return publish-safe config locations in precedence order.

    Installed Codex plugins run from a cache that intentionally excludes the
    gitignored ``config.yaml``.  Keep secrets outside the package and discover
    them at MCP call time instead of baking a machine path into ``.mcp.json``.
    """

    candidates: list[Path] = []
    explicit = str(os.environ.get("PAPERWORKFLOW_CONFIG") or "").strip()
    if explicit:
        candidates.append(Path(explicit).expanduser())

    inherited_pwd = str(os.environ.get("PWD") or "").strip()
    if inherited_pwd:
        workspace = Path(inherited_pwd).expanduser()
        candidates.extend((workspace / "config.yaml", workspace / "PaperWorkflow" / "config.yaml"))

    candidates.extend(
        (
            ROOT / "config.yaml",
            Path.home() / ".config" / "paperworkflow" / "config.yaml",
        )
    )

    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate.resolve(strict=False))
        if key not in seen:
            seen.add(key)
            unique.append(candidate)
    return unique


def find_config_path() -> Path | None:
    """Find the first readable PaperWorkflow config for this MCP process."""

    for candidate in config_candidates():
        if candidate.is_file():
            return candidate.resolve()
    return None


def load_config() -> dict[str, Any]:
    """Load the MCP config, or {} when unavailable (tools degrade, not crash)."""

    cfg_path = find_config_path()
    if cfg_path is None:
        return {}
    try:
        import yaml  # type: ignore
    except ImportError:
        log("[config] pyyaml not installed; config.yaml paths/modes unavailable")
        return {}
    try:
        config = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
        if not isinstance(config, dict):
            raise ValueError("top-level YAML value must be a mapping")
        return config
    except Exception as exc:  # noqa: BLE001
        log(f"[config] parse failed: {exc}")
        return {}


def input_root(source_dir: str | None = None) -> Path:
    if source_dir:
        path = resolve_path(source_dir, must_exist=True)
        if not path.is_dir():
            raise ValueError(f"source_dir must be a directory: {path}")
        return path
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
    """List PDFs in any directory or build the stage-1 prompt."""
    from utils.literature_prompt import build_prompt_builder_result

    source_root = input_root(args.get("source_dir"))
    root_label = "INput" if source_root == input_root() else str(source_root)
    return build_prompt_builder_result(
        source_root,
        selected_pdf=args.get("selected_pdf"),
        research_goal=args.get("research_goal"),
        focus_questions=args.get("focus_questions"),
        additional_context=args.get("additional_context"),
        root_label=root_label,
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
        conversion = _ocr_to_markdown(source_path)
        markdown_path = Path(conversion["markdown_path"])
        ingestion = {
            "mode": _mineru_mode(),
            "engine": "mineru",
            **{key: value for key, value in conversion.items() if key != "content"},
        }
    else:
        raise ValueError("source_path must be .pdf or .md")

    output_dir = args.get("output_dir")
    if output_dir:
        out = resolve_path(output_dir)
    else:
        from utils.paper_tools import source_fingerprint

        out = DEFAULT_WORKFLOW_ROOT / source_fingerprint(source_path)
    out.mkdir(parents=True, exist_ok=True)

    workflow = build_literature_workflow(
        markdown_path=markdown_path,
        source_path=source_path,
        project_root=source_path.parent,
        output_dir=out,
        custom_queries=args.get("queries") or (),
        include_default_queries=bool(args.get("include_default_queries", True)),
        top_k=int(args.get("top_k", 5)),
        chunk_chars=int(args.get("chunk_chars", 6000)),
        ingestion=ingestion,
    )

    readiness = workflow.get("synthesis_readiness") or {}
    result = {
        "status": "completed",
        "schema_version": workflow.get("schema_version"),
        "workflow_id": workflow.get("workflow_id"),
        "source": {
            "input_path": workflow["source"]["input_path"],
            "markdown_path": workflow["source"]["markdown_path"],
            "input_type": workflow["source"]["input_type"],
        },
        "artifacts": workflow.get("artifacts"),
        "bundle_dir": str(out.resolve()),
        "workflow_path": str((out / "workflow.json").resolve()),
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
    }
    if bool(args.get("include_workflow", False)):
        result["workflow"] = workflow
    return result


def _mineru_mode() -> str:
    return (load_config().get("api") or {}).get("mineru", {}).get("mode", "official_cli")


def _ocr_to_markdown(pdf_path: Path) -> dict[str, Any]:
    """OCR a PDF while preserving MinerU's Markdown and image directory."""
    from utils.pdf_handler import PDFProcessor

    config = load_config()
    paths = config.setdefault("paths", {})
    temp_dir = paths.get("temp_dir") or "./temp_markdowns"
    temp_path = Path(temp_dir)
    if not temp_path.is_absolute():
        temp_path = ROOT / temp_path
    paths["temp_dir"] = str(temp_path)
    config.setdefault("api", {}).setdefault("mineru", {}).setdefault("mode", "official_cli")

    return PDFProcessor(config).convert_to_markdown_result(str(pdf_path))


def tool_process_pdf(args: dict[str, Any]) -> dict[str, Any]:
    """OCR a PDF to Markdown only — no evidence registry is built."""
    raw = args.get("pdf_path")
    if not raw:
        raise ValueError("pdf_path is required")
    pdf_path = resolve_source(raw, suffix=".pdf")
    if missing_ocr_deps():
        return blocked_ocr("paperworkflow_process_pdf")
    result = _ocr_to_markdown(pdf_path)
    target = Path(result["markdown_path"])
    text = result["content"]
    return {
        "status": "completed",
        "source_pdf": str(pdf_path),
        "markdown_path": str(target),
        "cache_dir": result["cache_dir"],
        "cache_hit": result["cache_hit"],
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
    raw = (
        args.get("output_dir")
        or (cfg.get("paths") or {}).get("output_dir")
        or str(DEFAULT_OUTPUT_ROOT)
    )
    base = Path(raw).expanduser()
    if not base.is_absolute():
        base = ROOT / base
    base = resolve_path(str(base))
    if not base.is_dir():
        return {"output_dir": str(base), "exists": False, "items": []}

    limit = int(args.get("limit", 200))
    items = []
    for path in sorted(base.rglob("*")):
        if path.is_file():
            name = path.name
            items.append(
                {
                    "path": str(path),
                    "name": name,
                    "size": path.stat().st_size,
                    "kind": "manifest"
                    if name.endswith(".manifest.json")
                    else "workflow"
                    if name == "workflow.json"
                    else path.suffix.lstrip("."),
                }
            )
            if len(items) >= limit:
                break
    return {"output_dir": str(base), "exists": True, "count": len(items), "items": items}


TOOLS: dict[str, dict[str, Any]] = {
    "paperworkflow_prompt_builder": {
        "description": (
            "Stage 1a/1c. List PDFs under source_dir (legacy default: INput) as a "
            "pdf_index of selection_id (P001…) + relative_path — show it to the user "
            "and let them choose, never pick for them. With selected_pdf: build the "
            "stage-1 workflow prompt. Standard library only."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "source_dir": {
                    "type": "string",
                    "description": "Any local directory to index recursively; defaults to configured input_dir.",
                },
                "selected_pdf": {
                    "type": "string",
                    "description": "selection_id (P001) or a source_dir-relative path",
                },
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
            "bundle: workflow.json, document.manifest.json, evidence.md, paper.md, "
            "extracted figures and bundle.manifest.json in one directory. Returns "
            "the bundle path and synthesis_readiness hard gate. Slow for PDFs "
            "(OCR); do not re-run unnecessarily."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "source_path": {
                    "type": "string",
                    "description": "Required. Any readable local .pdf or .md path.",
                },
                "queries": {
                    "type": "array",
                    "items": {"type": "string"},
                    "maxItems": 12,
                    "description": "Research questions, each <=2000 chars",
                },
                "include_default_queries": {"type": "boolean", "default": True},
                "top_k": {"type": "integer", "minimum": 1, "maximum": 20, "default": 5},
                "chunk_chars": {
                    "type": "integer",
                    "minimum": 500,
                    "maximum": 20000,
                    "default": 6000,
                },
                "output_dir": {
                    "type": "string",
                    "description": "Optional local bundle directory; may be outside the project.",
                },
                "include_workflow": {
                    "type": "boolean",
                    "default": False,
                    "description": "Embed the full workflow document in the MCP response. Defaults to false; use workflow_path to avoid a very large response.",
                },
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
    sys.stdout.write(json.dumps(message, ensure_ascii=True) + "\n")
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
                    "content": [
                        {"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=2)}
                    ],
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
