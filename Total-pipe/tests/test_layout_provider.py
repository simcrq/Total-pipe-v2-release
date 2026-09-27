import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from deck_compiler.contracts import digest
from deck_compiler.layout import compile_deck
from deck_compiler.layout_provider import compile_v26
from deck_compiler.pipeline import compile_input
from test_deck_compiler import fixture


class LayoutProviderTests(unittest.TestCase):
    def run_ir(self, ir, **options):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'deck_ir.json'
            path.write_text(json.dumps(ir), encoding='utf-8')
            return compile_v26(path, candidates=4, **options)

    def test_provider_preserves_ir_content_ids_and_rng(self):
        import torch
        ir = fixture()
        original = copy.deepcopy(ir)
        rng = torch.random.get_rng_state().clone()
        layout, issues = self.run_ir(ir)
        self.assertEqual(ir, original)
        self.assertTrue(torch.equal(rng, torch.random.get_rng_state()))
        self.assertEqual(layout['ir_sha256'], digest(ir))
        self.assertFalse([i for i in issues if i['severity']=='FAIL'])
        for source, page in zip(ir['slides'], layout['slides']):
            actual = {e['id']: e for e in page['elements']}
            for block in source['composition']['blocks']:
                self.assertEqual(actual[block['id']]['source_text'], block['text'])
            self.assertIn(source['semantic']['speaker_notes'], page['notes'])

    def test_model_failure_is_not_counted_as_success(self):
        import torch
        def invalid(model, batch, seed):
            return torch.zeros((*batch[0].shape, 4), dtype=torch.long)
        with patch('totalpipe_layout.model.sample', side_effect=invalid):
            layout, _ = self.run_ir(fixture())
        for record in layout['layout_provider']['slides']:
            self.assertEqual(record['valid_candidates'], 0)
            self.assertNotEqual(record['status'], 'MODEL_PROPOSAL')

    def test_missing_checkpoint_fails_closed_with_qa(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path = root/'ir.json'
            path.write_text(json.dumps(fixture()), encoding='utf-8')
            _, layout, qa = compile_input(path, root/'out',
                {'name':'v26', 'checkpoint':root/'absent.pt'})
            self.assertIsNone(layout)
            self.assertEqual(qa['items'][0]['rule'], 'LAYOUT_PROVIDER_FAILED')
            self.assertGreater(qa['counts']['FAIL'], 0)

    def test_checkpoint_hash_prevents_untrusted_load(self):
        with tempfile.TemporaryDirectory() as folder:
            bad = Path(folder)/'bad.pt'
            bad.write_bytes(b'not a checkpoint')
            with self.assertRaisesRegex(ValueError, 'SHA-256'):
                self.run_ir(fixture(), checkpoint=bad)

    def test_distributed_text_uses_original_compiler(self):
        ir = fixture()
        ir['slides'] = [ir['slides'][1]]
        block = ir['slides'][0]['composition']['blocks'][0]
        block.update(text='First measured scientific finding and its context.\nSecond independent finding and limitations.\nThird observation and the unresolved question.',
                     text_flow='distributed_arrow_list')
        ir['slides'][0]['composition']['blocks'] = [block]
        layout, _ = self.run_ir(ir)
        self.assertEqual(layout['layout_provider']['slides'][0]['status'], 'COMPILER_FALLBACK')
        self.assertTrue(any(e['id'].endswith(':panel') for e in layout['slides'][0]['elements']))

    def test_missing_unit_is_rejected(self):
        ir = fixture()
        with self.assertRaisesRegex(ValueError, 'identities'):
            compile_deck(ir, '.', proposals={ir['slides'][0]['id']:
                         {'units':{}, 'status':'MODEL_PROPOSAL'}})

    def test_geometric_failure_is_not_hidden(self):
        ir = fixture()
        s = ir['slides'][1]
        proposals = {s['id']:{'status':'MODEL_PROPOSAL', 'units':{
            b['id']:{'bbox':[-200,260,400,320]} for b in s['composition']['blocks']}}}
        _, issues = compile_deck(ir, '.', proposals=proposals)
        self.assertTrue(any(i['rule']=='SHAPE_OUT_OF_BOUNDS' and i['severity']=='FAIL' for i in issues))


if __name__ == '__main__':
    unittest.main()
