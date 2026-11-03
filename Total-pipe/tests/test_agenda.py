"""A contents page is generated from the sections the deck already declares, not from new content."""
import json
from pathlib import Path
import unittest

from deck_compiler.ir import validate
from deck_compiler.layout import agenda_sections, compile_deck

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT/'examples/research.deck_ir.json'
DESIGN = {'style': 'research-seminar', 'title_treatment': 'thin-rule', 'density': 'balanced',
          'figure_treatment': 'unframed', 'decoration_policy': 'minimal',
          'header_variant': 'compact', 'type_scale': 'standard'}


def fixture(sections=('条件与边界', '结果与解释'), agenda=True, numbers=True):
    ir = json.loads(EXAMPLE.read_text(encoding='utf-8'))
    ir['presentation'] = {'academic_design': dict(DESIGN),
                          'visual_style': {'pack': 'academic'},
                          'page_numbers': numbers}
    if agenda:
        ir['presentation']['agenda'] = {'title': '目录'}
    for slide, label in zip(ir['slides'], sections):
        slide['presentation']['section'] = label
    return ir


class AgendaSectionTests(unittest.TestCase):
    def compile(self, ir):
        layout, issues = compile_deck(ir, EXAMPLE.parent)
        self.assertFalse([i for i in issues if i['severity'] == 'FAIL'], issues)
        return layout, issues

    def test_sections_follow_the_slide_order(self):
        ir = fixture()
        self.assertEqual(agenda_sections(ir), [('条件与边界', 1), ('结果与解释', 2)])
        ir['slides'][1]['presentation'].pop('section')          # a section runs until the next label
        self.assertEqual(agenda_sections(ir), [('条件与边界', 1)])

    def test_the_contents_page_is_inserted_after_the_opening_page(self):
        layout, _ = self.compile(fixture())
        self.assertEqual([s['id'] for s in layout['slides']],
                         ['evidence', 'agenda', 'limits'])
        numbers = [next(e['text'] for e in s['elements'] if e['id'] == 'page:number')
                   for s in layout['slides']]
        self.assertEqual(numbers, ['1', '2', '3'])

    def test_rows_quote_the_declared_sections_and_their_starting_page(self):
        layout, _ = self.compile(fixture())
        agenda = layout['slides'][1]
        rows = [e for e in agenda['elements'] if e['id'].startswith('agenda:row:')]
        pages = [e['text'] for e in agenda['elements'] if e['id'].startswith('agenda:page:')]
        self.assertEqual(len(rows), 2)
        self.assertTrue(rows[0]['text'].startswith('01'))
        self.assertIn('条件与边界', rows[0]['text'])
        self.assertEqual(pages, ['1', '3'])      # the second section starts on the third page
        leaders = [e for e in agenda['elements'] if e['id'].startswith('agenda:leader:')]
        self.assertTrue(all('·' in e['text'] for e in leaders))

    def test_the_contents_page_carries_the_same_furniture(self):
        layout, _ = self.compile(fixture())
        agenda = layout['slides'][1]
        self.assertIn('page:rule', {e['id'] for e in agenda['elements']})
        self.assertEqual(next(e['text'] for e in agenda['elements'] if e['id'] == 'page:number'), '2')

    def test_no_agenda_without_two_sections(self):
        ir = fixture()
        ir['slides'][1]['presentation'].pop('section')
        layout, issues = self.compile(ir)
        self.assertEqual(len(layout['slides']), 2)
        self.assertIn('AGENDA_EMPTY', [i['rule'] for i in issues])

    def test_page_numbers_can_be_off_while_the_contents_page_stays(self):
        layout, _ = self.compile(fixture(numbers=False))
        self.assertEqual(len(layout['slides']), 3)
        self.assertFalse([e for s in layout['slides'] for e in s['elements']
                          if e['id'] == 'page:number'])

    def test_invalid_section_labels_are_rejected(self):
        ir = fixture()
        ir['slides'][0]['presentation']['section'] = '章节' * 20
        self.assertIn('SECTION_INVALID', [i['rule'] for i in validate(ir)])
        ir = fixture()
        ir['presentation']['agenda'] = {'title': '目' * 40}
        self.assertIn('AGENDA_INVALID', [i['rule'] for i in validate(ir)])
        ir = fixture()
        ir['presentation']['agenda'] = {'heading': '目录'}
        self.assertIn('AGENDA_INVALID', [i['rule'] for i in validate(ir)])


if __name__ == '__main__':
    unittest.main()
