#!/usr/bin/env python3
"""Compatibility launcher for the canonical PaperWorkflow MCP server.

Historically this integration carried a second copy of the JSON-RPC server and
its path sandbox.  Keeping one implementation prevents tool schemas and output
contracts from drifting: both launch paths now expose ``PaperWorkflow/mcp_server.py``.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(
    os.environ.get("PAPERWORKFLOW_ROOT") or Path(__file__).resolve().parent.parent.parent
).resolve()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from mcp_server import main  # noqa: E402

if __name__ == "__main__":
    main()
