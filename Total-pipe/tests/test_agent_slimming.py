"""Regression tests for page-count freedom, compact responses and read-only inspection."""
import copy
from datetime import datetime, timedelta
import json
import math
import subprocess
import sys
from unittest.mock import patch

from agent import adapters as a, runner
from agent.state import read, write
from agent_fixture import AgentCase, workflow
from deck_compiler.design import story_items


def scientific_story_and_design():
    story = {
        'story': [{'answer': f'Scientific observation {chr(97+i)}.',
                   'key_points': ['Measured at 300 K.'] * (2 if i < 2 else 1),
                   'evidence': ['EV0001']} for i in range(9)],
        'ending': {'takeaway': 'The measured response is reproducible.',
                   'limitation': 'Only the tested conditions were measured.'},
    }
    pages = [{'id': f'P{i}', 'role': 'result', 'claim': 'Measured at 300 K.',
              'shape': 'One scientific statement with its supporting observation.',
              'anchor': {'kind': 'none', 'why': 'A single observation.'},
              'items': [{'id': f'item-{i}', 'source': source, 'text': text,
                         'evidence': ['EV0001']}], 'rationale': 'Keep the full scientific unit.'}
             for i, (source, text) in enumerate(story_items(story).items(), 1)]
    design = {'schema_version': '1.0', 'deck_id': 'scientific',
              'setting': {'audience': 'Scientific peers', 'occasion': 'group-meeting',
                          'reading': 'spoken'}, 'pages': pages}
    evidence = {'EV0001': 'The scientific observations were measured at 300 K.'}
    return story, design, evidence


class SlimmingTests(AgentCase):
    def prepare_rpa(self):
        work = self.out/'work'
        flow = workflow()
        write(self.root/'workflow.json', flow)
        write(work/'evidence_pointer.json', {'workflow': str(self.root/'workflow.json')})
        story, _, _ = scientific_story_and_design()
        write(work/'story_plan.json', story)
        briefs = [{'id': f'brief-{i}', 'slide_id': f'brief-{i}',
                   'title': f'Observation {i}', 'body': f'Complete scientific observation {i}.',
                   'key_points': [], 'evidence_ids': ['EV0001']} for i in range(11)]
        payload = {'paperworkflow_v4': flow, 'slide_briefs': briefs}
        model = {'slide_briefs': briefs, 'status': 'valid'}
        job = {'request': {'out_dir': str(self.out), 'language': 'en', 'requirements': '',
                          'presentation_type': 'group_meeting', 'slide_count': 22}}
        def pwf(out, *args):
            write(work/'rpa_input.json', payload)
        def rpa(command, path, out, **kwargs):
            if command == 'normalize-content':
                return model
            if command == 'plan':
                return {'slides': [{'id': b['id']} for b in briefs]}
            return {'status': 'valid'}
        return work, job, pwf, rpa

    def test_target_22_pages_does_not_require_22_story_nodes_or_briefs(self):
        work, job, pwf, rpa = self.prepare_rpa()
        with patch.object(a, 'pwf_cli', side_effect=pwf), patch.object(a, 'rpa', side_effect=rpa):
            a.execute('rpa', job)
        self.assertEqual(len(read(work/'story_plan.json')['story']), 9)
        self.assertEqual(len(read(work/'normalized_content.json')['slide_briefs']), 11)
        self.assertEqual(read(work/'ir_prompt.json')['request']['slide_count'], 22)
        a.execute('page_design', job)
        self.assertEqual(read(work/'page_design_prompt.json')['request']['slide_count'], 22)
        story, design, evidence = scientific_story_and_design()
        self.assertEqual(len(design['pages']), 22)
        a.check_design(design, story, evidence)
        a.check_design(design, story, evidence, slide_count=22)
        with self.assertRaises(a.Failure) as caught:
            a.check_design(design, story, evidence, slide_count=21)
        self.assertEqual(caught.exception.code, 'PAGE_DESIGN_INVALID')
        ir = read(self.fixture_ir())
        ir['assets'] = {}
        ir['slides'] = [{'id': page['id'], 'semantic': {
            'purpose': 'Retain the full scientific unit while splitting reasoning into pages.',
            'title': page['claim'], 'takeaway': page['claim'],
            'speaker_notes': page['items'][0]['text'], 'evidence_refs': ['EV0001'], 'caveats': []},
            'composition': {'archetype': 'composite-research',
                'blocks': [{'id': 'body', 'component': 'body', 'text': page['items'][0]['text']}],
                'figure_refs': [], 'layout_tree': {'version': '1.0', 'regions': {
                    'body': {'id': 'leaf', 'type': 'block', 'ref': 'body'}}}},
            'presentation': {'variant': 'default'}} for page in design['pages']]
        normalized = read(work/'normalized_content.json')
        normalized['evidence'] = [{'evidence_id': key, 'text': text} for key, text in evidence.items()]
        a.check_ir(ir, normalized, design=design, slide_count=22)

    def test_merging_complete_briefs_keeps_content_and_evidence_gates(self):
        value = read(self.fixture_ir())
        page = value['slides'][0]
        page['semantic'] = {
            'purpose': 'Test complete scientific content when two briefs share one page.',
            'title': 'Measured response', 'takeaway': 'The measured response is reproducible.',
            'speaker_notes': 'The calibrated probe measures the response. Independent controls confirm the observation.',
            'evidence_refs': ['EV0001'], 'caveats': []}
        page['composition'] = {
            'archetype': 'composite-research',
            'blocks': [{'id': 'body', 'component': 'body',
                        'text': 'The calibrated probe measures the response. Independent controls confirm the observation.'}],
            'figure_refs': [],
            'layout_tree': {'version': '1.0', 'regions': {
                'body': {'id': 'leaf', 'type': 'block', 'ref': 'body'}}}}
        page['presentation'] = {'variant': 'default'}
        value['slides'] = [page]
        normalized = {'slide_briefs': [
            {'body': 'The calibrated probe measures the response.'},
            {'body': 'Independent controls confirm the observation.'}],
            'evidence': [{'evidence_id': 'EV0001', 'text': 'The calibrated probe measures the response.'}]}
        a.check_ir(copy.deepcopy(value), normalized)
        missing = copy.deepcopy(value)
        missing['slides'][0]['semantic']['speaker_notes'] = 'The calibrated probe measures the response.'
        missing['slides'][0]['composition']['blocks'][0]['text'] = 'The calibrated probe measures the response.'
        with self.assertRaises(a.Failure) as caught:
            a.check_ir(missing, normalized)
        self.assertEqual(caught.exception.code, 'CONTENT_LOSS')
        unknown = copy.deepcopy(value)
        unknown['slides'][0]['semantic']['evidence_refs'] = ['EV_UNKNOWN']
        with self.assertRaises(a.Failure) as caught:
            a.check_ir(unknown, normalized)
        self.assertEqual(caught.exception.code, 'CONTENT_LOSS')

    def test_expanded_design_keeps_coverage_evidence_and_numeric_gates(self):
        story, design, evidence = scientific_story_and_design()
        missing = copy.deepcopy(design)
        missing['pages'].pop()
        with self.assertRaisesRegex(a.Failure, 'unused Story item'):
            a.check_design(missing, story, evidence)
        duplicate = copy.deepcopy(design)
        duplicate['pages'][1]['items'].append(copy.deepcopy(duplicate['pages'][0]['items'][0]))
        with self.assertRaisesRegex(a.Failure, 'appears on 2 pages'):
            a.check_design(duplicate, story, evidence)
        unknown = copy.deepcopy(design)
        unknown['pages'][0]['items'][0]['evidence'] = ['EV_UNKNOWN']
        with self.assertRaisesRegex(a.Failure, 'unknown evidence'):
            a.check_design(unknown, story, evidence)
        invented = copy.deepcopy(design)
        invented['pages'][0]['items'][0]['text'] = 'Measured at 777 K.'
        with self.assertRaisesRegex(a.Failure, 'number 777'):
            a.check_design(invented, story, evidence)

    def test_approved_design_is_checked_even_without_normalized_rpa_content(self):
        value = read(self.fixture_ir())
        design = {'pages': [{'id': f'P{i}', 'items': []}
                            for i in range(len(value['slides']))]}
        a.check_ir(copy.deepcopy(value), design=design)
        missing_evidence = copy.deepcopy(design)
        missing_evidence['pages'][0]['items'] = [
            {'text': 'An observation.', 'evidence': ['EV_MUST_RETAIN']}]
        with self.assertRaises(a.Failure) as caught:
            a.check_ir(copy.deepcopy(value), design=missing_evidence)
        self.assertEqual(caught.exception.code, 'DESIGN_REALIZATION_FAILED')
        missing_number = copy.deepcopy(design)
        missing_number['pages'][0]['items'] = [{'text': 'Measured at 987654 K.', 'evidence': []}]
        with self.assertRaises(a.Failure) as caught:
            a.check_ir(copy.deepcopy(value), design=missing_number)
        self.assertEqual(caught.exception.code, 'DESIGN_REALIZATION_FAILED')

    def test_supplement_page_is_extra_but_cannot_hide_a_paper_evidence_page(self):
        value = read(a.COMPONENT/'examples/research.deck_ir.json')
        value['slides'] = [copy.deepcopy(value['slides'][1])]
        supplement = copy.deepcopy(value['slides'][0])
        supplement['id'] = 'extra-background'
        supplement['semantic']['evidence_refs'] = []
        for block in supplement['composition']['blocks']:
            block['basis'] = 'supplement'
            block['supplement'] = {'kind': 'background', 'source': 'A textbook definition.'}
        value['slides'].append(supplement)
        a.check_ir(copy.deepcopy(value), supplement='pages', slide_count=1)
        value['slides'][1]['semantic']['evidence_refs'] = ['EV0001']
        with self.assertRaises(a.Failure) as caught:
            a.check_ir(value, supplement='pages', slide_count=1)
        self.assertEqual(caught.exception.code, 'SLIDE_COUNT_MISMATCH')

    def test_invalid_presentation_type_and_count_fail_before_creating_job(self):
        for kind in ('not-a-presentation', '', None, 1, [], {}):
            with self.subTest(presentation_type=kind), self.assertRaises(ValueError):
                runner.start(str(self.source), str(self.out), 'en', kind)
            self.assertFalse(self.out.exists())
        for count in (False, True, 0, -1, 41, '22', 22.0, [], {}):
            with self.subTest(slide_count=count), self.assertRaises(ValueError):
                runner.start(str(self.source), str(self.out), 'en', 'group_meeting', slide_count=count)
            self.assertFalse(self.out.exists())

    def test_presentation_aliases_normalize_before_resume_matching(self):
        cases = {'组会': 'group_meeting', '研究生组会': 'group_meeting',
                 'group-meeting': 'group_meeting', 'research-sharing': 'journal_club',
                 'research-report': 'paper_presentation', 'lecture': 'custom', 'commercial': 'custom'}
        for number, (alias, canonical) in enumerate(cases.items()):
            with self.subTest(alias=alias):
                out = self.root/f'alias-{number}'
                result = runner.start(str(self.source), str(out), 'en', alias)
                request = read(out/'.totalpipe/job.json')['request']
                self.assertEqual(request['presentation_type'], canonical)
                if alias in ('lecture', 'commercial'):
                    self.assertIn(alias, request['presentation_context'])
                repeated = runner.start(str(self.source), str(out), 'en', alias)
                self.assertEqual(repeated['job_id'], result['job_id'])

    def test_legacy_raw_alias_request_resumes_without_rewriting_authorization(self):
        cases = [('组会', 'group_meeting'), ('research-sharing', 'journal_club'),
                 ('研究生组会，面向本领域研究生，约30分钟。',
                  '研究生组会，面向本领域研究生，约30分钟。')]
        for index, (legacy_label, requested_label) in enumerate(cases):
            with self.subTest(legacy_label=legacy_label):
                out = self.root/f'legacy-{index}'
                result = runner.start(str(self.source), str(out), 'en', legacy_label)
                state = out/'.totalpipe/job.json'
                job = read(state)
                job['request']['presentation_type'] = legacy_label
                job['request'].pop('presentation_context', None)
                job['inputs'] = {'model': 'explicitly-selected-model', 'reasoning_effort': 'high',
                                 'selected_by_user': True}
                write(state, job)
                expected_request, expected_inputs = copy.deepcopy(job['request']), copy.deepcopy(job['inputs'])
                resumed = runner.start(str(self.source), str(out), 'en', requested_label)
                self.assertEqual(resumed['job_id'], result['job_id'])
                self.assertNotEqual(resumed['next_action']['reason'], 'JOB_OUTPUT_IN_USE')
                self.assertEqual(read(state)['request'], expected_request)
                self.assertEqual(read(state)['inputs'], expected_inputs)

    def test_equivalent_occasion_aliases_resume_the_same_existing_job(self):
        for index, (first, second) in enumerate([
                ('group_meeting', '组会'), ('group-meeting', 'group_meeting'),
                ('research-sharing', 'journal_club'), ('lecture', '讲课'),
                ('组会，博士生，30分钟', 'group-meeting，博士生，30分钟')]):
            with self.subTest(first=first, second=second):
                out = self.root/f'equivalent-{index}'
                result = runner.start(str(self.source), str(out), 'en', first)
                request = read(out/'.totalpipe/job.json')['request']
                resumed = runner.start(str(self.source), str(out), 'en', second)
                self.assertEqual(resumed['job_id'], result['job_id'])
                self.assertNotEqual(resumed['next_action']['reason'], 'JOB_OUTPUT_IN_USE')
                self.assertEqual(read(out/'.totalpipe/job.json')['request'], request)

    def test_substantive_occasion_description_or_request_changes_are_rejected(self):
        cases = [('lecture', 'commercial', {}), ('lecture', 'custom', {}),
                 ('组会，博士生，30分钟', '组会，本科生，30分钟', {}),
                 ('group_meeting', '组会', {'requirements': 'Changed scientific focus'}),
                 ('group_meeting', '组会', {'slide_count': 22}),
                 ('group_meeting', '组会', {'language': 'zh'})]
        for index, (first, second, changes) in enumerate(cases):
            with self.subTest(first=first, second=second, changes=changes):
                out = self.root/f'different-{index}'
                runner.start(str(self.source), str(out), 'en', first)
                before = read(out/'.totalpipe/job.json')
                arguments = {'source': str(self.source), 'out_dir': str(out), 'language': 'en',
                             'presentation_type': second, **changes}
                rejected = runner.start(**arguments)
                self.assertEqual(rejected['next_action']['reason'], 'JOB_OUTPUT_IN_USE')
                self.assertEqual(read(out/'.totalpipe/job.json'), before)

    def test_default_envelopes_are_compact_and_full_status_has_inventory(self):
        result = runner.start(str(self.source), str(self.out), 'en', 'group_meeting', requirements='full requirement')
        for compact in (result, runner.advance(result['job_id']), runner.status(result['job_id'])):
            self.assertNotIn('request', compact)
            self.assertNotIn('artifacts', compact)
            self.assertIn('next_action', compact)
        full = runner.status(result['job_id'], detail='full')
        self.assertEqual(full['request']['requirements'], 'full requirement')
        self.assertIn('artifacts', full)
        from agent.mcp_server import transport
        handler = transport.TOOLS['totalpipe_status']['handler']
        self.assertNotIn('request', handler({'job_id': result['job_id']}))
        self.assertEqual(handler({'job_id': result['job_id'], 'detail': 'full'})['request'], full['request'])
        with self.assertRaises(ValueError):
            handler({'job_id': result['job_id'], 'detail': 'unknown'})
        cli = subprocess.run([sys.executable, '-m', 'agent', 'status', '--job-id', result['job_id'],
                              '--detail', 'full'], cwd=a.COMPONENT, capture_output=True, text=True)
        self.assertEqual(cli.returncode, 0, cli.stderr)
        self.assertEqual(json.loads(cli.stdout)['request'], full['request'])

    def test_imported_ir_must_meet_final_slide_target_before_build(self):
        target = len(read(self.fixture_ir())['slides']) + 1
        with patch('agent.runner.a.execute') as execute:
            result = runner.start(str(self.fixture_ir()), str(self.out), 'en', 'group_meeting', slide_count=target)
        execute.assert_not_called()
        self.assertEqual(result['next_action']['reason'], 'SLIDE_COUNT_MISMATCH')
        self.assertEqual(result['next_action']['type'], 'author_artifact')
        self.assertEqual(result['next_action']['target_stage'], 'deck_ir')

    def test_new_submission_failure_does_not_point_to_stale_layout_feedback(self):
        result = runner.start(str(self.source), str(self.out), 'en', 'group_meeting')
        stale = self.out/'build/layout_feedback.json'
        write(stale, {'code': 'OLD_UNRELATED_LAYOUT_FAILURE'})
        path = self.out/'work/queries.json'
        path.write_text('{broken', encoding='utf-8')
        failed = runner.advance(result['job_id'], artifact_kind='queries', artifact_path=str(path))
        self.assertEqual(failed['next_action']['reason'], 'ARTIFACT_INVALID_JSON')
        self.assertNotEqual(failed['next_action']['feedback_path'], str(stale))
        self.assertEqual(read(failed['next_action']['feedback_path'])['code'], 'ARTIFACT_INVALID_JSON')
        self.assertEqual(read(stale)['code'], 'OLD_UNRELATED_LAYOUT_FAILURE')

    def test_status_does_not_mutate_job_events_or_prompt_files(self):
        result = runner.start(str(self.source), str(self.out), 'en', 'group_meeting')
        def snapshot():
            return {str(p.relative_to(self.out)): (p.read_bytes(), p.stat().st_mtime_ns)
                    for p in self.out.rglob('*') if p.is_file() and p.name != 'lock'}
        before = snapshot()
        with patch('agent.runner.a.execute') as execute:
            runner.status(result['job_id'])
            runner.status(result['job_id'], detail='full')
        execute.assert_not_called()
        self.assertEqual(snapshot(), before)
        self.source.write_text('# Changed upstream source\n')
        runner.status(result['job_id'], detail='full')
        self.assertEqual(snapshot(), before)

    def test_inspecting_ir_stage_does_not_regenerate_missing_designed_prompt(self):
        result = runner.start(str(self.source), str(self.out), 'en', 'group_meeting')
        work = self.out/'work'
        _, design, _ = scientific_story_and_design()
        write(work/'page_design.json', design)
        write(work/'ir_prompt.json', {'instructions': 'Map the complete scientific design into IR.'})
        before = {str(p): p.read_bytes() for p in self.out.rglob('*') if p.is_file()}
        ir_stage = next(stage for stage in runner.STAGES if stage['id'] == 'deck_ir')
        # Inspect the derived pending stage in isolation; prompt creation belongs to advance.
        with patch.object(runner, 'current', return_value=(ir_stage, 'upstream')):
            pending = runner.status(result['job_id'], detail='full')
        self.assertEqual(pending['stage'], 'deck_ir')
        self.assertEqual({str(p): p.read_bytes() for p in self.out.rglob('*') if p.is_file()}, before)

    def test_timing_events_append_across_failure_retry_and_revision_without_private_content(self):
        result = runner.start(str(self.source), str(self.out), 'en', 'group_meeting',
                              requirements='PRIVATE_PROMPT_BODY')
        job_id = result['job_id']
        query = self.out/'work/queries.json'
        write(query, [{'id': 'response', 'query': 'measured response'}])
        with patch('agent.runner.a.execute', side_effect=a.Failure('DEPENDENCY_TEST_FAILURE',
                   'PRIVATE_MODEL_REASONING secret-test-api-key')):
            failed = runner.advance(job_id, artifact_kind='queries', artifact_path=str(query))
        self.assertEqual(failed['next_action']['reason'], 'DEPENDENCY_TEST_FAILURE')
        events_path = self.out/'logs/events.jsonl'
        failed_bytes = events_path.read_bytes()
        def evidence(stage, job):
            a.run([sys.executable, '-c', 'import json; print(json.dumps({"ok": True}))'],
                  self.root, self.out, 'local-evidence-probe')
            return self.fake_evidence(stage, job)
        with patch('agent.runner.a.execute', side_effect=evidence):
            recovered = runner.advance(job_id)
            self.assertEqual(recovered['stage'], 'model_selection')
            recovered_bytes = events_path.read_bytes()
            self.assertTrue(recovered_bytes.startswith(failed_bytes))
            runner.advance(job_id, replan_from='queries')
            write(query, [{'id': 'control', 'query': 'independent control response'}])
            revised = runner.advance(job_id, artifact_kind='queries', artifact_path=str(query))
        self.assertEqual(revised['stage'], 'model_selection')
        log = events_path.read_text(encoding='utf-8')
        self.assertTrue(log.encode().startswith(recovered_bytes))
        for private in ('PRIVATE_PROMPT_BODY', 'PRIVATE_MODEL_REASONING', 'secret-test-api-key'):
            self.assertNotIn(private, log)
        events = [json.loads(line) for line in log.splitlines()]
        allowed = {'schema_version', 'timestamp', 'event', 'job_id', 'stage', 'span_id',
                   'operation', 'status', 'duration_ms', 'code', 'component', 'target_stage', 'wait_type'}
        for event in events:
            self.assertLessEqual(set(event), allowed)
            self.assertEqual(event['schema_version'], 1)
            self.assertEqual(datetime.fromisoformat(event['timestamp']).utcoffset(), timedelta(0))
        self.assertTrue({'success', 'failure', 'waiting'} <= {event['status'] for event in events})
        started = {event['span_id']: event for event in events if event['event'].endswith('_started')}
        finished = {event['span_id']: event for event in events if event['event'].endswith('_finished')}
        self.assertEqual(set(started), set(finished))
        self.assertEqual(len(started), sum(event['event'].endswith('_started') for event in events))
        for span_id, event in finished.items():
            self.assertEqual(event['stage'], started[span_id]['stage'])
            self.assertTrue(math.isfinite(event['duration_ms']))
            self.assertGreaterEqual(event['duration_ms'], 0)
        evidence_runs = [event for event in events if event['event'] == 'stage_finished'
                         and event.get('stage') == 'evidence' and event.get('operation') == 'execute']
        self.assertEqual([event['status'] for event in evidence_runs], ['failure', 'success', 'success'])
        component_log = read(self.out/'logs/local-evidence-probe.json')
        self.assertGreaterEqual(component_log['duration_ms'], 0)
        self.assertLessEqual(datetime.fromisoformat(component_log['started_at']),
                             datetime.fromisoformat(component_log['finished_at']))
