"""Build integration binds the effective IR, provider input and optional diagram audit."""
import copy
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

from deck_compiler.contracts import digest, file_hash, issue, report
from deck_compiler.explain_viz.plugin import EnhanceResult
from deck_compiler.explain_viz.runtime import CompilationAdapter, PreparedEnhancement, prepare
from deck_compiler.pipeline import build, compile_input, ingest_native, write_json
from test_explain_viz import EXAMPLE, ROOT, inputs


def layout_for(ir):
    return {'schema_version': '2.0', 'ir_sha256': digest(ir), 'assets': {},
            'slides': [{'id': s['id'], 'elements': []} for s in ir['slides']]}


def request_for(slots, proposal):
    return {'version': '1.0', 'options': {'mode': 'auto'}, 'slots': slots, 'proposal': proposal}


class ExplainVizRuntimeTests(unittest.TestCase):
    def test_off_never_calls_the_selected_compiler(self):
        ir, _, _ = inputs()
        compiler = Mock(side_effect=AssertionError('disabled'))
        prepared = prepare(ir, {'version': '1.0', 'options': {}}, EXAMPLE, compiler)
        self.assertIs(prepared.result.deck_ir, ir)
        self.assertEqual(prepared.result.status, 'disabled')
        compiler.assert_not_called()

    def test_malformed_and_unreadable_requests_fail_open_without_leaking_text(self):
        ir, slots, proposal = inputs()
        compiler = Mock(side_effect=AssertionError('invalid requests must not compile'))
        bad = [None, [], {'version': '9', 'options': {}},
               {'version': '1.0', 'options': {'mode': 'auto'}},
               {**request_for(slots, proposal), 'execute': 'sensitive document text'},
               {'version': '1.0', 'options': {'mode': 'unknown'}}]
        for request in bad:
            with self.subTest(request=type(request).__name__):
                prepared = prepare(ir, request, EXAMPLE, compiler)
                self.assertIs(prepared.result.deck_ir, ir)
                self.assertEqual(prepared.result.status, 'fallback')
                self.assertEqual(prepared.result.warnings, ['invalid_request'])
                self.assertNotIn('sensitive document text', json.dumps(prepared.audit(ir, ir)))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'broken.json'
            path.write_text('{ private document content', encoding='utf-8')
            self.assertEqual(prepare(ir, path, EXAMPLE, compiler).result.status, 'fallback')
            self.assertEqual(prepare(ir, Path(folder)/'missing.json', EXAMPLE, compiler).result.status, 'fallback')
        compiler.assert_not_called()

    def test_compiler_adapter_isolates_callback_mutations_and_rejects_stale_results(self):
        ir, _, _ = inputs()
        original = copy.deepcopy(ir)
        def compiler(value):
            layout = layout_for(value)
            value['deck_id'] = 'callback-mutated-copy'
            return layout, []
        adapter = CompilationAdapter(EXAMPLE, compiler)
        self.assertEqual(adapter.compile(ir)['ir_sha256'], digest(ir))
        self.assertEqual(ir, original)
        adapter.compile_fn = lambda value: ({**layout_for(value), 'ir_sha256': '0'*64}, [])
        with self.assertRaisesRegex(ValueError, 'compile_failed'):
            adapter.compile(ir)
        adapter.compile_fn = lambda value: (layout_for(value), [issue('BASELINE', 'FAIL', 'failed')])
        with self.assertRaisesRegex(ValueError, 'compile_failed'):
            adapter.compile(ir)

    def test_request_wrapper_reuses_only_a_matching_checked_compilation(self):
        ir, slots, proposal = inputs()
        candidate = copy.deepcopy(ir)
        candidate['slides'][0]['composition']['graphics'][0]['paths'].append({
            'id': 'evz_extra', 'commands': [['M', 10, 10], ['L', 20, 20]]})
        expected = layout_for(candidate)
        def enhanced(source, context, options, adapter):
            adapter.compile(candidate)
            return EnhanceResult(candidate, status='enhanced')
        with patch('deck_compiler.explain_viz.runtime.enhance', side_effect=enhanced):
            prepared = prepare(ir, request_for(slots, proposal), EXAMPLE, lambda value: (expected, []))
        self.assertEqual(prepared.compiled, (expected, []))
        self.assertEqual(prepared.request_sha256, digest(request_for(slots, proposal)))
        with patch('deck_compiler.explain_viz.runtime.enhance', return_value=EnhanceResult(candidate, status='enhanced')):
            rejected = prepare(ir, request_for(slots, proposal), EXAMPLE, lambda value: (expected, []))
        self.assertIs(rejected.result.deck_ir, ir)
        self.assertEqual(rejected.result.status, 'fallback')

    def test_request_schema_includes_the_constructed_build_request(self):
        import jsonschema
        schema = json.loads((ROOT/'schemas/explain-viz.schema.json').read_text())
        request = json.loads((EXAMPLE/'request.json').read_text())
        jsonschema.validate(request, {**schema, '$ref': '#/$defs/request'})
        jsonschema.validate({'version': '1.0', 'options': {}}, {**schema, '$ref': '#/$defs/request'})
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate({'version': '1.0', 'options': {'mode': 'auto'}},
                                {**schema, '$ref': '#/$defs/request'})


class ExplainVizPipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.source = self.folder/'source.deck_ir.json'
        self.out = self.folder/'build'
        self.ir, self.slots, self.proposal = inputs()
        write_json(self.source, self.ir)
        self.addCleanup(patch.stopall)
        patch('deck_compiler.pipeline.derive', return_value={}).start()
        patch('deck_compiler.pipeline.write_qa',
              side_effect=lambda out, qa, ir, layout: write_json(out/'qa_report.json', qa)).start()

    def compile(self, request=None):
        with patch('deck_compiler.pipeline._compile_ir', side_effect=lambda ir, *args: (layout_for(ir), [])) as compiler:
            result = compile_input(self.source, self.out, {'name': 'packer'},
                                   require_visual_design=False, explain_viz_request=request)
        return result, compiler

    def test_absent_request_removes_old_audit_and_never_runs_plugin(self):
        write_json(self.out/'explain_viz.json', {'status': 'enhanced'})
        write_json(self.out/'explain_viz.source.deck_ir.json', {'stale': True})
        with patch('deck_compiler.explain_viz.runtime.prepare') as prepare_mock:
            (_, _, qa), compiler = self.compile()
        prepare_mock.assert_not_called()
        compiler.assert_called_once()
        self.assertNotIn('explain_viz', qa)
        self.assertFalse((self.out/'explain_viz.json').exists())
        self.assertFalse((self.out/'explain_viz.source.deck_ir.json').exists())

    def test_off_request_freezes_source_without_changing_its_resource_base(self):
        before = self.source.read_bytes()
        (effective, _, qa), _ = self.compile({'version': '1.0', 'options': {'mode': 'off'}})
        self.assertEqual(self.source.read_bytes(), before)
        self.assertEqual(effective, self.ir)
        self.assertEqual(qa['explain_viz']['status'], 'disabled')
        audit = json.loads((self.out/'explain_viz.json').read_text())
        self.assertEqual(audit['source_base'], str(self.source.parent.resolve()))
        self.assertEqual(audit['output_ir_sha256'], qa['ir_sha256'])
        self.assertEqual(json.loads((self.out/'explain_viz.source.deck_ir.json').read_text()), self.ir)

    def test_invalid_optional_request_cannot_turn_a_good_compile_into_failure(self):
        (_, _, qa), compiler = self.compile({'version': '1.0', 'options': {'mode': 'auto'}})
        self.assertEqual(qa['counts']['FAIL'], 0)
        self.assertEqual(qa['explain_viz']['status'], 'fallback')
        self.assertTrue(any(item['rule'] == 'EXPLAIN_VIZ_FALLBACK' for item in qa['items']))
        compiler.assert_called_once()

    def test_checked_enhancement_is_the_single_effective_input_and_creates_review(self):
        effective = copy.deepcopy(self.ir)
        effective['slides'][0]['composition']['graphics'][0]['paths'].append({
            'id': 'evz_extra', 'commands': [['M', 10, 10], ['L', 20, 20]]})
        result = EnhanceResult(effective, status='enhanced', added_object_ids=['peel-angle/extra'],
            manifest=[{'slide_id': 'peel-angle', 'shape_ids': ['extra']}])
        prepared = PreparedEnhancement(result, 'a'*64, (layout_for(effective), []))
        with patch('deck_compiler.explain_viz.runtime.prepare', return_value=prepared):
            (compiled_ir, layout, qa), compiler = self.compile(request_for(self.slots, self.proposal))
        compiler.assert_not_called()
        self.assertEqual(compiled_ir, effective)
        self.assertEqual(layout['ir_sha256'], digest(effective))
        self.assertEqual(qa['ir_sha256'], digest(effective))
        self.assertEqual(qa['explain_viz']['output_ir_sha256'], digest(effective))
        self.assertEqual(json.loads((self.out/'deck_ir.json').read_text()), effective)
        self.assertTrue(any(item['rule'] == 'EXPLAIN_VIZ_SEMANTIC_REVIEW' for item in qa['items']))
        self.assertEqual(json.loads(self.source.read_text()), self.ir)

    def test_plugin_does_not_mask_existing_compiler_failures(self):
        failure = issue('SOURCE_FAILURE', 'FAIL', 'Existing source could not compile')
        with patch('deck_compiler.pipeline._compile_ir', return_value=(None, [failure])):
            effective, layout, qa = compile_input(self.source, self.out, require_visual_design=False,
                explain_viz_request=request_for(self.slots, self.proposal))
        self.assertEqual(effective, self.ir)
        self.assertIsNone(layout)
        self.assertGreater(qa['counts']['FAIL'], 0)
        self.assertEqual(qa['explain_viz']['status'], 'fallback')
        self.assertTrue(any(item['rule'] == 'SOURCE_FAILURE' for item in qa['items']))

    def test_design_gate_precedes_request_loading_and_enhancement(self):
        value = copy.deepcopy(self.ir)
        value.pop('presentation')
        write_json(self.source, value)
        with patch('deck_compiler.explain_viz.runtime.prepare') as plugin:
            _, layout, qa = compile_input(self.source, self.out,
                                         explain_viz_request=self.folder/'missing-request.json')
        plugin.assert_not_called()
        self.assertIsNone(layout)
        self.assertEqual(qa['next_action']['action'], 'author_visual_proposal')
        self.assertEqual(qa['explain_viz']['warnings'], ['visual_design_required'])

    def test_audit_cannot_overwrite_input_or_request(self):
        self.out.mkdir()
        source = self.out/'explain_viz.source.deck_ir.json'
        write_json(source, self.ir)
        before = source.read_bytes()
        with self.assertRaisesRegex(ValueError, 'must not overwrite'):
            compile_input(source, self.out, explain_viz_request={'version': '1.0', 'options': {}})
        self.assertEqual(source.read_bytes(), before)
        request = self.out/'explain_viz.json'
        write_json(request, {'version': '1.0', 'options': {}})
        before = request.read_bytes()
        with self.assertRaisesRegex(ValueError, 'must not overwrite'):
            compile_input(self.source, self.out, explain_viz_request=request)
        self.assertEqual(request.read_bytes(), before)

    def test_build_preserves_optional_audit_summary_when_backend_fails(self):
        summary = {'status': 'fallback', 'applied_visuals': 0, 'audit': 'explain_viz.json'}
        qa = report([], ir_sha256=digest(self.ir))
        qa['explain_viz'] = summary
        request = {'version': '1.0', 'options': {}}
        with patch('deck_compiler.pipeline.compile_input', return_value=(self.ir, layout_for(self.ir), qa)) as compile_mock, \
             patch('deck_compiler.pipeline.officecli.preflight', side_effect=ValueError('backend unavailable')):
            result = build(self.source, self.out, native_render=False, explain_viz_request=request)
        self.assertEqual(compile_mock.call_args.kwargs['explain_viz_request'], request)
        self.assertEqual(result['explain_viz'], summary)
        self.assertGreater(result['counts']['FAIL'], 0)

    def test_native_import_preserves_the_artifact_bound_explain_summary(self):
        write_json(self.out/'layout.json', layout_for(self.ir))
        write_json(self.out/'deck_ir.json', self.ir)
        (self.out/'staging.pptx').write_bytes(b'unit-test-only-pptx')
        pdf = self.folder/'export.pdf'
        pdf.write_bytes(b'%PDF-unit-test-only')
        prior = report([], file_hash(self.out/'staging.pptx'), digest(self.ir))
        prior['layout_sha256'] = file_hash(self.out/'layout.json')
        prior['explain_viz'] = {'status': 'enhanced', 'applied_visuals': 1}
        write_json(self.out/'qa_report.json', prior)
        with patch('deck_compiler.pipeline._load_powerpoint_review', return_value={'reviewer': 'test'}), \
             patch('deck_compiler.pipeline.verify', return_value=[]), \
             patch('deck_compiler.pipeline.native.inspect_pdf', return_value=[]):
            qa = ingest_native(self.out, pdf)
        self.assertEqual(qa['explain_viz'], prior['explain_viz'])

    def test_real_provider_compilation_uses_in_memory_ir_without_rewriting_source(self):
        from deck_compiler.layout_provider import PackerProvider, compile_with_provider
        source_bytes = self.source.read_bytes()
        override = copy.deepcopy(self.ir)
        override['deck_id'] = 'in-memory-snapshot'
        layout, findings = compile_with_provider(self.source, PackerProvider(), deck_ir=override)
        self.assertEqual(layout['ir_sha256'], digest(override))
        self.assertFalse(any(item['severity'] == 'FAIL' for item in findings))
        self.assertEqual(self.source.read_bytes(), source_bytes)

    def test_mcp_build_flag_is_forwarded_and_capability_contract_matches_cli(self):
        from deck_compiler import mcp_server
        from deck_compiler.explain_viz.specs import capabilities
        completed = subprocess.CompletedProcess([], 0, stdout=json.dumps(report([])), stderr='')
        args = {'ir': str(self.source), 'out': str(self.out),
                'explain_viz_request': str(self.folder/'request.json')}
        with patch.object(mcp_server.subprocess, 'run', return_value=completed) as run:
            mcp_server.transport.TOOLS['totalpipe_compile']['handler'](args)
        command = run.call_args.args[0]
        self.assertEqual(command[command.index('--explain-viz-request')+1], args['explain_viz_request'])
        self.assertEqual(mcp_server.capability_handler({})['explain_viz'], capabilities())
        with self.assertRaises(ValueError):
            mcp_server.transport.TOOLS['totalpipe_compile']['handler']({**args, 'explain_viz_request': 'relative.json'})

    def test_unified_generator_forwards_the_explicit_request(self):
        from deck_compiler.unified_cli import generate_presentation
        request = self.folder/'request.json'
        with patch('deck_compiler.unified_cli.pipeline.build', return_value=report([])) as build_mock:
            success, _, _ = generate_presentation(self.source, self.out, explain_viz_request=request)
        self.assertTrue(success)
        self.assertEqual(build_mock.call_args.kwargs['explain_viz_request'], request)


if __name__ == '__main__':
    unittest.main()
