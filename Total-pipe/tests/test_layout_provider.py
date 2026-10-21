"""The provider interface: a body layout may come from outside, but never bypasses the gates.

The diffusion model that used to be the only provider is gone. What these tests hold down is the
boundary it had to respect, so any replacement -- a rule engine, a remote service, a future model --
inherits the same guarantees:

* content is canonical: a provider cannot add, drop or rewrite a unit, and the IR is not mutated;
* a proposal that fails the geometric gates is dropped, not shipped;
* a provider that raises cannot break the build;
* the compiler templates always remain as the fallback, and the fallback is recorded;
* the removed v26 name fails loudly instead of silently mapping somewhere else.
"""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from deck_compiler.contracts import digest
from deck_compiler.layout import compile_deck
from deck_compiler.layout_provider import (CompilerProvider, PackerProvider, compile_with_provider,
                                           load_provider)
from test_deck_compiler import fixture

FAILED = ('FAIL',)


def run(ir, provider):
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder)/'deck_ir.json'
        path.write_text(json.dumps(ir), encoding='utf-8')
        return compile_with_provider(path, provider)


class StubProvider:
    name = 'stub'

    def __init__(self, boxes, status='PACKED'):
        self.boxes = boxes
        self.status = status

    def propose(self, requests):
        return {request['slide_id']: {
            'units': {unit['id']: {'bbox': list(self.boxes)} for unit in request['units']},
            'status': self.status} for request in requests}


class ExplodingProvider:
    name = 'exploding'

    def propose(self, requests):
        raise RuntimeError('provider backend is down')


class LayoutProviderTests(unittest.TestCase):
    def test_content_ids_and_ir_are_unchanged(self):
        ir = fixture()
        original = copy.deepcopy(ir)
        layout, issues = run(ir, PackerProvider())
        self.assertEqual(ir, original)
        self.assertEqual(layout['ir_sha256'], digest(ir))
        self.assertFalse([i for i in issues if i['severity'] in FAILED])
        for source, page in zip(ir['slides'], layout['slides']):
            actual = {element['id']: element for element in page['elements']}
            for block in source['composition']['blocks']:
                self.assertEqual(actual[block['id']]['source_text'], block['text'])
            self.assertIn(source['semantic']['speaker_notes'], page['notes'])

    def test_packer_packs_pages(self):
        layout, issues = run(fixture(), PackerProvider())
        counts = layout['layout_provider']['counts']
        self.assertGreaterEqual(counts['packed'], 1)
        self.assertEqual(counts['rejected'], 0)
        self.assertFalse([i for i in issues if i['severity'] in FAILED])
        self.assertEqual(len(layout['layout_provider']['slides']), len(fixture()['slides']))

    def test_compiler_provider_matches_the_reference_layout(self):
        ir = fixture()
        reference, _ = compile_deck(ir, '.')
        layout, issues = run(ir, CompilerProvider())
        self.assertEqual(layout['layout_provider']['counts'],
                         {'packed': 0, 'fallback': len(ir['slides']), 'rejected': 0})
        self.assertEqual([page['elements'] for page in layout['slides']],
                         [page['elements'] for page in reference['slides']])
        self.assertFalse([i for i in issues if i['severity'] in FAILED])

    def test_invalid_proposal_is_rejected_not_shipped(self):
        layout, issues = run(fixture(), StubProvider([-200, 260, 400, 320]))
        statuses = {record['status'] for record in layout['layout_provider']['slides']}
        self.assertEqual(statuses, {'REJECTED_GATES'})
        self.assertFalse([i for i in issues if i['rule'] == 'SHAPE_OUT_OF_BOUNDS'])
        self.assertFalse([i for i in issues if i['severity'] in FAILED])

    def test_provider_exception_is_a_warning(self):
        layout, issues = run(fixture(), ExplodingProvider())
        self.assertIsNotNone(layout)
        providers = [i for i in issues if i['rule'] == 'LAYOUT_PROVIDER_FAILED']
        self.assertTrue(providers)
        self.assertTrue(all(i['severity'] == 'WARNING' for i in providers))
        self.assertEqual(layout['layout_provider']['counts']['packed'], 0)

    def test_external_plugin_spec_loads(self):
        with tempfile.TemporaryDirectory() as folder:
            plugin = Path(folder)/'my_provider.py'
            plugin.write_text(
                'class Provider:\n'
                '    name = "file-plugin"\n'
                '    def propose(self, requests):\n'
                '        return {}\n\n'
                'def make():\n'
                '    return Provider()\n', encoding='utf-8')
            provider = load_provider(f'{plugin}:make')
            self.assertEqual(provider.name, 'file-plugin')
            self.assertEqual(provider.propose([]), {})

    def test_removed_v26_name_fails_loudly(self):
        with self.assertRaisesRegex(ValueError, 'v26 diffusion provider was removed'):
            load_provider('v26')

    def test_distributed_text_uses_original_compiler(self):
        ir = fixture()
        ir['slides'] = [ir['slides'][1]]
        block = ir['slides'][0]['composition']['blocks'][0]
        block.update(text='First measured scientific finding and its context.\n'
                          'Second independent finding and limitations.\n'
                          'Third observation and the unresolved question.',
                     text_flow='distributed_arrow_list')
        ir['slides'][0]['composition']['blocks'] = [block]
        layout, _ = run(ir, PackerProvider())
        self.assertEqual(layout['layout_provider']['slides'][0]['status'], 'COMPILER_FALLBACK')
        self.assertTrue(any(element['id'].endswith(':panel')
                            for element in layout['slides'][0]['elements']))

    def test_missing_unit_is_rejected(self):
        ir = fixture()
        with self.assertRaisesRegex(ValueError, 'identities'):
            compile_deck(ir, '.', proposals={ir['slides'][0]['id']:
                         {'units': {}, 'status': 'PACKED'}})

    def test_geometric_failure_is_not_hidden(self):
        ir = fixture()
        slide = ir['slides'][1]
        proposals = {slide['id']: {'status': 'PACKED', 'units': {
            block['id']: {'bbox': [-200, 260, 400, 320]}
            for block in slide['composition']['blocks']}}}
        _, issues = compile_deck(ir, '.', proposals=proposals)
        self.assertTrue(any(i['rule'] == 'SHAPE_OUT_OF_BOUNDS' and i['severity'] in FAILED
                            for i in issues))


if __name__ == '__main__':
    unittest.main()
