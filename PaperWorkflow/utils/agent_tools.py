"""Small JSON-friendly tool wrappers for Agent runtimes.

These wrappers intentionally have no model or network dependency.  They can
be registered as function tools in an Agent SDK, exposed through MCP, or used
from a notebook without changing the ingestion workflow.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .paper_tools import search_markdown, section_index


def retrieve_evidence(markdown_path: str, query: str, top_k: int = 5) -> dict[str, Any]:
    """Return ranked, line-addressable evidence for a user question."""

    path = Path(markdown_path).expanduser().resolve()
    return {
        "source": str(path),
        "query": query,
        "results": search_markdown(path, query, top_k=top_k),
    }


def get_document_outline(markdown_path: str, chunk_chars: int = 6000) -> dict[str, Any]:
    """Return an outline without sending document content to a model."""

    path = Path(markdown_path).expanduser().resolve()
    markdown = path.read_text(encoding="utf-8")
    return {
        "source": str(path),
        "char_count": len(markdown),
        "sections": section_index(markdown, chunk_chars=chunk_chars),
    }

