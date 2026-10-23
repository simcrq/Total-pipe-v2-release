"""Formula abstraction: parse once, project to OMML, plain text and a measured box.

The pipeline must never hand markup to the writer that it cannot measure. These tests pin the three
projections and the boundary: an unknown command is rejected with a position, a formula page is not
packed by a bbox provider, and the compiled element carries the OMML paragraph the writer inserts.
"""
from pathlib import Path
import shutil
import tempfile
import unittest
import zipfile

from lxml import etree as ET

from deck_compiler.ir import validate
from deck_compiler.layout import compile_deck
from totalpipe_layout import formula as F
from totalpipe_layout.contracts import check, read_requests
from deck_compiler.officecli import render
from deck_compiler.pipeline import write_json
from deck_compiler.structural import MATH_NS, verify

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

    def test_roots_preserve_the_degree_and_the_entire_radicand(self):
        for source in (r'\sqrt{x^2+y^2}', r'\sqrt {x^2+y^2}'):
            with self.subTest(source=source):
                ast = F.parse(source)
                self.assertIsInstance(ast, F.Sqrt)
                self.assertEqual(F.to_plain(ast), '√(x²+y²)')
                root = ET.fromstring(F.to_omml(ast))
                self.assertEqual(len(root.findall('.//m:rad/m:e/m:sSup', MATH_NS)), 2)
        ast = F.parse(r'\sqrt[3]{1+\sqrt{x^2}}')
        root = ET.fromstring(F.to_omml(ast))
        self.assertEqual(root.find('m:rad/m:deg/m:r/m:t', MATH_NS).text, '3')
        self.assertEqual(root.find('m:rad/m:radPr/m:degHide', MATH_NS).get('{'+F.MATH_NS+'}val'), '0')
        self.assertIn('³√', F.to_plain(ast))

    def test_scripts_preserve_grouped_bases_and_nested_exponents(self):
        ast = F.parse(r'{xy}^{a^{2}}')
        self.assertEqual(F.to_latex(ast), r'{xy}^{{a}^{2}}')
        self.assertEqual(F.to_plain(ast), '(xy)^(a²)')
        self.assertEqual(F.parse('x ^ 2'), F.parse('x^2'))
        ast = F.parse(r'x_i^2')
        self.assertIsNotNone(ET.fromstring(F.to_omml(ast)).find('m:sSubSup', MATH_NS))

    def test_agent_math_delimiters_and_functions_are_supported(self):
        source = r'\exp\left(-\frac{x^2}{2\sigma^2}\right)'
        expected = F.parse(source)
        for left, right in (('$', '$'), ('$$', '$$'), (r'\(', r'\)'), (r'\[', r'\]')):
            self.assertEqual(F.parse(left+source+right), expected)
        self.assertTrue(F.measure(expected).exact)
        self.assertTrue(F.measure(F.parse(r'\mathrm{MoO}_{x}')).exact)
        self.assertIsNotNone(ET.fromstring(F.to_omml(expected)).find('.//m:d', MATH_NS))

    def test_malformed_arguments_return_formula_errors_instead_of_index_errors(self):
        for source in (r'\left', r'\left(x\right', r'\sqrt', r'\sqrt{}', r'\sqrt[]{x}',
                       r'\sqrt[3{x}', 'x^', 'x^}', 'x^^2', r'\sum_i_j x', '$$x^2$', r'\(x^2'):
            with self.subTest(source=source), self.assertRaises(F.FormulaError):
                F.parse(source)

    def test_measure_typesets_math_instead_of_measuring_literal_latex(self):
        from matplotlib.mathtext import MathTextParser
        from matplotlib.font_manager import FontProperties
        parser = MathTextParser('path')
        for source in (r'\frac{a}{b}', r'\sqrt{x^2+y^2}', r'\sqrt[3]{x}', r'x^{a^{2}}',
                       r'\frac{1}{\sqrt{1+e^{-t}}}'):
            with self.subTest(source=source):
                ast = F.parse(source)
                expected = parser.parse('$'+F.to_latex(ast)+'$', dpi=96, prop=FontProperties(size=18))
                actual = F.measure(ast, 24)
                self.assertTrue(actual.exact)
                self.assertEqual((actual.width, actual.height), (expected.width, expected.height))
        fraction = F.measure(F.parse(r'\frac{a}{b}'), 24)
        literal = parser.parse(r'\frac{a}{b}', dpi=96, prop=FontProperties(size=18))
        self.assertLess(fraction.width, literal.width/3)

    def test_display_math_has_a_real_equation_container(self):
        paragraph = ET.fromstring(F.to_omml_paragraph(F.parse(r'\sqrt{x^2}'), 24))
        path = 'mc:AlternateContent/mc:Choice/a14:m/m:oMathPara'
        math = paragraph.find(path, MATH_NS)
        self.assertEqual([child.tag for child in math], ['{'+F.MATH_NS+'}oMath'])
        self.assertIsNotNone(math.find('m:oMath/m:rad/m:e/m:sSup', MATH_NS))
        self.assertIsNotNone(ET.fromstring(F.to_omml(F.parse('x^2'), 24)).find('.//a:rPr/a:latin', MATH_NS))


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

    def test_an_over_wide_formula_is_a_capacity_failure_not_a_smaller_equation(self):
        long_formula = ' + '.join([r'\frac{1}{1+e^{-t}}'] * 20)
        _, issues = compile_deck(self.formulas_deck(long_formula), ROOT)
        rules = [i['rule'] for i in issues]
        self.assertIn('FORMULA_CAPACITY', rules)
        failure = next(i for i in issues if i['rule'] == 'FORMULA_CAPACITY')
        self.assertEqual(failure['source'].get('suggested_fix'),
                         'widen_text_column_or_split_slide')
        self.assertNotIn('SPLIT_REQUIRED', rules,
                         'a formula that cannot fit is a budget problem, not a generic split')

    def test_common_root_and_exponential_formulas_compile_without_false_capacity_failures(self):
        for source in (r'\sqrt{x^2+y^2}', r'\sqrt[3]{x}',
                       r'\exp\left(-\frac{x^2}{2\sigma^2}\right)',
                       r'\frac{1}{1+e^{-t}} + \frac{1}{1+e^{-t}} + \frac{1}{1+e^{-t}} + \frac{1}{1+e^{-t}}'):
            with self.subTest(source=source):
                layout, issues = compile_deck(self.formulas_deck(source), ROOT)
                self.assertFalse([i for i in issues if i['severity'] == 'FAIL'], issues)
                equation = next(e for e in layout['slides'][0]['elements'] if e['kind'] == 'math')
                self.assertEqual(equation['source_text'], source)
                self.assertTrue(equation['measured_exact'])

    @unittest.skipUnless(shutil.which('officecli'), 'OfficeCLI executable required')
    def test_officecli_inserts_native_roots_and_powers_and_verifier_detects_corruption(self):
        ir = self.formulas_deck(r'\sqrt[3]{x^{2}+\frac{1}{e^{-t}}}')
        layout, issues = compile_deck(ir, ROOT)
        self.assertFalse([i for i in issues if i['severity'] == 'FAIL'], issues)
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            write_json(base/'layout.json', layout)
            pptx = base/'formula.pptx'
            render(base/'layout.json', pptx)
            self.assertFalse([i for i in verify(pptx, layout) if i['severity'] == 'FAIL'])
            with zipfile.ZipFile(pptx) as archive:
                parts = {name: archive.read(name) for name in archive.namelist()}
            original = parts['ppt/slides/slide1.xml']
            for mutation, rule in (('exponent', 'FORMULA_CONTENT_MISMATCH'),
                                   ('wrapper', 'FORMULA_MISSING'), ('fallback', 'FORMULA_FALLBACK_MISMATCH')):
                with self.subTest(mutation=mutation):
                    root = ET.fromstring(original)
                    if mutation == 'exponent':
                        root.find('.//m:sSup/m:sup/m:r/m:t', MATH_NS).text = '9'
                    elif mutation == 'wrapper':
                        math = root.find('.//m:oMath', MATH_NS)
                        math.getparent().remove(math)
                    else:
                        fallback = root.find('.//mc:Fallback', MATH_NS)
                        fallback.getparent().remove(fallback)
                    parts['ppt/slides/slide1.xml'] = ET.tostring(root)
                    with zipfile.ZipFile(pptx, 'w') as archive:
                        for name, data in parts.items(): archive.writestr(name, data)
                    self.assertIn(rule, {i['rule'] for i in verify(pptx, layout)})


if __name__ == '__main__':
    unittest.main()
