"""PageScene pipeline integration: design binding, stage graph, build and MCP surface."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pptx import Presentation

from agent import runner
from agent import runner as agent_runner
from agent.page_scene_binding import SceneBindingError, bind, copy_bindings
from agent.page_scene_build import build as build_scene
from agent.state import read, sha, write
from agent_fixture import AgentCase, workflow


def page_design():
    return {
        'schema_version': '1.0',
        'deck_id': 'scene-integration',
        'setting': {'audience': 'peers', 'occasion': 'group-meeting', 'reading': 'spoken'},
        'pages': [{
            'id': 'P1',
            'title': '一个器件完成两类功能',
            'take': '同一固定拓扑同时承载数字与模拟功能。',
            'claim': 'c',
            'items': [{'id': 'observation', 'source': 'S1.answer',
                       'text': '固定拓扑在两种偏置下保持功能。', 'evidence': ['EV0001']}],
            'design': 'One device photo and one short conclusion.',
        }],
    }


def page_scene(title='一个器件完成两类功能', take='同一固定拓扑同时承载数字与模拟功能。'):
    return {
        'schema_version': '0.1',
        'deck_id': 'scene-integration',
        'theme': {'font': 'Microsoft YaHei'},
        'pages': [{
            'id': 'P1',
            'title': title,
            'take': take,
            'objects': [
                {'id': 'body', 'type': 'text', 'role': 'body', 'box': [0.8, 2.2, 6.0, 0.7],
                 'text': '固定拓扑在两种偏置下保持功能。', 'size': 18},
            ],
        }],
    }


class PageScenePipelineTests(AgentCase):
    def prepare_design(self):
        work = self.out/'work'
        write(work/'page_design.json', page_design())
        write(work/'story_plan.json', {'story': [{'answer': '固定拓扑在两种偏置下保持功能。',
                                                   'evidence': ['EV0001']}]})
        write(work/'evidence_pointer.json', {'workflow': str(self.out/'workflow.json')})
        write(self.out/'workflow.json', workflow())
        return work

    def test_bind_uses_approved_title_evidence_and_rejects_new_numbers(self):
        work = self.prepare_design()
        canonical, report = bind(page_scene(title='一个器件完成两类功能',
                                            take='同一固定拓扑同时承载数字与模拟功能。'),
                                 work, source_dir=work)
        page = canonical['pages'][0]
        self.assertEqual(page['title_ref'], 'P1.title')
        self.assertEqual(page['take_ref'], 'P1.take')
        self.assertEqual(page['evidence_refs'], ['EV0001'])
        self.assertEqual(report['pages'][0]['required_copy'], [])
        with self.assertRaises(SceneBindingError) as caught:
            bind(page_scene(title='一个器件完成两类功能 777',
                            take='同一固定拓扑同时承载数字与模拟功能。'), work, source_dir=work)
        self.assertEqual(caught.exception.code, 'PAGE_SCENE_COPY_DRIFT')
        with self.assertRaises(SceneBindingError) as caught:
            bind(page_scene(title='一个器件完成两类功能',
                            take='同一固定拓扑同时承载数字与模拟功能。999'), work, source_dir=work)
        self.assertIn(caught.exception.code, ('PAGE_SCENE_COPY_DRIFT', 'PAGE_SCENE_NUMBER_UNBOUND'))

    def test_copy_bindings_include_page_aliases_and_legacy_title(self):
        canonical = copy_bindings(page_design())
        self.assertEqual(canonical['P1.title'], '一个器件完成两类功能')
        self.assertEqual(canonical['P1.take'], '同一固定拓扑同时承载数字与模拟功能。')

    def test_atomic_display_copy_carriers_must_be_bound(self):
        design = {
            'schema_version': '1.3', 'deck_id': 'atomic',
            'pages': [{
                'id': 'P1',
                'display_copy': [
                    {'id': 'p1-title', 'role': 'title', 'text': '一个器件完成两类功能',
                     'source_refs': ['C1']},
                    {'id': 'p1-take', 'role': 'takeaway', 'text': '同一固定拓扑同时承载数字与模拟功能。',
                     'source_refs': ['C1']},
                    {'id': 'p1-body', 'role': 'body', 'text': '固定拓扑在两种偏置下保持功能。',
                     'source_refs': ['C1']},
                ],
                'content_map': {'C1': {'destination': 'visible', 'carriers': [
                    {'kind': 'copy', 'ref': 'p1-title'},
                    {'kind': 'copy', 'ref': 'p1-take'},
                    {'kind': 'copy', 'ref': 'p1-body'},
                ]}},
                'items': [{'source': 'C1', 'evidence': ['EV0001'], 'text': '固定拓扑在两种偏置下保持功能。'}],
            }],
        }
        value = page_scene()
        value['pages'][0]['title_ref'] = 'P1.title'
        value['pages'][0]['take_ref'] = 'P1.take'
        value['pages'][0].pop('title')
        value['pages'][0].pop('take')
        value['pages'][0]['objects'][0]['copy_ref'] = 'P1.p1-body'
        value['pages'][0]['objects'][0].pop('text')
        with patch('agent.adapters.load_design', return_value=design):
            canonical, report = bind(value, self.out/'work', source_dir=self.out/'work')
        self.assertEqual(canonical['pages'][0]['evidence_refs'], ['EV0001'])
        self.assertEqual(report['pages'][0]['required_copy'],
                         ['p1-body', 'p1-take', 'p1-title'])
        missing = json.loads(json.dumps(value))
        missing['pages'][0]['objects'] = []
        with patch('agent.adapters.load_design', return_value=design), \
                self.assertRaises(SceneBindingError) as caught:
            bind(missing, self.out/'work', source_dir=self.out/'work')
        self.assertEqual(caught.exception.code, 'PAGE_SCENE_COPY_MISSING')

    def test_stage_graph_skips_deck_ir_and_runs_scene_before_build(self):
        work = self.out/'work'
        work.mkdir(parents=True)
        names = ['queries', 'evidence', 'story_prompt', 'story', 'scientific_review', 'rpa',
                 'page_design', 'page_review', 'page_scene']
        checkpoints = {}
        for index, name in enumerate(names):
            path = work/('checkpoint-%d.json' % index)
            write(path, {'stage': name})
            checkpoints[name] = {'upstream': 'u', 'files': {str(path.resolve()): sha(path)}}
        job = {'request': {'source': str(self.source), 'out_dir': str(self.out), 'language': 'zh',
                           'presentation_type': 'group_meeting', 'source_kind': 'markdown',
                           'page_mode': 'page_scene'},
               'inputs': {'model': 'test-model', 'reasoning_effort': 'max', 'selected_by_user': True},
               'checkpoints': checkpoints, 'attempts': {}}
        with patch.object(runner, 'dependency', return_value='u'):
            self.assertEqual(runner.current(job)[0]['id'], 'build')
            job['checkpoints'].pop('page_scene')
            self.assertEqual(runner.current(job)[0]['id'], 'page_scene')

    def test_accept_binds_scene_and_checkpoints_images(self):
        work = self.prepare_design()
        draft = work/'draft.json'
        write(draft, page_scene())
        job = {'job_id': 'a'*32,
               'request': {'out_dir': str(self.out), 'source': str(self.source), 'language': 'zh',
                           'presentation_type': 'group_meeting', 'source_kind': 'markdown',
                           'page_mode': 'page_scene'},
               'checkpoints': {}, 'inputs': {}, 'attempts': {}}
        runner._accept(job, runner.BY_ARTIFACT['page_scene'], 'u', 'page_scene', draft)
        canonical = read(work/'page_scene.json')
        self.assertEqual(canonical['pages'][0]['title_ref'], 'P1.title')
        self.assertEqual(canonical['pages'][0]['evidence_refs'], ['EV0001'])
        self.assertIn(str((work/'page_scene.json').resolve()), job['checkpoints']['page_scene']['files'])

    def test_one_page_scene_builds_native_candidate_and_package_qa(self):
        work = self.out/'work'
        work.mkdir(parents=True)
        write(work/'page_scene.json', page_scene())
        paths = build_scene(work, self.out)
        self.assertTrue((self.out/'build/candidate.pptx').is_file())
        self.assertEqual(len(Presentation(str(self.out/'build/candidate.pptx')).slides), 1)
        qa = read(self.out/'build/qa_report.json')
        self.assertEqual(qa['status'], 'PASS', qa)
        self.assertEqual(qa['checks']['backend'], 'page_scene')
        self.assertTrue(qa['checks']['structural'])
        self.assertEqual(qa['counts']['FAIL'], 0)
        self.assertTrue(any(path.name == 'page_scene.json' for path in paths))

    def test_full_scene_job_reaches_candidate_ready_without_deck_ir_or_officecli(self):
        work = self.prepare_design()
        names = ['queries', 'evidence', 'story_prompt', 'story', 'scientific_review', 'rpa',
                 'page_design', 'page_review']
        checkpoints = {}
        for index, name in enumerate(names):
            path = work/('checkpoint-%d.json' % index)
            write(path, {'stage': name})
            checkpoints[name] = {'upstream': 'u', 'files': {str(path.resolve()): sha(path)}}
        job = {'schema_version': 1, 'job_id': 'b'*32, 'created_at': '2026-01-01T00:00:00+00:00',
               'request': {'source': str(self.source), 'out_dir': str(self.out), 'language': 'zh',
                           'presentation_type': 'group_meeting', 'source_kind': 'markdown',
                           'requirements': '', 'page_mode': 'page_scene', 'supplement': 'off',
                           'explain_viz_mode': 'auto'},
               'inputs': {'model': 'test-model', 'reasoning_effort': 'max', 'selected_by_user': True},
               'checkpoints': checkpoints, 'attempts': {}}
        from agent.state import save
        save(job)
        write(runner.home()/'jobs'/(job['job_id']+'.json'), {'out_dir': str(self.out)})
        with patch.object(runner, 'dependency', return_value='u'):
            waiting = runner.advance(job['job_id'])
            self.assertEqual(waiting['stage'], 'page_scene', waiting)
            self.assertEqual(waiting['next_action']['reason'], 'PAGE_SCENE_REQUIRED')
            draft = work/'draft.json'
            write(draft, page_scene())
            ready = runner.advance(job['job_id'], artifact_kind='page_scene', artifact_path=str(draft))
        self.assertEqual(ready['status'], 'candidate_ready', ready)
        self.assertEqual(ready['qa']['counts']['FAIL'], 0)
        self.assertTrue((self.out/'build/candidate.pptx').is_file())
        self.assertFalse((self.out/'work/deck_ir.json').exists())

    def test_mcp_exposes_page_mode_artifact_and_scene_preview(self):
        from agent.mcp_server import transport
        start = transport.TOOLS['totalpipe_start']['inputSchema']
        advance = transport.TOOLS['totalpipe_advance']['inputSchema']
        self.assertIn('page_mode', start['properties'])
        self.assertIn('page_scene', start['properties']['page_mode']['enum'])
        self.assertIn('page_scene', advance['properties']['artifact_kind']['enum'])
        self.assertIn('scene_preview', advance['properties'])
        self.assertIn('artifact_path', advance['properties']['scene_preview']['required'])


if __name__ == '__main__':
    unittest.main()
