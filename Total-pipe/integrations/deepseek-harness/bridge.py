"""JSON bridge for the Total-pipe DeepSeek Harness plugin."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(
    os.environ.get("TOTALPIPE_ROOT") or Path(__file__).resolve().parent.parent.parent
).resolve()
REPO_ROOT = PROJECT_ROOT.parent
for path in (PROJECT_ROOT, PROJECT_ROOT / "pwf2rpa", PROJECT_ROOT / "tests", REPO_ROOT / ".pydeps"):
    if path.is_dir():
        sys.path.insert(0, str(path))

from agent import mcp_server  # noqa: E402

TOOLS = mcp_server.transport.TOOLS


def run(payload: dict) -> dict:
    operation = payload.get("operation")
    tool_name = operation if operation in TOOLS else "totalpipe_" + str(operation)
    if tool_name not in TOOLS:
        raise ValueError("unsupported operation: " + repr(operation))
    arguments = payload.get("arguments") or {}
    if not isinstance(arguments, dict):
        raise ValueError("arguments must be an object")
    return TOOLS[tool_name]["handler"](arguments)


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            raise ValueError("request must be a JSON object")
        result = run(payload)
        json.dump(result, sys.stdout, ensure_ascii=False, default=str)
        sys.stdout.write("\n")
        return 0
    except Exception as error:
        print("Total-pipe bridge error: " + str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
