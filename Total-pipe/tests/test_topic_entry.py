import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

from PIL import Image
from pptx import Presentation

from agent import COMPONENT, runner
from agent.mcp_server import transport
from agent.state import read, sha, write
from agent_fixture import AgentCase


TOPIC = '二分查找为什么快？'


def design(count=1):
    return {
        'schema_version': 'topic-1.0',
        'deck_id': 'binary-search',
        'pages': [{'id': f'P{i}', 'design': '逐步缩小有序候选集合。'} for i in range(1, count+1)],
    }


def scene(count=1):
    return {
        'schema_version': '0.1',
        'deck_id': 'binary-search',
        'theme': {'font': 'Microsoft YaHei'},
        'pages': [{'id': f'P{i}', 'objects': [
            {'type': 'text', 'role': 'body', 'box': [0.8, 2.2, 11, 0.7], 'size': 20,
             'text': '从 256 项开始，每轮排除一半，最多 8 次折半。'},
        ]} for i in range(1, count+1)],
    }


class TopicEntryTests(AgentCase):
    def setUp(self):
        super().setUp()
        self.source.unlink()

    def submit(self, state, value):
        next_action = state['next_action']
        path = Path(next_action['expected_output'])
        write(path, value)
        return runner.advance(state['job_id'], artifact_kind=next_action['artifact_kind'], artifact_path=str(path))

    def test_mcp_topic_builds_six_freeform_pages_without_paper_components(self):
        # Six text-only pages catch an accidental reuse of the scientific expression gate.
        with (patch('agent.state.resources', side_effect=AssertionError('unexpected source-file scan')),
              patch('agent.adapters.pwf_cli', side_effect=AssertionError('unexpected PaperWorkflow')),
              patch('agent.adapters.rpa', side_effect=AssertionError('unexpected RPA')),
              patch('agent.adapters.compiler', side_effect=AssertionError('unexpected Deck IR compiler'))):
            state = transport.TOOLS['totalpipe_start']['handler']({
                'source_kind': 'topic', 'source': TOPIC, 'out_dir': str(self.out),
            })
            self.assertEqual(state['stage'], 'page_design', state)
            self.assertEqual(state['next_action']['type'], 'author_artifact')
            self.assertNotIn('delegation', state['next_action'])
            prompt = read(state['next_action']['input_path'])
            self.assertEqual(prompt['request']['topic'], TOPIC)
            self.assertEqual(prompt['request']['language'], 'auto')
            self.assertEqual(prompt['request']['presentation_type'], 'custom')
            self.assertTrue(Path(prompt['example_lookup']['command_prefix'][-1]).is_file())
            self.assertNotIn('evidence', prompt)
            state = self.submit(state, design(6))
            self.assertEqual(state['stage'], 'page_scene', state)
            self.assertNotIn('evidence', read(state['next_action']['input_path']))
            values = scene(6)
            values['pages'][0]['footer'] = True
            state = self.submit(state, values)
            self.assertEqual(state['status'], 'candidate_ready', state)
            self.assertEqual(state['artifacts_summary']['stages'], ['page_design', 'page_scene', 'build'])
            self.assertEqual(state['qa']['counts']['FAIL'], 0)
            self.assertIn('native', state)
            self.assertNotIn('ir_preview', state)
            saved = read(self.out/'work/page_scene.json')
            self.assertEqual(saved['provenance']['mode'], 'topic')
            self.assertNotIn('evidence_refs', saved['pages'][0])
            self.assertEqual(read(self.out/'build/qa_report.json')['expression_gate']['status'], 'SKIP')
            candidate = Path(state['candidate'])
            pptx = Presentation(str(candidate))
            self.assertEqual(len(pptx.slides), 6)
            copy = ' '.join(shape.text for shape in pptx.slides[0].shapes if shape.has_text_frame)
            self.assertIn('256 项', copy)
            self.assertNotIn('Tian et al.', copy)
            before = sha(candidate)
            resumed = runner.start(TOPIC, self.out, source_kind='topic')
            self.assertEqual(resumed['job_id'], state['job_id'])
            self.assertEqual(resumed['status'], 'candidate_ready')
            self.assertEqual(sha(candidate), before)
            self.assertEqual(runner.start('换个题目', self.out, source_kind='topic')['next_action']['reason'],
                             'JOB_OUTPUT_IN_USE')

    def test_topic_preserves_user_page_count_and_geometry(self):
        state = runner.start(TOPIC, self.out, source_kind='topic', slide_count=1)
        rejected = self.submit(state, design(2))
        self.assertEqual(rejected['next_action']['reason'], 'TOPIC_PAGE_DESIGN_INVALID')
        self.assertIn('Requested 1 pages', rejected['issues'][0]['message'])
        state = self.submit(state, design())
        values = scene()
        values['pages'][0]['objects'][0]['box'] = [11, 2, 8, 1]
        rejected = self.submit(state, values)
        self.assertEqual(rejected['next_action']['reason'], 'PAGE_SCENE_INVALID')
        self.assertIn('box outside page', rejected['issues'][0]['message'])
        self.assertEqual(self.submit(state, scene())['status'], 'candidate_ready')

    def test_topic_can_use_an_explicit_delegation_without_model_selection_pause(self):
        state = runner.start(TOPIC, self.out, source_kind='topic')
        selection = {'model': 'test-model', 'reasoning_effort': 'max', 'selected_by_user': True}
        delegated = runner.advance(state['job_id'], inputs=selection)
        self.assertEqual(delegated['stage'], 'page_design')
        self.assertEqual(delegated['next_action']['type'], 'invoke_subagent')
        self.assertEqual(delegated['next_action']['delegation'], selection)
        self.assertEqual(runner.status(state['job_id'])['next_action']['delegation'], selection)

    def test_topic_can_refine_copy_and_tracks_assets_relative_to_the_draft(self):
        state = runner.start(TOPIC, self.out, source_kind='topic')
        plan = design()
        plan['pages'][0]['title'] = '大纲标题'
        state = self.submit(state, plan)
        draft = self.out/'work/drafts/scene.json'
        draft.parent.mkdir()
        image = draft.parent/'example.png'
        Image.new('RGB', (36, 36), 'navy').save(image)
        values = scene()
        page = values['pages'][0]
        page['title'] = '修改后的投屏标题'
        page['objects'].append({'type': 'image', 'path': image.name, 'box': [0.8, 3.5, 1, 1]})
        write(draft, values)
        result = runner.advance(state['job_id'], artifact_kind='page_scene', artifact_path=str(draft))
        self.assertEqual(result['status'], 'candidate_ready', result)
        saved = read(self.out/'work/page_scene.json')['pages'][0]
        self.assertEqual(saved['title'], '修改后的投屏标题')
        self.assertEqual(saved['objects'][1]['path'], str(image))
        Image.new('RGB', (36, 36), 'teal').save(image)
        self.assertEqual(runner.status(state['job_id'])['stage'], 'page_scene')

    def test_cli_passes_the_source_as_text(self):
        run = subprocess.run(
            [sys.executable, '-m', 'agent', 'start', '--source-kind', 'topic',
             '--source', TOPIC, '--out-dir', str(self.out)],
            cwd=COMPONENT, capture_output=True, text=True, check=True,
        )
        state = json.loads(run.stdout)
        self.assertEqual(state['stage'], 'page_design')
        self.assertEqual(read(state['next_action']['input_path'])['request']['topic'], TOPIC)
