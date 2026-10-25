"""Native matrix math and measured dense pages retain every cell, equation and explanation."""
import copy
import json
from pathlib import Path
import shutil
import tempfile
import unittest
import zipfile

from lxml import etree as ET

from totalpipe_layout import formula as F
from deck_compiler.formula_layout import formula_groups
from deck_compiler.ir import validate
from deck_compiler.layout import compile_deck, geometry_issues, lower_whitespace_issue
from deck_compiler.layout_provider import compile_with_provider
from deck_compiler.officecli import render
from deck_compiler.pipeline import write_json
from deck_compiler.structural import MATH_NS, verify
from test_deck_compiler import ROOT, fixture
from test_formula_capacity import figure_deck


A = r'\begin{bmatrix}4&2&0&0\\2&5&2&0\\0&2&5&2\\0&0&2&2\end{bmatrix}'


def deck(blocks, archetype='equation-derivation'):
    ir = fixture()
    page = ir['slides'][1]
    page['semantic'].update(title='Matrix and derivation', takeaway='Preserve every cell and equation.', caveats=[])
    page['composition'] = {'archetype': archetype, 'blocks': blocks, 'figure_refs': []}
    ir['slides'] = [page]
    return ir


class MatrixParseTests(unittest.TestCase):
    def test_matrix_environments_emit_native_rows_columns_and_delimiters(self):
        for env, delimiters in F.MATRIX_DELIMITERS.items():
            with self.subTest(environment=env):
                ast = F.parse(r'\begin{'+env+r'}1&2\\3&4\end{'+env+'}')
                self.assertIsInstance(ast, F.Matrix)
                root = ET.fromstring(F.to_omml(ast, 30, '#142735'))
                matrix = root.find('.//m:m', MATH_NS)
                rows = matrix.findall('m:mr', MATH_NS)
                self.assertEqual([[c.find('m:r/m:t', MATH_NS).text for c in r.findall('m:e', MATH_NS)]
                                  for r in rows], [['1', '2'], ['3', '4']])
                self.assertEqual(matrix.find('m:mPr/m:mcs/m:mc/m:mcPr/m:count', MATH_NS).get('{'+F.MATH_NS+'}val'), '2')
                self.assertFalse(root.findall('.//m:mcJc', MATH_NS), 'DrawingML math forbids mcJc')
                for tag in ('cGp', 'cGpRule', 'cSp', 'rSp', 'rSpRule'):
                    self.assertFalse(root.findall('.//m:'+tag, MATH_NS), 'DrawingML math forbids custom spacing')
                if env != 'matrix':
                    self.assertEqual(root.find('.//m:dPr/m:begChr', MATH_NS).get('{'+F.MATH_NS+'}val'), delimiters[0])
                    self.assertEqual(root.find('.//m:dPr/m:endChr', MATH_NS).get('{'+F.MATH_NS+'}val'), delimiters[1])
                    self.assertEqual(root.find('.//m:dPr/m:grow', MATH_NS).get('{'+F.MATH_NS+'}val'), '1')
                    self.assertEqual(root.find('.//m:dPr/m:shp', MATH_NS).get('{'+F.MATH_NS+'}val'), 'centered')
                    self.assertEqual(root.find('.//m:dPr/m:ctrlPr/a:rPr', MATH_NS).get('sz'), '2250')
                    self.assertEqual(rows[0].find('m:e/m:r/a:rPr', MATH_NS).get('sz'), '2250')

    def test_fraction_root_scripts_and_transpose_survive_inside_cells(self):
        ast = F.parse(r'\begin{pmatrix}\frac{1}{2}&\sqrt{x^2}\\0&y_{i+1}\end{pmatrix}^{T}')
        root = ET.fromstring(F.to_omml(ast, 30))
        self.assertIsNotNone(root.find('m:sSup/m:e/m:d/m:e/m:m', MATH_NS))
        self.assertIsNotNone(root.find('.//m:mr/m:e/m:f', MATH_NS))
        self.assertIsNotNone(root.find('.//m:rad/m:e/m:sSup', MATH_NS))
        self.assertIsNotNone(root.find('.//m:sSub', MATH_NS))
        self.assertEqual(root.find('.//m:dPr/m:ctrlPr/a:rPr', MATH_NS).get('sz'), '3375')
        self.assertEqual(F.to_plain(ast), '(1/2, √(x²); 0, y_(i+1))^T')

    def test_blank_cells_and_trailing_row_separator_preserve_the_shape(self):
        ast = F.parse(r'\begin{bmatrix}1&\\&2\\\end{bmatrix}')
        root = ET.fromstring(F.to_omml(ast))
        self.assertEqual(len(root.findall('.//m:mr', MATH_NS)), 2)
        self.assertEqual([len(r.findall('m:e', MATH_NS)) for r in root.findall('.//m:mr', MATH_NS)], [2, 2])
        self.assertEqual(F.to_plain(ast), '[1, ; , 2]')

    def test_nested_matrices_and_cell_local_sums_do_not_steal_separators(self):
        source = r'\begin{bmatrix}\sum_{i=1}^{n} x_i&\begin{matrix}1&2\\3&4\end{matrix}\\0&1\end{bmatrix}'
        ast = F.parse(source)
        self.assertEqual(len(ast.rows), 2)
        self.assertIsInstance(ast.rows[0][0], F.Nary)
        self.assertIsInstance(ast.rows[0][1], F.Matrix)
        self.assertGreater(F.measure(ast, 30).height, F.measure(F.parse(A), 30).height/2)

    def test_invalid_environments_and_ragged_rows_fail_with_a_source_position(self):
        for source in (r'\begin{bmatrix}1&2\\3\end{bmatrix}', r'\begin{bmatrix}\end{bmatrix}',
                       r'\begin{bmatrix}1&2', r'\begin{bmatrix}1\end{pmatrix}',
                       r'\begin{array}{cc}1&2\end{array}', r'1&2', r'\end{matrix}'):
            with self.subTest(source=source), self.assertRaises(F.FormulaError) as caught:
                F.parse(source)
            self.assertIsInstance(caught.exception.position, int)

    def test_measurement_uses_rows_and_column_maxima_instead_of_flat_text_length(self):
        one = F.measure(F.parse(r'\begin{matrix}1&2&3&4\end{matrix}'), 30)
        four = F.measure(F.parse(A.replace('bmatrix', 'matrix')), 30)
        self.assertAlmostEqual(four.width, one.width, delta=30)
        self.assertGreater(four.height, one.height*3)
        self.assertLess(four.width, len(A)*30*.4)
        self.assertFalse(four.exact, 'Office matrix row spacing still requires native review')
        for source in ('A='+A, r'\frac{'+A+r'}{2}', r'\sqrt{'+A+'}', '{'+A+'}^{2}'):
            measured = F.measure(F.parse(source), 30)
            self.assertGreater(measured.height, 80)
            self.assertGreater(measured.width, 0)

    def test_matrix_source_round_trip_keeps_cells_and_external_fences(self):
        ast = F.parse(r'\left[\begin{matrix}1&2\\3&4\end{matrix}\right]')
        self.assertEqual(F.to_plain(ast), '[1, 2; 3, 4]')
        self.assertEqual(F.to_plain(F.parse(F.to_latex(ast))), F.to_plain(ast))

    def test_parallel_matrix_spacing_is_preserved_and_measured(self):
        base = r'\begin{bmatrix}1&2\\3&4\end{bmatrix}'
        joined = F.parse(base+base)
        spaced = F.parse(base+r'\qquad '+base)
        self.assertGreater(F.measure(spaced, 30).width, F.measure(joined, 30).width+40)
        root = ET.fromstring(F.to_omml(spaced, 30))
        self.assertIn('\u2003\u2003', ''.join(root.xpath('.//m:t/text()', namespaces=MATH_NS)))

    def test_display_fraction_cells_and_radical_over_sum_keep_native_height_allowance(self):
        scalar = F.measure(F.parse(r'\frac{1}{2}'), 30)
        self.assertGreaterEqual(scalar.height, 75)
        matrix = F.measure(F.parse(r'\begin{bmatrix}1&0\\\frac{1}{2}&1\\0&\frac{1}{2}\end{bmatrix}'), 30)
        self.assertGreater(matrix.height, 180)
        source = r'l_{jj}=\sqrt{a_{jj}-\sum_{k=1}^{j-1}l_{jk}^{2}}'
        native = F.measure(F.parse(source), 30)
        self.assertGreater(native.height, 120, 'mathtext alone measured 98 px, clipping the native radical')
        root = ET.fromstring(F.to_omml(F.parse(source), 30))
        for path in ('.//m:radPr/m:ctrlPr/a:rPr', './/m:naryPr/m:ctrlPr/a:rPr'):
            self.assertIsNotNone(root.find(path, MATH_NS))

    def test_reference_factors_and_solution_match_the_numeric_matrix(self):
        from fractions import Fraction as Q
        a = [[4,2,0,0],[2,5,2,0],[0,2,5,2],[0,0,2,2]]
        l = [[2,0,0,0],[1,2,0,0],[0,1,2,0],[0,0,1,1]]
        l0 = [[1,0,0,0],[Q(1,2),1,0,0],[0,Q(1,2),1,0],[0,0,Q(1,2),1]]
        d = [4,4,4,1]
        self.assertEqual([[sum(l[i][k]*l[j][k] for k in range(4)) for j in range(4)] for i in range(4)], a)
        self.assertEqual([[sum(l0[i][k]*d[k]*l0[j][k] for k in range(4)) for j in range(4)] for i in range(4)], a)
        self.assertEqual([sum(row[i]*x for i,x in enumerate([1,-1,2,1])) for row in a], [2,1,10,6])


class DenseFormulaLayoutTests(unittest.TestCase):
    def compile_ok(self, ir):
        before = copy.deepcopy(ir)
        layout, issues = compile_deck(ir, ROOT)
        self.assertFalse([i for i in issues if i['severity'] == 'FAIL'], issues)
        self.assertFalse([i for i in geometry_issues(layout['slides'][0]['elements'], 1) if i['severity'] == 'FAIL'])
        self.assertEqual(ir, before)
        return layout

    def test_many_formulas_use_measured_rows_without_a_two_equation_limit(self):
        blocks = [{'id': f'f{k}', 'component': 'formula', 'text': f'x_{{{k}}}={k}'} for k in range(12)]
        ir = deck(blocks)
        layout = self.compile_ok(ir)
        equations = [e for e in layout['slides'][0]['elements'] if e['kind'] == 'math']
        self.assertEqual([e['id'] for e in equations], [b['id'] for b in blocks])
        self.assertTrue(all(e['font_size_px'] >= 24 for e in equations))
        flow = next(a for a in layout['slides'][0]['adaptation_log'] if a['action'] == 'formula_flow')
        self.assertEqual(flow['columns'], 2)
        self.assertGreaterEqual(equations[0]['bbox'][1], 280,
                                'equations follow the balanced body band, not a hard top pin')
        self.assertLessEqual(equations[0]['bbox'][1], 340)
        self.assertLess(max(flow['column_heights_px']), 400)

    def test_tall_matrix_and_parallel_matrices_fit_their_real_regions(self):
        blocks = [{'id': f'm{k}', 'component': 'formula', 'text': 'A='+A} for k in range(3)]
        layout = self.compile_ok(deck(blocks))
        flow = next(a for a in layout['slides'][0]['adaptation_log'] if a['action'] == 'formula_flow')
        # Sum of all three matrix heights exceeds the old page-share budget, yet two independent
        # columns can hold them. Matrix height must not be flattened to a single text line.
        equations = [e for e in layout['slides'][0]['elements'] if e['kind'] == 'math']
        self.assertEqual(len(equations), 3)
        self.assertEqual(flow['columns'], 2)
        self.assertTrue(all(e['bbox'][3] > 100 for e in equations))

    def test_consecutive_unlabelled_equations_are_never_hidden_under_the_first(self):
        blocks = [{'id': f'f{k}', 'component': 'formula', 'text': f'x={k}'} for k in range(3)]
        self.assertEqual(len(formula_groups(blocks)), 3)
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            ir = figure_deck(base, blocks)
            layout, issues = compile_deck(ir, base)
            self.assertFalse([i for i in issues if i['severity'] == 'FAIL'], issues)
            self.assertEqual([e['id'] for e in layout['slides'][0]['elements'] if e['kind'] == 'math'], ['f0', 'f1', 'f2'])

    def test_explicit_anchors_remain_with_the_full_explanation(self):
        blocks = []
        for group in ('forward', 'back'):
            blocks.append({'id': group, 'component': 'body', 'text': 'Keep the full explanation next to these equations.'})
            blocks += [{'id': f'{group}{k}', 'component': 'formula', 'anchor': group,
                        'text': f'x_{{{k}}}={k}'} for k in range(5)]
        layout = self.compile_ok(deck(blocks))
        flow = next(a for a in layout['slides'][0]['adaptation_log'] if a['action'] == 'formula_flow')
        self.assertEqual(flow['columns'], 2)
        for group in ('forward', 'back'):
            self.assertEqual(len({flow['boxes'][b['id']][0] for b in blocks if b['id'].startswith(group)}), 1)
        self.assertLess(flow['boxes']['forward0'][1]-flow['boxes']['forward'][1], 100,
                        'the explanation box must not absorb the unused column height')

    def test_impossible_content_fails_with_real_height_and_width_diagnostics(self):
        ir = deck([{'id': f'f{k}', 'component': 'formula', 'text': 'x='+A} for k in range(12)])
        ir['presentation'] = {'text_capacity_policy': 'preserve-terms'}
        _, issues = compile_deck(ir, ROOT)
        failure = next(i for i in issues if i['rule'] == 'FORMULA_CAPACITY')
        self.assertEqual(failure['severity'], 'FAIL')
        self.assertTrue(failure['source']['attempts'])
        self.assertEqual(failure['source']['suggested_fix'], 'widen_text_column_or_split_slide')
        self.assertNotIn('FORMULA_BUDGET', [i['rule'] for i in issues])

    def test_dense_formula_planning_preserves_over_budget_scientific_prose_for_review(self):
        prose = 'X-ray photoelectron spectroscopy of molybdenum(VI) oxide preserves the chemical-state assignment. '*40
        ir = deck([{'id':'terms', 'component':'body', 'text':prose},
                   {'id':'eq', 'component':'formula', 'text':'x=1', 'anchor':'terms'}])
        ir['presentation'] = {'text_capacity_policy': 'preserve-terms'}
        layout, issues = compile_deck(ir, ROOT)
        self.assertFalse([i for i in issues if i['severity'] == 'FAIL'], issues)
        objects = {e['id']:e for e in layout['slides'][0]['elements']}
        self.assertEqual(objects['terms']['source_text'], prose)
        self.assertEqual(objects['terms']['contract']['overflow_policy'], 'preserve_terms_review')
        self.assertEqual(objects['eq']['kind'], 'math')
        self.assertIn('SCIENTIFIC_TEXT_OVERFLOW', {i['rule'] for i in issues})
        self.assertFalse([i for i in geometry_issues(layout['slides'][0]['elements'], 1) if i['severity'] == 'FAIL'])
        ir['presentation']['text_capacity_policy'] = 'strict'
        self.assertTrue([i for i in compile_deck(ir, ROOT)[1] if i['severity'] == 'FAIL'])

    def test_reference_fixture_compiles_every_equation_without_geometry_failures(self):
        path = ROOT/'examples/matrix-derivation.deck_ir.json'
        ir = json.loads(path.read_text())
        layout, issues = compile_deck(ir, path.parent)
        self.assertFalse([i for i in issues if i['severity'] == 'FAIL'], issues)
        self.assertEqual(len(layout['slides']), 6)
        for source, compiled in zip(ir['slides'], layout['slides']):
            expected = [b['id'] for b in source['composition']['blocks'] if b['component'] == 'formula']
            self.assertEqual([e['id'] for e in compiled['elements'] if e['kind'] == 'math'], expected)
            self.assertFalse([i for i in geometry_issues(compiled['elements'], 1) if i['severity'] == 'FAIL'])

    def test_whitespace_detector_counts_math_instead_of_only_the_prose(self):
        elements = [{'id': 'matrix', 'kind': 'math', 'role': 'formula', 'bbox': [56, 260, 300, 320]}]
        self.assertIsNone(lower_whitespace_issue(elements, 1, 260, 640))

    def test_anchors_cannot_point_forward_in_reading_order(self):
        ir = deck([{'id':'eq','component':'formula','text':'x=1','anchor':'later'},
                   {'id':'later','component':'body','text':'This explanation comes too late.'}])
        self.assertIn('FORMULA_ANCHOR_INVALID', [i['rule'] for i in validate(ir)])

    def test_provider_never_packs_or_truncates_dense_formula_pages(self):
        class Provider:
            name = 'spy'
            def propose(self, requests):
                self.requests = requests
                return {}
        ir = deck([{'id': f'f{k}', 'component': 'formula', 'text': f'x={k}'} for k in range(18)])
        ir['presentation'] = {'academic_design': {'style': 'research-seminar', 'title_treatment': 'plain',
            'density': 'balanced', 'figure_treatment': 'unframed', 'decoration_policy': 'none'}}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'deck.json'
            write_json(path, ir)
            provider = Provider()
            layout, issues = compile_with_provider(path, provider, ROOT)
        self.assertFalse([i for i in issues if i['severity'] == 'FAIL'], issues)
        self.assertFalse(hasattr(provider, 'requests'))
        self.assertEqual(layout['layout_provider']['slides'][0]['reason'], 'measured_formula_flow')
        self.assertEqual(sum(e['kind'] == 'math' for e in layout['slides'][0]['elements']), 18)

    @unittest.skipUnless(shutil.which('officecli'), 'OfficeCLI executable required')
    def test_native_matrix_insertion_and_cell_mutation_detection(self):
        ir = deck([{'id': 'matrix', 'component': 'formula', 'text': 'A='+A}])
        layout = self.compile_ok(ir)
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            write_json(base/'layout.json', layout)
            pptx = base/'matrix.pptx'
            render(base/'layout.json', pptx)
            self.assertFalse([i for i in verify(pptx, layout) if i['severity'] == 'FAIL'])
            with zipfile.ZipFile(pptx) as archive:
                parts = {name: archive.read(name) for name in archive.namelist()}
            root = ET.fromstring(parts['ppt/slides/slide1.xml'])
            matrix = root.find('.//m:m', MATH_NS)
            self.assertEqual(len(matrix.findall('m:mr', MATH_NS)), 4)
            self.assertEqual(sum(len(r.findall('m:e', MATH_NS)) for r in matrix.findall('m:mr', MATH_NS)), 16)
            matrix.find('m:mr/m:e/m:r/m:t', MATH_NS).text = '99'
            parts['ppt/slides/slide1.xml'] = ET.tostring(root)
            with zipfile.ZipFile(pptx, 'w') as archive:
                for name, data in parts.items(): archive.writestr(name, data)
            self.assertIn('FORMULA_CONTENT_MISMATCH', [i['rule'] for i in verify(pptx, layout)])


if __name__ == '__main__':
    unittest.main()
