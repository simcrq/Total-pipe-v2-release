"""Deterministic text-flow selection for prose-heavy content blocks."""
import re
from unicodedata import category

from totalpipe_layout.inline_math import has_markup


DISTRIBUTED_ARROW_LIST = "distributed_arrow_list"
NATIVE_BULLET_LIST = "native_bullet_list"
NATIVE_NUMBERED_LIST = "native_numbered_list"
EXPLICIT_LISTS = (DISTRIBUTED_ARROW_LIST, NATIVE_BULLET_LIST, NATIVE_NUMBERED_LIST)
TEXT_FLOWS = ("auto", "plain", *EXPLICIT_LISTS)
ARROW_GLYPH = "➢"
_PREFIX = re.compile(r"^\s*(?:[-*]\s+|[•●▪◦‣⁃➢▶▷►▸→]\s*|\d+[.)](?!\d)\s*|\d+、\s*)")
_EXCLUDED = re.compile(r"(?:^|\n)\s*(?:```|\|.+\||[$].+[$])", re.MULTILINE)


def _display_units(value):
    return sum(2 if "\u3400" <= char <= "\u9fff" else 1 for char in value if not char.isspace())


def split_parallel_items(value, *, strip_prefix=True):
    """Return explicit paragraphs/list rows without inventing semantic splits."""
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return []
    rows = [row.strip() for row in re.split(r"\n+", text) if row.strip()]
    if not strip_prefix:
        return rows
    return [_PREFIX.sub("", row).strip() for row in rows if _PREFIX.sub("", row).strip()]


def list_min_width(block):
    return 240 if block.get('text_flow') in (NATIVE_BULLET_LIST, NATIVE_NUMBERED_LIST) else 520


def valid_bullet_icon(glyph):
    return isinstance(glyph, str) and len(glyph) == 1 and category(glyph)[0] in 'PS'


def fallback_list(block):
    """Deck IR fallback: several paragraphs stacked in one block read as a list.

    Two or more explicit paragraphs are a vertical run of statements; without a marker they read as
    one wall of prose. The block keeps its text, id and evidence refs — only the flow changes.
    A native list carries one run style, so a block whose author wrote emphasis stays plain: the
    emphasised phrase is worth more than the marker, and the list is the compiler's suggestion.
    """
    if not isinstance(block, dict) or block.get('component') in ('formula', 'caption'):
        return block
    if block.get('text_flow') or block.get('inline_math'):
        return block
    text = str(block.get('text') or '')
    if has_markup(text):
        return block
    items = split_parallel_items(text)
    if not 2 <= len(items) <= 6 or _EXCLUDED.search(text):
        return block
    if any(_display_units(item) > 240 for item in items):
        return block
    return {**block, 'text_flow': DISTRIBUTED_ARROW_LIST, '_inferred_list': True}


def select_text_flow(value, requested="auto"):
    """Choose the reusable distributed-list treatment or preserve plain text.

    Auto mode is deliberately conservative: only three to five explicit rows,
    enough total prose to benefit from distribution, and no table/code/formula
    signature.  Long single paragraphs remain plain and can trigger normal
    wrapping/split logic instead of being rewritten.
    """
    mode = requested or "auto"
    if mode not in TEXT_FLOWS:
        raise ValueError(f"Unknown text_flow: {mode}")
    items = split_parallel_items(value, strip_prefix=mode not in (NATIVE_BULLET_LIST, NATIVE_NUMBERED_LIST))
    total = sum(_display_units(item) for item in items)
    # Long rows are allowed: a three-to-five paragraph block whose rows wrap to several lines
    # is exactly the case where a native list reads better than one wall of text.
    safe_items = 3 <= len(items) <= 5 and max((_display_units(item) for item in items), default=0) <= 240
    explicit = mode in EXPLICIT_LISTS
    automatic = mode == "auto" and safe_items and total >= 72 and not _EXCLUDED.search(str(value or ""))
    selected = explicit or automatic
    minimum = 1 if mode in (NATIVE_BULLET_LIST, NATIVE_NUMBERED_LIST) else 2
    if selected and not minimum <= len(items) <= 6:
        return {"mode": "plain", "source": "fallback", "items": []}
    return {
        "mode": DISTRIBUTED_ARROW_LIST if selected else "plain",
        "source": "explicit" if explicit and selected else "auto" if automatic else "default",
        "items": items if selected else [],
        "bullet_glyph": ARROW_GLYPH if selected else "",
        "distribution": "space_between" if selected else "top",
        "container_style": "soft_panel" if selected else "none",
    }
