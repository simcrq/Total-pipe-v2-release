"""Supplement content keeps paper claims gated while allowing marked additions."""
import copy
import json
from pathlib import Path
import unittest

from deck_compiler.explanation import coverage, validate_explanation
from deck_compiler.ir import validate
from deck_compiler.provenance import validate as validate_provenance
from deck_compiler.quality_metrics import analyze_completeness

ROOT = Path(__file__).resolve().parents[1]


def base_ir():
    ir = json.loads((ROOT / 'examples/research.deck_ir.json').read_text(encoding='utf-8'))
    ir['slides'] = [copy.deepcopy(ir['slides'][1])]
    slide = ir['slides'][0]
    slide['id'] = 'supplement-page'
    slide['semantic']['evidence_refs'] = []
    for block in slide['composition']['blocks']:
        block['basis'] = 'supplement'
        block['supplement'] = {'kind': 'background', 'source': 'textbook, ch. 1'}
    return ir


def mixed_ir():
    ir = base_ir()
    slide = ir['slides'][0]
    blocks = slide['composition']['blocks']
    blocks[0].pop('basis', None)
    blocks[0].pop('supplement', None)
    blocks[0]['evidence_refs'] = []
    slide['semantic']['evidence_refs'] = []
    return ir


def rules(ir):
    return [item['rule'] for item in validate_provenance(ir)]


class SupplementProvenanceTests(unittest.TestCase):
    def test_example_is_valid(self):
        ir = json.loads((ROOT / 'examples/supplement.deck_ir.json').read_text(encoding='utf-8'))
        self.assertEqual(validate(ir), [])

    def test_all_paper_deck_is_unchanged(self):
        ir = json.loads((ROOT / 'examples/research.deck_ir.json').read_text(encoding='utf-8'))
        self.assertEqual(validate_provenance(ir), [])
        self.assertEqual(validate(ir), [])

    def test_mixed_page_requires_paper_evidence(self):
        ir = mixed_ir()
        found = validate(ir)
        self.assertIn('PROVENANCE_PAPER_EVIDENCE_MISSING', [item['rule'] for item in found])

    def test_mixed_page_block_evidence_must_be_subset(self):
        ir = mixed_ir()
        ir['slides'][0]['semantic']['evidence_refs'] = ['EV0001']
        ir['slides'][0]['composition']['blocks'][0]['evidence_refs'] = ['EV9999']
        found = validate(ir)
        self.assertIn('PROVENANCE_PAPER_EVIDENCE_INVALID', [item['rule'] for item in found])

    def test_mixed_page_with_gated_paper_block_passes(self):
        ir = mixed_ir()
        ir['slides'][0]['semantic']['evidence_refs'] = ['EV0001']
        self.assertEqual(validate(ir), [])

    def test_supplement_page_is_valid(self):
        self.assertEqual(validate(base_ir()), [])

    def test_missing_source_is_info(self):
        ir = base_ir()
        ir['slides'][0]['composition']['blocks'][0]['supplement'].pop('source')
        found = validate(ir)
        self.assertIn('SUPPLEMENT_UNCITED', [item['rule'] for item in found])
        self.assertTrue(all(item['severity'] == 'INFO' for item in found
                            if item['rule'] == 'SUPPLEMENT_UNCITED'))

    def test_constructed_without_label_is_review(self):
        ir = base_ir()
        block = ir['slides'][0]['composition']['blocks'][0]
        block['text'] = '一个数值算例。'
        block['supplement']['constructed'] = True
        found = validate(ir)
        self.assertIn('SUPPLEMENT_CONSTRUCTED_UNLABELED', [item['rule'] for item in found])
        self.assertEqual(next(item['severity'] for item in found
                              if item['rule'] == 'SUPPLEMENT_CONSTRUCTED_UNLABELED'), 'REVIEW')

    def test_constructed_with_visible_label_passes(self):
        ir = base_ir()
        block = ir['slides'][0]['composition']['blocks'][0]
        block['text'] = '示意：一个简化的数值算例。'
        block['supplement']['constructed'] = True
        self.assertEqual(validate(ir), [])

    def test_derivation_without_assumptions_is_info(self):
        ir = base_ir()
        block = ir['slides'][0]['composition']['blocks'][0]
        block['supplement']['kind'] = 'derivation'
        found = validate(ir)
        self.assertIn('SUPPLEMENT_ASSUMPTION_MISSING', [item['rule'] for item in found])

    def test_supplement_evidence_forbidden(self):
        ir = base_ir()
        ir['slides'][0]['composition']['blocks'][0]['evidence_refs'] = ['EV0001']
        found = validate(ir)
        self.assertIn('SUPPLEMENT_EVIDENCE_FORBIDDEN', [item['rule'] for item in found])

    def test_supplement_only_page_with_evidence_refs_is_review(self):
        ir = base_ir()
        ir['slides'][0]['semantic']['evidence_refs'] = ['EV0001']
        found = validate(ir)
        self.assertIn('SUPPLEMENT_EVIDENCE_CONFLICT', [item['rule'] for item in found])
        self.assertEqual(next(item['severity'] for item in found
                              if item['rule'] == 'SUPPLEMENT_EVIDENCE_CONFLICT'), 'REVIEW')

    def test_paper_block_cannot_carry_supplement(self):
        ir = base_ir()
        block = ir['slides'][0]['composition']['blocks'][0]
        block['basis'] = 'paper'
        found = validate(ir)
        self.assertIn('SUPPLEMENT_ON_PAPER_BLOCK', [item['rule'] for item in found])

    def test_basis_invalid(self):
        ir = base_ir()
        ir['slides'][0]['composition']['blocks'][0]['basis'] = 'external'
        found = validate(ir)
        self.assertIn('SUPPLEMENT_BASIS_INVALID', [item['rule'] for item in found])

    def test_supplement_page_with_paper_figure_fails(self):
        ir = base_ir()
        ir['assets']['paperfig'] = {'path': 'paper.png', 'origin': 'paper', 'source_figure': '3'}
        ir['slides'][0]['composition']['figure_refs'] = [
            {'asset_id': 'paperfig', 'source_figure': '3', 'caption': 'Fig. 3'}]
        found = validate(ir)
        self.assertIn('SUPPLEMENT_PAPER_FIGURE', [item['rule'] for item in found])
        self.assertEqual(next(item['severity'] for item in found
                              if item['rule'] == 'SUPPLEMENT_PAPER_FIGURE'), 'FAIL')

    def test_ratio_is_info(self):
        ir = base_ir()
        supplement = ir['slides'][0]
        paper = copy.deepcopy(supplement)
        paper['id'] = 'paper-page'
        paper['semantic']['evidence_refs'] = ['EV0001']
        for block in paper['composition']['blocks']:
            block.pop('basis', None)
            block.pop('supplement', None)
        ir['slides'] = [paper, supplement, copy.deepcopy(supplement)]
        ir['slides'][2]['id'] = 'supplement-page-2'
        found = validate(ir)
        self.assertIn('SUPPLEMENT_RATIO_HIGH', [item['rule'] for item in found])
        self.assertEqual(next(item['severity'] for item in found
                              if item['rule'] == 'SUPPLEMENT_RATIO_HIGH'), 'INFO')


class SupplementExplanationTests(unittest.TestCase):
    def setup(self, basis, refs=None):
        semantic = {'title': '补充页', 'takeaway': '这是补充结论。', 'evidence_refs': []}
        composition = {'blocks': [{'id': 'b1', 'component': 'body', 'text': '计算\n更新',
                                   'text_flow': 'distributed_arrow_list'}]}
        obligation = {'id': 'ob-1', 'kind': 'parallel_items', 'required': True,
                      'basis': basis, 'content': {'items': ['计算', '更新']}}
        if refs is not None:
            obligation['evidence_refs'] = refs
        return {'reader_task': 'distinguish', 'obligations': [obligation]}, semantic, composition

    def test_supplement_obligation_does_not_need_evidence(self):
        value, semantic, composition = self.setup('supplement')
        self.assertEqual(validate_explanation(value, semantic, composition, 1), [])

    def test_supplement_obligation_rejects_evidence(self):
        value, semantic, composition = self.setup('supplement', refs=['EV0001'])
        found = validate_explanation(value, semantic, composition, 1)
        self.assertIn('EXPLANATION_EVIDENCE_FORBIDDEN', [item['rule'] for item in found])

    def test_paper_obligation_still_needs_evidence(self):
        value, semantic, composition = self.setup('paper')
        found = validate_explanation(value, semantic, composition, 1)
        self.assertIn('EXPLANATION_INVALID', [item['rule'] for item in found])

    def test_coverage_ledger_records_basis(self):
        value, semantic, composition = self.setup('supplement')
        ir = {'slides': [{'id': 's1', 'semantic': {**semantic, 'explanation': value},
                          'composition': composition}]}
        ledger = coverage(ir)
        self.assertEqual(ledger['slides'][0]['obligations'][0]['basis'], 'supplement')


class SupplementQualityMetricsTests(unittest.TestCase):
    def deck(self, bases, refs=(), takeaway='这是一个足够长的补充页结论用于测试完整性评分'):
        blocks = []
        for index, basis in enumerate(bases):
            block = {'id': f'b{index}', 'component': 'body', 'text': '补充内容'}
            if basis == 'supplement':
                block['basis'] = 'supplement'
                block['supplement'] = {'kind': 'background', 'source': 'textbook'}
            blocks.append(block)
        return {'slides': [{'semantic': {'takeaway': takeaway, 'evidence_refs': list(refs)},
                            'composition': {'blocks': blocks}}]}

    def test_supplement_only_page_is_not_penalised(self):
        score = analyze_completeness({}, {}, self.deck(['supplement']), False)
        messages = [issue.message for issue in score.issues]
        self.assertNotIn('No evidence citations on this slide', messages)
        self.assertEqual(score.score, 100)
        self.assertEqual(score.details['supplement_slides'], 1)

    def test_paper_page_still_requires_evidence(self):
        score = analyze_completeness({}, {}, self.deck(['paper']), False)
        messages = [issue.message for issue in score.issues]
        self.assertIn('No evidence citations on this slide', messages)
        self.assertEqual(score.details['supplement_slides'], 0)

    def test_supplement_without_source_is_counted(self):
        deck = self.deck(['supplement'])
        deck['slides'][0]['composition']['blocks'][0]['supplement'].pop('source')
        score = analyze_completeness({}, {}, deck, False)
        self.assertEqual(score.details['uncited_supplements'], 1)


if __name__ == '__main__':
    unittest.main()
