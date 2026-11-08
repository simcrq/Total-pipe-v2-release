"""Recipe pilot: native lists, inline math and no card surfaces."""
import json
import tempfile
import unittest
from pathlib import Path

from pptx import Presentation

from agent.page_recipes import RECIPES, compose_deck
from agent.page_scene_qa import check_file, expression_report, render_spec


def page_specs():
    return [
        {'id': 'R1', 'recipe': 'cover', 'section': '01 · TEST',
         'title': '让 $V_{ds}$ 成为第三个控制端',
         'take': '同一器件覆盖 $10^8$ 开关比。',
         'meta': 'WSe₂｜两管拓扑',
         'stats': [('13', '种功能'), ('7', '数字逻辑'), ('6', '模拟功能')]},
        {'id': 'R2', 'recipe': 'contrast', 'section': '02 · TEST',
         'title': '数字要对称，模拟要连续',
         'take': '两种注入条件必须在同一沟道内协调。',
         'left': {'head': 'DIGITAL', 'items': [{'text': '极性明确'}, {'text': '对称注入'}]},
         'right': {'head': 'ANALOG', 'items': [{'text': '非对称注入'}, {'text': '连续调节'}]},
         'key': '关键：同一器件内协调两端注入'},
        {'id': 'R3', 'recipe': 'figure_readout', 'section': '03 · TEST',
         'title': '读出图中的源漏关系', 'take': '先认源漏，再看双空气隙。',
         'figure': {'path': '', 'caption': 'Fig. 1a'},
         'items': [{'text': '源在上、漏在下'}, {'text': '双空气隙夹住沟道'}]},
        {'id': 'R4', 'recipe': 'metrics', 'section': '04 · TEST',
         'title': 'on/off 超过 $10^8$', 'take': '同一器件可逆编程。',
         'figures': [], 'caption': '',
         'items': [{'text': 'n/p on/off > $10^8$'}, {'text': '$I_{on}$ 13 μA/μm'}],
         'condition': '$V_{ds}=\\pm2$ V'},
        {'id': 'R5', 'recipe': 'table_compare', 'section': '05 · TEST',
         'title': '七 + 六 种功能', 'take': '同一拓扑覆盖数字与模拟。',
         'table': {'rows': [['维度', '本工作'], ['数字', '七种'], ['模拟', '六种']]},
         'big': '13', 'big_label': '种功能',
         'items': [{'text': '本工作：七 + 六'}],
         'source': '论文官方补充材料（DOI 公开获取）'},
        {'id': 'R6', 'recipe': 'closing', 'section': '06 · TEST',
         'title': '一个结构，十三种功能',
         'take': '结构非对称 → $V_{ds}$ 控制 → 两管拓扑。',
         'items': [{'text': '结构非对称'}, {'text': '$V_{ds}$ 控制', 'level': 1}],
         'stats': '七数字 ｜ 六模拟', 'fixed': '同一版图'},
    ]


class RecipePilotTests(unittest.TestCase):
    def test_recipe_pilot_has_native_moves_no_cards_and_inline_math(self):
        scene = compose_deck(page_specs())
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'page_scene.json'
            path.write_text(json.dumps(scene, ensure_ascii=False), encoding='utf-8')
            # The fixture uses two empty figures; validate without them.
            scene['pages'][0]['objects'].append(
                {'id': 'demo_path', 'type': 'path', 'box': [0.72, 6.3, 2.0, .4],
                 'view_box': [0, 0, 100, 30], 'fill': 'none', 'stroke': '#0B6E99',
                 'd': 'M 0 15 L 50 15 L 50 5 L 100 5'})
            scene['pages'][2]['objects'] = [o for o in scene['pages'][2]['objects']
                                            if o.get('type') != 'image']
            scene['pages'][3]['objects'] = [o for o in scene['pages'][3]['objects']
                                            if o.get('type') != 'image']
            path.write_text(json.dumps(scene, ensure_ascii=False), encoding='utf-8')
            report = check_file(path)
            self.assertEqual(report['status'], 'PASS', report['errors'])
            summary = report['expression']['summary']
            self.assertEqual(summary['text_only_pages'], 0)
            self.assertEqual(summary['card_area'], 0)
            self.assertGreaterEqual(summary['inline_math'], 3)
            self.assertGreaterEqual(len(summary['list_styles']), 2)
            self.assertEqual(summary['status'], 'PASS')

    def test_inline_math_renders_as_native_omml(self):
        scene = compose_deck([page_specs()[0]])
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'page_scene.json'
            path.write_text(json.dumps(scene, ensure_ascii=False), encoding='utf-8')
            out = render_spec(scene, path, Path(temp)/'out.pptx')
            slide_xml = Presentation(str(out)).slides[0]._element.xml
            self.assertIn('m:oMath', slide_xml)
            self.assertIn('mc:AlternateContent', slide_xml)

    def test_expression_report_flags_large_filled_card(self):
        scene = compose_deck([page_specs()[1]])
        scene['pages'][0]['objects'].append(
            {'id': 'card', 'type': 'shape', 'box': [0.7, 2.2, 8.0, 3.0],
             'shape': 'rounded', 'fill': '#DDE7F2'})
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'page_scene.json'
            path.write_text(json.dumps(scene, ensure_ascii=False), encoding='utf-8')
            summary = expression_report(scene, path)['summary']
            self.assertGreater(summary['card_area'], 0)
            self.assertEqual(summary['status'], 'REVIEW')

    def test_all_recipe_names_are_exposed(self):
        self.assertEqual(set(RECIPES), {'cover', 'contrast', 'figure_readout',
                                        'metrics', 'table_compare', 'closing'})


if __name__ == '__main__':
    unittest.main()
