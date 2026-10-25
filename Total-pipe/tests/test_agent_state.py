from pathlib import Path
from unittest.mock import patch

from agent import runner
from agent.state import JobError, locked, read, write, locate, confined, sha, checkpoint
from agent_fixture import AgentCase


class StateTests(AgentCase):
    def start_queries(self):
        return runner.start(str(self.source), str(self.out), 'zh', 'group_meeting')

    def test_missing_modified_and_deleted_artifacts_invalidate_derived_state(self):
        result = self.start_queries()
        self.assertEqual(result['stage'], 'queries')
        write(self.out/'work/queries.json', [{'id': 'q', 'query': 'measured response'}])
        def evidence(stage, job):
            write(self.out/'evidence/workflow.json', {'value': 1})
            return [self.out/'evidence']
        with patch('agent.runner.a.execute', side_effect=evidence):
            result = runner.advance(result['job_id'], artifact_kind='queries', artifact_path=str(self.out/'work/queries.json'))
        self.assertEqual(result['stage'], 'model_selection')
        job_id = result['job_id']
        write(self.out/'evidence/workflow.json', {'value': 2})
        self.assertEqual(runner.status(job_id)['stage'], 'evidence')
        (self.out/'work/queries.json').unlink()
        self.assertEqual(runner.status(job_id)['stage'], 'queries')

    def test_source_change_rewinds_and_status_has_no_component_side_effects(self):
        result = self.start_queries()
        with patch('agent.runner.a.execute') as execute:
            runner.status(result['job_id'])
        execute.assert_not_called()
        self.source.write_text('Changed source')
        self.assertEqual(runner.status(result['job_id'])['stage'], 'queries')

    def test_process_lock_and_unknown_or_corrupt_job_are_business_envelopes(self):
        result = self.start_queries()
        with locked(self.out):
            blocked = runner.advance(result['job_id'])
        self.assertEqual(blocked['next_action']['reason'], 'JOB_BUSY')
        self.assertEqual(runner.status('unknown')['next_action']['reason'], 'JOB_NOT_FOUND')
        (self.out/'.totalpipe/job.json').write_text('{broken')
        self.assertEqual(runner.status(result['job_id'])['next_action']['reason'], 'JOB_STATE_INVALID')

    def test_path_traversal_and_symlink_cannot_submit_an_artifact(self):
        self.start_queries()
        outside = self.root/'outside.json'
        write(outside, [])
        for path in (outside, self.out/'work/../outside.json'):
            with self.assertRaises(JobError):
                confined(path, self.out/'work')
        link = self.out/'work/linked.json'
        link.symlink_to(outside)
        with self.assertRaises(JobError):
            confined(link, self.out/'work')

    def test_repeated_invalid_submission_only_consumes_one_attempt(self):
        result = self.start_queries()
        path = self.out/'work/queries.json'
        path.write_text('{broken', encoding='utf-8')
        for _ in range(2):
            result = runner.advance(result['job_id'], artifact_kind='queries', artifact_path=str(path))
            self.assertEqual(result['next_action']['reason'], 'ARTIFACT_INVALID_JSON')
        job = read(self.out/'.totalpipe/job.json')
        self.assertEqual(sum(value['count'] for value in job['attempts'].values()), 1)

    def test_new_model_does_not_invalidate_evidence(self):
        result = self.start_queries()
        path = self.out/'work/queries.json'
        write(path, [{'id': 'q', 'query': 'response'}])
        def evidence(stage, job):
            write(self.out/'evidence/check.json', {'test': True})
            return [self.out/'evidence/check.json']
        with patch('agent.runner.a.execute', side_effect=evidence):
            result = runner.advance(result['job_id'], artifact_kind='queries', artifact_path=str(path))
        with patch('agent.runner.a.execute', side_effect=lambda stage, job: (_ for _ in ()).throw(AssertionError(stage))):
            _, job = locate(result['job_id'])
            job['inputs'] = {'model': 'chosen', 'reasoning_effort': 'high', 'selected_by_user': True}
            stage, _ = runner.current(job)
        self.assertEqual(stage['id'], 'story_prompt')

    def test_duplicate_query_submission_after_interruption_continues_without_rerunning_evidence(self):
        from agent.adapters import Failure
        calls = []
        def component(stage, job):
            calls.append(stage)
            if stage == 'evidence':
                write(self.out/'evidence/proof.json', {'source': 'fixture'})
                return [self.out/'evidence/proof.json']
            raise Failure('TEMPORARY_DEPENDENCY', 'Restore the missing dependency.')
        result = self.start_queries()
        path = self.out/'work/queries.json'
        write(path, [{'id': 'q', 'query': 'measured response'}])
        with patch('agent.runner.a.execute', side_effect=component):
            result = runner.advance(result['job_id'], artifact_kind='queries', artifact_path=str(path))
            result = runner.advance(result['job_id'], inputs={'model': 'selected', 'reasoning_effort': 'high', 'selected_by_user': True})
            result = runner.advance(result['job_id'], artifact_kind='queries', artifact_path=str(path))
        self.assertEqual(calls.count('evidence'), 1)
        self.assertEqual(calls.count('story_prompt'), 2)

    def test_markdown_image_bytes_are_part_of_upstream_state(self):
        from agent.state import dependency
        image = self.root/'figure.png'
        image.write_bytes(b'old image')
        self.source.write_text('# Paper\n![evidence](figure.png)\n')
        result = self.start_queries()
        _, job = locate(result['job_id'])
        before = dependency(job, [])
        image.write_bytes(b'new evidence image')
        self.assertNotEqual(before, dependency(job, []))

    def test_successful_dependency_retry_clears_persisted_failure(self):
        from agent.adapters import Failure
        result = self.start_queries()
        path = self.out/'work/queries.json'
        write(path, [{'id': 'q', 'query': 'measured response'}])
        with patch('agent.runner.a.execute', side_effect=Failure('TEMPORARY_DEPENDENCY', 'Restore the dependency.')):
            result = runner.advance(result['job_id'], artifact_kind='queries', artifact_path=str(path))
        self.assertTrue(runner.status(result['job_id'])['blocking'])
        with patch('agent.runner.a.execute', side_effect=self.fake_evidence):
            recovered = runner.advance(result['job_id'])
        restarted = runner.status(result['job_id'])
        self.assertEqual(recovered['stage'], 'model_selection')
        self.assertEqual(restarted['status'], recovered['status'])
        self.assertFalse(restarted['blocking'])

    def test_changed_upstream_does_not_report_an_obsolete_failure(self):
        from agent.adapters import Failure
        result = self.start_queries()
        path = self.out/'work/queries.json'
        write(path, [{'id': 'q', 'query': 'measured response'}])
        with patch('agent.runner.a.execute', side_effect=Failure('TEMPORARY_DEPENDENCY', 'Restore the dependency.')):
            result = runner.advance(result['job_id'], artifact_kind='queries', artifact_path=str(path))
        self.source.write_text('# Revised source\nIndependent control measurements.\n')
        restarted = runner.status(result['job_id'])
        self.assertEqual(restarted['stage'], 'queries')
        self.assertEqual(restarted['next_action']['type'], 'author_artifact')
        self.assertFalse(restarted['blocking'])
