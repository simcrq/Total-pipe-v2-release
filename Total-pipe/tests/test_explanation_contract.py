"""The Deck IR carries reader obligations and the compiler measures their coverage."""
import copy
import json
from pathlib import Path
import unittest

from deck_compiler.explanation import coverage
from deck_compiler.ir import derive, validate

ROOT = Path(__file__).resolve().parents[1]


def base_ir():
    ir = json.loads((ROOT/'examples/research.deck_ir.json').read_text(encoding='utf-8'))
    ir['slides'] = [copy.deepcopy(ir['slides'][1])]
    slide = ir['slides'][0]
    slide['id'] = 'obligation-page'
    slide['semantic']['evidence_refs'] = ['fixture:limits']
    slide['semantic']['explanation'] = {
        'reader_task': 'distinguish',
        'obligations': [{
            'id': 'ob-1',
            'kind': 'parallel_items',
            'required': True,
            'primary': True,
            'carrier': 'native_list',
            'status': 'bound',
            'content': {'items': ['Scope', 'Boundary', 'Uncertainty']},
            'evidence_refs': ['fixture:limits'],
        }],
    }
    slide['composition']['blocks'][0].update(
        text='Scope\nBoundary\nUncertainty',
        text_flow='distributed_arrow_list',
    )
    return ir


def rules(ir):
    return [item['rule'] for item in validate(ir)]


class ExplanationContractTests(unittest.TestCase):
    def test_native_list_satisfies_parallel_items(self):
        ir = base_ir()
        self.assertNotIn('EXPLANATION_OBLIGATION_MISSING', rules(ir))
        ledger = coverage(ir)
        self.assertEqual(ledger['summary'],
                         {'total': 1, 'satisfied': 1, 'waived': 0, 'unsupported': 0, 'missing': 0})
        self.assertEqual(ledger['slides'][0]['obligations'][0]['found_carriers'], ['native_list'])

    def test_ordered_steps_without_a_process_is_review(self):
        ir = base_ir()
        obligation = ir['slides'][0]['semantic']['explanation']['obligations'][0]
        obligation.update(kind='ordered_steps', carrier='process',
                          content={'items': ['Scope', 'Boundary', 'Uncertainty']})
        ir['slides'][0]['composition']['blocks'][0].pop('text_flow')
        self.assertIn('EXPLANATION_OBLIGATION_MISSING', rules(ir))
        self.assertEqual(coverage(ir)['summary']['missing'], 1)

    def test_required_obligation_can_be_waived_with_a_note(self):
        ir = base_ir()
        obligation = ir['slides'][0]['semantic']['explanation']['obligations'][0]
        obligation.update(kind='curve', carrier='path', status='waived',
                          note='No schematic is needed for a text-only limitations page.',
                          content={'shape': 'flat', 'schematic': True})
        self.assertNotIn('EXPLANATION_OBLIGATION_MISSING', rules(ir))
        self.assertEqual(coverage(ir)['summary']['waived'], 1)

    def test_waiver_without_a_note_fails(self):
        ir = base_ir()
        ir['slides'][0]['semantic']['explanation']['obligations'][0].update(
            status='waived', note='')
        self.assertIn('EXPLANATION_WAIVER_INVALID', rules(ir))

    def test_obligation_evidence_must_bind_to_the_slide(self):
        ir = base_ir()
        ir['slides'][0]['semantic']['explanation']['obligations'][0]['evidence_refs'] = ['other']
        self.assertIn('EXPLANATION_EVIDENCE_INVALID', rules(ir))

    def test_declared_content_must_be_visible(self):
        ir = base_ir()
        ir['slides'][0]['semantic']['explanation']['obligations'][0]['content'] = {
            'items': ['A claim that is only in the speaker notes', 'Another missing claim']}
        self.assertIn('EXPLANATION_CONTENT_NOT_VISIBLE', rules(ir))

    def test_derive_writes_the_coverage_ledger(self):
        ir = base_ir()
        derived = derive(ir, {'slides': []})
        self.assertIn('explanation_coverage.json', derived)
        self.assertEqual(derived['explanation_coverage.json']['summary']['total'], 1)

    def test_schema_accepts_explanation(self):
        try:
            import jsonschema
        except ImportError:
            self.skipTest('jsonschema is not installed')
        schema = json.loads((ROOT/'schemas/deck-ir.schema.json').read_text(encoding='utf-8'))
        jsonschema.validate(base_ir(), schema)


if __name__ == '__main__':
    unittest.main()
