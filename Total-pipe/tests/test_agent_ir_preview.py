"""Preview isolation, page cache invalidation and failure reporting; renderer is mocked here."""
import copy
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from agent import COMPONENT, adapters as a, runner
from agent.state import read, write
from agent_fixture import AgentCase


class IRPreviewTests(AgentCase):
    def prepare(self):
        with patch('agent.runner.a.execute', side_effect=a.Failure(
                'INSUFFICIENT_DRAWING_SPACE', 'Fixture stops at draft IR.', 'replan', 'deck_ir')):
            result = runner.start(str(COMPONENT/'examples/native-bullets.deck_ir.json'), str(self.out), 'en', 'group_meeting')
        self.job_id = result['job_id']
        self.path = self.out/'work/deck_ir.json'
        self.value = read(self.path)
        self.value['slides'] = [copy.deepcopy(self.value['slides'][0]) for _ in range(2)]
        for i, slide in enumerate(self.value['slides'], 1):
            slide['id'] = f'P{i}'
        write(self.path, self.value)
        self.render = self.enter(patch('deck_compiler.officecli.render', side_effect=self.fake_render))
        self.screenshot = self.enter(patch('deck_compiler.officecli._run', side_effect=self.fake_screenshot))
        self.enter(patch('deck_compiler.officecli.preflight', return_value={'version': 'test', 'schema_sha256': 'test'}))
        return (self.out/'.totalpipe/job.json').read_bytes()

    def enter(self, context):
        value = context.start()
        self.addCleanup(context.stop)
        return value

    @staticmethod
    def fake_render(layout, pptx):
        pptx.write_bytes(b'synthetic renderer output; unit tests only')

    @staticmethod
    def fake_screenshot(*args, **kwargs):
        output = Path(args[args.index('--out')+1])
        Image.new('RGB', (1280, 720), 'white').save(output)
        return {'success': True}

    def preview(self, **request):
        return runner.advance(self.job_id, preview={'artifact_path': str(self.path), **request})['preview_result']

    def test_preview_does_not_accept_or_change_job_candidate_or_qa(self):
        state = self.prepare()
        build = self.out/'build'
        build.mkdir(exist_ok=True)
        (build/'candidate.pptx').write_bytes(b'old candidate')
        (build/'qa_report.json').write_text('{}')
        result = self.preview(slide_ids=['P1'])
        self.assertEqual(result['status'], 'PASS', result)
        self.assertEqual(state, (self.out/'.totalpipe/job.json').read_bytes())
        self.assertEqual((build/'candidate.pptx').read_bytes(), b'old candidate')
        self.assertEqual((build/'qa_report.json').read_text(), '{}')
        self.assertFalse(result['powerpoint_ui_review'])
        self.assertTrue(Path(result['pages'][0]['png']).is_file())
        self.assertTrue(runner.status(self.job_id)['ir_preview'])

    def test_only_changed_page_renders_and_corrupt_cached_outputs_are_rebuilt(self):
        self.prepare()
        first = self.preview()
        self.assertEqual(self.render.call_count, 2)
        self.value['slides'][0]['semantic']['speaker_notes'] += '\nChanged P1 notes.'
        write(self.path, self.value)
        second = self.preview()
        self.assertEqual(self.render.call_count, 3)
        self.assertFalse(second['pages'][0]['reused'])
        self.assertTrue(second['pages'][1]['reused'])
        self.assertEqual(first['pages'][1]['png'], second['pages'][1]['png'])
        Path(second['pages'][1]['png']).write_bytes(b'corrupt')
        third = self.preview(slide_ids=['P2'])
        self.assertFalse(third['pages'][0]['reused'])
        self.assertEqual(self.render.call_count, 4)

    def test_failed_scientific_checks_remain_fail_and_are_written_to_preview_report(self):
        state = self.prepare()
        self.value['slides'][0]['semantic'].pop('purpose')
        write(self.path, self.value)
        result = self.preview(slide_ids=['P1'])
        self.assertEqual(result['status'], 'FAIL', result)
        self.assertGreater(result['pages'][0]['counts']['FAIL'], 0)
        report = read(result['pages'][0]['qa_report'])
        self.assertEqual(report['counts'], result['pages'][0]['counts'])
        self.assertEqual(state, (self.out/'.totalpipe/job.json').read_bytes())

    def test_source_change_during_render_cannot_produce_a_current_cached_preview(self):
        state = self.prepare()
        def mutate(*args, **kwargs):
            self.fake_screenshot(*args, **kwargs)
            self.path.write_text(self.path.read_text()+'\n')
        self.screenshot.side_effect = mutate
        result = self.preview(slide_ids=['P1'])
        self.assertEqual(result['status'], 'FAIL', result)
        self.assertIn('changed during rendering', result['message'])
        self.assertEqual(state, (self.out/'.totalpipe/job.json').read_bytes())
        self.assertFalse(list((self.out/'work/previews').rglob('preview.json')))

    def test_unknown_slides_and_external_artifacts_are_rejected_without_state_changes(self):
        state = self.prepare()
        result = self.preview(slide_ids=['missing'])
        self.assertEqual(result['status'], 'FAIL')
        self.assertEqual(self.render.call_count, 0)
        outside = self.root/'outside.json'
        write(outside, self.value)
        result = runner.advance(self.job_id, preview={'artifact_path': str(outside)})['preview_result']
        self.assertEqual(result['status'], 'FAIL')
        self.assertEqual(state, (self.out/'.totalpipe/job.json').read_bytes())

    def test_resource_mutation_while_reusing_a_preview_is_rejected(self):
        state = self.prepare()
        background = self.root/'background.png'
        Image.new('RGB', (1280, 720), 'red').save(background)
        self.value['theme']['background_image'] = str(background)
        write(self.path, self.value)
        self.assertEqual(self.preview(slide_ids=['P1'])['status'], 'PASS')
        from agent.ir_preview import _cached
        def mutate(*args):
            cached = _cached(*args)
            Image.new('RGB', (1280, 720), 'blue').save(background)
            return cached
        with patch('agent.ir_preview._cached', side_effect=mutate):
            result = self.preview(slide_ids=['P1'])
        self.assertEqual(result['status'], 'FAIL', result)
        self.assertIn('changed while reading the cache', result['message'])
        self.assertEqual(state, (self.out/'.totalpipe/job.json').read_bytes())

    def test_preview_cannot_be_mixed_with_acceptance(self):
        state = self.prepare()
        with self.assertRaises(ValueError):
            runner.advance(self.job_id, artifact_kind='deck_ir', artifact_path=str(self.path),
                           preview={'artifact_path': str(self.path)})
        self.assertEqual(state, (self.out/'.totalpipe/job.json').read_bytes())
