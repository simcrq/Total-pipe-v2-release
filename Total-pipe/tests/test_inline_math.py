"""Native inline equations are measured as atomic math within variable-height prose lines."""
import copy
import json
from pathlib import Path
import shutil
import tempfile
import unittest
import zipfile

from lxml import etree as ET

from deck_compiler.contracts import TextBoxContract
from deck_compiler.fonts import load_font_file, resolve_theme_fonts
from deck_compiler.inline_text import fit_inline
from deck_compiler.ir import coarse_characters, validate
from deck_compiler.layout import compile_deck, text_visible_bottom
from deck_compiler.layout_tree import LayoutTreeError
from deck_compiler.native_table import compile_table, table_has_math
from deck_compiler.officecli import render
from deck_compiler.pipeline import write_json
from deck_compiler.structural import MATH_NS, verify
from totalpipe_layout.inline_math import InlineMathError, InlineWidthError, measure_inline, parse_inline, plain_text

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT/'examples/inline-math.deck_ir.json'


def fixture():
    return json.loads(EXAMPLE.read_text())


class InlineMathTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        regular, bold, _ = resolve_theme_fonts(fixture()['theme'], EXAMPLE.parent, '完整科学术语矩阵正文')
        cls.fonts = {'font_file': regular, 'bold_font_file': bold}
        cls.font = load_font_file(regular, 24)

    def compile_ok(self, ir=None):
        ir = ir or fixture(); before = copy.deepcopy(ir)
        layout, items = compile_deck(ir, EXAMPLE.parent)
        self.assertFalse([i for i in items if i['severity'] == 'FAIL'], items)
        self.assertEqual(ir, before)
        return layout, items

    def test_delimiters_escaped_currency_and_source_positions(self):
        source = r'完整科学术语 $x_i^2$ 与 \(\sqrt{1+x^2}\)，价格 \$5。'
        spans = parse_inline(source)
        self.assertEqual([s.text for s in spans if s.kind == 'formula'], ['x_i^2', r'\sqrt{1+x^2}'])
        self.assertIn('$5', plain_text(source))
        self.assertIn('√', plain_text(source))
        self.assertEqual(parse_inline(source), spans)

    def test_malformed_inline_math_never_silently_becomes_plain_text(self):
        for source in ('unclosed $x', '$$', '$ $', r'\[x\]', r'\(x', r'\)', r'$\unknown{x}$', r'$x^$'):
            with self.subTest(source=source), self.assertRaises(InlineMathError): parse_inline(source)

    def test_capacity_counts_prose_and_math_atoms_not_latex_source_characters(self):
        source = r'完整术语 $\sqrt{\frac{1+e^{-t}}{1+t^{2}}}$。'
        self.assertEqual(coarse_characters(source, True), 7)
        self.assertEqual(coarse_characters(source, False), len(source))

    def test_each_line_uses_its_own_maximum_ascent_and_descent(self):
        source = '普通说明\n含公式 '+r'$\sqrt{\frac{1+x^2}{1+y^2}}$'+' 后继续说明\n普通说明'
        plan = measure_inline(source, 1100, self.font, 24)
        self.assertEqual(len(plan['lines']), 3)
        a, b, c = plan['lines']
        self.assertGreater(b['height'], a['height'])
        self.assertEqual(a['height'], c['height'])
        self.assertAlmostEqual(plan['height'], sum(line['height'] for line in plan['lines']))
        self.assertLess(plan['height'], 3*b['height'])
        self.assertTrue(all(line['height'] >= line['ascent']+line['descent'] for line in plan['lines']))

    def test_line_breaks_never_reach_glyph_measurement(self):
        # Model Pillow 13 + Raqm even on wheels built without Raqm. Also verify
        # Windows CRLF and bare CR keep the same explicit lines and capacity.
        class StrictFont:
            def getmetrics(inner):
                return self.font.getmetrics()

            def getlength(inner, text):
                if '\n' in text or '\r' in text:
                    raise RuntimeError('raqm_layout() failed')
                return self.font.getlength(text)

        expected = None
        for separator in ('\n', '\r\n', '\r'):
            with self.subTest(separator=repr(separator)):
                source = separator + '说明 $x^2$' + separator + separator + '完整术语' + separator
                plan = measure_inline(source, 1100, StrictFont(), 24)
                self.assertEqual(len(plan['lines']), 5)
                self.assertEqual(plan['formula_count'], 1)
                self.assertEqual([line['text'] for line in plan['lines']], ['', '说明 x²', '', '完整术语', ''])
                self.assertAlmostEqual(plan['height'], sum(line['height'] for line in plan['lines']))
                if expected is None:
                    expected = plan
                else:
                    self.assertEqual(plan, expected)

    def test_formulas_stay_atomic_across_wrapped_text_and_matrices(self):
        source = r'先定义 $M=\begin{bmatrix}x^2&0\\1&\sqrt{y}\end{bmatrix}$，再保留完整说明和 $q(t)=e^{-t}$。'
        plan = measure_inline(source, 360, self.font, 24)
        fragments = [f for line in plan['lines'] for f in line['fragments'] if f['kind'] == 'formula']
        self.assertEqual([f['text'] for f in fragments], [s.text for s in parse_inline(source) if s.kind == 'formula'])
        self.assertTrue(all(line['width'] <= 360+.01 for line in plan['lines']))
        self.assertFalse(any(line['text'].startswith(('，', '。')) for line in plan['lines']))
        self.assertEqual(''.join(plan['text'].split()), ''.join(plain_text(source).split()))
        spaced = measure_inline('说明 $x^2$   ，完整术语', 120, self.font, 24)
        self.assertFalse(any(line['text'].startswith('，') for line in spaced['lines']))

    def test_oversized_atom_reports_width_and_never_shrinks_below_the_floor(self):
        source = r'公式 $a+b+c+d+e+f+g+h+i+j+k+l+m+n$ 后的完整说明'
        contract = TextBoxContract('Test face', 28, self.fonts['font_file'], font_floor=24)
        with self.assertRaises(InlineWidthError) as caught:
            fit_inline(source, [0, 0, 80, 500], contract, True)
        self.assertGreater(caught.exception.required_width, 80)
        plan, fitted, overflow = fit_inline(r'完整术语 $x^2$\n继续说明', [0, 0, 500, 10], contract, True)
        self.assertTrue(overflow)
        self.assertEqual(fitted.font_size, 24)
        self.assertGreater(plan['height'], 10)
        with self.assertRaises(ValueError): fit_inline(r'完整术语 $x^2$', [0, 0, 500, 10], contract, False)

    def test_schema_native_payloads_and_literal_legacy_block(self):
        import jsonschema
        ir = fixture()
        jsonschema.validate(ir, json.loads((ROOT/'schemas/deck-ir.schema.json').read_text()))
        layout, items = self.compile_ok(ir)
        inline = [e for s in layout['slides'] for e in s['elements'] if e.get('inline_math')]
        self.assertGreaterEqual(len(inline), 6)
        for element in inline:
            root = ET.fromstring(element['inline_xml'])
            self.assertTrue(root.findall('.//a14:m/m:oMath', MATH_NS))
            self.assertFalse(root.findall('.//m:oMathPara', MATH_NS))
            self.assertEqual(len(root.findall('a:p', MATH_NS)), len(element['inline_layout']['lines']))
            self.assertGreaterEqual(element['contract']['font_size'], element['contract']['font_floor'])
        legacy = next(e for e in layout['slides'][0]['elements'] if e['id'] == 'legacy')
        self.assertNotIn('inline_math', legacy)
        self.assertIn('$x^2$', legacy['text'])
        self.assertTrue(any(e['kind'] == 'math' for e in layout['slides'][1]['elements']))
        self.assertIn('INLINE_MATH_MEASUREMENT_REVIEW', [i['rule'] for i in items])

    def test_semantic_flags_and_invalid_block_combinations_are_structured_errors(self):
        for mutation in ('fields', 'syntax', 'type', 'list', 'formula'):
            ir = fixture(); slide = ir['slides'][0]; block = slide['composition']['blocks'][0]
            if mutation == 'fields': slide['semantic']['inline_math'] = None
            if mutation == 'syntax': block['text'] = '无结束符 $x'
            if mutation == 'type': block['inline_math'] = 'yes'
            if mutation == 'list': block['text_flow'] = 'distributed_arrow_list'
            if mutation == 'formula': block['component'] = 'formula'
            self.assertTrue(any(i['severity'] == 'FAIL' for i in validate(ir)), mutation)

    def test_visible_bottom_uses_measured_mixed_height(self):
        layout, _ = self.compile_ok()
        element = next(e for e in layout['slides'][0]['elements'] if e['id'] == 'fraction')
        self.assertAlmostEqual(text_visible_bottom(element), min(element['bbox'][1]+element['bbox'][3],
            element['bbox'][1]+element['inline_layout']['height']))

    def test_inline_tables_use_true_math_height_and_preserve_old_formula_cells(self):
        table = fixture()['slides'][2]['composition']['tables'][0]
        self.assertTrue(table_has_math(table))
        with self.assertRaises(LayoutTreeError) as caught:
            compile_table(table, [0, 0, 1168, 60], self.fonts, fixture()['theme'], True)
        self.assertIn('18 pt', str(caught.exception))
        layout, _ = self.compile_ok()
        rendered = next(e for e in layout['slides'][2]['elements'] if e['kind'] == 'table')
        root = ET.fromstring(rendered['table_xml'])
        self.assertTrue(root.findall('.//a14:m/m:oMath', MATH_NS))
        self.assertTrue(root.findall('.//m:oMathPara', MATH_NS))
        self.assertEqual(sum(c.get('inline_formula_count', 0) for c in rendered['cells']), 2)

    def test_plain_overflow_repair_cannot_split_inline_math_or_its_source_group(self):
        from deck_compiler.overflow_repair import repair_overflow
        ir = fixture(); ir['presentation']['text_capacity_policy'] = 'strict'
        layout, _ = self.compile_ok(ir)
        qa = {'items': [{'rule': 'OFFICECLI_FORMAT', 'severity': 'WARNING', 'slide': 1, 'shape': '/slide[1]/shape[@id=1]',
            'message': 'text overflow: 3 lines at 18pt need 160pt, usable 30pt.'}]}
        fixed, changed = repair_overflow(ir, layout, qa)
        self.assertFalse(changed)
        self.assertEqual(fixed, ir)

    @unittest.skipUnless(shutil.which('officecli'), 'OfficeCLI required')
    def test_native_roundtrip_and_inline_corruption_detection(self):
        layout, _ = self.compile_ok()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); output = root/'candidate.pptx'
            write_json(root/'layout.json', layout)
            render(root/'layout.json', output, executable=shutil.which('officecli'))
            self.assertFalse([i for i in verify(output, layout) if i['severity'] == 'FAIL'])
            with zipfile.ZipFile(output) as source:
                parts = {n: source.read(n) for n in source.namelist()}
            slide = ET.fromstring(parts['ppt/slides/slide1.xml'])
            slide.find('.//a14:m/m:oMath//m:t', MATH_NS).text = 'WRONG'
            parts['ppt/slides/slide1.xml'] = ET.tostring(slide)
            with zipfile.ZipFile(root/'corrupt.pptx', 'w') as dest:
                for name, data in parts.items(): dest.writestr(name, data)
            self.assertIn('INLINE_CONTENT_MISMATCH', [i['rule'] for i in verify(root/'corrupt.pptx', layout)])


if __name__ == '__main__': unittest.main()
