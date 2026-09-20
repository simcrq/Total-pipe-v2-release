#!/usr/bin/env python3
"""MCP stdio server that exposes PaperWorkflow as tools.

This is a thin protocol shell around ``integrations/deepseek-harness/bridge.py``
-- the same JSON bridge the DeepSeek Harness plugin drives -- so the identical
operations are reachable over the Model Context Protocol without depending on
dsh. Standard library only; every heavy import happens lazily inside the bridge.

``stdout`` is reserved for JSON-RPC. Anything the bridge or its libraries print
is diverted to stderr so progress bars and logs can never corrupt a response.
"""

from __future__ import annotations

import importlib.util
import io
import json
import os
import sys
import threading
from pathlib import Path
from typing import Any, Iterator

PROJECT_ROOT = Path(
    os.environ.get("PAPERWORKFLOW_ROOT") or Path(__file__).resolve().parent.parent.parent
).resolve()
BRIDGE_PATH = PROJECT_ROOT / "integrations" / "deepseek-harness" / "bridge.py"

SERVER_NAME = "paperworkflow"
SERVER_VERSION = "0.1.0"
PROTOCOL_VERSION = "2025-06-18"
SUPPORTED_PROTOCOLS = {"2025-06-18", "2025-03-26", "2024-11-05"}

#: Seconds a single tool call may run. ``literature_workflow`` OCRs a paper and
#: audits it, so it legitimately needs minutes; override with
#: PAPERWORKFLOW_TOOL_TIMEOUT for a shorter leash.
DEFAULT_TIMEOUT = float(os.environ.get("PAPERWORKFLOW_TOOL_TIMEOUT", "1800"))

INSTRUCTIONS = (
    "Call paperworkflow_prompt_builder with no arguments first to list the PDFs "
    "under INput; present the returned index and wait for the user to choose. "
    "Then call paperworkflow_literature_workflow with the chosen path to produce "
    "workflow.json, document.manifest.json and evidence.md. Use "
    "synthesis_readiness (not quality_audit) to decide whether the paper is ready "
    "for scientific hand-off. Cite EV#### together with S####/E###, exact lines and "
    "character offsets for every major claim. For an already-converted Markdown "
    "file, paperworkflow_outline and paperworkflow_search_evidence are cheap and "
    "need no network."
)


def _load_bridge():
    """Import bridge.py by path so the server needs no package install."""
    sys.path.insert(0, str(PROJECT_ROOT))
    spec = importlib.util.spec_from_file_location("paperworkflow_bridge", BRIDGE_PATH)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise RuntimeError("cannot load bridge at " + str(BRIDGE_PATH))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_bridge = _load_bridge()


class _Divert:
    """Minimal write-only stream that forwards anything printed to stderr."""

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


def run_operation(payload: dict[str, Any], timeout: float = DEFAULT_TIMEOUT) -> dict[str, Any]:
    """Run one bridge operation off the protocol thread with a wall-clock cap."""
    box: dict[str, Any] = {}

    def target() -> None:
        saved = sys.stdout
        sys.stdout = _Divert(sys.stderr)
        try:
            box["value"] = _bridge.run(payload)
        except BaseException as error:  # noqa: BLE001 - reported to the caller
            box["error"] = error
        finally:
            sys.stdout = saved

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    thread.join(timeout)
    if thread.is_alive():
        raise TimeoutError(
            "operation timed out after %g s; raise PAPERWORKFLOW_TOOL_TIMEOUT if the "
            "paper is legitimately slower" % timeout
        )
    if "error" in box:
        raise box["error"]
    return box["value"]


TOOLS: dict[str, dict[str, Any]] = {
    "paperworkflow_literature_workflow": {
        "operation": "literature_workflow",
        "description": (
            "Run the complete PaperWorkflow literature-ingestion workflow for one "
            "project-local PDF or Markdown file. PDF input is converted with the "
            "configured MinerU OCR pipeline; Markdown input skips OCR. The tool "
            "builds raw E### chunks plus atomic S#### spans, localizes exact "
            "supporting passages, deduplicates them in an EV#### Evidence Registry, "
            "measures retrieval precision and workflow-facet coverage separately, and "
            "audits text capture, reading order, semantic headings, chunk coherence, "
            "supplementary dependencies, linked quantities and symbol definitions. It "
            "writes workflow.json, document.manifest.json and evidence.md. "
            "quality_audit means OCR/Markdown usability only; synthesis_readiness is "
            "hard-gated and must be used for scientific hand-off. Cite EV#### plus "
            "S####/E###, exact lines and character offsets for every major claim and "
            "number. Treat unavailable supplementary-dependent mechanisms as partial, "
            "separate laboratory and roll-to-roll conditions, and never merge "
            "differing values silently. The tool itself does not invent an LLM summary."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["source_path"],
            "properties": {
                "source_path": {
                    "type": "string",
                    "description": "Project-local .pdf or .md path, absolute or relative to the PaperWorkflow project root.",
                },
                "queries": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional research questions in Chinese or English. Recognized scientific intents are expanded bilingually and reranked by relevant paper sections.",
                },
                "include_default_queries": {
                    "type": "boolean",
                    "description": "Include built-in bilingual evidence queries. Defaults to true.",
                },
                "top_k": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 20,
                    "description": "Base number of ranked evidence passages per query. Coverage-sensitive intents may add passages needed to audit workflow facets. Defaults to 5.",
                },
                "chunk_chars": {
                    "type": "integer",
                    "minimum": 500,
                    "maximum": 20000,
                    "description": "Maximum characters per addressable evidence chunk. Defaults to 6000.",
                },
                "output_dir": {
                    "type": "string",
                    "description": "Optional project-local artifact directory. Defaults to output/workflows/<source fingerprint>.",
                },
            },
        },
    },
    "paperworkflow_prompt_builder": {
        "operation": "prompt_builder",
        "description": (
            "Index every PDF under PaperWorkflow/INput and generate a ready-to-use "
            "literature-workflow prompt from the user information. Call without "
            "selected_pdf first when the user has not chosen a paper: the result "
            "contains a deterministic numbered PDF index whose paths are all relative "
            "to INput. Present those choices and wait for the user selection. Call "
            "again with a selection_id such as P001 or an INput-relative path such as "
            "4668/paper.pdf, plus any research goal, focus questions, and context. "
            "Never invent or expose an absolute path in the selection index."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "selected_pdf": {
                    "type": "string",
                    "description": "Optional selection_id from the returned index, or PDF path relative to INput. Omit to list all selectable PDFs.",
                },
                "research_goal": {
                    "type": "string",
                    "description": "Optional research objective. A literature-analysis default is used when omitted.",
                },
                "focus_questions": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional questions the generated prompt must answer. Defaults cover preparation, measurement, physical picture, results, and limitations.",
                },
                "additional_context": {
                    "type": "string",
                    "description": "Optional background, domain, audience, comparison target, or special constraint to include in the prompt.",
                },
            },
        },
    },
    "paperworkflow_outline": {
        "operation": "outline",
        "description": (
            "Return a section outline and character count for an already-converted "
            "Markdown file without sending document content to a model. Cheap, local, "
            "and useful before deciding which passages to retrieve."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["markdown_path"],
            "properties": {
                "markdown_path": {
                    "type": "string",
                    "description": "Project-local .md path, absolute or relative to the PaperWorkflow project root.",
                },
                "chunk_chars": {
                    "type": "integer",
                    "description": "Maximum characters per addressable section. Defaults to 6000.",
                },
            },
        },
    },
    "paperworkflow_search_evidence": {
        "operation": "search_evidence",
        "description": (
            "Return ranked, line-addressable evidence passages from an "
            "already-converted Markdown file for a user question. Local retrieval, no "
            "model call."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["markdown_path", "query"],
            "properties": {
                "markdown_path": {
                    "type": "string",
                    "description": "Project-local .md path, absolute or relative to the PaperWorkflow project root.",
                },
                "query": {"type": "string", "description": "Question to retrieve evidence for, Chinese or English."},
                "top_k": {"type": "integer", "description": "Number of passages to return. Defaults to 5."},
            },
        },
    },
    "paperworkflow_process_pdf": {
        "operation": "process_pdf",
        "description": (
            "Convert one project-local PDF to Markdown with the configured MinerU "
            "pipeline and stop there. Reports the cache directory, whether the "
            "conversion was a cache hit, and the resulting character count. No LLM "
            "summary is produced. Prefer paperworkflow_literature_workflow when you "
            "also want the evidence registry and audits."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["pdf_path"],
            "properties": {
                "pdf_path": {
                    "type": "string",
                    "description": "Project-local .pdf path, absolute or relative to the PaperWorkflow project root.",
                }
            },
        },
    },
}


def _tool_descriptors() -> list[dict[str, Any]]:
    return [
        {"name": name, "description": spec["description"], "inputSchema": spec["inputSchema"]}
        for name, spec in TOOLS.items()
    ]


def _write(message: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(message, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _result(message_id: Any, result: Any) -> dict[str, Any] | None:
    if message_id is None:
        return None
    return {"jsonrpc": "2.0", "id": message_id, "result": result}


def _failure(message_id: Any, code: int, text: str) -> dict[str, Any] | None:
    if message_id is None:
        return None
    return {"jsonrpc": "2.0", "id": message_id, "error": {"code": code, "message": text}}


def handle(message: dict[str, Any]) -> dict[str, Any] | None:
    """Dispatch one JSON-RPC request. Returns None for notifications."""
    if not isinstance(message, dict):
        return _failure(None, -32600, "request must be a JSON object")

    message_id = message.get("id")
    method = message.get("method")
    params = message.get("params") or {}

    if method == "initialize":
        requested = params.get("protocolVersion")
        protocol = requested if requested in SUPPORTED_PROTOCOLS else PROTOCOL_VERSION
        return _result(
            message_id,
            {
                "protocolVersion": protocol,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                "instructions": INSTRUCTIONS,
            },
        )
    if method in ("notifications/initialized", "initialized"):
        return None
    if method == "ping":
        return _result(message_id, {})
    if method == "tools/list":
        return _result(message_id, {"tools": _tool_descriptors()})
    if method == "tools/call":
        name = params.get("name")
        spec = TOOLS.get(name) if isinstance(name, str) else None
        if spec is None:
            return _failure(message_id, -32602, "unknown tool: " + repr(name))
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            return _failure(message_id, -32602, "arguments must be an object")
        payload = {"operation": spec["operation"]}
        payload.update(arguments)
        try:
            value = run_operation(payload)
        except Exception as error:  # noqa: BLE001 - surfaced as a tool error
            text = "%s: %s" % (type(error).__name__, error)
            return _result(
                message_id,
                {"content": [{"type": "text", "text": text}], "isError": True},
            )
        return _result(
            message_id,
            {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(value, ensure_ascii=False, indent=2),
                    }
                ],
                "isError": False,
            },
        )
    if method in ("resources/list", "prompts/list"):
        return _result(message_id, {method.split("/")[0]: []})
    if method in ("resources/templates/list",):
        return _result(message_id, {"resourceTemplates": []})
    if method == "shutdown":
        return _result(message_id, {})
    return _failure(message_id, -32601, "method not found: " + repr(method))


def _read_framed(stream: Any, first_line: bytes) -> bytes:
    headers: dict[str, str] = {}
    line = first_line
    while line and line not in (b"\r\n", b"\n"):
        if b":" in line:
            key, _, value = line.decode("utf-8", "replace").partition(":")
            headers[key.strip().lower()] = value.strip()
        line = stream.readline()
    length = int(headers.get("content-length", "0") or 0)
    return stream.read(length) if length > 0 else b""


def iter_messages(stream: Any) -> Iterator[bytes]:
    """Yield raw message bodies, accepting both newline-delimited and LSP framing."""
    while True:
        line = stream.readline()
        if not line:
            return
        if not line.strip():
            continue
        raw = _read_framed(stream, line) if line.lower().startswith(b"content-length") else line
        if raw.strip():
            yield raw


def main() -> int:
    stream = sys.stdin.buffer
    for raw in iter_messages(stream):
        try:
            message = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            _write({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": str(error)}})
            continue
        response = handle(message)
        if response is not None:
            _write(response)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
