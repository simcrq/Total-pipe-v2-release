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
    def test_story_binding_uses_delegation_and_existing_provenance_gate(self):
        from pwf2rpa import Workflow, build_story_prompt
        prompt = build_story_prompt(Workflow(workflow()), model='test-model', reasoning_effort='high', selected_by_user=True)
        a.check_story(prompt, story(), workflow())
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

    def test_rpa_file_payload_and_full_original_content_validation(self):
        self.out.mkdir()
        work = self.out/'work'
        write(work/'evidence_pointer.json', {'workflow': str(self.root/'workflow.json')})
        write(self.root/'workflow.json', workflow())
        payload = {'paperworkflow_v4': workflow(), 'slide_briefs': [{'id': 'SLIDE0001', 'body': 'Complete original body'}]}
        def pwf(out, *args): write(work/'rpa_input.json', payload)
        calls = []
        model = {'slide_briefs': payload['slide_briefs'], 'status': 'valid'}
        def rpa(command, path, out):
            calls.append((command, read(path)))
            return model if command == 'normalize-content' else {'slides': [{'id': 'SLIDE0001'}]} if command == 'plan' else {'status': 'valid'}
        job = {'request': {'out_dir': str(self.out), 'language': 'en', 'requirements': 'Preserve source details', 'presentation_type': 'journal_club'}}
        with patch.object(a, 'pwf_cli', side_effect=pwf), patch.object(a, 'rpa', side_effect=rpa):
            a.execute('rpa', job)
        self.assertEqual(calls[1][1]['presentation_type'], 'journal_club')
        self.assertEqual(calls[2][1]['content_model'], model)
        self.assertEqual(calls[1][1]['paperworkflow_v4'], payload['paperworkflow_v4'])

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
