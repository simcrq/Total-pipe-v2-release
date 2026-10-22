"""Formula capacity: a page tells the author when it cannot hold the equation, before it ships.

The delivered test deck put a 520 px equation in a 408 px slot and the writer shrank it to about
13 pt, below the 18 pt floor, because the layout had no other answer. The budgets here are the
alternative: the column widens to the equation's measured width, the equation is anchored to the
sentence it explains, and a page that still does not fit fails with the numbers and the instruction
to split instead of trimming the prose.
"""
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from deck_compiler.capacity import FORMULA_GAP, FORMULA_MAX_PER_SLIDE
from deck_compiler.ir import validate
from deck_compiler.layout import compile_deck

from test_deck_compiler import ROOT, fixture


def formulas_deck(blocks, archetype='three-conclusions'):
    ir = fixture()
    slide = ir['slides'][1]
    slide['composition'] = {'archetype': archetype, 'blocks': blocks, 'figure_refs': []}
    slide['semantic']['caveats'] = []
    return {**ir, 'slides': [slide]}


def figure_deck(base, blocks):
    """A one-figure page: the only family that stacks blocks in a column."""
    Image.new('RGB', (300, 230), (40, 90, 120)).save(base/'panel.png')
    ir = fixture()
    ir['assets'] = {'panel': {'path': 'panel.png', 'source_figure': '2b'}}
    slide = ir['slides'][0]
    slide['composition'] = {
        'archetype': 'figure-parameters', 'blocks': blocks,
        'figure_refs': [{'asset_id': 'panel', 'source_figure': '2b', 'panel_count': 1,
                         'caption': 'Fig. 2b · Fit against power.', 'alt': 'fit panel'}]}
    return {**ir, 'slides': [slide]}


def rules(issues, severity='FAIL'):
    return [item['rule'] for item in issues if item['severity'] == severity]


class FormulaBudgetTests(unittest.TestCase):
    def test_a_page_holds_two_equations_and_reports_the_third(self):
        blocks = [{'id': f'f{k}', 'component': 'formula', 'text': 'x = %d' % k} for k in range(1, 4)]
        blocks.append({'id': 'c1', 'component': 'conclusion', 'text': '一条说明文字。'})
        self.assertIn('FORMULA_BUDGET', rules(validate(formulas_deck(blocks))))
        self.assertLessEqual(FORMULA_MAX_PER_SLIDE, 2)

    def test_an_unlabelled_equation_sits_under_the_block_it_explains(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            ir = figure_deck(base, [
                {'id': 'c1', 'component': 'conclusion', 'text': '拟合得到幂律指数。'},
                {'id': 'f1', 'component': 'formula', 'text': r'I_{ph}\propto P^{\alpha}'},
                {'id': 'c2', 'component': 'conclusion', 'text': '另一条结论。'}])
            layout, issues = compile_deck(ir, base)
        self.assertEqual([i for i in issues if i['severity'] == 'FAIL'], [])
        elements = {e['id']: e for e in layout['slides'][0]['elements']}
        anchor, equation = elements['c1'], elements['f1']
        self.assertGreaterEqual(equation['bbox'][0], anchor['bbox'][0])
        self.assertLessEqual(equation['bbox'][0] + equation['bbox'][2],
                             anchor['bbox'][0] + anchor['bbox'][2] + .5,
                             'the equation stays inside its anchor column')
        self.assertGreaterEqual(equation['bbox'][1],
                                anchor['bbox'][1] + anchor['bbox'][3] + FORMULA_GAP - 1,
                                'the equation starts below the text it explains')
        self.assertGreater(elements['c2']['bbox'][1], equation['bbox'][1],
                           'the peer conclusion keeps its own row below the group')

    def test_an_over_wide_equation_is_a_capacity_failure_with_a_way_out(self):
        ir = formulas_deck([
            {'id': 'c1', 'component': 'conclusion', 'text': '读者复算与作者报告的差异。'},
            {'id': 'f1', 'component': 'formula',
             'text': r'20\,\text{log}_{10}(2.04\times10^{4})\approx86.2 + 12 + 33 + 44 + 55 + 66'}])
        layout, issues = compile_deck(ir, ROOT)
        capacity = [i for i in issues if i['rule'] == 'FORMULA_CAPACITY']
        self.assertTrue(capacity)
        self.assertEqual(capacity[0]['source'].get('suggested_fix'),
                         'widen_text_column_or_split_slide')
        self.assertNotIn('SPLIT_REQUIRED', rules(issues))

    def test_an_equation_only_page_is_a_review_not_a_failure(self):
        ir = formulas_deck([{'id': 'f1', 'component': 'formula', 'text': r'E = mc^2'}])
        layout, issues = compile_deck(ir, ROOT)
        self.assertIsNotNone(layout, 'a REVIEW must not stop the compiler')
        self.assertIn('FORMULA_TEXT_FLOOR', rules(issues, 'REVIEW'))
        self.assertEqual([i for i in issues if i['severity'] == 'FAIL'], [])

    def test_an_explicit_anchor_must_name_text_on_the_same_slide(self):
        ir = formulas_deck([
            {'id': 'c1', 'component': 'conclusion', 'text': '一条说明。'},
            {'id': 'f1', 'component': 'formula', 'text': 'x = 1', 'anchor': 'missing'}])
        self.assertIn('FORMULA_ANCHOR_INVALID', rules(validate(ir)))
        ir = formulas_deck([
            {'id': 'f0', 'component': 'formula', 'text': 'y = 2'},
            {'id': 'f1', 'component': 'formula', 'text': 'x = 1', 'anchor': 'f0'}])
        self.assertIn('FORMULA_ANCHOR_INVALID', rules(validate(ir)))


if __name__ == '__main__':
    unittest.main()
