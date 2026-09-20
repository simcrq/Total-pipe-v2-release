"""Offline reproduction of RPA's two capacity gates.

RPA rejects a page in two different places, for two different reasons:

``layout-retriever.mjs``
    Whole-page hard constraints decide which layouts are even *candidates*
    (title chars, total text chars, image/table/chart counts, process steps,
    minimum display width per visual).

``slot-binding.mjs``
    The surviving layout must actually absorb the text: items are poured into
    slots in a fixed order and an untrimmable item that overflows its slot
    raises ``SLOT_CAPACITY_EXCEEDED``.

Both gates are pure functions of the slide brief, so we can replay them here
against :mod:`pwf2rpa.capacity`.  Doing so turns "RPA quietly picked a weird
layout" into an actionable message naming the field, the character count and
the ceiling -- *before* anything is written to disk.

The simulation is intentionally conservative: it reports a problem only when
*every* Pareto-optimal layout of the category fails, which is exactly when RPA
would relax the category hint and search the whole library.
"""

from __future__ import annotations

import difflib
from typing import Iterable, NamedTuple

from .capacity import CATEGORIES, VISUAL_TYPE_MIN_WIDTH, Category, Layout

__all__ = [
    "LAYOUTS_PER_CATEGORY",
    "TextItem",
    "VisualItem",
    "PageShape",
    "FitReport",
    "category_ids",
    "is_known_category",
    "suggest_categories",
    "evaluate",
    "category_pressure",
    "crowded_pages",
    "fitting_layout_count",
    "overused_categories",
]

#: Slot types that ``slot-binding.mjs`` canonicalises to "text".
_TEXT_SLOT_TYPES = frozenset(
    {
        "title", "subtitle", "meta", "text", "callout", "caption",
        "question", "reference", "citation", "metadata", "body", "label",
    }
)


class TextItem(NamedTuple):
    """One untrimmable string that must land in some slot."""

    field: str
    """Brief field it came from, e.g. ``claims[2]`` -- used in messages."""

    text: str
    preferred: tuple[str, ...]
    """Slot types RPA prefers for this field (affinity 90 when matched)."""

    trimmable: bool = False
    """When true RPA truncates instead of failing, so overflow is not fatal."""

    @property
    def length(self) -> int:
        """Length in code points, matching RPA's ``[...text].length``."""
        return len(self.text)


class VisualItem(NamedTuple):
    """One figure and the slide width fraction it needs to stay readable."""

    visual_type: str
    panel_count: int = 1
    has_embedded_text: bool = False

    @property
    def required_width(self) -> float:
        """Mirror of RPA ``requiredVisualWidth``."""
        base = VISUAL_TYPE_MIN_WIDTH.get(self.visual_type, VISUAL_TYPE_MIN_WIDTH["visual_evidence"])
        if self.visual_type == "multi_panel_figure":
            if self.panel_count >= 6:
                base += 0.07
            elif self.panel_count >= 4:
                base += 0.03
        if self.has_embedded_text and self.visual_type == "visual_evidence":
            base = max(base, 0.44)
        return min(max(base, 0.1), 0.72)


class PageShape(NamedTuple):
    """Everything the two gates look at, extracted from one slide brief."""

    category: str
    title: str
    text_items: tuple[TextItem, ...]
    visuals: tuple[VisualItem, ...]
    table_count: int = 0
    chart_count: int = 0
    process_step_count: int = 0

    @property
    def title_chars(self) -> int:
        return len(self.title)

    @property
    def text_chars(self) -> int:
        """Total body text, the figure the retriever compares to max_text_chars."""
        return sum(item.length for item in self.text_items)

    @property
    def image_count(self) -> int:
        return len(self.visuals)


class FitReport(NamedTuple):
    """Outcome of replaying both gates for one page."""

    fits: bool
    """True when at least one layout in the category accepts the page."""

    category: str
    reasons: tuple[str, ...]
    """Why the roomiest layout still failed; empty when ``fits``."""

    limits: dict[str, int | None]
    """Best ceiling the category offers per axis, for actionable messages."""

    def describe(self) -> str:
        """One-line explanation suitable for a CLI error."""
        if self.fits:
            return f"fits category {self.category!r}"
        return f"no {self.category!r} layout fits: " + "; ".join(self.reasons)


def category_ids() -> tuple[str, ...]:
    """All 40 legal ``category_hint`` values, sorted."""
    return tuple(sorted(CATEGORIES))


def is_known_category(value: str) -> bool:
    """Whether ``value`` is a real RPA layout category id."""
    return value in CATEGORIES


def suggest_categories(value: str, limit: int = 3) -> tuple[str, ...]:
    """Closest legal category ids for a typo or an invented string."""
    return tuple(difflib.get_close_matches(value, CATEGORIES, n=limit, cutoff=0.4))


def _canonical(slot_type: str) -> str:
    return "text" if slot_type in _TEXT_SLOT_TYPES else slot_type


def _affinity(slot_type: str, item: TextItem) -> int:
    """Mirror of ``itemSlotAffinity`` for text items.

    Slot ids and Chinese labels also count as semantic roles inside RPA, but
    they can only *raise* affinity; ignoring them keeps the simulation
    conservative in the direction that matters (never a false "fits").
    """
    if slot_type in item.preferred:
        return 90
    if _canonical(slot_type) == "text":
        return 50
    return 0


def _pour(profile: Layout, items: Iterable[TextItem]) -> tuple[list[str], int]:
    """Greedily assign text items to slots exactly as slot-binding does.

    Returns the overflow reasons and the total character deficit; an empty
    reason list means every item found a slot it fits in.
    """
    free = list(profile.text_slots)
    reasons: list[str] = []
    deficit = 0
    for item in items:
        if not item.text:
            continue
        ranked = sorted(
            (( -_affinity(slot_type, item), position, slot_type, max_chars)
             for position, (slot_type, max_chars) in enumerate(free)),
        )
        if not ranked:
            reasons.append(
                f"{item.field} has no free text slot left "
                f"(category offers {len(profile.text_slots)})"
            )
            deficit += item.length
            continue
        _, position, slot_type, max_chars = ranked[0]
        free.pop(position)
        if max_chars is not None and item.length > max_chars and not item.trimmable:
            reasons.append(
                f"{item.field} is {item.length} chars but the {slot_type} slot holds {max_chars}"
            )
            deficit += item.length - max_chars
    return reasons, deficit


def _check_layout(profile: Layout, shape: PageShape) -> tuple[list[str], int]:
    """Run both gates against a single layout.

    Returns the failure reasons and a deficit score (how many characters or
    slots short the layout was).  The score lets :func:`evaluate` report the
    *closest* layout, which yields the most actionable advice: telling an
    author their claim must shrink to 68 chars is useful, telling them some
    cramped sibling layout only holds 9 is not.
    """
    reasons: list[str] = []
    deficit = 0

    if profile.title_chars is not None and shape.title_chars > profile.title_chars:
        reasons.append(f"title is {shape.title_chars} chars but the title slot holds {profile.title_chars}")
        deficit += shape.title_chars - profile.title_chars
    if shape.text_chars > profile.text_chars:
        reasons.append(f"body text is {shape.text_chars} chars but the layout holds {profile.text_chars}")
        deficit += shape.text_chars - profile.text_chars
    if shape.image_count > profile.image_capacity:
        reasons.append(f"{shape.image_count} visual(s) but only {profile.image_capacity} figure slot(s)")
        deficit += (shape.image_count - profile.image_capacity) * 100
    if shape.table_count > profile.table_capacity:
        reasons.append(f"{shape.table_count} table(s) but only {profile.table_capacity} table slot(s)")
        deficit += (shape.table_count - profile.table_capacity) * 100
    if shape.chart_count > profile.chart_capacity:
        reasons.append(f"{shape.chart_count} chart(s) but only {profile.chart_capacity} chart slot(s)")
        deficit += (shape.chart_count - profile.chart_capacity) * 100
    if shape.process_step_count > profile.process_capacity:
        reasons.append(
            f"{shape.process_step_count} process step(s) but only {profile.process_capacity} process slot(s)"
        )
        deficit += (shape.process_step_count - profile.process_capacity) * 100
    # NOTE: mandatory figure slots are deliberately *not* enforced here.
    # create_deck_plan marks briefs with planning_mode "guidance", and
    # slot-binding then fills any unassigned required slot with a placeholder
    # prompt instead of failing. Verified: a text-only page with category
    # figure_text still binds to RM-FIGURE_TEXT-05 with no warning.

    for index, visual in enumerate(shape.visuals):
        if index >= len(profile.visual_widths):
            break
        width = profile.visual_widths[index]
        required = visual.required_width
        if width < required:
            reasons.append(
                f"visuals[{index}] ({visual.visual_type}) needs {required:.0%} of the slide "
                f"width but the slot is {width:.0%}"
            )
            deficit += int((required - width) * 100)

    overflow_reasons, overflow_deficit = _pour(profile, shape.text_items)
    return reasons + overflow_reasons, deficit + overflow_deficit


def evaluate(shape: PageShape) -> FitReport:
    """Replay RPA's gates for one page against every layout of its category.

    The page "fits" as soon as one layout accepts it, because that is the
    condition under which RPA keeps the requested category instead of
    relaxing to a whole-library search.  When nothing fits, the reasons come
    from the layout that came closest.
    """
    category: Category | None = CATEGORIES.get(shape.category)
    if category is None:
        return FitReport(
            fits=False,
            category=shape.category,
            reasons=(f"{shape.category!r} is not one of RPA's {len(CATEGORIES)} layout categories",),
            limits={},
        )

    best: tuple[int, list[str]] | None = None
    for profile in category.layouts:
        reasons, deficit = _check_layout(profile, shape)
        if not reasons:
            return FitReport(True, shape.category, (), _limits(category))
        if best is None or deficit < best[0]:
            best = (deficit, reasons)
    return FitReport(False, shape.category, tuple(best[1] if best else ()), _limits(category))


def _limits(category: Category) -> dict[str, int | None]:
    """The most permissive ceiling the category offers on each axis."""
    profiles = category.layouts
    titles = [profile.title_chars for profile in profiles if profile.title_chars is not None]
    slot_caps = [
        max_chars
        for profile in profiles
        for _slot_type, max_chars in profile.text_slots
        if max_chars is not None
    ]
    return {
        "title_chars": max(titles) if titles else None,
        "text_chars": max((profile.text_chars for profile in profiles), default=0),
        "text_slot_chars": max(slot_caps) if slot_caps else None,
        "text_slot_count": max((len(profile.text_slots) for profile in profiles), default=0),
        "image_capacity": max((profile.image_capacity for profile in profiles), default=0),
        "table_capacity": max((profile.table_capacity for profile in profiles), default=0),
        "chart_capacity": max((profile.chart_capacity for profile in profiles), default=0),
    }


#: Layouts per category in RPA's bundled library. create_deck_plan passes the
#: already-used layout ids as exclude_ids, so a category cannot be reused more
#: times than it has layouts before the retriever runs out of candidates.
LAYOUTS_PER_CATEGORY = 8


def category_pressure(categories: Iterable[str]) -> dict[str, int]:
    """Count how often each category is requested across a deck.

    RPA never reuses a layout within one deck: ``createDeckPlan`` feeds the
    already-used ids back as ``exclude_ids``. Requesting one category on many
    pages therefore forces later pages onto progressively more cramped
    variants, and eventually off the category altogether -- a failure that is
    invisible when each page is checked on its own.
    """
    counts: dict[str, int] = {}
    for category in categories:
        counts[category] = counts.get(category, 0) + 1
    return counts


def overused_categories(categories: Iterable[str]) -> dict[str, int]:
    """Categories requested more often than the library can serve."""
    return {
        category: count
        for category, count in category_pressure(categories).items()
        if category in CATEGORIES and count > LAYOUTS_PER_CATEGORY
    }


def fitting_layout_count(shape: PageShape) -> int:
    """How many layouts of the category could actually hold this page.

    This is the number that governs deck-level crowding. RPA excludes
    already-used layouts, so a page competing for one of only two suitable
    variants gets relaxed once those are taken -- even though the page fits
    the category perfectly well when checked on its own.
    """
    category = CATEGORIES.get(shape.category)
    if category is None:
        return 0
    return sum(1 for profile in category.layouts if not _check_layout(profile, shape)[0])


def crowded_pages(shapes: Iterable[PageShape]) -> list[tuple[int, str, int]]:
    """Find pages that cannot get a layout of their own within the deck.

    ``createDeckPlan`` feeds already-used layout ids back as ``exclude_ids``,
    so every page in a deck needs a *distinct* layout. Whether that is
    possible is a bipartite matching problem, not a counting one: two pages
    sharing a category are fine as long as two different layouts can hold
    them, even if each page individually only fits a handful.

    A simple augmenting-path search (Hopcroft-Karp would be overkill for 40
    pages) decides it exactly, which avoids the false alarms a naive
    "pages > layouts that fit" rule produces.

    Returns:
        ``(page_index, category, layouts_that_fit)`` for each page left
        unmatched, i.e. the pages RPA will push off their category.
    """
    pages = list(shapes)
    # Candidate layout indices per page, restricted to its own category.
    candidates: list[list[tuple[str, int]]] = []
    for shape in pages:
        category = CATEGORIES.get(shape.category)
        if category is None:
            candidates.append([])
            continue
        candidates.append([
            (shape.category, index)
            for index, layout in enumerate(category.layouts)
            if not _check_layout(layout, shape)[0]
        ])

    owner: dict[tuple[str, int], int] = {}

    def augment(page: int, seen: set[tuple[str, int]]) -> bool:
        for slot in candidates[page]:
            if slot in seen:
                continue
            seen.add(slot)
            if slot not in owner or augment(owner[slot], seen):
                owner[slot] = page
                return True
        return False

    unmatched: list[tuple[int, str, int]] = []
    for index, shape in enumerate(pages):
        if not augment(index, set()):
            unmatched.append((index, shape.category, len(candidates[index])))
    return unmatched


def max_claim_chars(category_id: str) -> int | None:
    """Roomiest slot a claim can land in for this category.

    Used to explain ``SLOT_CAPACITY_EXCEEDED`` before it happens: a claim
    longer than this cannot fit anywhere in the category, no matter the
    layout.
    """
    category = CATEGORIES.get(category_id)
    if category is None:
        return None
    caps = [
        max_chars
        for profile in category.layouts
        for slot_type, max_chars in profile.text_slots
        if max_chars is not None and slot_type in ("callout", "text")
    ]
    return max(caps) if caps else None
