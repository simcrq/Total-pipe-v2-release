"""Formula abstraction: parse once, project to OMML, plain text and a measured box.

The pipeline must never hand markup to the writer that it cannot measure. These tests pin the three
projections and the boundary: an unknown command is rejected with a position, a formula page is not
packed by a bbox provider, and the compiled element carries the OMML paragraph the writer inserts.
"""
import unittest

from deck_compiler.ir import validate
from deck_compiler.layout import compile_deck
from totalpipe_layout import formula as F
from totalpipe_layout.contracts import check, read_requests

from test_deck_compiler import ROOT, fixture


class FormulaParseTests(unittest.TestCase):
    def test_fraction_and_scripts_become_omml_nodes(self):
        ast = F.parse(r'E = \frac{1}{2} m v^2')
        omml = F.to_omml(ast, 24)
        self.assertIn('<m:f>', omml)
        self.assertIn('<m:sSup>', omml)
        self.assertIn('xmlns:m=', omml)
        self.assertEqual(F.to_plain(ast), 'E = 1/2 m v²')

    def test_sum_keeps_its_limits(self):
        ast = F.parse(r'\sum_{i=1}^{n} x_i')
        omml = F.to_omml(ast)
        self.assertIn('<m:nary>', omml)
        self.assertIn('<m:limLoc m:val="undOvr" />', omml)
        self.assertEqual(F.to_plain(ast), '∑ᵢ₌₁^n x_i')

    def test_unknown_command_is_rejected_with_position(self):
        with self.assertRaises(F.FormulaError) as caught:
            F.parse(r'x + \input{secret}')
        self.assertEqual(caught.exception.position, 4)
        self.assertIn('unsupported command', str(caught.exception))

    def test_measure_is_exact_for_math_and_flagged_for_text(self):
        latin = F.measure(F.parse(r'\frac{a}{b}'), 24)
        self.assertTrue(latin.exact)
        self.assertGreater(latin.width, 0)
        mixed = F.measure(F.parse(r'\text{当 } x > 0'), 24)
        self.assertFalse(mixed.exact, 'CJK inside math cannot be measured by mathtext')

    def test_paragraph_carries_the_namespaces_and_a_fallback(self):
        paragraph = F.to_omml_paragraph(F.parse('a^2+b^2'), 24, '#142735')
        for namespace in ('xmlns:a=', 'xmlns:mc=', 'xmlns:a14=', 'xmlns:m='):
            self.assertIn(namespace, paragraph)
        self.assertIn('<mc:Fallback>', paragraph)
        self.assertIn('<a:rPr lang="en-US" sz="1800">', paragraph)


class FormulaDeckTests(unittest.TestCase):
    def formulas_deck(self, source=r'E = mc^2'):
        ir = fixture()
        slide = ir['slides'][1]
        slide['composition'] = {
            'archetype': 'three-conclusions',
            'blocks': [{'id': 'f1', 'component': 'formula', 'text': source},
                       {'id': 'c1', 'component': 'conclusion', 'text': '一条结论。'},
                       {'id': 'c2', 'component': 'conclusion', 'text': '另一条结论。'}],
            'figure_refs': []}
        return {**ir, 'slides': [slide]}

    def test_syntax_error_is_reported_from_the_ir(self):
        rules = [issue['rule'] for issue in validate(self.formulas_deck(r'\frac{a}'))]
        self.assertIn('FORMULA_SYNTAX', rules)

    def test_compiler_emits_a_math_element(self):
        layout, issues = compile_deck(self.formulas_deck(), ROOT)
        self.assertEqual([i for i in issues if i['severity'] == 'FAIL'], [])
        element = [e for e in layout['slides'][0]['elements'] if e['kind'] == 'math'][0]
        self.assertIn('<m:oMathPara', element['omml'])
        self.assertEqual(element['plain'], 'E = mc²')
        self.assertGreaterEqual(element['font_size_px'], 24)
        self.assertTrue(0 < element['bbox'][2] and 0 < element['bbox'][3])

    def test_a_bbox_provider_does_not_pack_formula_pages(self):
        requests, _ = read_requests(ROOT/'examples/formula.deck_ir.json', ROOT)
        request = requests[0]
        boxes = [[56.0, 260.0, 500.0, 300.0] for _ in request['units']]
        self.assertIn('f1:FORMULA_REQUIRES_COMPILER', check(request, boxes))

    def test_formula_above_the_font_floor_is_kept_at_least_18_pt(self):
        layout, issues = compile_deck(self.formulas_deck(), ROOT)
        element = [e for e in layout['slides'][0]['elements'] if e['kind'] == 'math'][0]
        self.assertGreaterEqual(element['font_size_px'], 24, '18 pt is 24 px at 96 dpi')
        self.assertFalse([i for i in issues if i['severity'] == 'FAIL'])

    def test_an_over_wide_formula_asks_for_a_split_instead_of_shrinking(self):
        long_formula = ' + '.join([r'\frac{1}{1+e^{-t}}'] * 4)
        _, issues = compile_deck(self.formulas_deck(long_formula), ROOT)
        self.assertIn('SPLIT_REQUIRED', [i['rule'] for i in issues])


if __name__ == '__main__':
    unittest.main()
