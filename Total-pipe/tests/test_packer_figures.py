"""Figure boxes follow the contain-fitted picture, not a column-width assumption.

The packer used to require a box tall enough for the picture at the full column width
(``max(width/aspect, panel floor)``). A 1.31-aspect panel with a wrapping caption could therefore
never be proposed on a 352 px body at any grid width, and seven of ten pages silently fell back to
the templates. These tests pin the model that replaced it: the picture is contain-fitted, the
caption strip is measured from the caption, and the gate is the panel extent.
"""
import unittest
from pathlib import Path

from deck_compiler.layout import caption_height
from deck_compiler.fonts import resolve_theme_fonts
from totalpipe_layout.contracts import (check, figure_box_height, figure_caption_height,
                                        figure_picture_size, required_height)

from test_deck_compiler import ROOT, fixture

REGION = [56, 236, 1168, 352]


def request(units):
    theme = fixture()['theme']
    regular, bold, _ = resolve_theme_fonts(theme, ROOT/'examples')
    return {'archetype': 'figure-left', 'region': REGION, 'units': units,
            'font': regular, 'bold_font': bold,
            'font_family': theme['font_family'], 'frame': [], 'slide_id': 'fixture',
            'sequence_flow': False, 'ir_sha256': 'x'}


def panel(caption='Fig. 2a. A one-line caption.', aspect=1.31):
    return {'id': 'figure-1', 'role': 'figure', 'aspect': aspect, 'caption': caption,
            'panel_count': 1, 'min_panel_extent': 220, 'source_figure': '2a'}


class FigureModelTests(unittest.TestCase):
    def test_a_tall_panel_fits_a_wide_column_by_giving_up_width(self):
        unit = panel()
        box_height = figure_box_height(unit, 692, request([unit]), 352)
        self.assertIsNotNone(box_height, 'a height-limited picture is a legitimate box')
        picture_w, picture_h, extent = figure_picture_size(unit, [0, 0, 692, box_height], request([unit]))
        self.assertLess(picture_w, 692, 'the picture is narrower than its column')
        self.assertAlmostEqual(picture_h, 352 - figure_caption_height(unit, 692, request([unit])) - 12, 1)
        self.assertGreaterEqual(extent, 220)

    def test_the_caption_strip_is_measured_not_reserved(self):
        short = panel('Fig. 2a. Short.')
        long = panel('Fig. 2a. ' + 'A caption that has to wrap onto a second line. ' * 2)
        one = figure_caption_height(short, 692, request([short]))
        two = figure_caption_height(long, 692, request([long]))
        self.assertLess(one, 62, 'a one-line caption does not reserve the old two-line strip')
        self.assertGreaterEqual(one, 34)
        self.assertGreater(two, one)
        self.assertAlmostEqual(
            one, caption_height(short['caption'], 692,
                                request([short])['font']), places=4)

    def test_the_extent_gate_replaces_the_empty_band_gate(self):
        unit = panel()
        req = request([unit])
        height = figure_box_height(unit, 692, req, 352)
        boxes = [[56, 236, 692, height]]
        self.assertEqual(check(req, boxes), [],
                         'a height-limited box in a full column must pass the gates')
        # A box only 120 px tall cannot reach the 220 px panel floor.
        self.assertIsNone(figure_box_height(unit, 692, req, 120))
        # A column too narrow to carry the panel at 220 px either.
        self.assertIsNone(figure_box_height(unit, 200, req, 352))

    def test_required_height_is_the_panel_floor_plus_measured_caption(self):
        unit = panel()
        req = request([unit])
        self.assertAlmostEqual(required_height(unit, 692, req),
                               220 + figure_caption_height(unit, 692, req) + 12, 1)


if __name__ == '__main__':
    unittest.main()
