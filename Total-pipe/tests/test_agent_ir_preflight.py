"""Acceptance and read-only preflight share scientific checks without repeating whole Story ledgers."""
import copy
from unittest.mock import patch

from agent import COMPONENT, adapters as a, runner
from agent.state import read, write
from agent_fixture import AgentCase
from deck_compiler.design import bind_design
from deck_compiler.ir import caption_figure_ids, validate


class SplitEvidenceTests(AgentCase):
    def split(self):
        value = read(COMPONENT/'examples/native-bullets.deck_ir.json')
        value['slides'] = [copy.deepcopy(value['slides'][0]) for _ in range(2)]
        story = {'story': [{'answer': 'The response changes.', 'key_points': ['The control is stable.'],
                            'evidence': ['EV0001', 'EV0002']}], 'ending': {}}
        design = bind_design({'schema_version': '1.1', 'pages': [
            {'id': 'P1', 'content_refs': ['S1.answer']},
            {'id': 'P2', 'content_refs': ['S1.key_points[0]']}]}, story)
        for i, slide in enumerate(value['slides']):
            slide['id'] = f'P{i+1}'
            slide['semantic']['evidence_refs'] = [f'EV000{i+1}']
        return value, design

    def test_split_pages_keep_relevant_refs_and_cover_the_node_once(self):
        value, design = self.split()
        a.check_design_realization(value, design)
        self.assertEqual(value['slides'][0]['semantic']['evidence_refs'], ['EV0001'])

    def test_node_evidence_cannot_disappear_and_each_page_needs_an_anchor(self):
        value, design = self.split()
        value['slides'][1]['semantic']['evidence_refs'] = ['EV0001']
        with self.assertRaisesRegex(a.Failure, 'EV0002'):
            a.check_design_realization(value, design)
        value['slides'][1]['semantic']['evidence_refs'] = ['EV_UNRELATED']
        with self.assertRaises(a.Failure) as caught:
            a.check_design_realization(value, design)
        self.assertEqual(len(caught.exception.issues), 2)
        self.assertIn('anchor', caught.exception.issues[0]['message'])

    def test_all_page_figure_and_number_errors_are_reported_together(self):
        value, design = self.split()
        for p in design['pages']:
            p['figures'] = ['original.png']
            p['items'][0]['text'] = 'Measured at 987654 K.'
        issues = a.design_realization_issues(value, design)
        self.assertEqual(len(issues), 4)
        self.assertEqual({i['slide'] for i in issues}, {1, 2})

    def test_supplementary_figure_number_retains_s_prefix(self):
        self.assertEqual(caption_figure_ids('Supplementary Fig. S14a and Figure 2b'), {'S14a', '2b'})
        value = read(self.fixture_ir())
        for asset in value['assets'].values():
            if asset.get('origin', 'paper') == 'paper': asset['source_figure'] = 'S14'
        for slide in value['slides']:
            for f in slide['composition']['figure_refs']:
                if value['assets'][f['asset_id']].get('origin', 'paper') == 'paper':
                    f['source_figure'], f['caption'] = 'S14', 'Supplementary Fig. S14'
        self.assertFalse([i for i in validate(value) if i['rule'].startswith('FIGURE_')])
        import jsonschema
        jsonschema.validate(value, read(COMPONENT/'schemas/deck-ir.schema.json'))


class ReadOnlyPreflightTests(AgentCase):
    def prepare(self):
        with patch('agent.runner.a.execute', side_effect=a.Failure(
                'INSUFFICIENT_DRAWING_SPACE', 'Fixture requests IR repair.', 'replan', 'deck_ir')):
            result = runner.start(str(COMPONENT/'examples/native-bullets.deck_ir.json'), str(self.out), 'en', 'group_meeting')
        self.assertEqual(runner.status(result['job_id'])['stage'], 'deck_ir')
        return result['job_id'], self.out/'work/deck_ir.json'

    def snapshot(self):
        return {str(p): (p.read_bytes(), p.stat().st_mtime_ns) for p in self.out.rglob('*') if p.is_file()}

    def test_geometry_preflight_does_not_accept_write_or_consume_attempts(self):
        job, path = self.prepare()
        before = self.snapshot()
        with patch('agent.runner.a.execute', side_effect=AssertionError('Preflight must not advance/build')):
            result = runner.advance(job, artifact_kind='deck_ir', artifact_path=str(path), preflight=True)
        self.assertEqual(before, self.snapshot())
        self.assertTrue(result['preflight_result']['geometry_checked'])
        self.assertTrue(result['preflight_result']['job_unchanged'])

    def test_semantic_preflight_and_submission_return_same_full_errors(self):
        job, path = self.prepare()
        value = read(path)
        value['slides'][0]['semantic'].pop('purpose')
        value['slides'][1]['semantic'].pop('purpose')
        write(path, value)
        before = self.snapshot()
        dry = runner.advance(job, artifact_kind='deck_ir', artifact_path=str(path), preflight=True)
        self.assertEqual(before, self.snapshot())
        issues = dry['preflight_result']['issues']
        self.assertGreaterEqual(len(issues), 2)
        runner.advance(job, artifact_kind='deck_ir', artifact_path=str(path))
        self.assertEqual(issues, read(self.out/'work/submission_feedback.json')['issues'])

    def test_geometry_errors_are_available_before_formal_submission(self):
        job, path = self.prepare()
        value = read(path)
        value['slides'] = [value['slides'][0]]
        comp = value['slides'][0]['composition']
        comp.clear()
        comp.update(archetype='composite-research', figure_refs=[], blocks=[
            {'id': 'wide', 'component': 'formula', 'text': '+'.join(['x']*100)}],
            layout_tree={'version': '1.0', 'regions': {'body': {'id': 'leaf', 'type': 'block', 'ref': 'wide'}}})
        write(path, value)
        before = self.snapshot()
        result = runner.advance(job, artifact_kind='deck_ir', artifact_path=str(path), preflight=True)['preflight_result']
        self.assertTrue(result['geometry_checked'])
        self.assertGreater(result['counts']['FAIL'], 0)
        self.assertEqual(before, self.snapshot())

    def test_preflight_never_attaches_results_to_changed_input_bytes(self):
        job, path = self.prepare()
        state = (self.out/'.totalpipe/job.json').read_bytes()
        def changed(*args, **kwargs):
            path.write_text(path.read_text()+'\n')
            return {}, None, {'items': [], 'checks': {'geometric': True}}
        with patch('deck_compiler.pipeline.compile_input', side_effect=changed):
            result = runner.advance(job, artifact_kind='deck_ir', artifact_path=str(path), preflight=True)['preflight_result']
        self.assertEqual(result['status'], 'FAIL')
        self.assertEqual(result['issues'][-1]['code'], 'PREFLIGHT_STALE')
        self.assertEqual(state, (self.out/'.totalpipe/job.json').read_bytes())

    def test_exhausted_revision_budget_does_not_block_read_only_diagnostics(self):
        job, path = self.prepare()
        state_path = self.out/'.totalpipe/job.json'
        state = read(state_path)
        for attempt in state['attempts'].values():
            attempt['count'] = 3
        write(state_path, state)
        before = self.snapshot()
        result = runner.advance(job, artifact_kind='deck_ir', artifact_path=str(path), preflight=True)
        self.assertTrue(result['preflight_result']['geometry_checked'])
        self.assertEqual(before, self.snapshot())
