"""Authored emphasis is a measured run, and a designed page carries a footer and a page number."""
import copy
import json
from pathlib import Path
import unittest

from deck_compiler.fonts import load_font_file, resolve_theme_fonts
from deck_compiler.inline_text import paragraphs, text_body
from deck_compiler.layout import compile_deck
from totalpipe_layout.inline_math import (has_markup, measure_inline, parse_inline, strip_markup)

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT/'examples/research.deck_ir.json'
DESIGN = {'style': 'research-seminar', 'title_treatment': 'thin-rule', 'density': 'balanced',
          'figure_treatment': 'unframed', 'decoration_policy': 'minimal',
          'header_variant': 'compact', 'type_scale': 'standard'}


def fixture(design=True):
    ir = json.loads(EXAMPLE.read_text(encoding='utf-8'))
    if design:
        ir['presentation'] = {'academic_design': copy.deepcopy(DESIGN),
                              'visual_style': {'pack': 'academic'}}
    return ir


def marked(ir, block_id, phrase):
    """Wrap one phrase of one block, exactly as an author would type it."""
    for slide in ir['slides']:
        for block in slide['composition']['blocks']:
            if block['id'] == block_id:
                block['text'] = block['text'].replace(phrase, '**'+phrase+'**', 1)
                return block['text']
    raise AssertionError(block_id)


class MarkupParserTests(unittest.TestCase):
    def test_markers_become_spans(self):
        spans = parse_inline('宽度 **W** 决定势垒，符号 ==Φ_B== 例外。')
        self.assertEqual([(s.text, s.mark) for s in spans if s.mark],
                         [('W', 'emphasis'), ('Φ_B', 'highlight')])
        self.assertEqual(''.join(s.text for s in spans), '宽度 W 决定势垒，符号 Φ_B 例外。')

    def test_escaped_markers_stay_literal(self):
        self.assertFalse(has_markup(r'两个星号 \*\* 不是强调'))
        self.assertEqual(strip_markup(r'两个星号 \*\* 不是强调'), '两个星号 ** 不是强调')

    def test_unclosed_marker_stays_literal(self):
        spans = parse_inline('未闭合的 **强调与 a==b')
        self.assertEqual([s.mark for s in spans], [''])
        self.assertIn('**', spans[0].text)

    def test_a_marker_never_spans_a_formula(self):
        spans = parse_inline('**前 $x^2$ 后**')
        self.assertEqual([s.kind for s in spans], ['text', 'formula', 'text'])
        self.assertFalse(any(s.mark for s in spans))

    def test_blank_markers_are_not_emphasis(self):
        self.assertEqual(parse_inline('** 空格 **')[0].mark, '')

    def test_strip_markup_keeps_the_words(self):
        self.assertEqual(strip_markup('**W** 与 ==Φ== 耦合'), 'W 与 Φ 耦合')


class EmphasisMeasurementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        regular, bold, _ = resolve_theme_fonts(fixture(False)['theme'], EXAMPLE.parent,
                                               '完整科学术语正文')
        cls.fonts = (regular, bold)

    def plan(self, source, size=24, strong=True):
        regular, bold = self.fonts
        return measure_inline(source, 900, load_font_file(regular, size), size,
                              strong_font=load_font_file(bold, size) if strong else None)

    def test_bold_advances_are_measured_with_the_bold_face(self):
        source = 'A measured **response** changes the result.'
        regular, _ = self.fonts
        wide = self.plan(source)['lines'][0]['width']
        narrow = self.plan(source, strong=False)['lines'][0]['width']
        plain = measure_inline('A measured response changes the result.', 900,
                               load_font_file(regular, 24), 24)['lines'][0]['width']
        self.assertAlmostEqual(narrow, plain, places=3)
        self.assertGreater(wide, narrow)

    def test_plan_reports_the_marks_that_were_used(self):
        plan = self.plan('**W** 与 ==Φ== 与正文')
        self.assertEqual(plan['marks'], ['emphasis', 'highlight'])
        self.assertEqual(plan['text'], 'W 与 Φ 与正文')

    def test_fragments_keep_their_own_mark(self):
        fragments = self.plan('前 **粗** 后')['lines'][0]['fragments']
        self.assertEqual([f.get('mark', '') for f in fragments], ['', 'emphasis', ''])


class EmphasisXmlTests(unittest.TestCase):
    def contract(self):
        return {'font_size': 24, 'font_family': 'Arial', 'font_weight': 400,
                'vertical_anchor': 'top', 'inset': {'left': 0, 'right': 0, 'top': 0, 'bottom': 0}}

    def plan(self):
        regular, bold, _ = resolve_theme_fonts(fixture(False)['theme'], EXAMPLE.parent, '强调高亮')
        return measure_inline('前 **粗** 与 ==高==', 900, load_font_file(regular, 24), 24,
                              strong_font=load_font_file(bold, 24))

    def test_runs_carry_bold_accent_and_highlight(self):
        xml = text_body(self.plan(), self.contract(), '#142735',
                        styles={'emphasis': '#C2410C', 'highlight': '#FFF1A8'})
        self.assertIn('<a:highlight><a:srgbClr val="FFF1A8" /></a:highlight>', xml)
        self.assertIn('b="1"', xml)
        self.assertIn('val="C2410C"', xml)
        # CT_TextCharacterProperties orders highlight after the fill and before the typefaces.
        start = xml.index('<a:highlight>')
        run = xml[xml.rindex('<a:rPr', 0, start):]
        run = run[:run.index('</a:rPr>')]
        self.assertLess(run.index('<a:solidFill>'), run.index('<a:highlight>'))
        self.assertLess(run.index('<a:highlight>'), run.index('<a:latin'))


class EmphasisLayoutTests(unittest.TestCase):
    def compile(self, ir):
        layout, issues = compile_deck(ir, EXAMPLE.parent)
        self.assertFalse([i for i in issues if i['severity'] == 'FAIL'], issues)
        return layout, issues

    def test_marked_text_is_set_as_runs_and_keeps_its_source(self):
        ir = fixture()
        source = marked(ir, 'scope', 'Measurements')
        self.assertIn('**Measurements**', source)
        layout, _ = self.compile(ir)
        element = next(e for e in layout['slides'][1]['elements'] if e['id'] == 'scope')
        self.assertEqual(element['source_text'], source)         # the IR keeps the markers
        self.assertNotIn('**', element['text'])                  # the page does not
        self.assertEqual(element['inline_layout']['marks'], ['emphasis'])
        self.assertIn('b="1"', element['inline_xml'])
        self.assertIn('inline_emphasis', [a['action'] for a in layout['slides'][1]['adaptation_log']])

    def test_unclosed_marker_is_reported_and_stays_visible(self):
        ir = fixture()
        for block in ir['slides'][0]['composition']['blocks']:
            if block['id'] == 'measurement':
                block['text'] = '**' + block['text']
        layout, issues = self.compile(ir)
        rules = [i['rule'] for i in issues]
        self.assertIn('EMPHASIS_UNCLOSED', rules)
        element = next(e for e in layout['slides'][0]['elements'] if e['id'] == 'measurement')
        self.assertIn('**', element['text'])

    def test_comma_marked_block_stays_plain_so_the_list_does_not_eat_it(self):
        from deck_compiler.text_flow import fallback_list
        block = {'id': 'b', 'component': 'body', 'text': '**第一句**\n第二句'}
        self.assertIs(fallback_list(block), block)

    def test_an_explicit_native_list_keeps_the_words_and_reports_the_mark(self):
        ir = fixture()
        slide = ir['slides'][1]
        block = slide['composition']['blocks'][0]
        slide['composition']['blocks'] = [block]
        block['text'] = ('**Measurements** cover one material family.\n'
                         'The thermal environment may change the outcome.\n'
                         'Independent calibration is required before integration.')
        block['text_flow'] = 'distributed_arrow_list'
        layout, issues = self.compile(ir)
        self.assertIn('EMPHASIS_IN_LIST', [i['rule'] for i in issues])
        element = next(e for e in layout['slides'][1]['elements'] if e['kind'] == 'list')
        self.assertNotIn('**', element['text'])
        self.assertIn('Measurements cover one material family.', element['text'])


class PageFurnitureTests(unittest.TestCase):
    def compile(self, ir):
        layout, issues = compile_deck(ir, EXAMPLE.parent)
        self.assertFalse([i for i in issues if i['severity'] == 'FAIL'], issues)
        return layout

    def furniture(self, layout, slide=0):
        return {e['id']: e for e in layout['slides'][slide]['elements'] if e['id'].startswith('page:')}

    def test_designed_pages_get_a_rule_and_a_continuous_number(self):
        layout = self.compile(fixture())
        first, second = self.furniture(layout, 0), self.furniture(layout, 1)
        self.assertEqual(first['page:rule']['bbox'], [56, 664, 1168, 1])
        self.assertEqual(first['page:number']['text'], '1')
        self.assertEqual(second['page:number']['text'], '2')
        self.assertEqual(first['page:number']['align'], 'right')
        self.assertNotIn('page:footer', first)

    def test_declared_footer_is_set_once_per_page(self):
        ir = fixture()
        ir['presentation']['footer'] = 'NbS2/MoS2 非对称接触 · 组会报告'
        layout = self.compile(ir)
        footer = self.furniture(layout, 0)['page:footer']
        self.assertEqual(footer['text'], 'NbS2/MoS2 非对称接触 · 组会报告')
        self.assertLess(footer['bbox'][0], 56 + 400)

    def test_the_deck_may_turn_the_numbers_off(self):
        ir = fixture()
        ir['presentation']['page_numbers'] = False
        layout = self.compile(ir)
        self.assertEqual(self.furniture(layout, 0), {})

    def test_one_page_may_hide_its_number(self):
        ir = fixture()
        ir['slides'][0]['presentation']['page_number'] = False
        layout = self.compile(ir)
        self.assertNotIn('page:number', self.furniture(layout, 0))
        self.assertIn('page:number', self.furniture(layout, 1))

    def test_a_legacy_page_keeps_no_furniture(self):
        layout = self.compile(fixture(design=False))
        self.assertEqual(self.furniture(layout, 0), {})


if __name__ == '__main__':
    unittest.main()
