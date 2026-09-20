"""Regenerate :mod:`pwf2rpa.capacity` from a research-ppt-assistant checkout.

The capacity table is derived data. Rather than reimplement RPA's readability
maths in Python -- which would drift the moment RPA retunes a font floor --
this module asks RPA itself, through a short Node script, and renders the
answer as a Python literal.

Node is required only here. The adapter's runtime has no such dependency.
"""

from __future__ import annotations

import json
import subprocess
import textwrap
from pathlib import Path
from typing import Any

__all__ = ["refresh", "EXTRACTOR_JS"]

#: Executed inside the RPA checkout. Emits one record per layout, with the
#: text slots already sorted into slot-binding order so the Python side only
#: has to render them.
EXTRACTOR_JS = r"""
import { getViewingProfile, enrichLayoutReadability } from "./server/readability.mjs";
import fs from "node:fs/promises";

const TEXT_SLOT_TYPES = new Set([
  "subtitle", "meta", "text", "callout", "caption", "question",
  "reference", "citation", "metadata", "body", "label",
]);
const VISUAL_SLOT_TYPES = new Set(["figure", "image", "visual"]);

const library = JSON.parse(await fs.readFile("assets/layout-library/layouts.json", "utf8"));
const profile = getViewingProfile("projector");
const categories = {};

for (const layout of library.layouts) {
  const enriched = enrichLayoutReadability(layout, profile);
  const slots = enriched.slots ?? layout.slots;
  const readingOrder = new Map((layout.reading_order ?? []).map((id, index) => [id, index]));

  let titleChars = null;
  const textSlots = [];
  const visualSlots = [];

  slots.forEach((slot, index) => {
    const type = String(slot.type ?? "").toLowerCase();
    const maxChars = slot.max_chars_at_min_font;
    if (type === "title") {
      titleChars = Number.isFinite(maxChars) ? maxChars : null;
      return;
    }
    if (VISUAL_SLOT_TYPES.has(type)) {
      visualSlots.push({
        priority: Number(slot.priority) || 0,
        width: slot.box?.w ?? 0,
        required: !slot.optional,
      });
      return;
    }
    if (!TEXT_SLOT_TYPES.has(type)) return;
    textSlots.push({
      id: slot.id,
      type,
      priority: Number(slot.priority) || 0,
      reading: readingOrder.has(slot.id) ? readingOrder.get(slot.id) : index,
      index,
      maxChars: Number.isFinite(maxChars) ? maxChars : null,
    });
  });

  // Mirror slot-binding's ordering: priority desc, then reading order.
  textSlots.sort((a, b) =>
    b.priority - a.priority || a.reading - b.reading || a.index - b.index || a.id.localeCompare(b.id));
  visualSlots.sort((a, b) => b.priority - a.priority || b.width - a.width);

  const contentProfile = layout.content_profile ?? {};
  (categories[layout.category] ??= []).push({
    title_chars: titleChars,
    text_chars: enriched.max_text_chars ?? layout.max_text_chars ?? 0,
    text_slots: textSlots.map((slot) => [slot.type, slot.maxChars]),
    visual_widths: visualSlots.map((slot) => Math.round(slot.width * 1000) / 1000),
    required_visual_slots: visualSlots.filter((slot) => slot.required).length,
    image_capacity: contentProfile.image_capacity ?? 0,
    table_capacity: contentProfile.table_capacity ?? 0,
    chart_capacity: contentProfile.chart_capacity ?? 0,
    process_capacity: slots.filter((slot) => String(slot.type).toLowerCase() === "process").length,
  });
}

const ids = [...new Set(library.layouts.map((layout) => layout.category))];
process.stdout.write(JSON.stringify({
  library_version: library.meta?.version ?? "unknown",
  categories,
  names: Object.fromEntries(ids.map((id) =>
    [id, library.layouts.find((layout) => layout.category === id).category_zh])),
  families: Object.fromEntries(ids.map((id) =>
    [id, library.layouts.find((layout) => layout.category === id).family])),
  roles: Object.fromEntries(ids.map((id) => [id, [...new Set(
    library.layouts.filter((layout) => layout.category === id)
      .flatMap((layout) => layout.content_roles ?? []))].sort()])),
}));
"""

_HEADER = '''"""RPA layout-library capacity table (generated data -- do not hand-edit).

Regenerate against a checkout of research-ppt-assistant with::

    python3 -m pwf2rpa refresh-capacity --rpa-root <path/to/research-ppt-assistant>

Why this table exists
---------------------
RPA gates a page twice, and both gates are pure functions of the slide brief:

1. ``layout-retriever.mjs`` filters candidate layouts by hard capacity
   constraints (title chars, total text chars, image/table/chart counts,
   process steps, and the minimum display width each visual type needs).
2. ``slot-binding.mjs`` then pours the brief's text into concrete slots and
   raises ``SLOT_CAPACITY_EXCEEDED`` when an untrimmable item does not fit.

Reproducing those numbers offline lets the adapter explain a problem in terms
of the offending field and its ceiling, instead of leaving the author to infer
it from a relaxed category hint several commands later.

All {layout_count} layouts are listed rather than one envelope per category,
because the number of layouts that can hold a page matters on its own: RPA
passes already-used layout ids back as ``exclude_ids``, so a deck reusing one
category competes for a shrinking pool of variants.

``Layout.text_slots`` is ordered the way slot-binding fills slots (priority
descending, then reading order), so a left-to-right greedy walk mirrors RPA's
own assignment order. A ``max_chars`` of ``None`` means the slot has no
character ceiling.
"""

from typing import NamedTuple

__all__ = [
    "CATEGORIES",
    "CONTENT_ROLES",
    "Category",
    "LAYOUT_LIBRARY_VERSION",
    "Layout",
    "VIEWING_MODE",
    "VISUAL_TYPE_MIN_WIDTH",
]

LAYOUT_LIBRARY_VERSION = "{library_version}"
VIEWING_MODE = "projector"


class Layout(NamedTuple):
    """The capacity envelope of one concrete layout."""

    title_chars: int | None
    """Title slot ceiling at the minimum readable font; ``None`` if unbounded."""

    text_chars: int
    """Whole-page body-text ceiling enforced by the retriever."""

    text_slots: tuple[tuple[str, int | None], ...]
    """``(slot_type, max_chars)`` in slot-binding order."""

    visual_widths: tuple[float, ...]
    """Figure slot widths as a fraction of slide width, widest first."""

    required_visual_slots: int
    """Figure slots that are not optional."""

    image_capacity: int
    table_capacity: int
    chart_capacity: int
    process_capacity: int


class Category(NamedTuple):
    """One of RPA's {category_count} layout categories."""

    name_zh: str
    family: str
    roles: tuple[str, ...]
    layouts: tuple[Layout, ...]


#: Minimum display width (fraction of slide width) per visual_type, mirroring
#: RPA's VISUAL_TYPE_RULES. A multi-panel figure needs more room than a photo.
VISUAL_TYPE_MIN_WIDTH: dict[str, float] = {{
    "photo": 0.25,
    "schematic": 0.36,
    "simple_plot": 0.36,
    "dense_plot": 0.5,
    "multi_panel_figure": 0.55,
    "composite_figure_region": 0.42,
    "table_screenshot": 0.55,
    "microscopy": 0.36,
    "visual_evidence": 0.34,
}}

#: content_role values RPA's content model recognises.
CONTENT_ROLES: tuple[str, ...] = (
    "primary_claim",
    "primary_evidence",
    "supporting_evidence",
    "caption",
    "context",
    "optional_visual",
)

CATEGORIES: dict[str, Category] = {{
'''


def _render(data: dict[str, Any]) -> str:
    """Render the extractor's JSON as a Python source file."""
    lines: list[str] = []
    layout_count = 0
    for category in sorted(data["categories"]):
        roles = data["roles"][category]
        lines.append(f"    {category!r}: Category(")
        lines.append(f"        name_zh={data['names'][category]!r},")
        lines.append(f"        family={data['families'][category]!r},")
        trailing = "," if len(roles) == 1 else ""
        lines.append(f"        roles=({', '.join(repr(role) for role in roles)}{trailing}),")
        lines.append("        layouts=(")
        for layout in data["categories"][category]:
            layout_count += 1
            slots = layout["text_slots"]
            widths = layout["visual_widths"]
            slot_src = "(" + ", ".join(f"({t!r}, {c})" for t, c in slots) + ("," if len(slots) == 1 else "") + ")"
            width_src = "(" + ", ".join(repr(w) for w in widths) + ("," if len(widths) == 1 else "") + ")"
            lines.append(
                f"            Layout({layout['title_chars']}, {layout['text_chars']}, "
                f"{slot_src}, {width_src}, {layout['required_visual_slots']}, "
                f"{layout['image_capacity']}, {layout['table_capacity']}, "
                f"{layout['chart_capacity']}, {layout['process_capacity']}),"
            )
        lines.append("        ),")
        lines.append("    ),")

    header = _HEADER.format(
        library_version=data["library_version"],
        category_count=len(data["categories"]),
        layout_count=layout_count,
    )
    return header + "\n".join(lines) + "\n}\n"


def refresh(rpa_root: str | Path, destination: str | Path | None = None) -> Path:
    """Rebuild ``capacity.py`` from the layout library in ``rpa_root``.

    Args:
        rpa_root: Path to a research-ppt-assistant checkout.
        destination: Where to write; defaults to this package's capacity.py.

    Returns:
        The path written.

    Raises:
        FileNotFoundError: if the checkout has no layout library.
        RuntimeError: if Node is unavailable or the extractor fails.
    """
    rpa_root = Path(rpa_root)
    library = rpa_root / "assets" / "layout-library" / "layouts.json"
    if not library.exists():
        raise FileNotFoundError(f"no layout library under {rpa_root} (expected {library})")

    script = rpa_root / ".pwf2rpa-extract.mjs"
    script.write_text(textwrap.dedent(EXTRACTOR_JS), encoding="utf-8")
    try:
        result = subprocess.run(
            ["node", script.name],
            cwd=rpa_root, capture_output=True, text=True, check=False,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("node is required to refresh the capacity table") from exc
    finally:
        script.unlink(missing_ok=True)

    if result.returncode != 0:
        raise RuntimeError(f"capacity extraction failed:\n{result.stderr.strip()}")

    destination = Path(destination) if destination else Path(__file__).with_name("capacity.py")
    destination.write_text(_render(json.loads(result.stdout)), encoding="utf-8")
    return destination
