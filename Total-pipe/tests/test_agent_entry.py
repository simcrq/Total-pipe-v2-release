import json
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
from unittest.mock import patch

import jsonschema

from agent import COMPONENT
from agent import runner
from agent.state import read, write, locate, sha
from agent.mcp_server import transport
from agent_fixture import AgentCase, workflow, story


class EntryTests(AgentCase):
    def assert_action(self, result):
        jsonschema.validate(result['next_action'], read(COMPONENT/'agent/schemas/next-action.schema.json'))

    def test_four_tool_surface_forbids_model_at_start_and_final_operations(self):
        self.assertEqual(len(transport.TOOLS), 4)
        schema = transport.TOOLS['totalpipe_start']['inputSchema']
        self.assertNotIn('model', schema['properties'])
        with self.assertRaises(ValueError):
            transport.TOOLS['totalpipe_start']['handler']({'source': str(self.source), 'out_dir': str(self.out),
                'language': 'zh', 'presentation_type': 'group_meeting', 'model': 'guessed'})
        result = transport.TOOLS['totalpipe_status']['handler']({'job_id': 'unknown'})
        self.assert_action(result)
        self.assertEqual(result['next_action']['reason'], 'JOB_NOT_FOUND')

    def test_query_and_model_pause_then_real_story_prompt(self):
        source = self.root/'workflow.json'
        write(source, workflow())
        result = runner.start(str(source), str(self.out), 'en', 'group_meeting', source_kind='workflow')
        self.assertEqual(result['stage'], 'model_selection', result)
        self.assert_action(result)
        with self.assertRaises(ValueError):
            runner.advance(result['job_id'], inputs={'model': 'test-model', 'reasoning_effort': 'medium', 'selected_by_user': True})
        result = runner.advance(result['job_id'], inputs={'model': 'test-model', 'reasoning_effort': 'high', 'selected_by_user': True})
        self.assertEqual(result['stage'], 'story', result)
        self.assertEqual(result['next_action']['type'], 'invoke_subagent')
        self.assertTrue(Path(result['next_action']['instructions_path']).is_file())
        self.assertEqual(read(self.out/'work/story_prompt.json')['delegation']['model'], 'test-model')
        self.assertEqual(read(self.out/'work/story_prompt.json')['request']['language'], 'en')
        self.assert_action(result)
        bad = story()
        bad['planner']['model'] = 'different-model'
        write(self.out/'work/story_plan.json', bad)
        result = runner.advance(result['job_id'], artifact_kind='story_plan', artifact_path=str(self.out/'work/story_plan.json'))
        self.assertEqual(result['next_action']['reason'], 'STORY_PROVENANCE_MISMATCH')
        self.assert_action(result)

    def test_evidence_readiness_gate_has_an_actionable_failure(self):
        source = self.root/'workflow.json'
        value = workflow()
        value['synthesis_readiness']['readiness'] = 'review'
        write(source, value)
        result = runner.start(str(source), str(self.out), 'en', 'group_meeting', source_kind='workflow')
        self.assertEqual(result['next_action']['type'], 'replan')
        self.assertEqual(result['next_action']['reason'], 'EVIDENCE_NOT_READY')
        self.assertTrue(Path(result['next_action']['feedback_path']).is_file())
        self.assert_action(result)

    @unittest.skipUnless(shutil.which('officecli'), 'OfficeCLI required')
    def test_actual_imported_ir_to_candidate_restart_and_idempotent_advance(self):
        result = runner.start(str(self.fixture_ir()), str(self.out), 'zh', 'group_meeting')
        self.assertEqual(result['status'], 'candidate_ready', result)
        self.assertEqual(result['qa']['counts']['FAIL'], 0)
        self.assertFalse(result['next_action']['promotion']['available'])
        self.assert_action(result)
        before = sha(self.out/'build/candidate.pptx')
        repeated = runner.advance(result['job_id'], artifact_kind='deck_ir', artifact_path=str(self.out/'work/deck_ir.json'))
        self.assertEqual(repeated['status'], 'candidate_ready')
        self.assertEqual(sha(self.out/'build/candidate.pptx'), before)
        restarted = subprocess.run([sys.executable, '-m', 'agent', 'status', '--job-id', result['job_id']],
                                   capture_output=True, text=True)
        self.assertEqual(restarted.returncode, 0, restarted.stderr)
        self.assertEqual(json.loads(restarted.stdout)['status'], 'candidate_ready')
        (self.out/'build/candidate.pptx').unlink()
        self.assertEqual(runner.status(result['job_id'])['stage'], 'build')

    def test_missing_design_yields_visual_prompt_and_does_not_omit_design(self):
        source = self.root/'input.json'
        from agent.adapters import import_ir
        import_ir(self.fixture_ir(), source)
        value = read(source)
        value['presentation'].pop('academic_design', None)
        for page in value['slides']:
            page['presentation'].pop('visual_plan', None)
        write(source, value)
        result = runner.start(str(source), str(self.out), 'zh', 'group_meeting')
        self.assertEqual(result['stage'], 'visual_design', result)
        self.assertTrue((self.out/'work/visual_prompt.json').is_file())
        self.assertFalse((self.out/'build/candidate.pptx').exists())
        self.assert_action(result)

    def test_unknown_component_failure_retains_log_and_cannot_be_acknowledged(self):
        from agent.adapters import Failure
        with patch('agent.runner.a.execute', side_effect=Failure('UNKNOWN_FAILURE', 'Inspect the environment.')):
            result = runner.start(str(self.fixture_ir()), str(self.out), 'zh', 'group_meeting')
        self.assertEqual(result['status'], 'blocked')
        self.assertEqual(result['next_action']['reason'], 'UNKNOWN_FAILURE')
        self.assert_action(result)

    def test_capacity_replan_rejects_same_input_without_rebuilding_and_has_finite_budget(self):
        from agent.adapters import Failure
        with patch('agent.runner.a.execute', side_effect=Failure('INSUFFICIENT_DRAWING_SPACE', 'Need more room.', 'replan', 'deck_ir')) as execute:
            result = runner.start(str(self.fixture_ir()), str(self.out), 'zh', 'group_meeting')
            self.assertEqual(result['next_action']['type'], 'replan')
            self.assertEqual(result['retry']['max'], 3)
            self.assert_action(result)
            path = self.out/'work/deck_ir.json'
            runner.advance(result['job_id'], artifact_kind='deck_ir', artifact_path=str(path))
            self.assertEqual(execute.call_count, 1)
            for i in range(3):
                value = read(path)
                value['slides'][0]['semantic']['speaker_notes'] += f'\nTest revision {i}.'
                write(path, value)
                result = runner.advance(result['job_id'], artifact_kind='deck_ir', artifact_path=str(path))
            self.assertEqual(result['next_action']['reason'], 'REPLAN_LIMIT_REACHED')
            self.assertEqual(execute.call_count, 3)

    def test_missing_officecli_and_corrupt_initial_ir_return_recoverable_envelopes(self):
        with patch('agent.adapters.shutil.which', return_value=None):
            result = runner.start(str(self.fixture_ir()), str(self.out), 'zh', 'group_meeting')
        self.assertEqual(result['next_action']['reason'], 'OFFICECLI_MISSING')
        self.assert_action(result)
        bad = self.root/'bad.json'
        value = read(self.fixture_ir())
        value['slides'][0]['semantic'].pop('purpose')
        write(bad, value)
        result = runner.start(str(bad), str(self.root/'bad-out'), 'zh', 'group_meeting')
        self.assertEqual(result['next_action']['type'], 'author_artifact')
        self.assertNotEqual(runner.status(result['job_id'])['next_action']['reason'], 'JOB_NOT_FOUND')

    @unittest.skipUnless(shutil.which('officecli'), 'OfficeCLI required')
    def test_actual_markdown_evidence_rpa_ir_design_and_build_with_explicit_test_story(self):
        # This synthetic fixture tests orchestration, not a real model call or scientific acceptance.
        self.source.write_text('# Field response study\n\n# Abstract\n'
            'We measure the response under applied field and independent controls.\n\n# Methods\n'
            'The sample was measured at 300 K using a calibrated probe. We repeat each response measurement under identical conditions.\n\n'
            '# Results\nThe response increased from 2 to 4 units when the field increased. '
            'Independent control measurements reproduced the response. The calibrated probe measured the same shift in three samples.\n\n'
            '# Discussion\nThe response may reflect field-driven transport, but the measurements do not establish a unique microscopic mechanism.\n\n'
            '# Conclusion\nThe field changes the measured response under the tested conditions. The sample size limits generalization.\n')
        result = runner.start(str(self.source), str(self.out), 'en', 'group_meeting', queries=[
            {'id': 'response', 'query': 'measured response applied field control'},
            {'id': 'probe', 'query': 'sample measured calibrated probe 300 K'}])
        self.assertEqual(result['stage'], 'model_selection', result)
        result = runner.advance(result['job_id'], inputs={'model': 'test-model', 'reasoning_effort': 'high', 'selected_by_user': True})
        self.assertEqual(result['stage'], 'story', result)
        write(self.out/'work/story_plan.json', story())
        result = runner.advance(result['job_id'], artifact_kind='story_plan', artifact_path=str(self.out/'work/story_plan.json'))
        self.assertEqual(result['stage'], 'deck_ir', result)
        model = read(self.out/'work/normalized_content.json')
        template = read(self.fixture_ir())
        design = template['presentation'].pop('academic_design')
        template['assets'] = {}
        template['slides'] = []
        for number, brief in enumerate(model['slide_briefs'], 1):
            body = brief.get('body') or brief.get('takeaway') or brief['title']
            template['slides'].append({'id': f'brief-{number}', 'semantic': {
                'purpose': 'Exercise complete source binding in a synthetic integration fixture.',
                'title': brief['title'], 'takeaway': brief.get('takeaway') or brief['title'],
                'speaker_notes': body+'\n'+'\n'.join(brief.get('key_points', [])),
                'evidence_refs': brief.get('evidence_ids', []), 'caveats': []},
                'composition': {'archetype': 'composite-research',
                    'blocks': [{'id': 'body', 'component': 'body', 'text': body}], 'figure_refs': [],
                    'layout_tree': {'version': '1.0', 'regions': {'body': {'id': 'leaf', 'type': 'block', 'ref': 'body'}}}},
                'presentation': {'variant': 'default'}})
        write(self.out/'work/deck_ir.json', template)
        result = runner.advance(result['job_id'], artifact_kind='deck_ir', artifact_path=str(self.out/'work/deck_ir.json'))
        self.assertEqual(result['stage'], 'visual_design', result)
        prompt = read(self.out/'work/visual_prompt.json')
        write(self.out/'work/visual_proposal.json', {'ir_sha256': prompt['ir_sha256'], 'academic_design': design, 'slides': []})
        result = runner.advance(result['job_id'], artifact_kind='visual_proposal', artifact_path=str(self.out/'work/visual_proposal.json'))
        self.assertEqual(result['status'], 'candidate_ready', result)
        self.assertEqual(result['qa']['counts']['FAIL'], 0)
        self.assertEqual(len(read(self.out/'build/layout.json')['slides']), len(model['slide_briefs']))
        self.assertFalse((self.out/'build/final.pptx').exists())
