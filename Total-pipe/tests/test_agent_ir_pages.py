"""Measured pages and deterministic bindings preserve scientific gates and passing work."""
import copy
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from agent import COMPONENT, adapters as a, runner
from agent.ir_pages import bind_sources, prepare_prompts
from agent.state import read, write, sha
from agent_fixture import AgentCase
from deck_compiler.crops import verified_source
from deck_compiler.layout import compile_deck


class PageIRTests(AgentCase):
    def prepare(self):
        with patch('agent.runner.a.execute', side_effect=a.Failure(
                'INSUFFICIENT_DRAWING_SPACE', 'Synthetic test requests page authoring.', 'replan', 'deck_ir')):
            result = runner.start(str(COMPONENT/'examples/native-bullets.deck_ir.json'), str(self.out), 'en', 'group_meeting')
        work = self.out/'work'
        write(work/'story_plan.json', {'story': [{'answer': 'The calibrated response is reproducible.',
            'key_points': ['The independent control supports the observation.'], 'evidence': ['EV0001', 'EV0002']}], 'ending': {}})
        write(work/'page_design.json', {'schema_version': '1.1', 'pages': [
            {'id': 'P1', 'content_refs': ['S1.answer'], 'design': 'Draw the calibrated response.'},
            {'id': 'P2', 'content_refs': ['S1.key_points[0]'], 'design': 'Explain the independent control.'}]})
        self.job_id = result['job_id']
        self.value = read(work/'deck_ir.json')
        self.value['slides'] = [copy.deepcopy(self.value['slides'][0])]
        return work

    def page(self, work, sid, broken=False):
        value = copy.deepcopy(self.value)
        slide = value['slides'][0]
        slide['id'] = sid
        slide['semantic'].pop('evidence_refs', None)
        slide['semantic'].pop('speaker_notes', None)
        if broken:
            slide['composition'] = {'archetype': 'composite-research', 'figure_refs': [],
                'blocks': [{'id': 'wide', 'component': 'formula', 'text': '+'.join(['x']*100)}],
                'layout_tree': {'version': '1.0', 'regions': {'body': {'id': 'leaf', 'type': 'block', 'ref': 'wide'}}}}
        path = work/'pages'/(sid+'.json')
        write(path, value)
        return path

    def submit(self, path, **kwargs):
        return runner.advance(self.job_id, artifact_kind='deck_ir_page', artifact_path=str(path), **kwargs)

    def test_only_the_failed_page_is_revised_and_unchanged_pages_reuse_measurement(self):
        work = self.prepare()
        p1 = self.page(work, 'P1')
        result = self.submit(p1)
        self.assertEqual(result['page_result']['status'], 'PASS', result)
        self.assertEqual(result['page_result']['pending_pages'], ['P2'])
        cached = work/'ir_pages/P1.json'
        before = (cached.read_bytes(), cached.stat().st_mtime_ns)
        bound = read(cached)['slides'][0]['semantic']
        self.assertEqual(bound['evidence_refs'], ['EV0001', 'EV0002'])
        self.assertIn('The calibrated response is reproducible.', bound['speaker_notes'])
        with patch('deck_compiler.pipeline.compile_input', side_effect=AssertionError('Unchanged page must reuse geometry')):
            self.assertTrue(self.submit(p1)['page_result']['reused_measurement'])
        self.assertEqual(self.submit(self.page(work, 'P2', broken=True))['page_result']['status'], 'FAIL')
        self.assertEqual(before, (cached.read_bytes(), cached.stat().st_mtime_ns))
        with patch('agent.runner.a.execute', side_effect=a.Failure('TEST_STOP', 'Synthetic downstream test stop.')):
            self.submit(self.page(work, 'P2'))
        assembled = read(work/'deck_ir.json')
        self.assertEqual([s['id'] for s in assembled['slides']], ['P1', 'P2'])
        a.check_ir(assembled, design=a.load_design(work))
        self.assertEqual(before, (cached.read_bytes(), cached.stat().st_mtime_ns))

    def test_page_preflight_is_read_only_and_failure_budgets_are_per_page(self):
        work = self.prepare()
        path = self.page(work, 'P1', broken=True)
        before = (self.out/'.totalpipe/job.json').read_bytes()
        self.assertEqual(self.submit(path, preflight=True)['page_result']['status'], 'FAIL')
        self.assertEqual(before, (self.out/'.totalpipe/job.json').read_bytes())
        for i in range(3):
            value = read(path)
            value['slides'][0]['semantic']['speaker_notes'] = f'Synthetic revision {i}.'
            write(path, value)
            self.assertEqual(self.submit(path)['page_result']['status'], 'FAIL')
        self.assertEqual(self.submit(path)['page_result']['status'], 'revision_limit')
        self.assertEqual(self.submit(self.page(work, 'P2'))['page_result']['status'], 'PASS')

    def test_shared_header_change_cannot_silently_restyle_cached_pages(self):
        work = self.prepare()
        self.submit(self.page(work, 'P1'))
        path = self.page(work, 'P2')
        value = read(path)
        value['theme']['accent'] = '#112233'
        write(path, value)
        result = self.submit(path)['page_result']
        self.assertEqual(result['status'], 'FAIL')
        self.assertIn('PAGE_HEADER_MISMATCH', [i.get('code') for i in result['issues']])


class SourceBindingTests(AgentCase):
    def test_page_prompt_contains_assigned_story_and_its_complete_evidence(self):
        work = self.out/'work'
        design = {'schema_version': '1.1', 'pages': [{'id': 'P1', 'content_refs': ['S1.answer'], 'design': 'Draw the mechanism.'}]}
        prompt = {'instructions': 'Complete implementation instructions.', 'story': {'story': [
            {'answer': 'The measured response changes.', 'evidence': ['EV0001', 'EV0002']},
            {'answer': 'Unrelated node.', 'evidence': ['EV0003']}]},
            'evidence': {'EV0001': 'Measurement.', 'EV0002': 'Control.', 'EV0003': 'Other.'}}
        prepare_prompts(work, design, prompt)
        pack = read(work/'ir_page_prompts/P1.json')
        self.assertEqual(pack['page_design']['items'][0]['text'], 'The measured response changes.')
        self.assertEqual(set(pack['evidence']), {'EV0001', 'EV0002'})
        self.assertEqual(len(pack['story_context']), 1)
        self.assertTrue(Path(pack['schema_path']).is_file())

    def test_inventory_paths_notes_ids_and_exact_crop_lineage_are_bound(self):
        work = self.out/'work'
        source = self.out/'evidence/sup_images/S14.png'
        source.parent.mkdir(parents=True)
        original = Image.new('RGB', (40, 30), '#123456')
        original.putpixel((12, 10), (255, 0, 0))
        original.save(source)
        cropped = self.root/'panel.png'
        original.crop((10, 5, 30, 25)).save(cropped)
        workflow = self.out/'evidence/workflow.json'
        write(workflow, {'artifacts': {'figure_assets_metadata': [
            {'asset_id': 's14', 'path': 'sup_images/S14.png'}]}})
        write(work/'evidence_pointer.json', {'workflow': str(workflow)})
        value = read(COMPONENT/'examples/native-bullets.deck_ir.json')
        value['slides'] = [value['slides'][0]]
        value['slides'][0]['id'] = 'P1'
        value['assets'] = {'panel': {'path': str(cropped), 'crop': {'source_path': 's14', 'box': [10, 5, 30, 25]}}}
        value['slides'][0]['composition']['figure_refs'] = [
            {'asset_id': 'panel', 'source_figure': 'S14a', 'caption': 'Supplementary Fig. S14a'}]
        design = {'schema_version': '1.1', '_content_bound': True, 'pages': [
            {'id': 'P1', 'figures': ['sup_images/S14.png'], 'items': []}]}
        bound = bind_sources(value, design, work, work/'page.json')
        asset = bound['assets']['panel']
        self.assertEqual(asset['source_figure'], 'S14a')
        self.assertEqual(asset['crop']['source_sha256'], sha(source))
        self.assertEqual(verified_source(asset), str(source))
        a.check_design_realization(bound, design)
        write(work/'story_plan.json', {'story': [], 'ending': {}})
        write(work/'page_design.json', {'schema_version': '1.1', 'pages': [
            {'id': 'P1', 'content_refs': [], 'figures': ['s14'], 'design': 'Show the selected panel.'}]})
        a.check_design_realization(bound, a.load_design(work))
        from agent.ir_pages import _stamp
        frozen = work/'bound.json'
        a.persist_ir(bound, work/'page.json', frozen)
        before = _stamp(frozen)
        original.putpixel((0, 0), (0, 255, 0))
        original.save(source)
        self.assertNotEqual(before, _stamp(frozen))
        original.putpixel((0, 0), (18, 52, 86))
        original.save(source)
        changed = Image.open(cropped).copy()
        changed.putpixel((2, 2), (255, 255, 255))
        changed.save(cropped)
        with self.assertRaisesRegex(ValueError, 'pixels differ'):
            verified_source(asset)
        with self.assertRaises(a.Failure):
            a.check_design_realization(bound, design)

    def test_compiler_rejects_forged_crop_even_without_page_design(self):
        source, crop = self.root/'original.png', self.root/'crop.png'
        Image.new('RGB', (40, 30), 'red').save(source)
        Image.new('RGB', (20, 20), 'blue').save(crop)
        value = read(COMPONENT/'examples/native-bullets.deck_ir.json')
        value['assets'] = {'forged': {'path': str(crop), 'source_figure': 'S14', 'crop': {
            'source_path': str(source), 'source_sha256': sha(source), 'box': [0, 0, 20, 20]}}}
        _, issues = compile_deck(value, self.root)
        self.assertTrue(any(i['severity'] == 'FAIL' and 'pixels differ' in i['message'] for i in issues))
