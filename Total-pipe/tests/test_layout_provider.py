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
from unittest.mock import patch

from deck_compiler.contracts import digest
from deck_compiler.layout import compile_deck
from deck_compiler.layout_provider import (CompilerProvider, PackerProvider, compile_with_provider,
                                           load_provider)
from test_deck_compiler import fixture
from totalpipe_layout.contracts import read_requests

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
                         {'packed': 0, 'owned': len(ir['slides']), 'fallback': 0,
                          'rejected': 0, 'coverage': None})
        self.assertTrue(all(r['reason'] == 'provider_disabled' for r in layout['layout_provider']['slides']))
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
        self.assertEqual(layout['layout_provider']['slides'][0]['status'], 'COMPILER_OWNED')
        self.assertTrue(any(element['id'].endswith(':panel')
                            for element in layout['slides'][0]['elements']))

    def test_native_graphic_pages_are_owned_without_querying_provider(self):
        root = Path(__file__).resolve().parents[1]
        provider = ExplodingProvider()
        with patch.object(provider, 'propose', wraps=provider.propose) as propose, \
                patch('deck_compiler.layout_provider.compile_deck', wraps=compile_deck) as compile_once, \
                patch('deck_compiler.layout.compile_deck', wraps=compile_deck) as request_compile:
            layout, issues = compile_with_provider(root/'examples/native-components.deck_ir.json', provider)
        propose.assert_not_called()
        self.assertEqual(compile_once.call_count, 1)
        request_compile.assert_not_called()
        self.assertEqual(layout['layout_provider']['counts'],
                         {'packed': 0, 'owned': 6, 'fallback': 0, 'rejected': 0, 'coverage': None})
        self.assertTrue(all(r['reason'] == 'graphic_page' for r in layout['layout_provider']['slides']))
        self.assertFalse([i for i in issues if i['rule'] == 'LAYOUT_PROVIDER_FAILED'])

    def test_no_proposal_has_a_reason_and_reuses_the_baseline(self):
        class AbstainingProvider:
            name = 'abstaining'
            def propose(self, requests):
                return {}
        with patch('deck_compiler.layout_provider.compile_deck', wraps=compile_deck) as compiler, \
                patch('deck_compiler.layout.compile_deck', wraps=compile_deck) as request_compile:
            layout, _ = run(fixture(), AbstainingProvider())
        self.assertEqual(compiler.call_count, 1)
        request_compile.assert_not_called()
        self.assertEqual(layout['layout_provider']['counts'],
                         {'packed': 0, 'owned': 0, 'fallback': 2, 'rejected': 0, 'coverage': 0.0})
        self.assertTrue(all(r['reason'] == 'no_proposal' for r in layout['layout_provider']['slides']))

    def test_batch_failure_is_retried_without_losing_healthy_pages(self):
        class PartiallyBrokenProvider(PackerProvider):
            def propose(self, requests):
                if any(r['slide_id'] == 'limits' for r in requests):
                    raise RuntimeError('only the limits page fails')
                return super().propose(requests)
        layout, issues = run(fixture(), PartiallyBrokenProvider())
        first, second = layout['layout_provider']['slides']
        self.assertEqual(first['status'], 'PACKED')
        self.assertEqual((second['status'], second['reason']), ('COMPILER_FALLBACK', 'provider_error'))
        failures = [i for i in issues if i['rule'] == 'LAYOUT_PROVIDER_FAILED']
        self.assertEqual([i['slide'] for i in failures], [2])
        self.assertEqual(layout['layout_provider']['counts']['coverage'], .5)
        self.assertFalse([i for i in issues if i['severity'] == 'FAIL'])

    def test_packed_and_owned_pages_have_separate_counts_and_queries(self):
        ir = fixture()
        ir['slides'][1]['composition']['blocks'][0].update(inline_math=True, text='Definition $x^2$.')
        provider = PackerProvider()
        with patch.object(provider, 'propose', wraps=provider.propose) as propose, \
                patch('deck_compiler.layout_provider.compile_deck', wraps=compile_deck) as compiler:
            layout, _ = run(ir, provider)
        self.assertEqual(compiler.call_count, 2)  # baseline + accepted proposals, no request recompile
        self.assertEqual([r['slide_id'] for r in propose.call_args.args[0]], ['evidence'])
        self.assertEqual(layout['layout_provider']['counts'],
                         {'packed': 1, 'owned': 1, 'fallback': 0, 'rejected': 0, 'coverage': 1.0})
        self.assertEqual(layout['layout_provider']['slides'][1]['reason'], 'measured_formula_flow')

    def test_empty_body_is_owned_with_an_explicit_reason(self):
        ir = fixture()
        ir['slides'] = [ir['slides'][1]]
        ir['slides'][0]['composition']['blocks'] = []
        layout, _ = run(ir, ExplodingProvider())
        record = layout['layout_provider']['slides'][0]
        self.assertEqual((record['status'], record['reason']), ('COMPILER_OWNED', 'no_units'))

    def test_read_requests_accepts_a_matching_baseline_and_rejects_a_stale_one(self):
        ir = fixture()
        baseline, issues = compile_deck(ir, '.')
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'deck_ir.json'
            path.write_text(json.dumps(ir), encoding='utf-8')
            expected, _ = read_requests(path)
            with patch('deck_compiler.layout.compile_deck') as compiler:
                requests, meta = read_requests(path, layout=baseline, compile_issues=issues)
            compiler.assert_not_called()
            self.assertEqual(requests, expected)
            self.assertEqual(meta['compiler_issues'], issues)
            baseline['ir_sha256'] = 'stale'
            with self.assertRaisesRegex(ValueError, 'does not match'):
                read_requests(path, layout=baseline, compile_issues=issues)

    def test_malformed_external_proposals_are_rejected_without_crashing(self):
        class MalformedProvider:
            name = 'malformed'
            def propose(self, requests):
                return {r['slide_id']: {'units': {u['id']: {'bbox': ['x', 260, 400, 320]}
                                               for u in r['units']}} for r in requests}
        layout, issues = run(fixture(), MalformedProvider())
        self.assertEqual(layout['layout_provider']['counts']['rejected'], 2)
        self.assertTrue(all(r['violations'] == ['MALFORMED_BBOX'] for r in layout['layout_provider']['slides']))
        self.assertFalse([i for i in issues if i['severity'] == 'FAIL'])

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
