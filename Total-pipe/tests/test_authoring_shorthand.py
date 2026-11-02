"""Authoring shorthands: LaTeX display blocks, inline math and simple diagrams."""
import copy
import json
from pathlib import Path
import unittest

from agent import adapters as a

ROOT = Path(__file__).resolve().parents[1]


def research_ir():
    return json.loads((ROOT / 'examples/research.deck_ir.json').read_text(encoding='utf-8'))


class AuthoringShorthandTests(unittest.TestCase):
    def test_latex_block_becomes_a_display_formula(self):
        ir = research_ir()
        slide = ir['slides'][1]
        slide['composition']['blocks'] = [
            {'id': 'eq', 'latex': r'S_{\\lambda}(z)=\\operatorname{sign}(z)\\max(|z|-\\lambda,0)'},
        ]
        a.normalize_authoring_ir(ir)
        block = slide['composition']['blocks'][0]
        self.assertEqual(block['component'], 'formula')
        self.assertEqual(block['text'], r'S_{\\lambda}(z)=\\operatorname{sign}(z)\\max(|z|-\\lambda,0)')
        self.assertNotIn('latex', block)

    def test_dollar_math_enables_inline_math(self):
        ir = research_ir()
        slide = ir['slides'][1]
        slide['semantic']['title'] = '误差为 $1.2\\times10^{-3}$'
        slide['semantic'].pop('inline_math', None)
        slide['composition']['blocks'] = [
            {'id': 'body', 'component': 'body', 'text': '达到 $10^{-3}$ 所需迭代数减少 1.8 倍。'},
        ]
        a.normalize_authoring_ir(ir)
        self.assertEqual(slide['semantic']['inline_math'], ['title'])
        self.assertTrue(slide['composition']['blocks'][0]['inline_math'])

    def test_diagram_shorthand_expands_to_a_native_process(self):
        ir = research_ir()
        slide = ir['slides'][1]
        slide['composition']['diagram'] = {
            'id': 'proximal-flow',
            'nodes': [
                {'id': 'grad', 'title': '梯度步', 'body': '沿负梯度走一步'},
                {'id': 'prox', 'title': '近端步', 'body': '软阈值收缩'},
                {'id': 'next', 'title': '新迭代', 'body': '得到稀疏解'},
            ],
        }
        a.normalize_authoring_ir(ir)
        self.assertNotIn('diagram', slide['composition'])
        graphic = slide['composition']['graphics'][-1]
        self.assertEqual(graphic['type'], 'process')
        self.assertEqual(graphic['direction'], 'horizontal')
        self.assertEqual(len(graphic['edges']), 2)
        self.assertEqual(graphic['edges'][0], {'from': 'grad', 'to': 'prox', 'kind': 'arrow'})

    def test_check_ir_accepts_latex_and_auto_inline(self):
        ir = research_ir()
        slide = ir['slides'][1]
        slide['composition']['archetype'] = 'equation-derivation'
        slide['composition']['blocks'] = [
            {'id': 'eq', 'latex': r'E=mc^2'},
            {'id': 'body', 'component': 'body', 'text': '其中 $m$ 为质量。'},
        ]
        a.check_ir(ir)
        self.assertEqual(slide['composition']['blocks'][0]['component'], 'formula')
        self.assertTrue(slide['composition']['blocks'][1]['inline_math'])

    def test_check_ir_accepts_the_expanded_diagram(self):
        ir = research_ir()
        slide = ir['slides'][1]
        slide['composition']['archetype'] = 'process-flow'
        slide['composition']['blocks'] = []
        slide['composition']['diagram'] = {
            'id': 'flow',
            'nodes': [
                {'id': 'a', 'title': '输入'},
                {'id': 'b', 'title': '处理'},
                {'id': 'c', 'title': '输出'},
            ],
        }
        a.check_ir(ir)
        self.assertEqual(slide['composition']['graphics'][-1]['id'], 'flow')


if __name__ == '__main__':
    unittest.main()
