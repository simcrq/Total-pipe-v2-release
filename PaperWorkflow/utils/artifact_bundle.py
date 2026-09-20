"""Build a self-contained PaperWorkflow hand-off directory.

The Total-pipe boundary is a directory, not a loose collection of cache paths.
This module stages the OCR/source Markdown and its local image assets next to
the v4 workflow artifacts, then writes a checksummed bundle manifest.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urlparse

BUNDLE_VERSION = 1
IMAGE_SUFFIXES = {
    ".avif",
    ".bmp",
    ".emf",
    ".gif",
    ".heic",
    ".jpeg",
    ".jpg",
    ".pdf",
    ".png",
    ".svg",
    ".tif",
    ".tiff",
    ".webp",
    ".wmf",
}
ASSET_DIRECTORY_NAMES = {"assets", "figs", "figures", "images", "imgs", "media"}
MARKDOWN_IMAGE_TARGET_RE = re.compile(
    r"!\[[^\]]*\]\(\s*(?:<(?P<angle>[^>]+)>|(?P<plain>[^\s)]+))",
    re.IGNORECASE,
)
HTML_IMAGE_TARGET_RE = re.compile(
    r"<img\b[^>]*\bsrc\s*=\s*[\"'](?P<src>[^\"']+)[\"']",
    re.IGNORECASE,
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _copy_file(source: Path, target: Path) -> None:
    """Copy one file atomically while preserving metadata when possible."""

    target.parent.mkdir(parents=True, exist_ok=True)
    if source.resolve() == target.resolve():
        return
    fd, temporary_name = tempfile.mkstemp(prefix=target.name + ".", dir=str(target.parent))
    os.close(fd)
    temporary = Path(temporary_name)
    try:
        shutil.copy2(source, temporary)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def _asset_candidates(
    markdown_path: Path, output_dir: Path, markdown: str
) -> tuple[list[tuple[Path, Path]], dict[str, str]]:
    """Return local image assets plus publish-safe Markdown path rewrites."""

    source_root = markdown_path.parent.resolve()
    output_resolved = output_dir.resolve()
    found: dict[str, tuple[Path, Path]] = {}
    replacements: dict[str, str] = {}

    referenced_targets = [
        match.group("angle") or match.group("plain")
        for match in MARKDOWN_IMAGE_TARGET_RE.finditer(markdown)
    ]
    referenced_targets.extend(
        match.group("src") for match in HTML_IMAGE_TARGET_RE.finditer(markdown)
    )
    for raw_target in referenced_targets:
        parsed = urlparse(raw_target)
        if parsed.scheme not in ("", "file") or parsed.netloc or raw_target.startswith(
            ("#", "data:")
        ):
            continue
        raw_path = Path(unquote(parsed.path))
        candidate = (raw_path if raw_path.is_absolute() else source_root / raw_path).resolve()
        if not candidate.is_file() or candidate.suffix.casefold() not in IMAGE_SUFFIXES:
            continue
        try:
            relative = candidate.relative_to(source_root)
        except ValueError:
            path_hash = hashlib.sha256(str(candidate).encode()).hexdigest()[:8]
            relative = Path("assets") / "external" / f"{path_hash}-{candidate.name}"
        found[relative.as_posix()] = (candidate, relative)
        portable_target = quote(relative.as_posix(), safe="/")
        if raw_target != portable_target:
            replacements[raw_target] = portable_target

    for child in sorted(source_root.iterdir(), key=lambda item: item.name.casefold()):
        if not child.is_dir() or child.name.casefold() not in ASSET_DIRECTORY_NAMES:
            continue
        try:
            if child.resolve() == output_resolved or output_resolved.is_relative_to(
                child.resolve()
            ):
                continue
        except OSError:
            continue
        for candidate in sorted(child.rglob("*")):
            if not candidate.is_file() or candidate.suffix.casefold() not in IMAGE_SUFFIXES:
                continue
            relative = candidate.resolve().relative_to(source_root)
            found[relative.as_posix()] = (candidate.resolve(), relative)
    return list(found.values()), replacements


def stage_markdown_bundle(markdown_path: Path, output_dir: Path) -> dict[str, Any]:
    """Stage Markdown and extracted images into ``output_dir``.

    MinerU normally emits ``images/`` next to its Markdown.  Preserving those
    relative paths means the staged ``paper.md`` remains directly renderable.
    """

    markdown_path = markdown_path.expanduser().resolve()
    output_dir = output_dir.expanduser().resolve()
    if not markdown_path.is_file():
        raise FileNotFoundError(markdown_path)
    output_dir.mkdir(parents=True, exist_ok=True)

    markdown = markdown_path.read_text(encoding="utf-8", errors="replace")
    assets, replacements = _asset_candidates(markdown_path, output_dir, markdown)
    for original, relative in replacements.items():
        markdown = markdown.replace(original, relative)

    target_markdown = output_dir / "paper.md"
    fd, temporary_name = tempfile.mkstemp(
        prefix=target_markdown.name + ".", dir=str(target_markdown.parent)
    )
    os.close(fd)
    temporary = Path(temporary_name)
    try:
        temporary.write_text(markdown, encoding="utf-8")
        os.replace(temporary, target_markdown)
    finally:
        temporary.unlink(missing_ok=True)

    copied_assets: list[str] = []
    for source, relative in assets:
        target = output_dir / relative
        _copy_file(source, target)
        copied_assets.append(relative.as_posix())

    image_roots = sorted({item.split("/", 1)[0] for item in copied_assets})
    return {
        "markdown_path": str(target_markdown),
        "original_markdown_path": str(markdown_path),
        "asset_count": len(copied_assets),
        "asset_paths": copied_assets,
        "asset_roots": image_roots,
        "rewritten_reference_count": len(replacements),
    }


def _role(relative_path: str) -> str:
    name = Path(relative_path).name
    if name == "workflow.json":
        return "paperworkflow_v4"
    if name == "document.manifest.json":
        return "line_addressable_manifest"
    if name == "evidence.md":
        return "evidence_report"
    if name == "paper.md":
        return "primary_markdown"
    if Path(relative_path).suffix.casefold() in IMAGE_SUFFIXES:
        return "figure_asset"
    return "supporting_artifact"


def write_bundle_manifest(
    output_dir: Path,
    *,
    workflow_id: str,
    generated_at: str | None = None,
) -> Path:
    """Write a deterministic inventory for the Total-pipe hand-off directory."""

    output_dir = output_dir.expanduser().resolve()
    manifest_path = output_dir / "bundle.manifest.json"
    files: list[dict[str, Any]] = []
    for path in sorted(output_dir.rglob("*")):
        if not path.is_file() or path == manifest_path:
            continue
        relative = path.relative_to(output_dir).as_posix()
        files.append(
            {
                "path": relative,
                "role": _role(relative),
                "size_bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )

    manifest = {
        "bundle_version": BUNDLE_VERSION,
        "contract": "total-pipe.paperworkflow-v4",
        "workflow_id": workflow_id,
        "created_at": generated_at or datetime.now(UTC).isoformat(),
        "bundle_dir": ".",
        "entrypoint": "workflow.json",
        "file_count": len(files),
        "files": files,
    }
    temporary = manifest_path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.replace(temporary, manifest_path)
    return manifest_path
