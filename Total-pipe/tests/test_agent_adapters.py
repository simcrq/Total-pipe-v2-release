import json
import subprocess
import sys
import unittest
import os
from pathlib import Path
from unittest.mock import patch

from agent import adapters as a
from agent.state import write, read
from agent_fixture import AgentCase, workflow, story


class AdapterTests(AgentCase):
    def test_design_task_is_independent_of_compiler_capabilities(self):
        task = a.design_task({'figures': [{}, {}, {}], 'briefs': [{}]*5})
        self.assertIn('5 条参考 briefs', task)
        self.assertIn('3 张', task)
        self.assertNotIn('forms', task)
        self.assertNotIn('devices', task)
        self.assertIn('page_design_prompt.json', task)
        self.assertIn('page_design.json', task)
        self.assertIn('content_refs', task)
        self.assertIn('精确资产 id', task)
        self.assertIn('讲解顺序', task)
        self.assertIn('不展开第二次听众分析', task)
        self.assertIn('nothing you decide here depends on what a tool can draw', a.DESIGN_INSTRUCTIONS)
        self.assertIn('You may draw your own explanatory diagrams', a.DESIGN_INSTRUCTIONS)
        self.assertNotIn('MUST', a.DESIGN_INSTRUCTIONS)

    def test_story_binding_uses_delegation_and_existing_provenance_gate(self):
        from pwf2rpa import Workflow, build_story_prompt
        from atomic_fixture import atomic_story, atomic_workflow
        valid = atomic_story()
        prompt = build_story_prompt(Workflow(atomic_workflow(valid)), model='test-model', reasoning_effort='high', selected_by_user=True)
        a.check_story(prompt, valid, atomic_workflow(valid))
        bad = story()
        bad['planner']['reasoning_effort'] = 'medium'
        with self.assertRaisesRegex(a.Failure, 'differs'):
            a.check_story(prompt, bad, workflow())
        bad['planner'] = {}
        with self.assertRaises(a.Failure) as caught:
            a.check_story(prompt, bad, workflow())
        self.assertEqual(caught.exception.action, 'author_artifact')
        bad = story()
        bad['planner']['mode'] = 'main_agent'
        with self.assertRaises(a.Failure):
            a.check_story(prompt, bad, workflow())

    def test_compact_process_metadata_must_be_carried_into_ir(self):
        ir = json.loads((a.COMPONENT/'examples/native-graphic.deck_ir.json').read_text(encoding='utf-8'))
        page = ir['slides'][1]
        page['id'] = 'compact-eight'
        page['semantic']['evidence_refs'] = []
        graphic = page['composition']['graphics'][0]
        items = [f'Step {index}' for index in range(1, 9)]
        graphic.update(layout='compact', direction='horizontal',
                       nodes=[{'id': f'n{index}', 'title': item} for index, item in enumerate(items)],
                       edges=[{'from': f'n{index}', 'to': f'n{index+1}'} for index in range(7)])
        ir['slides'] = [page]
        normalized = {'slide_briefs': [{'body': '', 'key_points': [], 'metadata': {
            'story_compact_process': {'items': items, 'node_count': len(items)}}}], 'evidence': []}
        a.check_ir(ir, normalized)

        broken = json.loads(json.dumps(ir))
        broken['slides'][0]['composition']['graphics'][0]['nodes'] = graphic['nodes'][:3]
        broken['slides'][0]['composition']['graphics'][0]['edges'] = graphic['edges'][:2]
        with self.assertRaisesRegex(a.Failure, 'compact process'):
            a.check_ir(broken, normalized)

    def test_classification_targets_the_stage_that_can_repair_the_fault(self):
        for code, stage, target in [('KEY_POINTS_LOST','rpa','story'), ('SOURCE_TEXT_NOT_BOUND','deck_ir','deck_ir'),
                                      ('INSUFFICIENT_FORMULA_SPACE','build','deck_ir'),
                                      ('VISUAL_PLAN_UNSATISFIABLE','build','visual_design')]:
            self.assertEqual(a.classify(code, 'detail', stage).target, target)
        self.assertEqual(a.classify('COMPILATION_FAILED', 'unknown', 'build').action, 'review_required')

    def test_subprocess_encoding_timeout_bad_json_and_secret_redaction(self):
        with patch.dict('os.environ', {'EXAMPLE_API_KEY': 'sensitive-example-value'}):
            process = subprocess.CompletedProcess([], 1, '', 'sensitive-example-value')
            with patch.object(a, 'run_process', return_value=process):
                with self.assertRaises(a.Failure):
                    a.run(['fake'], self.root, self.out, 'fake')
            self.assertNotIn('sensitive-example-value', (self.out/'logs/fake.json').read_text())
        with patch.object(a, 'run_process', side_effect=subprocess.TimeoutExpired('fake', 1)):
            with self.assertRaises(a.Failure) as caught:
                a.run(['fake'], self.root, self.out, 'fake', 1)
        self.assertEqual(caught.exception.code, 'COMPONENT_TIMEOUT')

    def test_rpa_normalize_only_preserves_complete_content_and_evidence(self):
        self.out.mkdir()
        work = self.out/'work'
        write(work/'evidence_pointer.json', {'workflow': str(self.root/'workflow.json')})
        write(self.root/'workflow.json', workflow())
        payload = {'paperworkflow_v4': workflow(), 'slide_briefs': [{'id': 'SLIDE0001',
            'body': 'Complete original scientific body with its experimental conditions.',
            'key_points': ['The independent control retains the stated uncertainty.'],
            'evidence_ids': ['EV0001']}]}
        def pwf(out, *args): write(work/'rpa_input.json', payload)
        calls = []
        model = {'slide_briefs': payload['slide_briefs'], 'status': 'valid',
                 'evidence': workflow()['evidence_registry']}
        def rpa(command, path, out, **kwargs):
            calls.append((command, read(path)))
            self.assertEqual(command, 'normalize-content', 'The four-tool adapter must not run template planning or validation.')
            return model
        job = {'request': {'out_dir': str(self.out), 'language': 'en', 'requirements': 'Preserve source details', 'presentation_type': 'journal_club'}}
        with patch.object(a, 'pwf_cli', side_effect=pwf), patch.object(a, 'rpa', side_effect=rpa):
            a.execute('rpa', job)
        self.assertEqual(calls, [('normalize-content', payload)])
        self.assertEqual(read(work/'normalized_content.json'), model)
        prompt = read(work/'ir_prompt.json')
        self.assertEqual(read(prompt['content_paths']['normalized_content']), model)
        self.assertEqual(read(work/'rpa_input.json')['paperworkflow_v4'], payload['paperworkflow_v4'])
        self.assertEqual(prompt['request']['presentation_type'], 'journal_club')
        self.assertFalse(prompt.get('deck_plan'))

    def test_normalize_only_does_not_reintroduce_a_stale_template_plan(self):
        work = self.out/'work'
        write(work/'evidence_pointer.json', {'workflow': str(self.root/'workflow.json')})
        write(self.root/'workflow.json', workflow())
        write(work/'deck_plan.json', {'marker': 'STALE_TEMPLATE_PLAN_MUST_NOT_PROPAGATE'})
        payload = {'paperworkflow_v4': workflow(), 'slide_briefs': [{'id': 'SLIDE0001', 'body': 'Complete body.'}]}
        model = {'slide_briefs': payload['slide_briefs'], 'status': 'valid'}
        def pwf(out, *args):
            write(work/'rpa_input.json', payload)
        job = {'request': {'out_dir': str(self.out), 'language': 'en', 'requirements': '',
                          'presentation_type': 'group_meeting'}}
        with patch.object(a, 'pwf_cli', side_effect=pwf), patch.object(a, 'rpa', return_value=model) as normalize:
            outputs = a.execute('rpa', job)
        normalize.assert_called_once()
        self.assertEqual(normalize.call_args.args[0], 'normalize-content')
        self.assertNotIn('STALE_TEMPLATE_PLAN_MUST_NOT_PROPAGATE', (work/'ir_prompt.json').read_text())
        self.assertNotIn(work/'deck_plan.json', outputs)

    def test_missing_scientific_body_is_not_accepted_as_valid_ir(self):
        value = read(self.fixture_ir())
        with self.assertRaises(a.Failure) as caught:
            a.check_ir(value, {'slide_briefs': [{'body': 'A required complete scientific statement not in the deck.'}]})
        self.assertEqual(caught.exception.code, 'CONTENT_LOSS')

    def test_imported_relative_assets_are_rebased_and_schema_prompt_uses_real_catalog(self):
        destination = self.root/'work/deck_ir.json'
        a.import_ir(self.fixture_ir(), destination)
        value = read(destination)
        self.assertTrue(all(Path(asset['path']).is_absolute() for asset in value['assets'].values()))
        from deck_compiler.catalog import ARCHETYPES
        self.assertEqual(a.ir_prompt({}, {}, {}, {})['archetypes'], ARCHETYPES)

    def test_real_utf8_subprocess_protocol(self):
        result = a.run([sys.executable, '-c', 'import json; print(json.dumps({"text":"中文"}, ensure_ascii=False))'],
                       self.root, self.out, 'utf8')
        self.assertEqual(result, {'text': '中文'})

    @unittest.skipIf(os.name == 'nt', 'POSIX process-group integration; Windows uses taskkill /T')
    def test_timeout_terminates_descendant_processes(self):
        signal_file = self.root/'child-terminated'
        ready = self.root/'child-ready'
        child = ('import signal,time; from pathlib import Path; '
            f'signal.signal(signal.SIGTERM,lambda *args:(Path({str(signal_file)!r}).write_text("terminated"),exit(0))); '
            f'Path({str(ready)!r}).write_text("ready"); time.sleep(60)')
        parent = f'import subprocess,sys,time; subprocess.Popen([sys.executable,"-c",{child!r}]); time.sleep(60)'
        with self.assertRaises(a.Failure) as caught:
            a.run([sys.executable, '-c', parent], self.root, self.out, 'timeout-family', timeout=2)
        self.assertEqual(caught.exception.code, 'COMPONENT_TIMEOUT')
        self.assertTrue(ready.is_file())
        self.assertTrue(signal_file.is_file())

    def test_failed_rpa_plan_without_error_items_still_requires_story_replanning(self):
        result = subprocess.CompletedProcess([], 0, json.dumps({'status': 'failed', 'slides': [],
            'unplanned_slide_briefs': [{'body': 'Must be retained'}]}), '')
        with patch.object(a, 'run_process', return_value=result):
            with self.assertRaises(a.Failure) as caught:
                a.run(['node', 'cli.mjs'], self.root, self.out, 'rpa-plan')
        self.assertEqual(caught.exception.action, 'replan')
        self.assertEqual(caught.exception.target, 'story')
