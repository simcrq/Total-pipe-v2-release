"""A page design must account for every Story item and only cite evidence that exists."""
import copy
import unittest

from deck_compiler.design import FORMS, capabilities, summary, validate_design

STORY = {
    'story': [
        {'title': '条件', 'answer': '合成基准', 'key_points': ['N=512', '100 次试验'],
         'evidence': ['EV1', 'EV2']},
        {'title': '结果', 'answer': '误差 1.2×10^-3', 'key_points': ['迭代少 1.8 倍'],
         'evidence': ['EV3']},
    ],
    'ending': {'takeaway': '合成基准上少 1.8 倍迭代', 'limitation': '仅合成信号'},
}
EVIDENCE = {
    'EV1': 'The benchmark used N = 512.',
    'EV2': 'The method was evaluated on 100 random trials.',
    'EV3': 'The error was 1.2 × 10^-3 and iterations were 1.8 times fewer.',
    'EV4': 'Only synthetic signals were tested.',
}
DESIGN = {
    'schema_version': '1.0', 'deck_id': 'd',
    'setting': {'audience': '同一课题组的同行', 'occasion': 'group-meeting',
                'reading': 'spoken'},
    'pages': [
        {'id': 'P1', 'role': 'setup', 'claim': '基准为 N=512、100 次试验。',
         'takeaway_from': 'S1.answer',
         'items': [{'id': 'a', 'text': 'N=512', 'source': 'S1.key_points[0]', 'evidence': ['EV1']},
                   {'id': 'b', 'text': '100 次试验', 'source': 'S1.key_points[1]', 'evidence': ['EV2']}],
         'form': 'spec-table', 'anchor': {'kind': 'table', 'why': '并列条件'},
         'rationale': '条件并列，表格最省版面。'},
        {'id': 'P2', 'role': 'result', 'claim': '误差 1.2×10^-3，迭代少 1.8 倍。',
         'takeaway_from': 'S2.answer',
         'items': [{'id': 'c', 'text': '迭代少 1.8 倍', 'source': 'S2.key_points[0]', 'evidence': ['EV3']}],
         'form': 'text-stack', 'anchor': {'kind': 'none', 'why': '一句结果'},
         'rationale': '结果只有一句，不需要结构。'},
        {'id': 'P3', 'role': 'limitation', 'claim': '仅合成信号。',
         'takeaway_from': 'ending.takeaway',
         'items': [{'id': 'd', 'text': '仅合成信号', 'source': 'ending.limitation',
                    'evidence': ['EV4']}],
         'form': 'closing-statement', 'anchor': {'kind': 'none', 'why': '边界一句'},
         'rationale': '收尾页只留边界。'},
    ],
}


class PageDesignTests(unittest.TestCase):
    def test_complete_design_passes(self):
        self.assertEqual(validate_design(copy.deepcopy(DESIGN), STORY, EVIDENCE), [])

    def test_dropped_story_item_is_reported(self):
        design = copy.deepcopy(DESIGN)
        design['pages'][0]['items'].pop()
        problems = ' '.join(validate_design(design, STORY, EVIDENCE))
        self.assertIn('unused Story item S1.key_points[1]', problems)

    def test_duplicate_use_is_reported(self):
        design = copy.deepcopy(DESIGN)
        design['pages'][1]['items'].append(dict(design['pages'][0]['items'][0], id='dup'))
        problems = ' '.join(validate_design(design, STORY, EVIDENCE))
        self.assertIn('appears on 2 pages', problems)

    def test_one_unit_may_be_elaborated_by_several_items_on_its_page(self):
        design = copy.deepcopy(DESIGN)
        page = design['pages'][1]
        page['items'].append({'id': 'second', 'text': '第二个切面', 'source': 'S2.key_points[0]',
                              'evidence': ['EV3']})
        self.assertEqual(validate_design(design, STORY, EVIDENCE), [])

    def test_latex_escaped_evidence_still_matches_its_numbers(self):
        design = copy.deepcopy(DESIGN)
        design['pages'][1]['items'][0]['text'] = '良率 95.8%'
        latex = dict(EVIDENCE, EV3='The error was 1.2 × 10^-3, iterations 1.8 times fewer, '
                                   'yield $95.8\\%$ over 100 trials.')
        self.assertEqual(validate_design(design, STORY, latex), [])

    def test_unknown_evidence_and_ungrounded_number(self):
        design = copy.deepcopy(DESIGN)
        design['pages'][1]['items'][0]['text'] = '迭代少 2.4 倍'
        problems = ' '.join(validate_design(design, STORY, EVIDENCE))
        self.assertIn('number 2.4 is not in its cited evidence', problems)
        design = copy.deepcopy(DESIGN)
        design['pages'][1]['items'][0]['evidence'] = ['EV99']
        self.assertIn('unknown evidence', ' '.join(validate_design(design, STORY, EVIDENCE)))

    def test_form_and_anchor_must_agree(self):
        design = copy.deepcopy(DESIGN)
        design['pages'][0]['anchor'] = {'kind': 'figure', 'why': 'x'}
        self.assertIn('carries a table anchor', ' '.join(validate_design(design, STORY, EVIDENCE)))
        design = copy.deepcopy(DESIGN)
        design['pages'][0]['form'] = 'poster-grid'
        self.assertIn('unknown form', ' '.join(validate_design(design, STORY, EVIDENCE)))

    def test_formula_item_is_exempt_from_number_matching(self):
        design = copy.deepcopy(DESIGN)
        design['pages'][1]['items'].append(
            {'id': 'eq', 'text': 'S_{1/L}(z)', 'source': 'EV3', 'evidence': ['EV3'], 'kind': 'formula'})
        self.assertEqual(validate_design(design, STORY, EVIDENCE), [])

    def test_occasion_is_a_key_and_the_brief_suggests_one(self):
        from deck_compiler.design import OCCASIONS, default_occasion
        self.assertEqual(set(OCCASIONS), {'group-meeting', 'research-report', 'research-sharing',
                                          'lecture', 'commercial'})
        self.assertEqual(default_occasion('paper_presentation', '组会研究报告'), 'group-meeting')
        self.assertEqual(default_occasion('seminar', '文献分享'), 'research-sharing')
        self.assertEqual(default_occasion('lecture', ''), 'lecture')
        self.assertEqual(default_occasion('pitch', ''), 'commercial')
        self.assertEqual(default_occasion('conference', ''), 'research-report')
        design = copy.deepcopy(DESIGN)
        design['setting']['occasion'] = '组会'
        problems = ' '.join(validate_design(design, STORY, EVIDENCE))
        self.assertIn('setting.occasion must be one of', problems)

    def test_a_page_can_be_described_in_words_instead_of_named_as_a_form(self):
        design = copy.deepcopy(DESIGN)
        page = design['pages'][0]
        page['shape'] = '三列读数，每列一个数字加一行标签，上方一条细线'
        page['marks'] = ['N=512']
        page.pop('form')
        self.assertEqual(validate_design(design, STORY, EVIDENCE), [])
        page['marks'] = ['N=999']
        problems = ' '.join(validate_design(design, STORY, EVIDENCE))
        self.assertIn('mark', problems)

    def test_capabilities_and_summary(self):
        published = capabilities()
        self.assertIn('figure-reading', published['forms'])
        self.assertIn('problem-route-result', published['forms'])
        self.assertEqual(published['forms']['problem-route-result']['anchor'], 'graphic')
        self.assertIn('figure', published['anchors'])
        self.assertIn('art_direction', published)
        self.assertIn('panel-group', published['art_direction']['devices'])
        brief = summary(DESIGN)
        self.assertEqual([page['id'] for page in brief['pages']], ['P1', 'P2', 'P3'])
        self.assertEqual(brief['pages'][0]['form'], 'spec-table')
        self.assertEqual(brief['pages'][0]['anchor'], 'table')
        self.assertIn('spec-table', FORMS)


if __name__ == '__main__':
    unittest.main()
