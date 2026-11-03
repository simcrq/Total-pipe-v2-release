"""The design layer may ask for a cover: the one page that carries no content blocks."""
import json
from pathlib import Path
import unittest

from deck_compiler.design import validate_design
from deck_compiler.layout import compile_deck

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT/'examples/research.deck_ir.json'
DESIGN = {'style': 'research-seminar', 'title_treatment': 'thin-rule', 'density': 'balanced',
          'figure_treatment': 'unframed', 'decoration_policy': 'minimal'}

STORY = {'story': [{'title': '条件', 'answer': 'Conditions are fixed.', 'key_points': [],
                    'evidence': ['EV1']}], 'ending': {}}
EVIDENCE = {'EV1': 'The conditions were fixed.'}


def cover_page(**overrides):
    page = {'id': 'P1', 'role': 'setup', 'claim': '这场报告讲什么。', 'form': 'cover',
            'anchor': {'kind': 'none', 'why': '开场页没有锚点'}, 'rationale': '开场页只需要标题与一句定位。',
            'items': []}
    page.update(overrides)
    return page


def deck(**overrides):
    value = json.loads(EXAMPLE.read_text(encoding='utf-8'))
    value['presentation'] = {'academic_design': dict(DESIGN), 'visual_style': {'pack': 'academic'}}
    value['slides'] = value['slides'][:1]
    value['slides'][0]['composition'].update(archetype='cover', blocks=[], figure_refs=[])
    value['slides'][0]['semantic']['caveats'] = []
    value['slides'][0].update(overrides)
    return value


class CoverDesignTests(unittest.TestCase):
    def test_a_cover_may_be_empty(self):
        design = {'pages': [cover_page(),
                            {'id': 'P2', 'role': 'setup', 'claim': '条件固定。', 'form': 'text-stack',
                             'anchor': {'kind': 'none', 'why': '一句陈述'}, 'rationale': '一句陈述。',
                             'items': [{'id': 'a', 'text': 'Conditions are fixed.',
                                        'source': 'S1.answer', 'evidence': ['EV1']}]}]}
        self.assertEqual(validate_design(design, STORY, EVIDENCE), [])

    def test_only_a_cover_may_be_empty(self):
        design = {'pages': [cover_page(form='text-stack')]}
        self.assertIn('only a cover may be empty', ' '.join(validate_design(design, STORY, EVIDENCE)))


class CoverRenderTests(unittest.TestCase):
    def compile(self, value):
        layout, issues = compile_deck(value, EXAMPLE.parent)
        self.assertFalse([i for i in issues if i['severity'] == 'FAIL'], issues)
        return layout

    def test_the_cover_has_title_takeaway_and_no_page_furniture(self):
        layout = self.compile(deck())
        elements = {e['id']: e for e in layout['slides'][0]['elements']}
        self.assertIn('title', elements)
        self.assertIn('takeaway', elements)
        self.assertIn('cover:rule', elements)
        self.assertNotIn('page:number', elements)
        self.assertNotIn('page:rule', elements)
        self.assertNotIn('caveats', elements)
        self.assertIn('cover', [a['action'] for a in layout['slides'][0]['adaptation_log']])

    def test_a_cover_may_open_a_deck_with_a_contents_page(self):
        value = deck()
        value['slides'].append(json.loads(EXAMPLE.read_text(encoding='utf-8'))['slides'][1])
        value['presentation']['agenda'] = {'title': '目录'}
        value['slides'][0]['presentation']['section'] = '背景'
        value['slides'][1]['presentation']['section'] = '边界'
        layout = self.compile(value)
        self.assertEqual([s['id'] for s in layout['slides']], ['evidence', 'agenda', 'limits'])
        cover = {e['id'] for e in layout['slides'][0]['elements']}
        self.assertNotIn('page:number', cover)                       # the page before page 1
        agenda = {e['id']: e for e in layout['slides'][1]['elements']}
        self.assertEqual(agenda['page:number']['text'], '2')


if __name__ == '__main__':
    unittest.main()
