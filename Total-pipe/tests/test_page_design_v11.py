"""Regression coverage for the 1.1 visual-handoff page design contract."""
import copy
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from jsonschema import Draft202012Validator

from agent import adapters as a, repair, runner
from agent.state import digest, read, sha, write
from agent_fixture import AgentCase
from deck_compiler.design import DESIGN_SCHEMA, bind_design, validate_design


STORY = {
    'story': [
        {'answer': 'The sample used N=512 at 300 K.',
         'key_points': ['It included 100 trials.'], 'evidence': ['EV0001', 'EV0002']},
        {'answer': 'The measured response was reproducible.', 'evidence': ['EV0003']},
    ],
    'ending': {'takeaway': 'The response was observed.'},
}
EVIDENCE = {
    'EV0001': 'The setup used N=512 pixels at 300 K.',
    'EV0002': 'The experiment included 100 trials.',
    'EV0003': 'The measured response was reproducible.',
}


def reference_design():
    return {
        'schema_version': '1.1',
        'deck_id': 'reference-design',
        'setting': {'audience': 'Scientific peers', 'occasion': 'group-meeting', 'reading': 'spoken'},
        'pages': [
            {'id': 'P0', 'content_refs': [],
             'design': {'route': ['setup', 'result'], 'walkthrough': ['Introduce the route.']}},
            {'id': 'P1', 'content_refs': ['S1.answer', 'S1.key_points[0]'],
             'design': {'elements': [{'type': 'diagram', 'label': 'N=512'}],
                        'walkthrough': ['Point to the measurement, then the trials.']}},
            {'id': 'P2', 'content_refs': ['S2.answer'],
             'design': 'Use the original response panel at left.'},
            {'id': 'P3', 'content_refs': ['ending.takeaway'],
             'design': {'closing_mark': 'summary'}},
        ],
    }


def one_page_design(figures=None):
    return {
        'schema_version': '1.1', 'deck_id': 'single-page',
        'setting': {'audience': 'Scientific peers', 'occasion': 'group-meeting', 'reading': 'spoken'},
        'pages': [{'id': 'P1', 'content_refs': ['S1.answer'],
                   'design': {'elements': ['one measured panel'],
                              'walkthrough': ['Point to the source panel.']},
                   'figures': list(figures or [])}],
    }


def one_slide_ir(visible='', evidence_refs=None, selected_figure=True, graphics=None, charts=None):
    figure_refs = ([{'asset_id': 'figure-one', 'caption': ''}] if selected_figure else [])
    return {
        'assets': {'figure-one': {'path': '/tmp/images/panel.png'}},
        'slides': [{
            'id': 'P1',
            'semantic': {'title': '', 'takeaway': '', 'speaker_notes': '',
                         'evidence_refs': list(evidence_refs or ['EV0001', 'EV0002']), 'caveats': []},
            'composition': {'blocks': [{'text': visible, 'label': ''}],
                            'figure_refs': figure_refs, 'tables': [],
                            'graphics': list(graphics or []), 'charts': list(charts or [])},
        }],
    }


class PageDesignV11Tests(AgentCase):
    def test_custom_design_passes_without_legacy_claim_items_anchor_or_shape(self):
        design = reference_design()
        self.assertEqual(validate_design(design, STORY, EVIDENCE, slide_count=4), [])
        for page in design['pages']:
            for legacy in ('claim', 'items', 'anchor', 'rationale', 'shape', 'marks'):
                self.assertNotIn(legacy, page)

    def test_missing_duplicate_and_unknown_content_refs_are_rejected(self):
        design = reference_design()
        design['pages'][1]['content_refs'].remove('S1.key_points[0]')
        self.assertIn('unused Story item S1.key_points[0]', ' '.join(validate_design(design, STORY, EVIDENCE)))

        design = reference_design()
        design['pages'][1]['content_refs'].append('S1.answer')
        self.assertIn('content_refs must be a list of unique Story paths',
                      ' '.join(validate_design(design, STORY, EVIDENCE)))

        design = reference_design()
        design['pages'][2]['content_refs'].append('S1.answer')
        self.assertIn('appears on 2 pages', ' '.join(validate_design(design, STORY, EVIDENCE)))

        design = reference_design()
        design['pages'][3]['content_refs'] = ['S9.answer']
        problems = ' '.join(validate_design(design, STORY, EVIDENCE))
        self.assertIn('unknown Story content_ref', problems)
        self.assertIn('unused Story item ending.takeaway', problems)

    def test_unknown_story_evidence_and_unlisted_figure_are_rejected(self):
        story = copy.deepcopy(STORY)
        story['story'][0]['evidence'] = ['EV_UNKNOWN']
        problems = ' '.join(validate_design(reference_design(), story, EVIDENCE))
        self.assertIn('unknown evidence EV_UNKNOWN', problems)

        design = reference_design()
        design['pages'][1]['figures'] = ['images/missing.png']
        with self.assertRaises(a.Failure) as caught:
            a.check_design(design, STORY, EVIDENCE, slide_count=4,
                           figures=[{'asset_id': 'images/panel.png'}])
        self.assertEqual(caught.exception.code, 'PAGE_DESIGN_INVALID')
        self.assertIn('unknown figure asset images/missing.png', str(caught.exception))

    def test_title_numbers_must_be_grounded_in_assigned_story_evidence(self):
        design = reference_design()
        design['pages'][1]['title'] = 'Accuracy 99%'
        self.assertIn('title number 99% is not in the cited evidence',
                      ' '.join(validate_design(design, STORY, EVIDENCE)))

    def test_malformed_reference_and_design_values_fail_without_type_errors(self):
        cases = []
        design = reference_design()
        design['pages'][1]['content_refs'] = {'S1.answer': True}
        cases.append(design)
        design = reference_design()
        design['pages'][1]['design'] = []
        cases.append(design)
        design = reference_design()
        design['pages'][1]['figures'] = ['']
        cases.append(design)
        design = reference_design()
        design['pages'][1]['id'] = 12
        cases.append(design)
        for malformed in cases:
            with self.subTest(malformed=malformed):
                self.assertTrue(validate_design(malformed, STORY, EVIDENCE))

    def test_schema_and_runtime_agree_on_structural_validity(self):
        schema = json.loads(DESIGN_SCHEMA.read_text(encoding='utf-8'))
        validator = Draft202012Validator(schema)
        valid = reference_design()
        self.assertTrue(validator.is_valid(valid))
        self.assertEqual(validate_design(valid, STORY, EVIDENCE), [])

        invalid_cases = []
        design = copy.deepcopy(valid)
        del design['pages'][1]['content_refs']
        invalid_cases.append(design)
        design = copy.deepcopy(valid)
        design['pages'][1]['design'] = {}
        invalid_cases.append(design)
        design = copy.deepcopy(valid)
        design['pages'][1]['figures'] = 'images/panel.png'
        invalid_cases.append(design)
        design = copy.deepcopy(valid)
        design['pages'][1]['title'] = '   '
        invalid_cases.append(design)
        design = copy.deepcopy(valid)
        design['pages'][1]['content_refs'].append('S1.answer')
        invalid_cases.append(design)
        design = copy.deepcopy(valid)
        design['setting']['reading'] = 'visual'
        invalid_cases.append(design)
        for invalid in invalid_cases:
            with self.subTest(invalid=invalid):
                self.assertFalse(validator.is_valid(invalid))
                self.assertTrue(validate_design(invalid, STORY, EVIDENCE))

    def test_binding_is_non_mutating_and_preserves_custom_visual_instructions(self):
        design = reference_design()
        design['pages'][1]['custom_elements'] = {'focus': 'thin yellow outline'}
        original = copy.deepcopy(design)
        bound = bind_design(design, STORY)
        self.assertEqual(design, original)
        self.assertTrue(bound['_content_bound'])
        self.assertEqual(bound['pages'][1]['design'], original['pages'][1]['design'])
        self.assertEqual(bound['pages'][1]['custom_elements'], original['pages'][1]['custom_elements'])
        self.assertEqual(bound['pages'][1]['items'][0]['id'], 'S1.answer')
        self.assertEqual(bound['pages'][1]['items'][0]['text'], STORY['story'][0]['answer'])
        self.assertEqual(bound['pages'][1]['items'][0]['evidence'], ['EV0001', 'EV0002'])

    def test_ir_realization_keeps_evidence_numbers_and_selected_figure(self):
        design = bind_design(one_page_design(['images/panel.png']), STORY)
        ir = one_slide_ir(visible='N=512 at 300 K', evidence_refs=['EV0001', 'EV0002'])
        a.check_design_realization(ir, design)

        without_evidence = one_slide_ir(visible='N=512 at 300 K', evidence_refs=['EV0001'])
        with self.assertRaisesRegex(a.Failure, 'must keep evidence'):
            a.check_design_realization(without_evidence, design)

        without_figure = one_slide_ir(visible='N=512 at 300 K', selected_figure=False)
        with self.assertRaisesRegex(a.Failure, 'lost selected figure'):
            a.check_design_realization(without_figure, design)

        without_numbers = one_slide_ir(visible='A measured result', evidence_refs=['EV0001', 'EV0002'])
        with self.assertRaisesRegex(a.Failure, 'lost the numbers'):
            a.check_design_realization(without_numbers, design)

    def test_native_graphic_labels_and_chart_values_carry_numbers_but_geometry_does_not(self):
        design = bind_design(one_page_design(), STORY)
        graphic = {'id': 'device', 'labels': [{'id': 'sample-size', 'text': 'N=512 at 300 K'}],
                   'geometry': {'x': 512, 'y': 300}}
        a.check_design_realization(one_slide_ir(graphics=[graphic]), design)

        chart = {'id': 'measured-values', 'x': {'label': 'condition', 'values': [300, 512]},
                 'y': {'label': 'count'},
                 'series': [{'label': 'Measured', 'values': [512, 300],
                             'evidence_refs': ['EV0001', 'EV0002']}],
                 'annotations': []}
        a.check_design_realization(one_slide_ir(charts=[chart]), design)

        geometry_only = {'id': 'device', 'labels': [], 'coordinates': [512, 300],
                         'position': {'x': 512, 'y': 300}}
        with self.assertRaisesRegex(a.Failure, 'lost the numbers'):
            a.check_design_realization(one_slide_ir(graphics=[geometry_only]), design)

    def test_unbound_raw_design_cannot_validate_an_ir(self):
        with self.assertRaisesRegex(a.Failure, 'Resolve content_refs with bind_design'):
            a.check_design_realization(one_slide_ir(visible='N=512 at 300 K'), one_page_design())

    def test_load_and_finalize_keep_custom_fields_and_supply_story_evidence_map(self):
        work = self.out/'work'
        raw = reference_design()
        raw['pages'][1]['arbitrary_diagram'] = {'nodes': ['input', 'response'], 'emphasis': 'yellow'}
        write(work/'page_design.json', raw)
        write(work/'story_plan.json', STORY)
        write(work/'ir_prompt.json', {'instructions': 'Implement the page.',
                                      'workflow': {'large_stale_input': True},
                                      'rpa_input': {'duplicate': True}})
        loaded = a.load_design(work)
        self.assertEqual(loaded['pages'][1]['design'], raw['pages'][1]['design'])
        self.assertEqual(loaded['pages'][1]['arbitrary_diagram'], raw['pages'][1]['arbitrary_diagram'])
        self.assertEqual(read(work/'page_design.json'), raw)

        path = a.finalize_design(work, design=loaded)
        prompt = read(path)
        page = prompt['page_design']['pages'][1]
        self.assertEqual(page['design'], raw['pages'][1]['design'])
        self.assertEqual(page['arbitrary_diagram'], raw['pages'][1]['arbitrary_diagram'])
        catalog = prompt['content_catalog']
        self.assertEqual(catalog['S1.answer']['evidence'], ['EV0001', 'EV0002'])
        self.assertEqual(catalog['ending.takeaway']['evidence'], ['EV0001', 'EV0002', 'EV0003'])
        self.assertNotIn('workflow', prompt)
        self.assertNotIn('rpa_input', prompt)

    def test_finalize_requires_story_source_for_v11(self):
        work = self.out/'work'
        write(work/'page_design.json', reference_design())
        write(work/'ir_prompt.json', {'instructions': 'Implement the page.'})
        with self.assertRaises(a.Failure) as caught:
            a.finalize_design(work)
        self.assertEqual(caught.exception.code, 'PAGE_DESIGN_SOURCE_MISSING')
        self.assertEqual(caught.exception.action, 'resolve_dependency')

    def test_runner_accept_and_design_complete_use_bound_design(self):
        work = self.out/'work'
        raw = one_page_design(['images/panel.png'])
        ir = one_slide_ir(visible='N=512 at 300 K')
        write(work/'page_design.json', raw)
        write(work/'story_plan.json', STORY)
        write(work/'deck_ir.json', ir)
        job = {'job_id': 'job', 'request': {'out_dir': str(self.out), 'slide_count': 1,
                                             'supplement': 'off'},
               'checkpoints': {}, 'attempts': {}}
        checked = []

        def capture_check(value, *args, **kwargs):
            checked.append(kwargs['design'])

        with patch.object(a, 'apply_art_direction', return_value=(ir, [])), \
             patch.object(a, 'check_ir', side_effect=capture_check), \
             patch.object(a, 'persist_ir'), patch.object(a, 'resources', return_value={}), \
             patch.object(runner, 'checkpoint'):
            runner._accept(job, runner.BY_ARTIFACT['deck_ir'], 'upstream', 'deck_ir', work/'deck_ir.json')

        with patch.object(a, 'check_ir', side_effect=capture_check), \
             patch('deck_compiler.visual_planner.pending_design',
                   return_value={'academic_design_required': False, 'slide_ids': []}):
            self.assertTrue(runner.design_complete(job))

        self.assertEqual(len(checked), 2)
        for design in checked:
            self.assertTrue(design['_content_bound'])
            self.assertEqual(design['pages'][0]['items'][0]['text'], STORY['story'][0]['answer'])

    def test_repair_preflight_uses_bound_design_without_running_compiler(self):
        work = self.out/'work'
        base_ir = one_slide_ir(visible='N=512 at 300 K')
        base_path = work/'deck_ir.json'
        write(base_path, base_ir)
        write(work/'page_design.json', one_page_design(['images/panel.png']))
        write(work/'story_plan.json', STORY)
        patch_value = {'mode': 'preflight', 'asset_updates': {}, 'slide_updates': [],
                       'base_ir_sha256': sha(base_path), 'base_resources_sha256': digest({})}
        patch_path = work/'deck_ir_patch.json'
        write(patch_path, patch_value)
        job = {'job_id': 'job', 'request': {'out_dir': str(self.out), 'slide_count': 1,
                                             'supplement': 'off'}}
        checked = []

        def capture_check(value, *args, **kwargs):
            checked.append(kwargs['design'])

        original_read = repair.read

        def read_preflight_artifacts(path):
            if Path(path).name == 'layout.json':
                return {'assets': {}}
            return original_read(path)

        with patch.object(repair, 'resource_snapshot', return_value={}), \
             patch.object(repair, 'patched_ir', side_effect=lambda value, item, path: (value, [], {})), \
             patch.object(repair, 'read', side_effect=read_preflight_artifacts), \
             patch.object(a, 'check_ir', side_effect=capture_check), patch.object(a, 'persist_ir'), \
             patch('deck_compiler.pipeline.compile_input',
                   return_value=(None, None, {'counts': {'FAIL': 0}})) as compile_input:
            result = repair._preflight(job, patch_value, patch_path)

        self.assertEqual(result.summary['status'], 'preflight_passed')
        compile_input.assert_called_once()
        self.assertEqual(len(checked), 1)
        self.assertTrue(checked[0]['_content_bound'])
        self.assertEqual(checked[0]['pages'][0]['items'][0]['text'], STORY['story'][0]['answer'])


if __name__ == '__main__':
    unittest.main()
