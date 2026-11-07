"""Agent-layer guards for supplement content (flag and paper-leak checks)."""
import copy
import json
from pathlib import Path
import unittest

from agent import adapters as a
from agent.supplement import leak_messages

ROOT = Path(__file__).resolve().parents[1]


def supplement_ir(all_supplement=True, supplement_text='效率达到 10^5 Ω。'):
    ir = json.loads((ROOT / 'examples/research.deck_ir.json').read_text(encoding='utf-8'))
    ir['slides'] = [copy.deepcopy(ir['slides'][1])]
    slide = ir['slides'][0]
    slide['id'] = 'supplement-page'
    slide['semantic']['evidence_refs'] = []
    blocks = slide['composition']['blocks']
    for block in blocks:
        block['basis'] = 'supplement'
        block['supplement'] = {'kind': 'background', 'source': 'textbook, ch. 1'}
    if not all_supplement:
        slide['semantic']['evidence_refs'] = ['EV0001']
        blocks[0].pop('basis', None)
        blocks[0].pop('supplement', None)
        blocks[1]['text'] = supplement_text
    return ir


def normalized(text='The device reaches 10^5 Ω at 300 K.'):
    return {'evidence': [{'evidence_id': 'EV0001', 'text': text}], 'slide_briefs': []}


class SupplementAgentTests(unittest.TestCase):
    def test_off_rejects_supplement_blocks(self):
        with self.assertRaises(a.Failure) as caught:
            a.check_ir(supplement_ir())
        self.assertEqual(caught.exception.code, 'SUPPLEMENT_NOT_ENABLED')

    def test_inline_rejects_standalone_supplement_page(self):
        with self.assertRaises(a.Failure) as caught:
            a.check_ir(supplement_ir(), supplement='inline')
        self.assertEqual(caught.exception.code, 'SUPPLEMENT_PAGE_NOT_ENABLED')

    def test_pages_allows_standalone_supplement_page(self):
        a.check_ir(supplement_ir(), supplement='pages')

    def test_numeric_paper_value_in_supplement_is_rejected(self):
        with self.assertRaises(a.Failure) as caught:
            a.check_ir(supplement_ir(all_supplement=False), normalized(), 'inline')
        self.assertEqual(caught.exception.code, 'SUPPLEMENT_PAPER_LEAK')
        self.assertIn('10^5', str(caught.exception))

    def test_long_verbatim_cjk_is_rejected(self):
        text = '该器件在低温下表现出稳定的整流特性'
        ir = supplement_ir(all_supplement=False)
        ir['slides'][0]['composition']['blocks'][1]['text'] = text
        with self.assertRaises(a.Failure) as caught:
            a.check_ir(ir, normalized(text), 'inline')
        self.assertEqual(caught.exception.code, 'SUPPLEMENT_PAPER_LEAK')

    def test_supplement_page_title_is_checked(self):
        ir = supplement_ir(all_supplement=True)
        ir['slides'][0]['semantic']['title'] = '效率达到 10^5 Ω'
        with self.assertRaises(a.Failure) as caught:
            a.check_ir(ir, normalized(), 'pages')
        self.assertEqual(caught.exception.code, 'SUPPLEMENT_PAPER_LEAK')

    def test_unrelated_supplement_is_allowed(self):
        ir = supplement_ir(all_supplement=False, supplement_text='这只是一个通用说明。')
        n = normalized('The device reaches 10^5 Ω.')
        a.check_ir(ir, n, 'inline')
        self.assertEqual(leak_messages(ir, n), [])

    def test_measurement_boundaries_allow_adjacent_chinese_but_not_identifiers(self):
        from agent.supplement import _number_tokens
        self.assertIn('10^5ω', _number_tokens('效率达到10^5 Ω时'))
        self.assertIn('0.537', _number_tokens('吸收率为0.537时'))
        self.assertEqual(_number_tokens('sample10mA and state0.537x'), set())

    def test_canonical_inline_math_cannot_hide_a_paper_measurement(self):
        for text in (r'效率达到 $10^{5}$ Ω。', r'效率达到 $10^{5}\,\Omega$。'):
            with self.subTest(text=text):
                ir = supplement_ir(all_supplement=False)
                ir['slides'][0]['composition']['blocks'][1]['text'] = text
                with self.assertRaises(a.Failure) as caught:
                    a.check_ir(ir, normalized(), 'inline')
                self.assertEqual(caught.exception.code, 'SUPPLEMENT_PAPER_LEAK')


if __name__ == '__main__':
    unittest.main()
