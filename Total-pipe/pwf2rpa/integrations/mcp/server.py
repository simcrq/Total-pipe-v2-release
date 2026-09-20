#!/usr/bin/env python3
"""MCP stdio server that exposes pwf2rpa as tools.

pwf2rpa turns a PaperWorkflow v4 ``workflow.json`` into the content-model input
RPA's ``normalize_content`` and ``create_deck_plan`` consume. This is a protocol
shell around the existing library -- no conversion logic is reimplemented here.

Standard library only, matching the project it wraps. ``stdout`` is reserved for
JSON-RPC; anything the library prints is diverted to stderr.
"""

from __future__ import annotations

import io
import json
import os
import sys
import threading
from pathlib import Path
from typing import Any, Callable, Iterator

PROJECT_ROOT = Path(
    os.environ.get("PWF2RPA_ROOT") or Path(__file__).resolve().parent.parent.parent
).resolve()

sys.path.insert(0, str(PROJECT_ROOT))

from pwf2rpa import (  # noqa: E402
    CATEGORIES,
    LAYOUT_LIBRARY_VERSION,
    Workflow,
    build_story_prompt,
    build_briefs,
    convert,
    fallback_specs,
    load_specs,
    load_story,
    write_output,
)
from pwf2rpa.errors import AdapterError, Problem  # noqa: E402

SERVER_NAME = "pwf2rpa"
SERVER_VERSION = "1.1.0"
PROTOCOL_VERSION = "2025-06-18"
SUPPORTED_PROTOCOLS = {"2025-06-18", "2025-03-26", "2024-11-05"}

DEFAULT_TIMEOUT = float(os.environ.get("PWF2RPA_TOOL_TIMEOUT", "120"))

INSTRUCTIONS = (
    "pwf2rpa converts a PaperWorkflow v4 workflow.json into the input RPA's "
    "normalize_content and create_deck_plan consume. For the full Total-pipe path, "
    "first ask the user to choose a high-capability model, delegate Story Planning "
    "to that model as a subagent, and save its evidence-bound output. Use "
    "pwf2rpa_story_prompt to build the prompt package; it refuses calls that do not "
    "record explicit user selection and high-or-stronger reasoning. Then call pwf2rpa_check: it "
    "validates and replays RPA's layout-capacity gates without writing anything, so "
    "you can fix warnings before committing to a file. Then call pwf2rpa_convert to "
    "write rpa_input.json. Use pwf2rpa_list_categories whenever you need the 40 legal "
    "category_hint ids -- a free-form category label is not an error, RPA silently "
    "relaxes to a whole-library search and picks a mismatched layout. In the full "
    "pipeline this is the middle stage: paperworkflow produces workflow.json, the "
    "user-selected Story subagent produces story_plan.json, pwf2rpa maps it to "
    "slide_briefs, and research_ppt plans and renders the deck."
)


class _Divert:
    """Write-only stream that forwards anything printed to stderr."""

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
        raise TimeoutError(
            "tool timed out after %g s; raise PWF2RPA_TOOL_TIMEOUT if needed" % timeout
        )
    if "error" in box:
        raise box["error"]
    return box["value"]


def _problem_dict(problem: Problem) -> dict[str, Any]:
    record = problem._asdict()
    record["rendered"] = problem.render()
    return record


def _summarise_slides(briefs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "index": index,
            "category_hint": brief.get("category_hint"),
            "title": brief.get("title"),
            "text_chars": brief.get("text_chars", 0),
            "image_count": brief.get("image_count", 0),
            "evidence_ids": list(brief.get("evidence_ids", [])),
        }
        for index, brief in enumerate(briefs, start=1)
    ]


def _resolve_input(workflow: Workflow, briefs_path: str | None, story_path: str | None):
    if briefs_path and story_path:
        raise ValueError("briefs_path and story_path are mutually exclusive")
    if story_path:
        return None, load_story(story_path), "story"
    if briefs_path:
        return load_specs(briefs_path), None, "briefs"
    return fallback_specs(workflow), None, "legacy_fallback"


def _analyse(
    workflow_path: str,
    briefs_path: str | None,
    story_path: str | None,
    strict_fit: bool,
):
    """Shared body: validate, build briefs, return payload plus diagnostics."""
    workflow = Workflow.from_path(workflow_path)
    workflow.validate()
    specs, story, input_mode = _resolve_input(workflow, briefs_path, story_path)
    payload, warnings = convert(workflow, specs, story=story, strict_fit=strict_fit)
    return payload, warnings, input_mode


def _report(
    payload: dict[str, Any],
    warnings: list[Problem],
    output_path: str | None,
    input_mode: str,
) -> dict:
    return {
        "output_path": output_path,
        "input_mode": input_mode,
        "slide_count": len(payload["slide_briefs"]),
        "slides": _summarise_slides(payload["slide_briefs"]),
        "warning_count": len(warnings),
        "warnings": [_problem_dict(problem) for problem in warnings],
        "layout_library_version": LAYOUT_LIBRARY_VERSION,
    }


def _default_out(workflow_path: str) -> Path:
    return Path(workflow_path).parent / "rpa_input.json"


def _tool_check(arguments: dict[str, Any]) -> dict[str, Any]:
    workflow_path = arguments["workflow_path"]
    payload, warnings, input_mode = _analyse(
        workflow_path,
        arguments.get("briefs_path"),
        arguments.get("story_path"),
        strict_fit=not arguments.get("no_strict_fit", False),
    )
    return _report(payload, warnings, None, input_mode)


def _tool_convert(arguments: dict[str, Any]) -> dict[str, Any]:
    workflow_path = arguments["workflow_path"]
    out_path = arguments.get("out_path")
    payload, warnings, input_mode = _analyse(
        workflow_path,
        arguments.get("briefs_path"),
        arguments.get("story_path"),
        strict_fit=not arguments.get("no_strict_fit", False),
    )
    if warnings and arguments.get("strict", False):
        report = _report(payload, warnings, None, input_mode)
        report["written"] = False
        report["reason"] = "strict mode: %d warning(s) treated as failure, nothing written" % len(warnings)
        return report

    destination = Path(out_path) if out_path else _default_out(workflow_path)
    write_output(payload, destination)
    report = _report(payload, warnings, str(destination), input_mode)
    report["written"] = True
    return report


def _tool_story_prompt(arguments: dict[str, Any]) -> dict[str, Any]:
    workflow = Workflow.from_path(arguments["workflow_path"])
    workflow.validate()
    return build_story_prompt(
        workflow,
        model=arguments.get("model", ""),
        reasoning_effort=arguments.get("reasoning_effort", "high"),
        selected_by_user=arguments.get("selected_by_user") is True,
    )


def _tool_list_categories(arguments: dict[str, Any]) -> dict[str, Any]:
    entries = []
    for name in sorted(CATEGORIES):
        category = CATEGORIES[name]
        roomiest = max(category.layouts, key=lambda profile: profile.text_chars)
        entries.append(
            {
                "id": name,
                "name_zh": category.name_zh,
                "max_text_chars": roomiest.text_chars,
                "max_images": max(profile.image_capacity for profile in category.layouts),
                "layout_count": len(category.layouts),
                "roles": sorted(category.roles),
            }
        )
    wanted = arguments.get("category")
    if wanted:
        entries = [entry for entry in entries if entry["id"] == wanted]
        if not entries:
            raise ValueError("unknown category: %r (see pwf2rpa_list_categories)" % wanted)
    return {
        "layout_library_version": LAYOUT_LIBRARY_VERSION,
        "count": len(entries),
        "categories": entries,
    }


def _tool_refresh_capacity(arguments: dict[str, Any]) -> dict[str, Any]:
    from pwf2rpa.refresh import refresh

    written = refresh(arguments["rpa_root"])
    return {
        "written": str(written),
        "rpa_root": arguments["rpa_root"],
        "note": "capacity.py was regenerated; re-run the test suite before trusting it.",
    }


TOOLS: dict[str, dict[str, Any]] = {
    "pwf2rpa_story_prompt": {
        "description": (
            "Build the evidence-bound prompt package for the required Story Planner "
            "subagent. Before calling, ask the user which currently available "
            "high-capability model to use. The tool blocks unless selected_by_user is "
            "true, a model is named, and reasoning_effort is high or stronger. The "
            "returned package must be sent to that subagent; the main agent must not "
            "write the Story output itself."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["workflow_path", "model", "selected_by_user"],
            "properties": {
                "workflow_path": {
                    "type": "string",
                    "description": "Path to a validated PaperWorkflow v4 workflow.json.",
                },
                "model": {
                    "type": "string",
                    "minLength": 1,
                    "description": "Exact high-capability model explicitly chosen by the user.",
                },
                "reasoning_effort": {
                    "type": "string",
                    "enum": ["high", "xhigh", "max", "ultra"],
                    "default": "high",
                },
                "selected_by_user": {
                    "type": "boolean",
                    "const": True,
                    "description": "Must be true only after the user explicitly chose the model.",
                },
            },
        },
        "handler": _tool_story_prompt,
        "timeout": DEFAULT_TIMEOUT,
    },
    "pwf2rpa_check": {
        "description": (
            "Validate a PaperWorkflow v4 workflow.json and replay RPA's layout-capacity "
            "gates without writing any file. Returns the slide plan that would be "
            "produced plus every warning, each naming the field, the character count "
            "and the ceiling. Call this before pwf2rpa_convert so problems are fixed "
            "while nothing is on disk yet."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["workflow_path"],
            "properties": {
                "workflow_path": {
                    "type": "string",
                    "description": "Path to a PaperWorkflow v4 workflow.json (schema_version 4).",
                },
                "briefs_path": {
                    "type": "string",
                    "description": "Optional legacy slide-brief spec JSON. Mutually exclusive with story_path.",
                },
                "story_path": {
                    "type": "string",
                    "description": "Recommended Story Planner JSON from the user-selected high-capability subagent.",
                },
                "no_strict_fit": {
                    "type": "boolean",
                    "description": "Skip the layout-capacity simulation entirely. Defaults to false.",
                },
            },
        },
        "handler": _tool_check,
        "timeout": DEFAULT_TIMEOUT,
    },
    "pwf2rpa_convert": {
        "description": (
            "Convert a PaperWorkflow v4 workflow.json into rpa_input.json, the two-key "
            "content model RPA's normalize_content and create_deck_plan consume. "
            "paperworkflow_v4 is passed through untouched; only slide_briefs is built. "
            "Blocking problems raise an error and write nothing. Warnings still produce "
            "a file because RPA does plan in those cases, just with a degraded layout "
            "-- unless strict is true. Output is byte-stable for identical input."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["workflow_path"],
            "properties": {
                "workflow_path": {
                    "type": "string",
                    "description": "Path to a PaperWorkflow v4 workflow.json (schema_version 4).",
                },
                "briefs_path": {
                    "type": "string",
                    "description": "Optional legacy slide-brief spec JSON. Mutually exclusive with story_path.",
                },
                "story_path": {
                    "type": "string",
                    "description": "Recommended Story Planner JSON from the user-selected high-capability subagent.",
                },
                "out_path": {
                    "type": "string",
                    "description": "Where to write rpa_input.json. Defaults to rpa_input.json next to the workflow.",
                },
                "strict": {
                    "type": "boolean",
                    "description": "Treat warnings as failure and write nothing. Useful in CI. Defaults to false.",
                },
                "no_strict_fit": {
                    "type": "boolean",
                    "description": "Skip the layout-capacity simulation. Defaults to false.",
                },
            },
        },
        "handler": _tool_convert,
        "timeout": DEFAULT_TIMEOUT,
    },
    "pwf2rpa_list_categories": {
        "description": (
            "List the 40 legal category_hint ids, each with its Chinese name, the "
            "text ceiling of its roomiest layout, its image ceiling, layout count and "
            "slot roles. Always consult this before writing a category_hint: an "
            "unrecognised value is not an error, RPA quietly relaxes to a whole-library "
            "search and picks a mismatched layout."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "category": {
                    "type": "string",
                    "description": "Optional single category id to look up instead of listing all 40.",
                }
            },
        },
        "handler": _tool_list_categories,
        "timeout": 30.0,
    },
    "pwf2rpa_refresh_capacity": {
        "description": (
            "Regenerate the bundled layout capacity table (capacity.py) from a Research "
            "PPT Assistant checkout, by asking RPA's own readability module for the "
            "numbers. Only needed when RPA's layout library changes. Requires node on "
            "PATH and overwrites capacity.py, so re-run the test suite afterwards."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["rpa_root"],
            "properties": {
                "rpa_root": {
                    "type": "string",
                    "description": "Path to the research-ppt-assistant checkout.",
                }
            },
        },
        "handler": _tool_refresh_capacity,
        "timeout": float(os.environ.get("PWF2RPA_REFRESH_TIMEOUT", "600")),
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
    return None if message_id is None else {"jsonrpc": "2.0", "id": message_id, "result": result}


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
        try:
            value = run_callable(lambda: spec["handler"](arguments), spec["timeout"])
        except AdapterError as error:
            # Blocking problems: report every one, not just the first.
            return _result(
                message_id,
                {
                    "content": [{"type": "text", "text": json.dumps(error.as_dict(), ensure_ascii=False, indent=2)}],
                    "isError": True,
                },
            )
        except Exception as error:  # noqa: BLE001 - surfaced as a tool error
            return _result(
                message_id,
                {"content": [{"type": "text", "text": "%s: %s" % (type(error).__name__, error)}], "isError": True},
            )
        return _result(
            message_id,
            {"content": [{"type": "text", "text": json.dumps(value, ensure_ascii=False, indent=2)}], "isError": False},
        )
    if method in ("resources/list", "prompts/list"):
        return _result(message_id, {method.split("/")[0]: []})
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
    for raw in iter_messages(sys.stdin.buffer):
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
