"""Semantic type scale: the few size steps a page may use to create hierarchy.

A deck whose title, heading, body and caption are all set within 6 px of each other has no
hierarchy: every object reads as the same thing. This module names the steps the compiler is
willing to defend, so a composition can say *what* an object is and get the size that follows
from it instead of a per-page font override.

Only measured, source-bound objects are promoted. A ``metric`` is the number the page is about,
so it is set at display size and the label beside it stays at body size; promotion never invents
text and never drops an evidence ref.
"""

# Display size in px (1 pt = 4/3 px) and the smallest accepted size before the block is reported
# as a capacity failure instead of being silently set as body copy. This is a reading step above
# body copy, not a poster headline: a research deck keeps numbers inside the sentence and lets
# the figure or the table carry the page. 36 px is 27 pt against 21 pt body.
DISPLAY = {'metric': (36, 32)}
DISPLAY_COMPACT = {'metric': (34, 30)}
DISPLAY_MAX_LINES = 2


def body_size(design=None):
    """The one size body copy is measured and set at on a page, in px."""
    if not design:
        return 24
    return 26 if design.get('type_scale') == 'compact' else 28


def constraints(design=None):
    """The type scale and floors a page must respect, in points, for authoring prompts."""
    from .visual_design import type_sizes
    sizes = type_sizes({'type_scale': (design or {}).get('type_scale', 'standard')})
    return {'unit': 'pt', 'page': {role: round(size*.75, 1) for role, size in sizes.items()},
            'floors': {'body': 18.0, 'annotation': 15.0},
            'rule': 'One body size per page. metric is the measured number the page is about and is set '
                    'one reading step above body copy; it is not a headline and never carries prose. '
                    'A page that cannot hold its content at these sizes is split, not shrunk.'}


def display_scale(block, design=None):
    """``(size, floor)`` for a block that owns the page, or ``None`` for body copy."""
    component = (block or {}).get('component')
    table = DISPLAY_COMPACT if (design or {}).get('type_scale') == 'compact' else DISPLAY
    return table.get(component)


def display_size(block, design=None):
    scale = display_scale(block, design)
    return scale[0] if scale else None


def display_floor(block, design=None):
    scale = display_scale(block, design)
    return scale[1] if scale else None


def is_display(block, design=None):
    return display_scale(block, design) is not None
