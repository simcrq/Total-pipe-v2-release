"""The design layer names devices; the compiler writes them into the IR and checks they landed."""
import json
from pathlib import Path
import unittest

from deck_compiler import art_direction as art
from deck_compiler.design import validate_design
from deck_compiler.layout import compile_deck

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT/'examples/research.deck_ir.json'
ACADEMIC = {'style': 'research-seminar', 'title_treatment': 'thin-rule', 'density': 'balanced',
            'figure_treatment': 'unframed', 'decoration_policy': 'minimal'}


def ir():
    deck = json.loads(EXAMPLE.read_text(encoding='utf-8'))
    deck['presentation'] = {'academic_design': dict(ACADEMIC), 'visual_style': {'pack': 'academic'}}
    return deck


def design(first=None, second=None):
    """A two-page design matching the two-page example deck."""
    pages = [
        {'id': 'P1', 'role': 'setup', 'claim': 'Conditions are fixed.', 'form': 'text-stack',
         'anchor': {'kind': 'none', 'why': '两句陈述'}, 'rationale': '没有可用的图或表。',
         'items': [{'id': 'a', 'text': 'A measured response changes under the condition.',
                    'source': 'S1.answer', 'evidence': ['EV1']}],
         'devices': {'emphasis': ['control'], 'takeaway-frame': 'fill'}},
        {'id': 'P2', 'role': 'limitation', 'claim': '边界一句。', 'form': 'text-stack',
         'anchor': {'kind': 'none', 'why': '边界一句'}, 'rationale': '收尾只留边界。',
         'items': [{'id': 'b', 'text': 'Measurements cover one material family.',
                    'source': 'S2.answer', 'evidence': ['EV2']}],
         'devices': {'highlight': ['material']}},
    ]
    pages[0].update(first or {})
    pages[1].update(second or {})
    return {'setting': {'audience': '同行', 'occasion': 'group-meeting', 'reading': 'spoken'},
            'pages': pages}


STORY = {'story': [
    {'title': '条件', 'answer': '', 'key_points': [], 'evidence': []},
    {'title': '边界', 'answer': '', 'key_points': [], 'evidence': []}],
    'ending': {}}
EVIDENCE = {'EV1': 'A measured response changes under the condition.',
            'EV2': 'Measurements cover one material family.'}


class DeviceCatalogueTests(unittest.TestCase):
    def test_the_inventory_covers_both_scopes(self):
        published = art.capabilities()['devices']
        self.assertEqual(published['emphasis']['scope'], art.PAGE)
        self.assertEqual(published['agenda']['scope'], art.DECK)
        for spec in published.values():
            self.assertTrue(spec['fallback'])
            self.assertTrue(spec['ir'])

    def test_shape_errors_never_judge_the_page(self):
        self.assertIn('2-3 labels', ' '.join(art.validate({'panel-group': ['one']}, art.PAGE)))
        self.assertIn('at most 8 characters',
                      ' '.join(art.validate({'panel-group': ['一二三四五六七八九', 'b']}, art.PAGE)))
        self.assertIn('not a page device', ' '.join(art.validate({'agenda': True}, art.PAGE)))
        self.assertIn('not a deck device', ' '.join(art.validate({'emphasis': ['x']}, art.DECK)))
        self.assertEqual(art.validate({'emphasis': ['W']}, art.PAGE), [])
        self.assertEqual(art.validate({'sections': [{'page': 'P1', 'label': '背景'},
                                                    {'page': 'P2', 'label': '结果'}]}, art.DECK), [])

    def test_the_design_layer_validates_devices_with_the_page(self):
        plan = design()
        # the example deck's own texts are what the devices refer to
        plan['pages'][0]['devices'] = {'emphasis': ['control']}
        self.assertEqual(validate_design(plan, STORY, EVIDENCE), [])
        broken = design(first={'devices': {'emphasis': 'not-a-list'}})
        self.assertIn('1-3 phrases', ' '.join(validate_design(broken, STORY, EVIDENCE)))
        broken = design(first={'devices': {'spotlight': ['x']}})
        self.assertIn('not a page device', ' '.join(validate_design(broken, STORY, EVIDENCE)))


class DeviceApplicationTests(unittest.TestCase):
    def test_text_marks_frames_and_deck_devices_are_written(self):
        deck, plan = ir(), design()
        plan['devices'] = {'page-numbers': True, 'footer': '出处 · 组会',
                           'sections': [{'page': 'P1', 'label': '条件'},
                                        {'page': 'P2', 'label': '边界'}],
                           'agenda': {'title': '目录'}}
        applied, notes = art.apply(deck, plan)
        self.assertEqual(notes, [])
        slide = applied['slides'][0]
        self.assertIn('**control**', slide['semantic']['takeaway'])
        self.assertEqual(slide['presentation']['takeaway_frame']['fill'], '#F8FAFC')
        self.assertIn('==material==', applied['slides'][1]['composition']['blocks'][0]['text'])
        self.assertEqual(applied['presentation']['footer'], '出处 · 组会')
        self.assertEqual(applied['presentation']['agenda'], {'title': '目录'})
        self.assertEqual([s['presentation'].get('section') for s in applied['slides']],
                         ['条件', '边界'])
        self.assertEqual(art.check(applied, plan), [])

    def test_marking_is_idempotent(self):
        deck, plan = ir(), design()
        once, _ = art.apply(deck, plan)
        twice, _ = art.apply(once, plan)
        self.assertEqual(twice['slides'][0]['semantic']['takeaway'],
                         once['slides'][0]['semantic']['takeaway'])
        self.assertNotIn('****', twice['slides'][0]['semantic']['takeaway'])
        self.assertNotIn('====', twice['slides'][1]['composition']['blocks'][0]['text'])

    def test_a_phrase_that_is_not_on_the_page_is_reported_not_invented(self):
        applied, notes = art.apply(ir(), design(first={'devices': {'emphasis': ['never said here']}}))
        self.assertIn('not in this page', ' '.join(notes))
        self.assertTrue(art.check(applied, design(first={'devices': {'emphasis': ['never said here']}})))

    def test_caption_provenance_lands_on_the_figure(self):
        deck = ir()
        deck['slides'][0]['composition']['figure_refs'] = [{'asset_id': 'demo3', 'caption': 'Fig. 3 | x'}]
        plan = design(first={'devices': {'caption-source': [{'figure': 0, 'label': 'Xie et al.'}]}})
        applied, _ = art.apply(deck, plan)
        self.assertEqual(applied['slides'][0]['composition']['figure_refs'][0]['source_label'],
                         'Xie et al.')
        self.assertEqual(art.check(applied, plan), [])

    def test_a_caption_policy_labels_every_paper_figure(self):
        deck = ir()
        deck['slides'][0]['composition']['figure_refs'] = [
            {'asset_id': 'demo3', 'caption': 'Fig. 3 | x', 'source_figure': '3f'}]
        plan = design(first={'devices': {'caption-source': True}})
        applied, _ = art.apply(deck, plan)
        self.assertEqual(applied['slides'][0]['composition']['figure_refs'][0]['source_label'],
                         '原文 Fig. 3f')
        self.assertEqual(art.check(applied, plan), [])

    def test_a_panel_group_must_be_built_by_the_author(self):
        plan = design(first={'devices': {'panel-group': ['读法', '边界']}})
        applied, notes = art.apply(ir(), plan)
        self.assertIn('panel-group', ' '.join(notes))
        missing = art.check(applied, plan)
        self.assertEqual(missing[0][0], 'P1')
        self.assertIn('panel-group', missing[0][1])

    def test_nothing_is_applied_without_a_plan(self):
        self.assertEqual(art.apply(ir(), None)[1], [])
        self.assertEqual(art.check(ir(), None), [])


class DeviceCompileTests(unittest.TestCase):
    def test_devices_land_on_a_real_page(self):
        plan = design()
        plan['devices'] = {'page-numbers': True, 'footer': '出处 · 组会',
                           'sections': [{'page': 'P1', 'label': '条件'},
                                        {'page': 'P2', 'label': '边界'}],
                           'agenda': {'title': '目录'}}
        applied, notes = art.apply(ir(), plan)
        self.assertEqual(notes, [])
        layout, issues = compile_deck(applied, EXAMPLE.parent)
        self.assertFalse([i for i in issues if i['severity'] == 'FAIL'], issues)
        self.assertEqual([s['id'] for s in layout['slides']], ['evidence', 'agenda', 'limits'])
        takeaway = next(e for e in layout['slides'][0]['elements'] if e['id'] == 'takeaway')
        self.assertEqual(takeaway['inline_layout']['marks'], ['emphasis'])


if __name__ == '__main__':
    unittest.main()
