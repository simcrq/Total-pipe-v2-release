#!/usr/bin/env python3
"""CLI entry point: PaperWorkflow v4 -> Research PPT Assistant input.

Kept at the repository root so the documented invocation keeps working::

    python3 pwf_to_rpa.py workflow.json --briefs briefs.json --out rpa_input.json

The implementation lives in the ``pwf2rpa`` package next to this file.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pwf2rpa.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
