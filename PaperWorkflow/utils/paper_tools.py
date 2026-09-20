"""Deterministic document utilities that can be exposed to an Agent.

The functions in this module deliberately do not call an LLM.  They turn the
Markdown emitted by MinerU into stable, addressable sections and provide a
small lexical evidence retriever.  An Agent can call these functions before
asking a model to synthesize an answer.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from .evidence_graph import build_document_graph, search_spans, split_chunks


def source_fingerprint(pdf_path: str | Path) -> str:
    """Return a stable cache namespace for a file path and its current stat."""

    path = Path(pdf_path).expanduser().resolve()
    stat = path.stat()
    payload = f"{path}\0{stat.st_size}\0{stat.st_mtime_ns}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]


def split_markdown_sections(markdown: str, max_chars: int = 6000) -> list[dict[str, Any]]:
    """Split Markdown into raw chunks enriched with semantic ownership."""
    return split_chunks(markdown, max_chars=max_chars)


def search_markdown(
    markdown_or_path: str | Path,
    query: str,
    top_k: int = 5,
    *,
    intent: str | None = None,
) -> list[dict[str, Any]]:
    """Find exact supporting passages with chunk-compatible metadata."""
    return search_spans(
        markdown_or_path,
        query,
        top_k=top_k,
        intent=intent,
    )


def document_manifest(
    markdown: str,
    *,
    pdf_path: str | Path | None = None,
    markdown_path: str | Path | None = None,
    chunk_chars: int = 6000,
) -> dict[str, Any]:
    """Build a raw-chunk plus atomic-span manifest for an Agent or indexer."""
    manifest = build_document_graph(markdown, max_chars=chunk_chars)
    if pdf_path is not None:
        manifest["pdf_path"] = str(Path(pdf_path).expanduser().resolve())
        try:
            manifest["source_id"] = source_fingerprint(pdf_path)
        except FileNotFoundError:
            manifest["source_id"] = None
    if markdown_path is not None:
        manifest["markdown_path"] = str(Path(markdown_path).expanduser().resolve())
    return manifest


def section_index(markdown: str, chunk_chars: int = 6000) -> list[dict[str, Any]]:
    """Return raw and semantic heading metadata for the document outline."""
    return [
        {
            key: chunk[key]
            for key in (
                "chunk_id", "heading", "raw_heading", "semantic_heading",
                "heading_kind", "empty_node", "level", "part", "line_start",
                "line_end", "modalities", "figure_parents", "semantic_owner_type",
            )
        }
        for chunk in build_document_graph(markdown, max_chars=chunk_chars)["chunks"]
    ]
