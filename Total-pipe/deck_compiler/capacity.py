"""Budgets for content the compiler measures instead of wraps.

A sentence can be re-wrapped, re-set at a smaller size, or split across two slides. A displayed
equation cannot: it is typeset as one object, the compiler refuses to set it below 18 pt, and it
cannot break across lines. That asymmetry is why a page with a formula can lose its body text: the
cheapest way to make room for an equation is to delete the prose beside it.

The budgets below make that trade explicit and bounded. They are checked before anything is written:

* ``FORMULA_MAX_PER_SLIDE``     -- two displayed equations per page; a third is a new page.
* ``FORMULA_MAX_HEIGHT_SHARE``  -- one equation may take at most 32% of the body height.
* ``FORMULA_MAX_TOTAL_SHARE``   -- all equations together at most 50%.
* ``FORMULA_GROUP_SHARE_MAX``   -- an equation anchored under a block may not take more than 45% of
  that block's group; the text it explains keeps the rest.
* ``FORMULA_MIN_TEXT_CHARS``    -- a page with an equation still carries a sentence of
  prose (4 characters -- a sentence, not a page of equations). Crowding is judged by
  measured height below, not by counting characters: a data page legitimately carries little text.

A page that violates one of these gets ``FORMULA_CAPACITY`` with the measured numbers and the
instruction to widen the slot or split the page. It never gets a silently shrunken body.
"""

FORMULA_SIZES = (30, 28, 26, 24)     # px; 24 px is 18 pt, the floor
FORMULA_GAP = 10.0                   # px between an anchor's last line and its equation
FORMULA_LABEL_MAX = 140.0            # an inline formula label never takes more than this
FORMULA_MAX_PER_SLIDE = 2
FORMULA_MAX_HEIGHT_SHARE = 0.32
FORMULA_MAX_TOTAL_SHARE = 0.50
FORMULA_GROUP_SHARE_MAX = 0.45
FORMULA_MIN_TEXT_CHARS = 4
FORMULA_MIN_ANCHOR_CHARS = 4


def budget(body_height):
    """The numbers a report quotes, so a failure can say what the limit actually was."""
    return {
        'per_slide': FORMULA_MAX_PER_SLIDE,
        'max_height_px': round(body_height * FORMULA_MAX_HEIGHT_SHARE, 1),
        'max_total_px': round(body_height * FORMULA_MAX_TOTAL_SHARE, 1),
        'group_share': FORMULA_GROUP_SHARE_MAX,
        'min_text_chars': FORMULA_MIN_TEXT_CHARS,
        'floor_px': FORMULA_SIZES[-1],
    }
