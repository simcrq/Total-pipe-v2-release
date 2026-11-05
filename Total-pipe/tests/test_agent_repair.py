"""Local repair is transactional and keeps the original scientific/QA contracts."""
import copy
import json
from pathlib import Path
import shutil
import unittest
from unittest.mock import patch

import jsonschema
from PIL import Image

from agent import COMPONENT, adapters as a, runner
from agent import repair
from agent.state import digest, read, resources, sha, write
from agent_fixture import AgentCase


class RepairCase(AgentCase):
    def make_source(self):
        image = self.root/'reference.png'
        Image.new('RGB', (1200, 900), '#DDE7EB').save(image)
        value = read(COMPONENT/'examples/native-bullets.deck_ir.json')
        page = copy.deepcopy(value['slides'][0])
        page['id'] = 'reference-page'
        page['semantic'] = {
            'title': 'A locally supplied reference image',
            'purpose': 'Exercise local image path and layout repair while retaining the source.',
            'takeaway': 'The supplied image remains bound to its original provenance.',
            'speaker_notes': 'Synthetic software test fixture; no measured scientific claim.',
            'evidence_refs': [], 'caveats': []}
        page['composition'] = {'archetype': 'composite-research',
            'blocks': [{'id': 'context', 'component': 'body',
                        'text': 'The original reference image and its source must remain identifiable.'}],
            'figure_refs': [{'asset_id': 'reference', 'caption': 'Locally supplied reference fixture.', 'panel_count': 1}],
            'layout_tree': {'version': '1.0', 'regions': {'body': {
                'id': 'image-and-context', 'type': 'columns', 'gap': 'standard',
                'children': [{'id': 'image', 'type': 'figure', 'ref': 0},
                             {'id': 'context', 'type': 'block', 'ref': 'context'}]}}}}
        page['presentation'] = {}
        value['slides'] = [page]
        value['assets'] = {'reference': {'path': str(image), 'origin': 'reference',
            'reference_source': 'Explicitly supplied synthetic local test fixture.'}}
        value['presentation']['text_capacity_policy'] = 'strict'
        source = self.root/'input.deck_ir.json'
        write(source, value)
        return source

    def fake_build(self, stage, job):
        # A deliberately non-PPTX fixture for fast state/transaction tests. Real OfficeCLI is
        # exercised separately; none of these bytes are presented as an editable candidate.
        self.assertEqual(stage, 'build')
        out = Path(job['request']['out_dir'])
        build = out/'build'
        build.mkdir(parents=True, exist_ok=True)
        ir = read(out/'work/deck_ir.json')
        write(build/'deck_ir.json', ir)
        write(build/'layout.json', {'assets': {}, 'slides': [
            {'id': page['id'], 'elements': []} for page in ir['slides']]})
        for name in ('candidate.pptx', 'staging.pptx'):
            (build/name).write_bytes(b'NON-PPTX-STATE-TEST-FIXTURE:'+digest(ir).encode())
        write(build/'layout_feedback.json', {'version': '1.0', 'slides': []})
        write(build/'qa_report.json', {'schema_version': '2.0', 'status': 'PASS',
            'counts': {'FAIL': 0, 'WARNING': 0, 'REVIEW': 0, 'INFO': 0}, 'items': [],
            'checks': {'semantic': True, 'geometric': True}, 'ir_sha256': digest(ir),
            'layout_sha256': sha(build/'layout.json'), 'artifact_sha256': sha(build/'candidate.pptx')})
        return [build/name for name in ('candidate.pptx', 'staging.pptx', 'qa_report.json',
                                       'layout.json', 'layout_feedback.json')]

    def start_fast(self):
        with patch('agent.runner.a.execute', side_effect=self.fake_build):
            result = runner.start(str(self.make_source()), str(self.out), 'en', 'group_meeting')
        self.assertEqual(result['status'], 'candidate_ready', result)
        return result

    def protected_snapshot(self):
        paths = [self.out/'work/deck_ir.json']
        paths += [p for p in (self.out/'build').rglob('*') if p.is_file()]
        return {str(p.relative_to(self.out)): (p.read_bytes(), p.stat().st_mtime_ns) for p in paths}

    def assert_protected_unchanged(self, before):
        for relative, state in before.items():
            path = self.out/relative
            self.assertTrue(path.is_file(), relative)
            self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), state, relative)

    def patch_value(self, mode='preflight'):
        descriptor = repair.descriptor(self.out)
        tree = read(self.out/'work/deck_ir.json')['slides'][0]['composition']['layout_tree']
        tree['regions']['body']['gap'] = 'compact'
        return {'schema_version': '1.0', 'mode': mode,
                'base_ir_sha256': descriptor['base_ir_sha256'],
                'base_resources_sha256': descriptor['base_resources_sha256'],
                'slide_updates': [{'id': 'reference-page', 'layout_tree': tree}]}

    def submit_patch(self, job_id, value):
        path = self.out/'work/deck_ir_patch.json'
        write(path, value)
        return runner.advance(job_id, artifact_kind='deck_ir_patch', artifact_path=str(path))


class PatchValidationTests(RepairCase):
    def test_published_schema_is_local_complete_and_rejects_scientific_edits(self):
        from referencing import Registry, Resource
        self.start_fast()
        schema = read(repair.SCHEMA)
        deck_schema = COMPONENT/'schemas/deck-ir.schema.json'
        registry = Registry().with_resources([
            (repair.SCHEMA.as_uri(), Resource.from_contents(schema)),
            (deck_schema.as_uri(), Resource.from_contents(read(deck_schema)))])
        validator = jsonschema.Draft202012Validator({'$ref': repair.SCHEMA.as_uri()}, registry=registry)
        good = self.patch_value()
        validator.validate(good)
        invalid = [dict(good, semantic={'takeaway': 'Changed scientific claim.'}),
                   dict(good, theme={'font_file': 'smaller.ttf'}),
                   dict(good, mode='promote'), dict(good, slides=[])]
        invalid.append({**good, 'asset_updates': {'reference': {'path': 'new.png', 'origin': 'paper'}}})
        invalid.append({**good, 'asset_updates': {'reference': {'path': 'new.png', 'width': 9999}}})
        invalid.append({**good, 'slide_updates': [{'id': 'reference-page', 'layout_tree':
            {'version': '1.0', 'regions': {'body': {'id': 'bad', 'type': 'block', 'ref': 'context',
                                                  'text': 'A hidden data change.'}}}}]})
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(jsonschema.ValidationError):
                validator.validate(value)

    def test_runtime_rejects_unknown_ids_duplicate_ids_and_metadata_edits(self):
        self.start_fast()
        base = read(self.out/'work/deck_ir.json')
        good = self.patch_value()
        variants = []
        unknown_slide = copy.deepcopy(good)
        unknown_slide['slide_updates'][0]['id'] = 'new-scientific-page'
        variants.append(unknown_slide)
        variants.append({**good, 'slide_updates': good['slide_updates']*2})
        variants.append({**good, 'asset_updates': {'new-asset': {'path': str(self.root/'reference.png')}}})
        for key, value in [('origin', 'paper'), ('source_figure', '99'),
                           ('reference_source', 'A different source.'), ('height', 9000)]:
            variants.append({**good, 'asset_updates': {'reference':
                {'path': str(self.root/'reference.png'), key: value}}})
        for value in variants:
            with self.subTest(value=value):
                with self.assertRaises(a.Failure) as caught:
                    repair.validate_patch(value)
                    repair.patched_ir(base, value, self.out/'work/deck_ir_patch.json')
                self.assertEqual(caught.exception.code, 'PATCH_INVALID')


class PatchPreflightTests(RepairCase):
    def test_successful_preflight_uses_original_compiler_without_pptx_or_auto_repair(self):
        from deck_compiler.pipeline import compile_input
        self.start_fast()
        value = self.patch_value()
        before = self.protected_snapshot()
        with patch('deck_compiler.pipeline.compile_input', wraps=compile_input) as compile_call, \
             patch('deck_compiler.officecli.render', side_effect=AssertionError('Preflight must not write PPTX')):
            prepared = repair.preflight(read(self.out/'.totalpipe/job.json'), value, self.out/'work/patch.json')
        self.assertEqual(prepared.summary['status'], 'preflight_passed')
        self.assertEqual(prepared.summary['counts']['FAIL'], 0)
        self.assertEqual(prepared.summary['changed_slide_ids'], ['reference-page'])
        self.assertFalse(compile_call.call_args.kwargs['enable_overflow_repair'])
        self.assertTrue(compile_call.call_args.kwargs['require_visual_design'])
        folder = Path(prepared.summary['qa_report']).parent
        self.assertFalse(list(folder.rglob('*.pptx')))
        self.assert_protected_unchanged(before)

    def test_original_readability_gate_rejects_layout_without_touching_existing_candidate(self):
        self.start_fast()
        value = self.patch_value()
        value['slide_updates'][0]['layout_tree']['regions']['body']['weights'] = [.1, 10]
        before = self.protected_snapshot()
        with self.assertRaises(a.Failure) as caught:
            repair.preflight(read(self.out/'.totalpipe/job.json'), value, self.out/'work/patch.json')
        self.assertEqual(caught.exception.code, 'PATCH_PREFLIGHT_FAILED')
        self.assertGreater(read(Path(caught.exception.log).parent/'qa_report.json')['counts']['FAIL'], 0)
        self.assert_protected_unchanged(before)

    def test_original_native_graphic_width_floor_rejects_a_narrow_repair(self):
        source = self.make_source()
        value = read(source)
        value['assets'] = {}
        comp = value['slides'][0]['composition']
        comp['figure_refs'] = []
        comp['graphics'] = [{'id': 'flow', 'type': 'dag', 'direction': 'horizontal', 'layout': 'chain',
            'nodes': [{'id': 'input', 'shape': 'rect', 'title': 'Input'},
                      {'id': 'output', 'shape': 'rect', 'title': 'Output'}],
            'edges': [{'from': 'input', 'to': 'output'}]}]
        comp['layout_tree']['regions']['body']['children'][0] = {
            'id': 'process-leaf', 'type': 'graphic', 'ref': 'flow'}
        write(source, value)
        with patch('agent.runner.a.execute', side_effect=self.fake_build):
            started = runner.start(str(source), str(self.out), 'en', 'group_meeting')
        self.assertEqual(started['status'], 'candidate_ready', started)
        patch_value = self.patch_value()
        patch_value['slide_updates'][0]['layout_tree']['regions']['body']['weights'] = [.1, 10]
        protected = self.protected_snapshot()
        with self.assertRaises(a.Failure) as caught:
            repair.preflight(read(self.out/'.totalpipe/job.json'), patch_value, self.out/'work/patch.json')
        self.assertEqual(caught.exception.code, 'PATCH_PREFLIGHT_FAILED')
        qa = read(Path(caught.exception.log).parent/'qa_report.json')
        self.assertIn('INSUFFICIENT_DRAWING_SPACE', [item['rule'] for item in qa['items']])
        self.assert_protected_unchanged(protected)

    def test_both_base_hashes_are_required_before_compilation(self):
        self.start_fast()
        original = self.patch_value()
        before = self.protected_snapshot()
        for field in ('base_ir_sha256', 'base_resources_sha256'):
            value = copy.deepcopy(original)
            value[field] = '0'*64
            with self.subTest(field=field):
                with patch('deck_compiler.pipeline.compile_input') as compile_call:
                    with self.assertRaises(a.Failure) as caught:
                        repair.preflight(read(self.out/'.totalpipe/job.json'), value, self.out/'work/patch.json')
                self.assertEqual(caught.exception.code, 'PATCH_STALE')
                compile_call.assert_not_called()
                self.assert_protected_unchanged(before)

    def test_current_asset_byte_change_invalidates_a_prepared_base_hash(self):
        self.start_fast()
        value = self.patch_value()
        before = self.protected_snapshot()
        Image.new('RGB', (1200, 900), '#FF0000').save(self.root/'reference.png')
        with self.assertRaises(a.Failure) as caught:
            repair.preflight(read(self.out/'.totalpipe/job.json'), value, self.out/'work/patch.json')
        self.assertEqual(caught.exception.code, 'PATCH_STALE')
        self.assert_protected_unchanged(before)

    def test_resource_binding_includes_resolved_font_bytes(self):
        self.start_fast()
        snapshot = repair.resource_snapshot(self.out/'work/deck_ir.json')
        fonts = {path: hashed for path, hashed in snapshot.items()
                 if Path(path).suffix.lower() in ('.ttf', '.ttc', '.otf') and hashed is not None}
        self.assertTrue(fonts)
        self.assertTrue(all(Path(path).is_file() and sha(path) == hashed for path, hashed in fonts.items()))

    def test_base_asset_change_during_compile_is_not_committed(self):
        from deck_compiler.pipeline import compile_input
        self.start_fast()
        value = self.patch_value()
        before = self.protected_snapshot()
        def change_after_compile(*args, **kwargs):
            result = compile_input(*args, **kwargs)
            Image.new('RGB', (1200, 900), '#FF0000').save(self.root/'reference.png')
            return result
        with patch('deck_compiler.pipeline.compile_input', side_effect=change_after_compile):
            with self.assertRaises(a.Failure) as caught:
                repair.preflight(read(self.out/'.totalpipe/job.json'), value, self.out/'work/patch.json')
        self.assertEqual(caught.exception.code, 'PATCH_STALE')
        self.assert_protected_unchanged(before)

    def test_replacement_asset_change_during_compile_is_not_committed(self):
        from deck_compiler.pipeline import compile_input
        self.start_fast()
        replacement = self.root/'replacement.png'
        Image.new('RGB', (1200, 900), '#DDE7EB').save(replacement)
        value = self.patch_value()
        value['asset_updates'] = {'reference': {'path': str(replacement)}}
        before = self.protected_snapshot()
        def change_after_compile(*args, **kwargs):
            result = compile_input(*args, **kwargs)
            Image.new('RGB', (1200, 900), '#FF0000').save(replacement)
            return result
        with patch('deck_compiler.pipeline.compile_input', side_effect=change_after_compile):
            with self.assertRaises(a.Failure) as caught:
                repair.preflight(read(self.out/'.totalpipe/job.json'), value, self.out/'work/patch.json')
        self.assertEqual(caught.exception.code, 'PATCH_STALE')
        self.assert_protected_unchanged(before)

    def test_layout_cannot_change_visible_panel_text_or_reassign_data_between_groups(self):
        base = read(self.make_source())
        tree = {'version': '1.0', 'regions': {'body': {
            'id': 'comparison', 'type': 'columns', 'children': [
                {'id': 'control', 'type': 'panel', 'title': 'Control',
                 'body': {'id': 'control-data', 'type': 'figure', 'ref': 0}},
                {'id': 'treatment', 'type': 'panel', 'title': 'Treatment',
                 'body': {'id': 'treatment-data', 'type': 'block', 'ref': 'context'}}]}}}
        base['slides'][0]['composition']['layout_tree'] = copy.deepcopy(tree)
        changed_title = copy.deepcopy(tree)
        changed_title['regions']['body']['children'][0]['title'] = 'Control reached 999 units'
        reassigned = copy.deepcopy(tree)
        panels = reassigned['regions']['body']['children']
        panels[0]['body'], panels[1]['body'] = panels[1]['body'], panels[0]['body']
        for replacement in (changed_title, reassigned):
            value = {'slide_updates': [{'id': 'reference-page', 'layout_tree': replacement}]}
            with self.subTest(tree=replacement):
                with self.assertRaises(a.Failure) as caught:
                    repair.patched_ir(base, value, self.root/'patch.json')
                self.assertEqual(caught.exception.code, 'PATCH_INVALID')
        moved = copy.deepcopy(tree)
        moved['regions']['body']['children'].reverse()
        value, changed, _ = repair.patched_ir(base, {'slide_updates': [
            {'id': 'reference-page', 'layout_tree': moved}]}, self.root/'patch.json')
        self.assertEqual(changed, ['reference-page'])
        self.assertEqual(value['slides'][0]['semantic'], base['slides'][0]['semantic'])

    def test_asset_dimensions_come_from_the_image_and_provenance_stays_unchanged(self):
        base = read(self.make_source())
        replacement = self.root/'replacement.png'
        Image.new('RGB', (1600, 1100), '#DDE7EB').save(replacement)
        value, changed, dimensions = repair.patched_ir(base,
            {'asset_updates': {'reference': {'path': 'replacement.png'}}}, self.root/'patch.json')
        self.assertEqual(dimensions, {'reference': [1600, 1100]})
        self.assertEqual(changed, ['reference-page'])
        self.assertEqual(value['assets']['reference']['path'], str(replacement))
        self.assertEqual({k: v for k, v in value['assets']['reference'].items() if k != 'path'},
                         {k: v for k, v in base['assets']['reference'].items() if k != 'path'})
        self.assertEqual(value['slides'], base['slides'])

    def test_asset_update_rejects_missing_corrupt_and_non_raster_files(self):
        base = read(self.make_source())
        corrupt = self.root/'corrupt.png'
        corrupt.write_bytes(b'not an image')
        vector = self.root/'figure.svg'
        vector.write_text('<svg xmlns="http://www.w3.org/2000/svg"><rect width="100" height="100"/></svg>')
        for path in (self.root/'missing.png', corrupt, vector):
            with self.subTest(path=path):
                with self.assertRaises(a.Failure) as caught:
                    repair.patched_ir(base, {'asset_updates': {'reference': {'path': str(path)}}}, self.root/'patch.json')
                self.assertEqual(caught.exception.code, 'PATCH_INVALID')


class PatchRunnerTests(RepairCase):
    def test_four_tools_expose_a_small_repair_descriptor_and_preflight_summary(self):
        from agent.mcp_server import transport
        result = self.start_fast()
        self.assertEqual(len(transport.TOOLS), 4)
        self.assertIn('deck_ir_patch', transport.TOOLS['totalpipe_advance']['inputSchema']
                      ['properties']['artifact_kind']['enum'])
        descriptor = result['repair']
        self.assertEqual(descriptor['artifact_kind'], 'deck_ir_patch')
        self.assertTrue(Path(descriptor['schema_path']).is_file())
        self.assertEqual(descriptor['base_ir_sha256'], sha(self.out/'work/deck_ir.json'))
        self.assertEqual(descriptor['base_resources_sha256'], digest(repair.resource_snapshot(self.out/'work/deck_ir.json')))
        protected = self.protected_snapshot()
        with patch('agent.runner.a.execute', side_effect=AssertionError('Preflight cannot rebuild')):
            response = self.submit_patch(result['job_id'], self.patch_value())
        self.assertEqual(response['repair_result']['status'], 'preflight_passed')
        self.assertEqual(response['repair_result']['changed_slide_ids'], ['reference-page'])
        self.assertNotIn('slides', response)
        self.assertNotIn('assets', response)
        self.assertNotIn('The original reference image and its source must remain identifiable.', json.dumps(response))
        self.assertLess(len(json.dumps(response).encode()), 8000)
        self.assert_protected_unchanged(protected)

    def test_rejected_optional_patch_preserves_candidate_qa_authorization_and_status(self):
        result = self.start_fast()
        state = self.out/'.totalpipe/job.json'
        job = read(state)
        job['inputs'] = {'model': 'explicit-user-model', 'reasoning_effort': 'high', 'selected_by_user': True}
        write(state, job)
        write(self.out/'work/story_plan.json', {'planner': copy.deepcopy(job['inputs']),
              'main_message': 'Preserve the existing independently authored scientific story.'})
        story_before = (self.out/'work/story_plan.json').read_bytes()
        protected = self.protected_snapshot()
        invalid = {**self.patch_value(), 'semantic': {'takeaway': 'A replacement scientific claim.'}}
        for _ in range(2):
            with patch('agent.runner.a.execute', side_effect=AssertionError('A rejected patch cannot rebuild')):
                response = self.submit_patch(result['job_id'], invalid)
            self.assertEqual(response['repair_result']['code'], 'PATCH_INVALID')
            self.assertEqual(response['repair_result']['status'], 'rejected')
            self.assertTrue(response['repair_result']['candidate_unchanged'])
            self.assert_protected_unchanged(protected)
        after = read(state)
        self.assertEqual(after['inputs'], job['inputs'])
        self.assertEqual(after['request'], job['request'])
        self.assertEqual(after['checkpoints'], job['checkpoints'])
        self.assertEqual(sum(len(items) for items in after['repair_attempts'].values()), 1)
        self.assertEqual((self.out/'work/story_plan.json').read_bytes(), story_before)
        current = runner.status(result['job_id'])
        self.assertEqual(current['status'], 'candidate_ready')
        self.assertFalse(current['blocking'])
        self.assertFalse((self.out/'build/qa_acknowledgements.json').exists())

    def test_apply_rebuilds_only_downstream_and_repeated_patch_is_idempotent(self):
        result = self.start_fast()
        state = self.out/'.totalpipe/job.json'
        job = read(state)
        job['inputs'] = {'model': 'explicit-user-model', 'reasoning_effort': 'high', 'selected_by_user': True}
        write(state, job)
        original = read(self.out/'work/deck_ir.json')
        story_path = self.out/'work/story_plan.json'
        design_path = self.out/'work/page_design.json'
        write(story_path, {'planner': copy.deepcopy(job['inputs']), 'story': [], 'ending': {}})
        write(design_path, {'schema_version': '1.0', 'deck_id': 'reference-fixture',
              'setting': {'audience': 'Test peers', 'occasion': 'group-meeting', 'reading': 'spoken'},
              'pages': [{'id': 'reference-page', 'role': 'context', 'claim': original['slides'][0]['semantic']['title'],
                         'items': [], 'anchor': {'kind': 'figure', 'why': 'A supplied reference.'},
                         'shape': 'Image beside unchanged context.', 'rationale': 'Synthetic preservation fixture.'}]})
        upstream_files = {path: (path.read_bytes(), path.stat().st_mtime_ns)
                          for path in (story_path, design_path)}
        value = self.patch_value(mode='apply')
        before = sha(self.out/'build/candidate.pptx')
        with patch('agent.runner.a.execute', side_effect=self.fake_build) as build:
            response = self.submit_patch(result['job_id'], value)
        self.assertEqual(response['status'], 'candidate_ready', response)
        self.assertEqual(response['repair_result']['status'], 'accepted')
        self.assertEqual(build.call_count, 1)
        self.assertEqual(build.call_args.args[0], 'build')
        changed = read(self.out/'work/deck_ir.json')
        self.assertEqual(changed['slides'][0]['semantic'], original['slides'][0]['semantic'])
        self.assertEqual(changed['theme'], original['theme'])
        self.assertEqual(changed['assets'], original['assets'])
        self.assertNotEqual(sha(self.out/'build/candidate.pptx'), before)
        self.assertEqual(read(state)['inputs'], job['inputs'])
        self.assertEqual(read(state)['request'], job['request'])
        self.assertEqual({path: (path.read_bytes(), path.stat().st_mtime_ns) for path in upstream_files}, upstream_files)
        protected = self.protected_snapshot()
        with patch('agent.runner.a.execute', side_effect=AssertionError('Same patch cannot rebuild')):
            repeated = self.submit_patch(result['job_id'], value)
        self.assertEqual(repeated['repair_result']['status'], 'already_accepted')
        self.assert_protected_unchanged(protected)

    def test_failed_geometry_preflight_does_not_remove_existing_candidate_or_qa(self):
        result = self.start_fast()
        protected = self.protected_snapshot()
        value = self.patch_value(mode='apply')
        value['slide_updates'][0]['layout_tree']['regions']['body']['weights'] = [.1, 10]
        with patch('agent.runner.a.execute', side_effect=AssertionError('Rejected preflight cannot build')):
            response = self.submit_patch(result['job_id'], value)
        self.assertEqual(response['repair_result']['code'], 'PATCH_PREFLIGHT_FAILED')
        self.assert_protected_unchanged(protected)
        self.assertEqual(runner.status(result['job_id'])['status'], 'candidate_ready')

    def test_patch_requires_canonical_ir_and_cannot_be_combined_with_model_input(self):
        result = runner.start(str(self.source), str(self.out), 'en', 'group_meeting')
        self.assertNotIn('repair', result)
        value = {'schema_version': '1.0', 'mode': 'preflight', 'base_ir_sha256': '0'*64,
                 'base_resources_sha256': '0'*64, 'asset_updates': {'reference': {'path': 'a.png'}}}
        response = self.submit_patch(result['job_id'], value)
        self.assertEqual(response['repair_result']['code'], 'PATCH_STAGE_MISMATCH')
        self.assertFalse((self.out/'work/deck_ir.json').exists())
        with self.assertRaises(ValueError):
            runner.advance(result['job_id'], artifact_kind='deck_ir_patch',
                           artifact_path=str(self.out/'work/deck_ir_patch.json'),
                           inputs={'model': 'another-model', 'reasoning_effort': 'high', 'selected_by_user': True})

    def test_canonical_write_failure_keeps_the_previous_checkpoints(self):
        result = self.start_fast()
        state = self.out/'.totalpipe/job.json'
        before_job = read(state)
        protected = self.protected_snapshot()
        canonical = self.out/'work/deck_ir.json'
        persist = a.persist_ir
        def fail_only_canonical(value, source, destination):
            if Path(destination) == canonical:
                raise OSError('Simulated atomic canonical write failure')
            return persist(value, source, destination)
        with patch('agent.runner.a.persist_ir', side_effect=fail_only_canonical), \
             patch('agent.runner.a.execute', side_effect=AssertionError('Failed commit cannot rebuild')):
            response = self.submit_patch(result['job_id'], self.patch_value(mode='apply'))
        self.assertTrue(response['blocking'])
        self.assertEqual(response['repair_result']['code'], 'PATCH_COMMIT_FAILED')
        self.assertEqual(read(state)['checkpoints'], before_job['checkpoints'])
        self.assertFalse(read(state).get('repair_attempts'))
        self.assert_protected_unchanged(protected)

    def test_repeated_geometry_rejection_reuses_its_current_feedback_without_compiling(self):
        from deck_compiler.pipeline import compile_input
        result = self.start_fast()
        value = self.patch_value()
        value['slide_updates'][0]['layout_tree']['regions']['body']['weights'] = [.1, 10]
        protected = self.protected_snapshot()
        with patch('deck_compiler.pipeline.compile_input', wraps=compile_input) as compile_call:
            first = self.submit_patch(result['job_id'], value)
            repeated = self.submit_patch(result['job_id'], value)
        self.assertEqual(first['repair_result']['code'], 'PATCH_PREFLIGHT_FAILED')
        self.assertEqual(repeated['repair_result']['code'], 'PATCH_PREFLIGHT_FAILED')
        self.assertTrue(repeated['repair_result']['reused_preflight'])
        self.assertEqual(compile_call.call_count, 1)
        self.assertEqual(repeated['repair_result']['feedback_path'], first['repair_result']['feedback_path'])
        self.assertTrue(Path(repeated['repair_result']['feedback_path']).is_file())
        self.assertEqual(sum(len(items) for items in read(self.out/'.totalpipe/job.json')['repair_attempts'].values()), 1)
        self.assert_protected_unchanged(protected)

    def test_changed_replacement_bytes_trigger_new_measurement_and_revision(self):
        from deck_compiler.pipeline import compile_input
        result = self.start_fast()
        replacement = self.root/'too-flat.png'
        value = self.patch_value()
        value['asset_updates'] = {'reference': {'path': str(replacement)}}
        with patch('deck_compiler.pipeline.compile_input', wraps=compile_input) as compile_call:
            Image.new('RGB', (2400, 40), '#DDE7EB').save(replacement)
            first = self.submit_patch(result['job_id'], value)
            Image.new('RGB', (2600, 45), '#DDE7EB').save(replacement)
            revised = self.submit_patch(result['job_id'], value)
            repeated = self.submit_patch(result['job_id'], value)
        self.assertEqual(first['repair_result']['code'], 'PATCH_PREFLIGHT_FAILED')
        self.assertEqual(revised['repair_result']['code'], 'PATCH_PREFLIGHT_FAILED')
        self.assertEqual(repeated['repair_result']['feedback_path'], revised['repair_result']['feedback_path'])
        self.assertNotEqual(first['repair_result']['feedback_path'], revised['repair_result']['feedback_path'])
        self.assertEqual(compile_call.call_count, 2)
        self.assertEqual(sum(len(items) for items in read(self.out/'.totalpipe/job.json')['repair_attempts'].values()), 2)

    def test_deleted_feedback_cannot_be_reused_for_the_same_rejected_patch(self):
        from deck_compiler.pipeline import compile_input
        result = self.start_fast()
        value = self.patch_value()
        value['slide_updates'][0]['layout_tree']['regions']['body']['weights'] = [.1, 10]
        with patch('deck_compiler.pipeline.compile_input', wraps=compile_input) as compile_call:
            first = self.submit_patch(result['job_id'], value)
            Path(first['repair_result']['feedback_path']).unlink()
            repeated = self.submit_patch(result['job_id'], value)
        self.assertEqual(compile_call.call_count, 2)
        self.assertNotEqual(repeated['repair_result']['feedback_path'], first['repair_result']['feedback_path'])
        self.assertTrue(Path(repeated['repair_result']['feedback_path']).is_file())
        self.assertEqual(sum(len(items) for items in read(self.out/'.totalpipe/job.json')['repair_attempts'].values()), 1)

    def test_changed_base_bytes_cannot_reuse_a_geometry_rejection(self):
        from deck_compiler.pipeline import compile_input
        result = self.start_fast()
        value = self.patch_value()
        value['slide_updates'][0]['layout_tree']['regions']['body']['weights'] = [.1, 10]
        with patch('deck_compiler.pipeline.compile_input', wraps=compile_input) as compile_call:
            first = self.submit_patch(result['job_id'], value)
            Image.new('RGB', (1200, 900), '#FF0000').save(self.root/'reference.png')
            stale = self.submit_patch(result['job_id'], value)
            refreshed = copy.deepcopy(value)
            refreshed['base_resources_sha256'] = repair.descriptor(self.out)['base_resources_sha256']
            revised = self.submit_patch(result['job_id'], refreshed)
        self.assertEqual(first['repair_result']['code'], 'PATCH_PREFLIGHT_FAILED')
        self.assertEqual(stale['repair_result']['code'], 'PATCH_STALE')
        self.assertEqual(revised['repair_result']['code'], 'PATCH_PREFLIGHT_FAILED')
        self.assertEqual(compile_call.call_count, 2)

    def test_temporary_preflight_dependency_failure_is_retryable_without_budget_or_cache(self):
        from deck_compiler.pipeline import compile_input
        result = self.start_fast()
        value = self.patch_value()
        attempts = 0
        def unavailable_then_recovered(*args, **kwargs):
            nonlocal attempts
            attempts += 1
            if attempts <= 3:
                raise OSError('Synthetic temporary compiler dependency failure')
            return compile_input(*args, **kwargs)
        with patch('deck_compiler.pipeline.compile_input', side_effect=unavailable_then_recovered):
            for _ in range(3):
                unavailable = self.submit_patch(result['job_id'], value)
                self.assertTrue(unavailable['blocking'])
                self.assertEqual(unavailable['repair_result']['code'], 'PATCH_PREFLIGHT_UNAVAILABLE')
                self.assertEqual(unavailable['next_action']['type'], 'resolve_dependency')
            recovered = self.submit_patch(result['job_id'], value)
        self.assertEqual(attempts, 4)
        self.assertEqual(recovered['repair_result']['status'], 'preflight_passed')
        self.assertFalse(read(self.out/'.totalpipe/job.json').get('repair_attempts'))

    def test_three_distinct_rejections_require_full_replan_without_removing_candidate(self):
        result = self.start_fast()
        protected = self.protected_snapshot()
        good = self.patch_value()
        for index in range(3):
            rejected = self.submit_patch(result['job_id'], {**good, f'forbidden-{index}': 'scientific edit'})
            self.assertEqual(rejected['repair_result']['code'], 'PATCH_INVALID')
        limited = self.submit_patch(result['job_id'], good)
        self.assertEqual(limited['repair_result']['code'], 'PATCH_LIMIT_REACHED')
        self.assertEqual(limited['next_action']['type'], 'replan')
        self.assertEqual(limited['next_action']['artifact_kind'], 'deck_ir')
        self.assertNotEqual(limited['next_action']['instructions_path'], str(repair.SCHEMA))
        self.assertTrue(Path(limited['next_action']['instructions_path']).is_file())
        self.assert_protected_unchanged(protected)

    def test_new_replacement_bytes_count_as_a_revision_but_same_rejection_does_not(self):
        result = self.start_fast()
        replacement = self.root/'corrupt.png'
        replacement.write_bytes(b'broken-image-first-revision')
        value = self.patch_value()
        value['asset_updates'] = {'reference': {'path': str(replacement)}}
        for contents in (b'broken-image-first-revision', b'broken-image-second-revision',
                         b'broken-image-second-revision'):
            replacement.write_bytes(contents)
            rejected = self.submit_patch(result['job_id'], value)
            self.assertEqual(rejected['repair_result']['code'], 'PATCH_INVALID')
        job = read(self.out/'.totalpipe/job.json')
        self.assertEqual(sum(len(items) for items in job['repair_attempts'].values()), 2)

    def test_stale_hash_does_not_consume_a_scientific_revision_attempt(self):
        result = self.start_fast()
        value = self.patch_value()
        value['base_ir_sha256'] = '0'*64
        rejected = self.submit_patch(result['job_id'], value)
        self.assertEqual(rejected['repair_result']['code'], 'PATCH_STALE')
        self.assertFalse(read(self.out/'.totalpipe/job.json').get('repair_attempts'))

    def test_missing_current_image_can_be_rebound_to_its_relocated_raster(self):
        result = self.start_fast()
        replacement = self.root/'relocated.png'
        shutil.copyfile(self.root/'reference.png', replacement)
        (self.root/'reference.png').unlink()
        self.assertEqual(runner.status(result['job_id'])['stage'], 'deck_ir')
        value = self.patch_value(mode='apply')
        value['asset_updates'] = {'reference': {'path': str(replacement)}}
        with patch('agent.runner.a.execute', side_effect=self.fake_build):
            repaired = self.submit_patch(result['job_id'], value)
        self.assertEqual(repaired['status'], 'candidate_ready', repaired)
        self.assertEqual(read(self.out/'work/deck_ir.json')['assets']['reference']['path'], str(replacement))


class PatchOfficeIntegrationTests(RepairCase):
    @unittest.skipUnless(shutil.which('officecli'), 'OfficeCLI required')
    def test_real_local_preflight_apply_and_rejection_keep_scientific_review_unacked(self):
        result = runner.start(str(self.make_source()), str(self.out), 'en', 'group_meeting')
        self.assertEqual(result['status'], 'candidate_ready', result)
        self.assertEqual(result['qa']['counts']['FAIL'], 0)
        review_ids = [item['id'] for item in read(self.out/'build/qa_report.json')['items']
                      if item['severity'] == 'REVIEW']
        self.assertTrue(review_ids)
        # Explicit synthetic review records exercise stale-ack invalidation. This is not a
        # scientific acceptance claim and is never an automatic acknowledgement by repair.
        acknowledged = runner.advance(result['job_id'], acknowledge={
            'reviewer': 'Synthetic test reviewer', 'note': 'Fixture for stale-ack invalidation only.',
            'review_ids': review_ids})
        self.assertEqual(acknowledged['qa']['unacked_count'], 0)
        ack_path = self.out/'build/qa_acknowledgements.json'
        ack_before = ack_path.read_bytes()
        protected = self.protected_snapshot()
        value = self.patch_value()
        with patch('deck_compiler.officecli.render', side_effect=AssertionError('Preflight cannot write PPTX')):
            dry_run = self.submit_patch(result['job_id'], value)
        self.assertEqual(dry_run['repair_result']['status'], 'preflight_passed', dry_run)
        self.assert_protected_unchanged(protected)
        replacement = self.root/'relocated-reference.png'
        shutil.copyfile(self.root/'reference.png', replacement)
        value.update(mode='apply', asset_updates={'reference': {'path': str(replacement)}})
        applied = self.submit_patch(result['job_id'], value)
        self.assertEqual(applied['status'], 'candidate_ready', applied)
        self.assertEqual(applied['repair_result']['status'], 'accepted')
        self.assertEqual(applied['repair_result']['asset_dimensions'], {'reference': [1200, 900]})
        self.assertTrue(applied['repair_result']['scientific_image_review_required'])
        self.assertEqual(applied['qa']['counts']['FAIL'], 0)
        self.assertGreater(applied['qa']['unacked_count'], 0)
        self.assertEqual(read(self.out/'build/qa_report.json')['acked_count'], 0)
        self.assertEqual(ack_path.read_bytes(), ack_before)
        self.assertFalse((self.out/'build/final.pptx').exists())
        protected = self.protected_snapshot()
        bad = {**self.patch_value(mode='apply'), 'theme': {'font_file': 'tiny.ttf'}}
        rejected = self.submit_patch(result['job_id'], bad)
        self.assertEqual(rejected['repair_result']['code'], 'PATCH_INVALID')
        self.assert_protected_unchanged(protected)
        self.assertEqual(runner.status(result['job_id'])['status'], 'candidate_ready')
