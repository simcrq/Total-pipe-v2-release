"""Read-only view over a PaperWorkflow v4 document.

The adapter never mutates the workflow: RPA consumes it verbatim under the
``paperworkflow_v4`` key and derives Source/Citation/Evidence itself. This
module only *indexes* the workflow so brief building and validation can ask
cheap questions ("does EV0007 exist?", "which evidence answers `results`?").
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable, Mapping, NamedTuple

from .errors import Problem, WorkflowError

__all__ = ["Evidence", "Workflow", "EVIDENCE_ID_RE"]

EVIDENCE_ID_RE = re.compile(r"^EV\d{4}$")

#: schema_version values RPA's adaptWorkflow accepts verbatim.
_SUPPORTED_SCHEMA_VERSIONS = (4, "4", "4.0", "4.0.0")


class Evidence(NamedTuple):
    """One ``evidence_registry`` entry, normalised for adapter use."""

    evidence_id: str
    text: str
    query_ids: tuple[str, ...]
    modality: str
    support_type: str
    chunk_id: str | None
    span_id: str | None
    line_start: int | None
    line_end: int | None
    index: int
    """Position in the registry; used only to keep ordering deterministic."""

    @property
    def sort_key(self) -> tuple[int, str]:
        """Stable ordering key: registry order, then id as a tiebreaker."""
        return (self.index, self.evidence_id)


def _as_str(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _as_int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _range(value: Any) -> tuple[int | None, int | None]:
    if not isinstance(value, Mapping):
        return (None, None)
    return (_as_int(value.get("start")), _as_int(value.get("end")))


class Workflow:
    """An indexed, validated PaperWorkflow v4 document."""

    def __init__(self, document: Mapping[str, Any], origin: str = "<memory>") -> None:
        self.document = document
        self.origin = origin
        self._evidence = self._index_evidence()

    # -- construction ----------------------------------------------------

    @classmethod
    def from_path(cls, path: str | Path) -> "Workflow":
        """Load and validate a ``workflow.json`` from disk."""
        path = Path(path)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise WorkflowError(
                [Problem("WORKFLOW_NOT_FOUND", str(path), "workflow.json does not exist.")],
                summary=f"Cannot read {path}",
            ) from exc
        except json.JSONDecodeError as exc:
            raise WorkflowError(
                [
                    Problem(
                        "WORKFLOW_NOT_JSON",
                        f"{path}:{exc.lineno}:{exc.colno}",
                        f"workflow.json is not valid JSON: {exc.msg}",
                    )
                ],
                summary=f"Cannot parse {path}",
            ) from exc
        return cls(raw, origin=str(path))

    # -- validation ------------------------------------------------------

    def validate(self) -> None:
        """Raise :class:`WorkflowError` if RPA would reject this workflow.

        Mirrors the checks in ``content-model.mjs`` ``adaptWorkflow`` so a bad
        workflow is reported here, with file context, instead of surfacing as
        an opaque violation three commands later.
        """
        problems: list[Problem] = []
        document = self.document

        if not isinstance(document, Mapping):
            raise WorkflowError(
                [Problem("WORKFLOW_NOT_OBJECT", "$", "workflow must be a JSON object.", actual=type(document).__name__)],
                summary=f"Unusable workflow: {self.origin}",
            )

        version = document.get("schema_version")
        if version not in _SUPPORTED_SCHEMA_VERSIONS:
            problems.append(
                Problem(
                    "WORKFLOW_SCHEMA_UNSUPPORTED",
                    "schema_version",
                    "RPA only adapts PaperWorkflow schema_version 4.",
                    actual=version,
                    expected=list(_SUPPORTED_SCHEMA_VERSIONS),
                    hint="Re-run the PaperWorkflow literature workflow to emit a v4 package.",
                )
            )

        source = document.get("source")
        if not isinstance(source, Mapping):
            problems.append(
                Problem(
                    "WORKFLOW_SOURCE_MISSING",
                    "source",
                    "source must be an object; RPA derives the Source record from it.",
                    actual=type(source).__name__,
                )
            )
        elif not any(_as_str(source.get(key)) for key in ("source_sha256", "markdown_sha256", "source_fingerprint")):
            problems.append(
                Problem(
                    "WORKFLOW_SOURCE_UNIDENTIFIED",
                    "source",
                    "source needs at least one identity field or RPA cannot deduplicate it.",
                    expected=["source_sha256", "markdown_sha256", "source_fingerprint"],
                )
            )

        registry = document.get("evidence_registry")
        if not isinstance(registry, (list, Mapping)):
            problems.append(
                Problem(
                    "WORKFLOW_REGISTRY_MISSING",
                    "evidence_registry",
                    "evidence_registry must be an array or object.",
                    actual=type(registry).__name__,
                )
            )
        elif not self._evidence:
            problems.append(
                Problem(
                    "WORKFLOW_REGISTRY_EMPTY",
                    "evidence_registry",
                    "evidence_registry has no usable EV#### entries; slides would have nothing to cite.",
                )
            )

        for evidence in self._evidence.values():
            if not EVIDENCE_ID_RE.match(evidence.evidence_id):
                problems.append(
                    Problem(
                        "WORKFLOW_EVIDENCE_ID_MALFORMED",
                        f"evidence_registry[{evidence.index}].evidence_id",
                        "evidence_id must match EV#### or RPA will reassign it.",
                        actual=evidence.evidence_id,
                        expected="EV0001",
                    )
                )

        if problems:
            raise WorkflowError(problems, summary=f"Unusable workflow: {self.origin}")

    # -- indexing --------------------------------------------------------

    def _index_evidence(self) -> dict[str, Evidence]:
        registry = self.document.get("evidence_registry") if isinstance(self.document, Mapping) else None
        if isinstance(registry, Mapping):
            entries: Iterable[Any] = list(registry.values())
        elif isinstance(registry, list):
            entries = registry
        else:
            entries = []

        indexed: dict[str, Evidence] = {}
        for index, entry in enumerate(entries):
            if not isinstance(entry, Mapping):
                continue
            evidence_id = _as_str(entry.get("evidence_id"))
            if not evidence_id or evidence_id in indexed:
                continue
            line_start, line_end = _range(entry.get("source_lines"))
            query_ids = tuple(
                _as_str(value) for value in entry.get("query_ids", []) if _as_str(value)
            ) if isinstance(entry.get("query_ids"), list) else ()
            indexed[evidence_id] = Evidence(
                evidence_id=evidence_id,
                text=_as_str(entry.get("text")),
                query_ids=query_ids,
                modality=_as_str(entry.get("modality")),
                support_type=_as_str(entry.get("support_type")),
                chunk_id=_as_str(entry.get("chunk_id")) or None,
                span_id=_as_str(entry.get("span_id")) or None,
                line_start=line_start,
                line_end=line_end,
                index=index,
            )
        return indexed

    # -- queries ---------------------------------------------------------

    @property
    def evidence(self) -> dict[str, Evidence]:
        """All evidence, keyed by ``EV####``, in registry order."""
        return dict(self._evidence)

    @property
    def evidence_ids(self) -> tuple[str, ...]:
        """Every known ``EV####``, in registry order."""
        return tuple(self._evidence)

    def has_evidence(self, evidence_id: str) -> bool:
        """Whether ``evidence_id`` resolves; the single hard rule for briefs."""
        return evidence_id in self._evidence

    def get(self, evidence_id: str) -> Evidence | None:
        """Look up one evidence entry."""
        return self._evidence.get(evidence_id)

    def by_query_id(self) -> dict[str, tuple[Evidence, ...]]:
        """Group evidence by ``query_ids``, preserving registry order.

        Entries with no query id land under ``"unassigned"`` so nothing is
        silently dropped by the fallback brief generator.
        """
        grouped: dict[str, list[Evidence]] = {}
        for evidence in self._evidence.values():
            for query_id in evidence.query_ids or ("unassigned",):
                grouped.setdefault(query_id, []).append(evidence)
        return {key: tuple(value) for key, value in grouped.items()}

    @property
    def title(self) -> str:
        """Best-effort paper title from workflow metadata."""
        metadata = self.document.get("metadata")
        if isinstance(metadata, Mapping):
            for key in ("title", "title_guess"):
                title = _as_str(metadata.get(key))
                if title:
                    return title
        outline = self.document.get("outline")
        if isinstance(outline, Mapping):
            sections = outline.get("sections")
            if isinstance(sections, list) and sections and isinstance(sections[0], Mapping):
                heading = _as_str(sections[0].get("semantic_heading")) or _as_str(sections[0].get("heading"))
                if heading:
                    return heading
        return "Untitled paper"

    @property
    def fingerprint(self) -> str:
        """Source fingerprint, used to make outputs traceable."""
        source = self.document.get("source")
        if isinstance(source, Mapping):
            for key in ("source_fingerprint", "source_sha256", "markdown_sha256"):
                value = _as_str(source.get(key))
                if value:
                    return value
        return ""
