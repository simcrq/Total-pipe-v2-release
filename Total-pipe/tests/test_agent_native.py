"""Artifact-bound native acceptance routes; PowerPoint is always mocked here.

The PPTX fixture is produced by the installed OfficeCLI. Exported PDFs and UI-review
records in these tests are synthetic and never represent native verification.
"""
import shutil
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image
from pdfplumber.utils.exceptions import PdfminerException

from agent import COMPONENT
from agent.mcp_server import transport
from agent.native_acceptance import SCHEMA, validate_request
from agent.runner import advance, start, status
from agent.state import checkpoint, read, sha, write
from deck_compiler import native
from deck_compiler.pipeline import POWERPOINT_REVIEW_CHECKS, record_powerpoint_review
from deck_compiler.contracts import issue
from agent_fixture import AgentCase


class _Page:
    width, height = 720, 405

    def to_image(self, resolution):
        return SimpleNamespace(original=Image.new('RGB', (640, 360), '#ffffff'))


class _Document:
    def __init__(self, count):
        self.pages = [_Page() for _ in range(count)]

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class NativeAgentAcceptanceTests(AgentCase):
    def build_candidate(self):
        if not shutil.which('officecli'):
            self.skipTest('OfficeCLI is required to create the real editable candidate fixture.')
        result = start(str(COMPONENT/'examples/native-bullets.deck_ir.json'), str(self.out), 'en', 'group_meeting')
        self.assertEqual(result['status'], 'candidate_ready', result)
        self.assertEqual(result['qa']['counts']['FAIL'], 0, result)
        self.assertEqual(result['native']['status'], 'awaiting_native_render', result)
        self.job_id = result['job_id']
        self.build = self.out/'build'
        self.layout = read(self.build/'layout.json')
        self.slide_ids = [slide['id'] for slide in self.layout['slides']]
        self.request = {'operation': 'render',
            'artifact_sha256': result['native']['artifact_sha256'],
            'layout_sha256': result['native']['layout_sha256']}
        return result

    def mock_export(self, calls=None):
        def export(pptx, pdf):
            if calls is not None:
                calls.append((Path(pptx), Path(pdf)))
            pdf = Path(pdf)
            pdf.write_bytes(b'%PDF-1.7\nsynthetic PowerPoint export fixture\n')
            return {'renderer': 'powerpoint', 'artifact_sha256': sha(pptx),
                    'pdf_sha256': sha(pdf), 'pdf': str(pdf.resolve())}, []
        return export

    def mock_pdf_inspection(self):
        return patch('deck_compiler.native.inspect_pdf', return_value=[])

    def mock_preview_rasterizer(self, page_count):
        import pdfplumber
        return patch.object(pdfplumber, 'open', return_value=_Document(page_count))

    def refresh_build_checkpoint(self):
        job_path = self.out/'.totalpipe/job.json'
        job = read(job_path)
        record = job['checkpoints']['build']
        checkpoint(job, 'build', [Path(path) for path in record['files']], record['upstream'])

    def test_four_tool_route_exposes_native_schema_and_mutations_are_exclusive(self):
        self.build_candidate()
        self.assertEqual(len(transport.TOOLS), 4)
        schema = read(SCHEMA)
        advance_schema = transport.TOOLS['totalpipe_advance']['inputSchema']['properties']['native']
        self.assertEqual(advance_schema, schema)
        self.assertEqual(advance_schema['properties']['operation']['enum'], ['render', 'review', 'ingest'])

        with self.assertRaisesRegex(ValueError, 'separate operation'):
            advance(self.job_id, native=self.request, artifact_kind='deck_ir',
                    artifact_path=str(self.out/'work/deck_ir.json'))

        handler = transport.TOOLS['totalpipe_advance']['handler']
        with patch.object(native, 'render', side_effect=self.mock_export()), \
             self.mock_pdf_inspection(), patch('agent.native_acceptance._previews', return_value=None):
            result = handler({'job_id': self.job_id, 'native': self.request})
        self.assertEqual(result['native_result']['status'], 'awaiting_powerpoint_review')
        self.assertEqual(status(self.job_id)['native']['status'], 'awaiting_powerpoint_review')

    def test_render_is_powerpoint_only_reuses_export_and_rebuilds_every_missing_preview(self):
        self.build_candidate()
        candidate = self.build/'candidate.pptx'
        staging = self.build/'staging.pptx'
        upstream = self.out/'work/deck_ir.json'
        protected = [candidate, staging, self.build/'layout.json', upstream]
        before = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in protected}
        selection = {'model': 'synthetic-user-selected-model', 'reasoning_effort': 'high',
                     'selected_by_user': True}
        job_path = self.out/'.totalpipe/job.json'
        job = read(job_path)
        job['inputs'] = selection
        write(job_path, job)
        prior_checkpoint = read(job_path)['checkpoints']['build']
        calls = []
        with patch.object(native, 'render', side_effect=self.mock_export(calls)), \
             self.mock_pdf_inspection(), self.mock_preview_rasterizer(len(self.slide_ids)):
            result = advance(self.job_id, native=self.request)
            self.assertEqual(result['native_result']['status'], 'awaiting_powerpoint_review', result)
            self.assertFalse(result['native']['powerpoint_ui_reviewed'])
            self.assertTrue(result['native']['rendered'])
            self.assertFalse(result['qa']['counts']['FAIL'])
            self.assertFalse(read(self.build/'qa_report.json')['checks']['visual_review'])
            self.assertTrue(read(self.build/'qa_report.json')['checks']['native'])
            self.assertFalse((self.build/'powerpoint_review.json').exists())
            self.assertFalse((self.build/'final.pptx').exists())
            self.assertFalse((self.build/'qa_acknowledgements.json').exists())
            self.assertEqual(result['native_result']['candidate_unchanged'], True)
            self.assertEqual(len(calls), 1)

            preview = read(result['native']['preview_manifest'])
            self.assertEqual(len(preview['pages']), len(self.slide_ids))
            self.assertEqual([page['slide'] for page in preview['pages']], list(range(1, len(self.slide_ids)+1)))
            self.assertTrue(Path(result['native']['contact_sheet']).is_file())
            self.assertTrue(Path(result['native']['page_previews']).is_file())
            missing = Path(preview['pages'][0]['path'])
            missing.unlink()

            again = advance(self.job_id, native=self.request)
            self.assertTrue(again['native_result']['reused_native_export'])
            self.assertEqual(len(calls), 1)
            rebuilt = read(again['native']['preview_manifest'])
            self.assertEqual(len(rebuilt['pages']), len(self.slide_ids))
            self.assertTrue(all(Path(page['path']).is_file() for page in rebuilt['pages']))

        for path, (contents, mtime) in before.items():
            self.assertEqual(path.read_bytes(), contents, str(path))
            self.assertEqual(path.stat().st_mtime_ns, mtime, str(path))
        current_job = read(job_path)
        self.assertEqual(current_job['inputs'], selection)
        current_checkpoint = current_job['checkpoints']['build']
        self.assertEqual(current_checkpoint['upstream'], prior_checkpoint['upstream'])
        self.assertEqual(set(current_checkpoint['files']), set(prior_checkpoint['files']))
        for path in (candidate, staging, self.build/'layout.json'):
            self.assertEqual(current_checkpoint['files'][str(path.resolve())], sha(path))
        self.assertEqual(current_job['checkpoints']['deck_ir']['files'][str(upstream.resolve())], sha(upstream))
        self.assertEqual(status(self.job_id)['native']['status'], 'awaiting_powerpoint_review')

    def test_missing_or_changed_native_pdf_is_reexported_without_rebuilding(self):
        self.build_candidate()
        calls = []
        with patch.object(native, 'render', side_effect=self.mock_export(calls)), \
             self.mock_pdf_inspection(), patch('agent.native_acceptance._previews', return_value=None):
            first = advance(self.job_id, native=self.request)
            self.assertEqual(first['native_result']['status'], 'awaiting_powerpoint_review')
            original_pdf = (self.build/'native.pdf').read_bytes()
            for mutation in ('delete', 'change'):
                if mutation == 'delete':
                    (self.build/'native.pdf').unlink()
                else:
                    (self.build/'native.pdf').write_bytes(b'%PDF-1.7\nchanged fixture\n')
                stale = status(self.job_id)
                self.assertEqual(stale['next_action']['reason'], 'NATIVE_EVIDENCE_STALE')
                self.assertEqual(stale['native']['status'], 'awaiting_native_render')
                recovered = advance(self.job_id, native=self.request)
                self.assertEqual(recovered['native_result']['status'], 'awaiting_powerpoint_review')
                self.assertEqual((self.build/'native.pdf').read_bytes(), original_pdf)
                self.assertEqual(sha(self.build/'candidate.pptx'), self.request['artifact_sha256'])
            self.assertEqual(len(calls), 3)

    def test_export_dependency_failure_retains_candidate_and_retry_recovers(self):
        self.build_candidate()
        original = (self.build/'candidate.pptx').read_bytes()
        with patch.object(native, 'render', side_effect=OSError('synthetic PowerPoint process failure')) as render:
            failed = advance(self.job_id, native=self.request)
        render.assert_called_once()
        self.assertEqual(failed['native_result']['status'], 'failed')
        self.assertIn('synthetic PowerPoint process failure', failed['native_result']['message'])
        self.assertFalse((self.build/'native.pdf').exists())
        self.assertFalse((self.build/'native.json').exists())
        self.assertEqual((self.build/'candidate.pptx').read_bytes(), original)
        self.assertEqual(status(self.job_id)['last_native']['status'], 'failed')

        with patch.object(native, 'render', side_effect=self.mock_export()), \
             self.mock_pdf_inspection(), patch('agent.native_acceptance._previews', return_value=None):
            recovered = advance(self.job_id, native=self.request)
        self.assertEqual(recovered['native_result']['status'], 'awaiting_powerpoint_review')
        self.assertEqual((self.build/'candidate.pptx').read_bytes(), original)

    def test_unparseable_pdf_is_a_recoverable_failure_without_attached_proof(self):
        self.build_candidate()
        candidate_bytes = (self.build/'candidate.pptx').read_bytes()

        def invalid_pdf(pptx, pdf):
            Path(pdf).write_bytes(b'%PDF-1.7\ntruncated synthetic PDF')
            return {'renderer': 'powerpoint', 'artifact_sha256': sha(pptx),
                    'pdf_sha256': sha(pdf), 'pdf': str(Path(pdf).resolve())}, []

        with patch.object(native, 'render', side_effect=invalid_pdf):
            failed = advance(self.job_id, native=self.request)
        self.assertEqual(failed['native_result']['status'], 'failed')
        self.assertTrue(failed['last_native'])
        self.assertFalse((self.build/'native.pdf').exists())
        self.assertFalse((self.build/'native.json').exists())
        self.assertEqual((self.build/'candidate.pptx').read_bytes(), candidate_bytes)

        with patch.object(native, 'render', side_effect=self.mock_export()), \
             self.mock_pdf_inspection(), patch('agent.native_acceptance._previews', return_value=None):
            recovered = advance(self.job_id, native={**self.request, 'force': True})
        self.assertEqual(recovered['native_result']['status'], 'awaiting_powerpoint_review')
        self.assertEqual((self.build/'candidate.pptx').read_bytes(), candidate_bytes)

    def test_preview_parser_failure_keeps_pdf_evidence_and_can_retry_preview(self):
        self.build_candidate()
        calls = []
        with patch.object(native, 'render', side_effect=self.mock_export(calls)), \
             self.mock_pdf_inspection(), \
             patch('pdfplumber.open', side_effect=PdfminerException('synthetic preview parser failure')):
            failed_preview = advance(self.job_id, native=self.request)
        self.assertEqual(failed_preview['native_result']['status'], 'awaiting_powerpoint_review')
        self.assertIn('synthetic preview parser failure', failed_preview['native_result']['preview_error'])
        self.assertTrue((self.build/'native.pdf').is_file())
        self.assertTrue((self.build/'native.json').is_file())
        self.assertFalse(failed_preview['native']['preview_manifest'])
        self.assertEqual(len(calls), 1)

        with patch.object(native, 'render', side_effect=self.mock_export(calls)), \
             self.mock_preview_rasterizer(len(self.slide_ids)):
            retry = advance(self.job_id, native=self.request)
        self.assertTrue(retry['native_result']['reused_native_export'])
        self.assertEqual(len(calls), 1)
        self.assertTrue(Path(retry['native']['preview_manifest']).is_file())

    def test_review_requires_every_explicit_slide_id_and_all_four_checks(self):
        self.build_candidate()
        review = {'operation': 'review', **{k: self.request[k] for k in ('artifact_sha256', 'layout_sha256')},
                  'reviewer': 'synthetic-reviewer',
                  'note': 'Synthetic route fixture only; no UI inspection occurred.',
                  'method': 'powerpoint-ui', 'reviewed_slide_ids': list(self.slide_ids),
                  'checks': list(POWERPOINT_REVIEW_CHECKS)}
        validate_request(review)
        with patch('deck_compiler.pipeline.record_powerpoint_review') as record:
            for ids in (['all'], self.slide_ids[:-1]):
                invalid = {**review, 'reviewed_slide_ids': ids}
                result = advance(self.job_id, native=invalid)
                self.assertEqual(result['native_result']['status'], 'failed')
                record.assert_not_called()
            invalid = {**review, 'checks': list(POWERPOINT_REVIEW_CHECKS[:-1])}
            result = advance(self.job_id, native=invalid)
            self.assertEqual(result['native_result']['status'], 'failed')
            record.assert_not_called()

            accepted = advance(self.job_id, native=review)
            record.assert_called_once_with(self.build, 'synthetic-reviewer', self.slide_ids,
                review['note'], expected_hashes=review)
        self.assertEqual(accepted['native_result']['status'], 'awaiting_native_render')
        self.assertFalse((self.build/'powerpoint_review.json').exists())
        self.assertFalse(read(self.build/'qa_report.json')['checks'].get('visual_review', False))

    def test_manual_ingest_requires_powerpoint_source_pdf_hash_and_matching_review(self):
        self.build_candidate()
        pdf = self.out/'synthetic-manual-export.pdf'
        pdf.write_bytes(b'%PDF-1.7\nsynthetic manual export fixture\n')
        request = {'operation': 'ingest', 'artifact_sha256': self.request['artifact_sha256'],
                   'layout_sha256': self.request['layout_sha256'], 'reviewer': 'synthetic-reviewer',
                   'pdf_path': str(pdf), 'pdf_sha256': sha(pdf), 'source': 'powerpoint-export'}
        validate_request(request)
        with self.mock_pdf_inspection(), patch('agent.native_acceptance._previews', return_value=None):
            no_review = advance(self.job_id, native=request)
            self.assertEqual(no_review['native_result']['status'], 'failed')
            self.assertFalse((self.build/'native.json').exists())

            note = 'Synthetic test record only; no PowerPoint UI inspection was performed.'
            record_powerpoint_review(self.build, 'synthetic-reviewer', self.slide_ids,
                                    note, expected_hashes=request)
            mismatched = {**request, 'reviewer': 'different-synthetic-reviewer'}
            mismatch_result = advance(self.job_id, native=mismatched)
            self.assertEqual(mismatch_result['native_result']['status'], 'failed')
            self.assertFalse((self.build/'native.json').exists())

            bad_hash = {**request, 'pdf_sha256': '0'*64}
            wrong_pdf = advance(self.job_id, native=bad_hash)
            self.assertEqual(wrong_pdf['native_result']['status'], 'failed')
            self.assertIn('PDF bytes differ', wrong_pdf['native_result']['message'])
            self.assertFalse((self.build/'native.json').exists())

            accepted = advance(self.job_id, native=request)
        self.assertEqual(accepted['native_result']['status'], 'awaiting_review_acknowledgements')
        evidence = read(self.build/'native.json')
        self.assertEqual(evidence['export_method'], 'powerpoint-manual')
        self.assertEqual(evidence['visual_review']['reviewer'], 'synthetic-reviewer')
        self.assertEqual(evidence['pdf_sha256'], sha(self.build/'native.pdf'))
        self.assertEqual(sha(self.build/'candidate.pptx'), self.request['artifact_sha256'])

        bad_source = {**request, 'source': 'unknown'}
        with self.assertRaisesRegex(ValueError, 'powerpoint-export'):
            validate_request(bad_source)

    def test_native_qa_fail_blocks_render_and_fail_id_cannot_be_acknowledged(self):
        self.build_candidate()
        qa_path = self.build/'qa_report.json'
        qa = read(qa_path)
        fail_id = 'synthetic-native-fail'
        qa['items'].append({'id': fail_id, 'rule': 'SYNTHETIC_NATIVE_FAIL', 'severity': 'FAIL',
                            'message': 'Test fixture only.',
                            'source': {'detector': 'native-visual', 'renderer': 'powerpoint'}})
        qa['counts']['FAIL'] += 1
        write(qa_path, qa)
        self.refresh_build_checkpoint()

        with patch.object(native, 'render') as render:
            response = advance(self.job_id, native=self.request)
        render.assert_not_called()
        self.assertEqual(response['status'], 'blocked')
        self.assertEqual(status(self.job_id)['next_action']['reason'], 'NATIVE_QA_FAILED')
        self.assertEqual(response['native_result']['status'], 'failed')
        self.assertFalse((self.build/'native.pdf').exists())
        with self.assertRaisesRegex(ValueError, 'current REVIEW finding'):
            advance(self.job_id, acknowledge={'reviewer': 'synthetic', 'note': 'Cannot sign a FAIL.',
                                               'review_ids': [fail_id]})

    def test_native_only_qa_fail_can_be_rechecked_but_non_native_fail_still_blocks(self):
        self.build_candidate()
        calls = []
        native_fail = issue('NATIVE_PAGE_COUNT', 'FAIL', 'Synthetic wrong page-count fixture.',
                            detector='native-visual', renderer='powerpoint')

        def export_distinct_pdf(pptx, pdf):
            calls.append(Path(pdf))
            Path(pdf).write_bytes(b'%PDF-1.7\nsynthetic export '+str(len(calls)).encode()+b'\n')
            return {'renderer': 'powerpoint', 'artifact_sha256': sha(pptx),
                    'pdf_sha256': sha(pdf), 'pdf': str(Path(pdf).resolve())}, []

        with patch.object(native, 'render', side_effect=export_distinct_pdf), \
             patch('deck_compiler.native.inspect_pdf', side_effect=[[native_fail], []]), \
             patch('agent.native_acceptance._previews', return_value=None):
            first = advance(self.job_id, native=self.request)
            self.assertEqual(first['status'], 'blocked')
            self.assertEqual(first['native_result']['counts']['FAIL'], 1)

            forced = {**self.request, 'force': True}
            recovered = advance(self.job_id, native=forced)
            self.assertEqual(recovered['native_result']['status'], 'awaiting_powerpoint_review')
            self.assertEqual(recovered['qa']['counts']['FAIL'], 0)
            self.assertEqual(len(calls), 2)

            qa_path = self.build/'qa_report.json'
            qa = read(qa_path)
            qa['items'].append(issue('SYNTHETIC_STRUCTURAL_FAIL', 'FAIL',
                'Unrelated structural failure must survive native retry.', detector='structural-ooxml'))
            qa['counts']['FAIL'] += 1
            write(qa_path, qa)
            self.refresh_build_checkpoint()
            rejected = advance(self.job_id, native=forced)
        self.assertEqual(rejected['native_result']['status'], 'failed')
        self.assertEqual(len(calls), 2)
        self.assertEqual(read(self.build/'qa_report.json')['counts']['FAIL'], 1)

    def test_candidate_mutation_during_export_cannot_create_native_proof(self):
        self.build_candidate()
        original = (self.build/'layout.json').read_bytes()

        def mutate_layout(pptx, pdf):
            result = self.mock_export()(pptx, pdf)
            (self.build/'layout.json').write_bytes(original+b'\n')
            return result

        with patch.object(native, 'render', side_effect=mutate_layout), self.mock_pdf_inspection():
            response = advance(self.job_id, native=self.request)
        self.assertEqual(response['native_result']['status'], 'failed')
        self.assertIn('Candidate, staging, IR, layout or QA differ', response['native_result']['message'])
        self.assertFalse((self.build/'native.pdf').exists())
        self.assertFalse((self.build/'native.json').exists())
        self.assertFalse(read(self.build/'qa_report.json')['checks']['native'])

    def test_native_inspection_toctou_cannot_commit_pdf_or_qa(self):
        self.build_candidate()
        staged = self.build/'staging.pptx'
        original = staged.read_bytes()
        export_calls = []

        def tamper_after_inspection(pdf, layout):
            staged.write_bytes(original+b'\nchanged during QA inspection')
            return []

        with patch.object(native, 'render', side_effect=self.mock_export(export_calls)), \
             patch('deck_compiler.native.inspect_pdf', side_effect=tamper_after_inspection):
            response = advance(self.job_id, native=self.request)
        self.assertEqual(len(export_calls), 1)
        self.assertEqual(response['native_result']['status'], 'failed')
        self.assertIn('Native validation input changed during inspection', response['native_result']['message'])
        self.assertFalse((self.build/'native.pdf').exists())
        self.assertFalse((self.build/'native.json').exists())

    def test_request_hash_and_upstream_snapshot_changes_do_not_run_export(self):
        self.build_candidate()
        calls = []
        wrong_hash = {**self.request, 'artifact_sha256': '0'*64}
        with patch.object(native, 'render', side_effect=self.mock_export(calls)):
            stale = advance(self.job_id, native=wrong_hash)
        self.assertEqual(stale['native_result']['status'], 'failed')
        self.assertIn('stale', stale['native_result']['message'].lower())
        self.assertFalse(calls)

        (self.build/'layout.json').write_bytes((self.build/'layout.json').read_bytes()+b' ')
        with patch.object(native, 'render', side_effect=self.mock_export(calls)):
            changed = advance(self.job_id, native=self.request)
        self.assertEqual(changed['native_result']['status'], 'failed')
        self.assertFalse(calls)
        self.assertFalse((self.build/'native.pdf').exists())


if __name__ == '__main__':
    import unittest
    unittest.main()
