"""Measured formula capacity, in CSS pixels.

Equation count and the sum of heights across independent columns are not page capacity.
Every equation must fit its actual region above the font floor; formula_layout packs complete
text/equation groups into the available width and height without stretching prose or dropping math.
"""

FORMULA_SIZES = (30, 28, 26, 24)     # 24 CSS px = 18 pt, the floor
# A page whose subject is one equation may set it as the anchor: 44 CSS px = 33 pt, below the
# 33 pt title and well above 21 pt body copy. Only used when the page has no other object.
DISPLAY_FORMULA_SIZES = (44, 40, 36, 32)
FORMULA_GAP = 10.0                  # explanation to its first equation
FORMULA_LABEL_MAX = 140.0
FORMULA_MIN_TEXT_CHARS = 4
FORMULA_MIN_ANCHOR_CHARS = 4
