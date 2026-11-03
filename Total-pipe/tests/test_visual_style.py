"""A deck's visual language is a chosen pack, and a sparse page is balanced, not left at the top."""
import unittest

from deck_compiler import style
from deck_compiler.layout_tree import Need, balanced_region
from deck_compiler.graphic_layout import node_elements


class StylePackTests(unittest.TestCase):
    def test_default_pack_is_academic_and_square(self):
        resolved = style.resolve({})
        self.assertEqual(resolved['graphic']['node']['shape'], 'rect')
        self.assertEqual(resolved['graphic']['node']['fill'], 'none')
        self.assertEqual(resolved['page']['sparse_balance'], 'center')

    def test_commercial_pack_keeps_the_tinted_card_language(self):
        resolved = style.resolve({'visual_style': {'pack': 'commercial'}})
        self.assertEqual(resolved['graphic']['node']['shape'], 'rounded-rect')
        self.assertEqual(resolved['page']['sparse_balance'], 'top')

    def test_overrides_apply_and_are_validated(self):
        resolved = style.resolve({'visual_style': {
            'pack': 'academic', 'overrides': {'graphic.node.stroke_width': 2,
                                              'graphic.edge.width': .75}}})
        self.assertEqual(resolved['graphic']['node']['stroke_width'], 2)
        self.assertEqual(resolved['graphic']['edge']['width'], .75)
        self.assertIn('unknown token', ' '.join(
            style.validate_style({'overrides': {'graphic.node.glow': 1}})))
        self.assertIn('number expected', ' '.join(
            style.validate_style({'overrides': {'graphic.edge.width': 'fat'}})))
        self.assertIn('one of', ' '.join(
            style.validate_style({'overrides': {'graphic.node.shape': 'blob'}})))

    def test_unknown_pack_is_rejected(self):
        with self.assertRaises(style.StyleError):
            style.resolve({'visual_style': {'pack': 'retro'}})
        self.assertIn('pack must be one of', ' '.join(style.validate_style({'pack': 'retro'})))

    def test_node_elements_follow_the_pack(self):
        node = {'id': 'a', 'title': '比较相邻两次目标值'}
        theme = {'accent': '#1D4ED8', 'foreground': '#0F172A', 'background': '#FFFFFF',
                 '_visual_style': style.resolve({'visual_style': {'pack': 'academic'}})}
        shape = node_elements('flow', node, [0, 0, 320, 80], theme)[0]
        self.assertEqual(shape['geometry'], 'rect')
        self.assertEqual(shape['fill'], 'none')
        self.assertEqual(shape['line'], '#0F172A')
        self.assertEqual(shape['line_width'], 1.25)
        commercial = dict(theme, _visual_style=style.resolve({'visual_style': {'pack': 'commercial'}}))
        card = node_elements('flow', node, [0, 0, 320, 80], commercial)[0]
        self.assertEqual(card['geometry'], 'roundRect')
        self.assertNotEqual(card['fill'], 'none')

    def test_declared_node_shape_still_wins(self):
        theme = {'accent': '#1D4ED8', 'foreground': '#0F172A', 'background': '#FFFFFF',
                 '_visual_style': style.resolve({})}
        shape = node_elements('flow', {'id': 'a', 'title': '触发', 'shape': 'diamond'},
                              [0, 0, 200, 120], theme)[0]
        self.assertEqual(shape['geometry'], 'diamond')

    def test_capabilities_publish_the_contract(self):
        published = style.capabilities()
        self.assertEqual(published['default'], 'academic')
        self.assertIn('academic', published['packs'])
        self.assertIn('commercial', published['packs'])
        self.assertIn('text.emphasis', published['packs']['academic']['tokens'])
        self.assertIn('page.furniture', published['packs']['academic']['tokens'])

    def test_emphasis_inks_follow_the_deck_accent(self):
        theme = {'accent': '#1D4ED8', 'foreground': '#0F172A', 'background': '#FFFFFF',
                 '_visual_style': style.resolve({})}
        inks = style.text_styles(theme)
        self.assertEqual(inks['emphasis'], '#1D4ED8')
        self.assertRegex(inks['highlight'], r'^#[0-9A-Fa-f]{6}$')
        print_pack = dict(theme, _visual_style=style.resolve({'visual_style': {'pack': 'print'}}))
        self.assertEqual(style.text_styles(print_pack)['emphasis'], '#0F172A')

    def test_page_furniture_can_be_turned_off_and_is_validated(self):
        theme = {'_visual_style': style.resolve({})}
        self.assertEqual(style.page_furniture(theme)['furniture'], 'rule')
        off = style.resolve({'visual_style': {'overrides': {'page.furniture': 'none'}}})
        self.assertEqual(style.page_furniture({'_visual_style': off})['furniture'], 'none')
        self.assertIn('rule or none', ' '.join(
            style.validate_style({'overrides': {'page.furniture': 'band'}})))
        self.assertIn('unknown token', ' '.join(
            style.validate_style({'overrides': {'page.watermark': '#FFFFFF'}})))


class SparseBalanceTests(unittest.TestCase):
    def compiler(self, preferred):
        class Stub:
            def measure(self, root, width, path, available):
                return Need(preferred, preferred)
        return Stub()

    def test_short_page_is_nudged_towards_the_middle_not_dropped(self):
        region = [56, 190, 1168, 450]
        inset = balanced_region({'type': 'stack'}, self.compiler(120), list(region), {})
        # A full half-slack shift left a hole the height of a paragraph under the takeaway.
        self.assertAlmostEqual(inset[1], 190+32, places=3)
        self.assertAlmostEqual(inset[3], 450-32, places=3)

    def test_full_page_is_not_moved(self):
        region = [56, 190, 1168, 450]
        self.assertEqual(balanced_region({'type': 'stack'}, self.compiler(430), list(region), {}), region)

    def test_top_policy_keeps_the_content_at_the_top(self):
        region = [56, 190, 1168, 450]
        theme = {'_visual_style': style.resolve({'visual_style': {'pack': 'commercial'}})}
        self.assertEqual(balanced_region({'type': 'stack'}, self.compiler(120), list(region), theme), region)


if __name__ == '__main__':
    unittest.main()
