"""Deterministic text-flow selection for prose-heavy content blocks."""
import re


DISTRIBUTED_ARROW_LIST = "distributed_arrow_list"
ARROW_GLYPH = "➢"
_PREFIX = re.compile(r"^\s*(?:[-*•●▪◦‣⁃➢▶▷►▸→]|\d+[.)、])\s*")
_EXCLUDED = re.compile(r"(?:^|\n)\s*(?:```|\|.+\||[$].+[$])", re.MULTILINE)


def _display_units(value):
    return sum(2 if "\u3400" <= char <= "\u9fff" else 1 for char in value if not char.isspace())


def split_parallel_items(value):
    """Return explicit paragraphs/list rows without inventing semantic splits."""
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return []
    rows = [row.strip() for row in re.split(r"\n+", text) if row.strip()]
    return [_PREFIX.sub("", row).strip() for row in rows if _PREFIX.sub("", row).strip()]


def select_text_flow(value, requested="auto"):
    """Choose the reusable distributed-list treatment or preserve plain text.

    Auto mode is deliberately conservative: only three to five explicit rows,
    enough total prose to benefit from distribution, and no table/code/formula
    signature.  Long single paragraphs remain plain and can trigger normal
    wrapping/split logic instead of being rewritten.
    """
    mode = requested or "auto"
    if mode not in ("auto", "plain", DISTRIBUTED_ARROW_LIST):
        raise ValueError(f"Unknown text_flow: {mode}")
    items = split_parallel_items(value)
    total = sum(_display_units(item) for item in items)
    safe_items = 3 <= len(items) <= 5 and max((_display_units(item) for item in items), default=0) <= 120
    explicit = mode == DISTRIBUTED_ARROW_LIST
    automatic = mode == "auto" and safe_items and total >= 72 and not _EXCLUDED.search(str(value or ""))
    selected = explicit or automatic
    if selected and not 2 <= len(items) <= 6:
        return {"mode": "plain", "source": "fallback", "items": []}
    return {
        "mode": DISTRIBUTED_ARROW_LIST if selected else "plain",
        "source": "explicit" if explicit and selected else "auto" if automatic else "default",
        "items": items if selected else [],
        "bullet_glyph": ARROW_GLYPH if selected else "",
        "distribution": "space_between" if selected else "top",
        "container_style": "soft_panel" if selected else "none",
    }
