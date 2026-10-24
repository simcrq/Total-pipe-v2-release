"""List spacing and the centred schematic band.

Two layout rules that came out of looking at the rendered pages rather than the numbers:

* list items were spread by "fill the remaining panel height", so three short rows drifted a
  hundred pixels apart. Spacing is now a fraction of the line height (deck-overridable), the card
  hugs its list, and extra room stays outside the card;
* a drawn schematic is not placed beside its text. It gets its own band: context lines above, the
  diagram centred across the page, caption underneath.
"""
import unittest

from deck_compiler.layout import DEFAULT_LIST_GAP, compile_deck
from deck_compiler.ir import validate
from totalpipe_layout.contracts import check, read_requests

from test_deck_compiler import ROOT, fixture
from test_schematic import schematic_deck
from test_native_list import BODY, block, list_deck


class ListSpacingTests(unittest.TestCase):
    def lists(self, ir):
        layout, issues = compile_deck(ir, ROOT)
        self.assertFalse([i for i in issues if i['severity'] == 'FAIL'], issues)
        return layout['slides'][0], [e for e in layout['slides'][0]['elements']
                                     if e['kind'] == 'list']

    def test_spacing_follows_the_line_height_not_the_panel(self):
        page, lists = self.lists(list_deck([block('a', 'body', BODY)]))
        element = lists[0]
        expected = round(element['contract']['font_size'] * element['contract']['line_height']
                         * DEFAULT_LIST_GAP, 2)
        self.assertEqual(element['bullet']['space_after'], expected)
        self.assertLess(expected, element['contract']['font_size'], 'one gap is smaller than a line')

    def test_the_card_hugs_its_list(self):
        page, lists = self.lists(list_deck([block('a', 'body', BODY)]))
        panel = [e for e in page['elements'] if e['id'] == 'a:panel'][0]
        element = lists[0]
        self.assertLess(panel['bbox'][3], 380, 'the card must not stretch to the whole body area')
        self.assertLessEqual(panel['bbox'][3],
                             2 * 18 + 44 + element['bbox'][3] + .1, 'card = padding + label + list')

    def test_a_deck_can_choose_the_spacing(self):
        page, lists = self.lists(list_deck([block('a', 'body', BODY)], {'list_gap': 0.8}))
        element = lists[0]
        self.assertEqual(element['bullet']['space_after'],
                         round(element['contract']['font_size'] * 1.25 * .8, 2))

    def test_spacing_outside_the_range_is_rejected(self):
        rules = [issue['rule'] for issue in validate(
            list_deck([block('a', 'body', BODY)], {'list_gap': 2.5}))]
        self.assertIn('LIST_GAP_INVALID', rules)

    def test_long_multi_line_rows_also_become_a_native_list(self):
        long_rows = "\n".join([
            '第一段说明这个体系在不同温度与功率组合下的响应边界，以及为什么必须把测量窗口限制在稳态区间内，否则拟合出的斜率没有物理意义。',
            '第二段把观测到的台阶高度与激光功率对应起来，并给出剂量阈值之外的近似线性区间，同时说明该区间上界由热扩散长度决定。',
            '第三段列出仍然不确定的因素：样品之间的批次漂移、标定误差，以及需要下一步实验确认的机制假设，这三项都会影响结论的适用范围。'])
        page, lists = self.lists(list_deck([block('a', 'body', long_rows)]))
        self.assertEqual(len(lists), 1)
        self.assertEqual(lists[0]['bullet']['style'], 'large_square')
        self.assertGreater(max(len(item) for item in lists[0]['items']), 1,
                           'at least one row wraps to several lines')


class CentredSchematicTests(unittest.TestCase):
    def compile_band(self):
        import tempfile
        from pathlib import Path
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        base = Path(folder.name)
        layout, issues = compile_deck(schematic_deck(base), base)
        self.assertFalse([i for i in issues if i['severity'] == 'FAIL'], issues)
        return layout['slides'][0]

    def test_schematic_is_centred_below_the_context(self):
        page = self.compile_band()
        figure = [e for e in page['elements'] if e['kind'] == 'image'][0]
        texts = [e for e in page['elements'] if e['kind'] == 'text' and e['id'] in ('c1', 'c2')]
        self.assertTrue(texts)
        self.assertTrue(all(t['bbox'][1] < figure['bbox'][1] for t in texts),
                        'context lines sit above the diagram')
        centre = figure['bbox'][0] + figure['bbox'][2] / 2
        self.assertLess(abs(centre - 640), 2, 'the diagram is centred on the page')

    def test_a_bbox_provider_does_not_place_schematic_pages(self):
        import tempfile
        from pathlib import Path
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        base = Path(folder.name)
        schematic_deck(base)
        (base/'deck_ir.json').write_text(
            __import__('json').dumps(schematic_deck(base)), encoding='utf-8')
        requests, _ = read_requests(base/'deck_ir.json', ROOT)
        boxes = [[56.0, 260.0, 500.0, 300.0] for _ in requests[0]['units']]
        self.assertIn('SCHEMATIC_REQUIRES_COMPILER', check(requests[0], boxes))


if __name__ == '__main__':
    unittest.main()
