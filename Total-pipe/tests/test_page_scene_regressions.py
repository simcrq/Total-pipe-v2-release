"""Regression coverage for approved copy, canonical saves and image checkpoints."""
import copy
from unittest.mock import patch

from PIL import Image

from agent import runner
from agent.page_scene_binding import SceneBindingError, bind
from agent.page_scene_build import build
from agent.page_scene_qa import validate_spec
from agent.state import read, sha, valid_record, write
from agent_fixture import AgentCase
from test_page_scene_pipeline import page_design, page_scene


class PageSceneRegressionTests(AgentCase):
    def prepare(self):
        work = self.out/'work'
        write(work/'page_design.json', page_design())
        return work

    def job(self):
        return {'job_id': 'c'*32,
                'request': {'out_dir': str(self.out), 'source': str(self.source),
                            'source_kind': 'markdown', 'page_mode': 'page_scene'},
                'checkpoints': {}, 'inputs': {}, 'attempts': {}}

    def atomic_design(self):
        design = page_design()
        design['schema_version'] = '1.3'
        page = design['pages'][0]
        page['display_copy'] = [
            {'id': 'title', 'role': 'title', 'text': page['title']},
            {'id': 'take', 'role': 'takeaway', 'text': page['take']},
            {'id': 'body', 'role': 'body', 'text': page['items'][0]['text']},
        ]
        return design

    def test_unapproved_body_is_rejected_even_without_new_numbers(self):
        work = self.prepare()
        value = page_scene()
        value['pages'][0]['objects'][0]['text'] = '所有偏置条件下功能都得到保证。'
        with self.assertRaises(SceneBindingError) as caught:
            bind(value, work)
        self.assertEqual(caught.exception.code, 'PAGE_SCENE_COPY_DRIFT')

    def test_unapproved_copy_is_rejected_in_all_rendered_carriers(self):
        work = self.prepare()
        claim = '所有偏置条件下功能都得到保证。'
        objects = [
            {'type': 'text', 'text': claim},
            {'type': 'shape', 'text': claim},
            {'type': 'list', 'items': [{'text': claim}]},
            {'type': 'table', 'rows': [[claim]]},
            {'type': 'formula', 'latex': 'x=y'},
            *[{'type': 'chart', key: claim} for key in ('title', 'x_label', 'y_label')],
            {'type': 'chart', 'categories': [claim]},
            {'type': 'chart', 'series': [{'name': claim, 'values': [1]}]},
            {'type': 'group', 'children': [{'type': 'text', 'text': claim}]},
        ]
        for obj in objects:
            with self.subTest(obj=obj), patch('agent.adapters.load_design',
                                             return_value=self.atomic_design()):
                value = page_scene()
                value['pages'][0]['objects'].append(obj)
                with self.assertRaises(SceneBindingError) as caught:
                    bind(value, work)
                self.assertEqual(caught.exception.code, 'PAGE_SCENE_COPY_DRIFT')

    def test_approved_literals_and_references_bind_to_actual_rendered_copy(self):
        work = self.prepare()
        design = self.atomic_design()
        page = design['pages'][0]
        page['display_copy'].extend([
            {'id': 'label', 'role': 'label', 'text': '器件'},
            {'id': 'formula', 'role': 'label', 'text': 'x=y'},
        ])
        page['content_map'] = {'C1': {'destination': 'visible',
                                     'carriers': [{'kind': 'copy', 'ref': 'body'}]}}
        value = page_scene()
        objects = value['pages'][0]['objects']
        objects[0] = {**objects[0], 'copy_ref': 'P1.body'}
        objects.extend([
            {'type': 'shape', 'copy_ref': 'P1.label'},
            {'type': 'list', 'items': [{'copy_ref': 'P1.label'}]},
            {'type': 'table', 'rows': [['器件']]},
            {'type': 'formula', 'latex': 'x=y'},
            {'type': 'chart', 'title': '器件', 'x_label': '器件', 'y_label': '器件',
             'categories': ['器件'], 'series': [{'name': '器件'}]},
        ])
        with patch('agent.adapters.load_design', return_value=design):
            _, report = bind(value, work)
            self.assertIn('P1.body', report['pages'][0]['used_copy'])
            # A ref on an image must not stand in for visible body copy.
            hidden = copy.deepcopy(value)
            hidden['pages'][0]['objects'][0] = {'type': 'image', 'copy_ref': 'P1.body',
                                              'path': 'figure.png'}
            with self.assertRaises(SceneBindingError) as caught:
                bind(hidden, work)
            self.assertEqual(caught.exception.code, 'PAGE_SCENE_COPY_MISSING')
            conflicting = copy.deepcopy(value)
            conflicting['pages'][0]['objects'][0]['text'] = '器件'
            with self.assertRaises(SceneBindingError) as caught:
                bind(conflicting, work)
            self.assertEqual(caught.exception.code, 'PAGE_SCENE_COPY_DRIFT')

    def test_copy_from_another_page_cannot_be_added_as_a_reference(self):
        work = self.prepare()
        design = self.atomic_design()
        other = copy.deepcopy(design['pages'][0])
        other['id'] = 'P2'
        other['display_copy'][-1]['text'] = '另一实验仅在低温下运行。'
        design['pages'].append(other)
        value = page_scene()
        other_scene = copy.deepcopy(value['pages'][0])
        other_scene['id'] = 'P2'
        other_scene['objects'][0] = {'type': 'text', 'copy_ref': 'P2.body'}
        value['pages'].append(other_scene)
        value['pages'][0]['objects'].append({'type': 'text', 'copy_ref': 'P2.body'})
        with patch('agent.adapters.load_design', return_value=design), \
                self.assertRaises(SceneBindingError) as caught:
            bind(value, work)
        self.assertEqual(caught.exception.code, 'PAGE_SCENE_COPY_DRIFT')

    def test_same_path_submission_persists_bindings_and_builds(self):
        work = self.prepare()
        path = work/'page_scene.json'
        value = page_scene()
        page = value['pages'][0]
        page['title_ref'] = 'P1.title'
        page['take_ref'] = 'P1.take'
        del page['title'], page['take']
        write(path, value)
        job = self.job()
        runner._accept(job, runner.BY_ARTIFACT['page_scene'], 'u', 'page_scene', path)
        saved = read(path)
        self.assertIn('bindings', saved)
        self.assertEqual(validate_spec(saved, path)[0], [])
        self.assertEqual(job['checkpoints']['page_scene']['files'][str(path)], sha(path))
        build(work, self.out)
        self.assertEqual(read(self.out/'build/qa_report.json')['counts']['FAIL'], 0)

    def test_same_path_recipe_is_saved_expanded_and_builds(self):
        work = self.prepare()
        path = work/'page_scene.json'
        value = page_scene()
        value['pages'] = [{'id': 'P1', 'recipe': 'contrast',
                           'title_ref': 'P1.title', 'take_ref': 'P1.take', 'slots': {}}]
        write(path, value)
        runner._accept(self.job(), runner.BY_ARTIFACT['page_scene'], 'u', 'page_scene', path)
        page = read(path)['pages'][0]
        self.assertNotIn('recipe', page)
        self.assertTrue(page['objects'])
        build(work, self.out)
        self.assertEqual(read(self.out/'build/qa_report.json')['counts']['FAIL'], 0)

    def test_relative_nested_image_is_canonical_and_checkpointed(self):
        work = self.prepare()
        folder = work/'drafts'
        folder.mkdir()
        image = folder/'figure.png'
        Image.new('RGB', (20, 20), 'white').save(image)
        value = page_scene()
        value['pages'][0]['objects'].append({
            'id': 'group', 'type': 'group', 'box': [7, 2.2, 2, 2],
            'children': [{'id': 'figure', 'type': 'image', 'box': [0, 0, 2, 2],
                          'path': 'figure.png'}]})
        original = copy.deepcopy(value)
        canonical, _ = bind(value, work, source_dir=folder)
        obj = canonical['pages'][0]['objects'][-1]['children'][0]
        self.assertEqual(obj['path'], str(image.resolve()))
        self.assertEqual(value, original)
        path = folder/'draft.json'
        write(path, value)
        job = self.job()
        runner._accept(job, runner.BY_ARTIFACT['page_scene'], 'u', 'page_scene', path)
        record = job['checkpoints']['page_scene']
        self.assertIn(str(image.resolve()), record['files'])
        self.assertTrue(valid_record(record, 'u'))
        build(work, self.out)
        Image.new('RGB', (20, 20), 'red').save(image)
        self.assertFalse(valid_record(record, 'u'))
