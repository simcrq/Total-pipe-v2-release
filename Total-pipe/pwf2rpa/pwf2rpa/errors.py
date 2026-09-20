"""Exception types and the machine-readable problem record they carry."""

from __future__ import annotations

from typing import Any, Literal, NamedTuple

__all__ = [
    "AdapterError",
    "Problem",
    "Severity",
    "WorkflowError",
    "BriefError",
    "StoryError",
]

Severity = Literal["error", "warning"]


class Problem(NamedTuple):
    """One actionable complaint about the input.

    The shape deliberately echoes RPA's own violation record so problems can be
    logged, diffed and asserted on the same way on both sides of the bridge.

    Severity mirrors how RPA itself reacts:

    ``error``
        RPA would reject the input outright (an unresolvable ``evidence_id``,
        a missing title). Writing the file would only defer the failure.

    ``warning``
        RPA would still produce a deck, but a degraded one -- typically by
        relaxing the category hint to a whole-library search and picking a
        mismatched layout. Worth surfacing loudly, not worth blocking on,
        because the caller may knowingly accept the fallback.
    """

    code: str
    """Stable machine-readable identifier, e.g. ``UNKNOWN_EVIDENCE_ID``."""

    path: str
    """JSON-pointer-ish location in the input, e.g. ``briefs[3].evidence_ids[1]``."""

    message: str
    """One-line human explanation."""

    actual: Any = None
    """What was found."""

    expected: Any = None
    """What would have been accepted."""

    hint: str | None = None
    """Concrete next action for the author of the briefs file."""

    severity: Severity = "error"
    """Whether RPA would reject the input or merely degrade the result."""

    def render(self) -> str:
        """Format as a single diagnostic line."""
        parts = [f"{self.path}: {self.message}"]
        if self.actual is not None:
            parts.append(f"actual={self.actual!r}")
        if self.expected is not None:
            expected = self.expected
            if isinstance(expected, (list, tuple, set)):
                items = sorted(str(item) for item in expected)
                if len(items) > 8:
                    expected = ", ".join(items[:8]) + f", ... (+{len(items) - 8})"
                else:
                    expected = ", ".join(items)
            parts.append(f"expected={expected}")
        if self.hint:
            parts.append(f"hint: {self.hint}")
        return f"[{self.severity.upper()}][{self.code}] " + " | ".join(parts)


class AdapterError(Exception):
    """Base class: carries every problem found, not just the first one.

    Collecting problems matters because a briefs file usually has several
    independent mistakes; failing on the first one turns fixing them into a
    slow guess-and-retry loop.
    """

    def __init__(self, problems: list[Problem], summary: str = "") -> None:
        self.problems = list(problems)
        self.summary = summary or f"{len(self.problems)} problem(s) found"
        detail = "\n".join(f"  {problem.render()}" for problem in self.problems)
        super().__init__(f"{self.summary}\n{detail}" if detail else self.summary)

    @property
    def errors(self) -> list[Problem]:
        """Only the blocking problems."""
        return [problem for problem in self.problems if problem.severity == "error"]

    @property
    def warnings(self) -> list[Problem]:
        """Only the degrade-but-continue problems."""
        return [problem for problem in self.problems if problem.severity == "warning"]

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable form for logs or CI annotations."""
        return {
            "error": type(self).__name__,
            "summary": self.summary,
            "problems": [problem._asdict() for problem in self.problems],
        }


class WorkflowError(AdapterError):
    """The PaperWorkflow document itself is unusable."""


class BriefError(AdapterError):
    """The slide briefs do not satisfy the RPA slide-brief contract."""


class StoryError(AdapterError):
    """The Story Planner output is unusable or lacks required provenance."""
