import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import subprocess
import sys
import zipfile

from deck_compiler.contracts import digest, file_hash, issue, report
from deck_compiler.pipeline import write_json, write_qa, promote, record_powerpoint_review
from deck_compiler.qa_review import acknowledge_reviews, show_qa


class CandidateReviewTests(unittest.TestCase):
    def prepare(self, out):
        ir = {'theme': {'foreground': '#000000'}, 'slides': [
            {'id': 'first', 'semantic': {'title': 'First'}},
            {'id': 'second', 'semantic': {'title': 'Second'}}]}
        layout = {'assets': {}, 'slides': [
            {'id': page['id'], 'elements': [{'id': 'body', 'kind': 'text', 'text': page['semantic']['title'],
                                           'bbox': [0, 0, 100, 30]}]}
            for page in ir['slides']]}
        return ir, layout

    def save(self, out, ir, layout, artifact=False, message='Inspect the baseline'):
        write_json(out/'deck_ir.json', ir)
        write_json(out/'layout.json', layout)
        qa = report([issue('MEASURE', 'REVIEW', message, n, 'body', detector='geometric-preflight')
                     for n in (1, 2)], file_hash(out/'staging.pptx') if artifact else None, digest(ir))
        write_qa(out, qa, ir, layout)
        return qa

    def test_notes_survive_recompile_and_pending_view_hides_only_acknowledged_items(self):
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder)
            ir, layout = self.prepare(out)
            qa = self.save(out, ir, layout)
            noted = acknowledge_reviews(out, 'Reviewer', 'Checked the actual page.', [qa['items'][0]['id']])
            self.assertEqual(noted['counts']['REVIEW'], 2)
            self.assertEqual(noted['unacked_count'], 1)
            self.assertEqual(noted['acked_count'], 1)
            self.assertTrue(noted['items'][0]['ack']['at'])
            self.assertEqual(len(show_qa(out)['items']), 1)
            self.assertEqual(len(show_qa(out, include_acked=True)['items']), 2)
            repeated = self.save(out, ir, layout)
            self.assertEqual(repeated['items'][0]['ack'], noted['items'][0]['ack'])
            self.assertEqual(repeated['unacked_count'], 1)
            ir['slides'][1]['semantic']['title'] = 'Changed other page'
            layout['slides'][1]['elements'][0]['bbox'][3] += 10
            self.assertEqual(self.save(out, ir, layout)['acked_count'], 1)

    def test_changed_content_geometry_or_finding_invalidates_note(self):
        for change in ('content', 'geometry', 'theme', 'finding', 'asset'):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as folder:
                out = Path(folder)
                ir, layout = self.prepare(out)
                layout['assets']['image'] = {'sha256': 'old'}
                layout['slides'][0]['elements'].append({'id': 'image', 'asset_id': 'image', 'kind': 'image'})
                qa = self.save(out, ir, layout)
                acknowledge_reviews(out, 'Reviewer', 'Checked.', [qa['items'][0]['id']])
                if change == 'content': ir['slides'][0]['semantic']['title'] = 'Changed'
                if change == 'geometry': layout['slides'][0]['elements'][0]['bbox'][3] += 1
                if change == 'theme': ir['theme']['foreground'] = '#112233'
                if change == 'asset': layout['assets']['image']['sha256'] = 'new'
                qa = self.save(out, ir, layout, message='Changed finding' if change == 'finding' else 'Inspect the baseline')
                self.assertEqual(qa['acked_count'], 0)
                self.assertEqual(qa['unacked_count'], 2)

    def test_stale_unknown_non_review_and_empty_notes_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder)
            ir, layout = self.prepare(out)
            qa = self.save(out, ir, layout)
            for by, note, ids in [(' ', 'Checked', [qa['items'][0]['id']]),
                                   ('Reviewer', ' ', [qa['items'][0]['id']]),
                                   ('Reviewer', 'Checked', ['unknown'])]:
                with self.assertRaises(ValueError):
                    acknowledge_reviews(out, by, note, ids)
            ir['slides'][0]['semantic']['title'] = 'Uncompiled edit'
            write_json(out/'deck_ir.json', ir)
            with self.assertRaisesRegex(ValueError, 'stale'):
                acknowledge_reviews(out, 'Reviewer', 'Checked', [qa['items'][0]['id']])

    def test_raw_qa_ack_is_not_trusted_without_matching_sidecar(self):
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder)
            ir, layout = self.prepare(out)
            qa = self.save(out, ir, layout)
            qa['items'][0]['ack'] = {'by': 'Someone', 'at': 'now', 'note': 'Unchecked stale record'}
            write_json(out/'qa_report.json', qa)
            self.assertEqual(show_qa(out)['unacked_count'], 2)

    def test_failed_invalid_input_still_writes_qa_without_review_context(self):
        from deck_compiler.pipeline import compile_input
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder)
            source = out/'invalid.json'
            source.write_text('[]')
            _, layout, qa = compile_input(source, out)
            self.assertIsNone(layout)
            self.assertGreater(qa['counts']['FAIL'], 0)
            self.assertEqual(qa['unacked_count'], 0)
            self.assertTrue((out/'qa_report.json').is_file())

    def test_mcp_and_cli_support_pending_and_explicit_review_ids(self):
        from deck_compiler.mcp_server import transport
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder)
            ir, layout = self.prepare(out)
            qa = self.save(out, ir, layout)
            args = {'out': str(out), 'reviewer': 'Reviewer', 'note': '核对了页面。',
                    'review_ids': [qa['items'][0]['id']]}
            noted = transport.TOOLS['totalpipe_ack_review']['handler'](args)
            self.assertEqual(noted['unacked_count'], 1)
            pending = transport.TOOLS['totalpipe_qa']['handler']({'out': str(out)})
            self.assertEqual(len(pending['items']), 1)
            full = subprocess.run([sys.executable, '-m', 'deck_compiler', 'qa', '--out', str(out),
                                   '--include-acked'], check=True, capture_output=True, text=True)
            self.assertEqual(len(json.loads(full.stdout)['items']), 2)
            with self.assertRaisesRegex(ValueError, 'boolean'):
                transport.TOOLS['totalpipe_qa']['handler']({'out': str(out), 'include_acked': 'true'})
            with self.assertRaisesRegex(ValueError, 'nonempty list'):
                transport.TOOLS['totalpipe_ack_review']['handler']({**args, 'review_ids': []})

    def test_backend_notes_follow_slide_dependencies_across_zip_rebuilds(self):
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder)
            ir, layout = self.prepare(out)
            parts = {'ppt/slides/slide1.xml': '<slide>First</slide>',
                'ppt/slides/slide2.xml': '<slide>Second</slide>',
                'ppt/slides/_rels/slide1.xml.rels':
                    '<Relationships><Relationship Target="../media/image.png"/></Relationships>',
                'ppt/media/image.png': 'old image'}
            def save_artifact():
                with zipfile.ZipFile(out/'staging.pptx', 'w') as package:
                    for name, content in parts.items():
                        package.writestr(name, content)
                write_json(out/'deck_ir.json', ir)
                write_json(out/'layout.json', layout)
                qa = report([issue('STRUCTURE_REVIEW', 'REVIEW', 'Inspect', 1, 'body',
                                   detector='structural-ooxml')], file_hash(out/'staging.pptx'), digest(ir))
                write_qa(out, qa, ir, layout)
                return qa
            qa = save_artifact()
            acknowledge_reviews(out, 'Reviewer', 'Checked native objects.', [qa['items'][0]['id']])
            parts['ppt/slides/slide2.xml'] = '<slide>Unrelated page changed</slide>'
            self.assertEqual(save_artifact()['acked_count'], 1)
            parts['ppt/media/image.png'] = 'changed referenced image'
            self.assertEqual(save_artifact()['acked_count'], 0)

    def test_font_bytes_and_invalid_sidecar_do_not_reuse_notes(self):
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder)
            ir, layout = self.prepare(out)
            font = out/'font.ttf'
            font.write_bytes(b'first font version')
            layout['slides'][0]['elements'][0]['contract'] = {'font_file': str(font)}
            qa = self.save(out, ir, layout)
            acknowledge_reviews(out, 'Reviewer', 'Checked font.', [qa['items'][0]['id']])
            font.write_bytes(b'changed font version')
            self.assertEqual(self.save(out, ir, layout)['acked_count'], 0)
            write_json(out/'qa_acknowledgements.json', {'version': '1.0', 'records': {'key': []}})
            with self.assertRaisesRegex(ValueError, 'Invalid candidate QA'):
                show_qa(out)

    def test_native_notes_follow_page_glyph_evidence_and_reject_stale_pdf(self):
        with tempfile.TemporaryDirectory() as folder, patch('deck_compiler.qa_review._native_pages') as pages:
            out = Path(folder)
            ir, layout = self.prepare(out)
            (out/'staging.pptx').write_bytes(b'candidate')
            pdf = out/'native.pdf'
            pdf.write_bytes(b'%PDF test page evidence')
            pages.return_value = {1: 'first glyph evidence', 2: 'second glyph evidence'}
            write_json(out/'deck_ir.json', ir)
            write_json(out/'layout.json', layout)
            def save_native():
                qa = report([issue('NATIVE_TEXT_REVIEW', 'REVIEW', 'Inspect text', 1, 'body',
                                   detector='native-visual')], file_hash(out/'staging.pptx'), digest(ir), {'native': True})
                write_json(out/'native.json', {'artifact_sha256': qa['artifact_sha256'], 'pdf_sha256': file_hash(pdf)})
                write_qa(out, qa, ir, layout)
                return qa
            qa = save_native()
            acknowledge_reviews(out, 'Reviewer', 'Checked native text.', [qa['items'][0]['id']])
            pages.return_value[2] = 'changed unrelated page'
            self.assertEqual(save_native()['acked_count'], 1)
            pages.return_value[1] = 'changed reviewed glyph evidence'
            self.assertEqual(save_native()['acked_count'], 0)
            pdf.write_bytes(b'%PDF changed outside validation')
            with self.assertRaisesRegex(ValueError, 'Native QA evidence is stale'):
                show_qa(out)

    def test_candidate_notes_never_replace_formal_final_acknowledgement(self):
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder)
            ir, layout = self.prepare(out)
            (out/'staging.pptx').write_bytes(b'candidate')
            (out/'candidate.pptx').write_bytes(b'candidate')
            (out/'candidate.officecli.batch.json').write_text('[]')
            (out/'native.pdf').write_bytes(b'%PDF placeholder')
            qa = self.save(out, ir, layout, artifact=True)
            review_path = record_powerpoint_review(out, 'Reviewer')
            visual_review = json.loads(review_path.read_text())
            qa['checks'] = {'structural': True, 'native': True, 'visual_review': True,
                'visual_review_method': 'powerpoint-ui', 'backend': 'officecli',
                'officecli_runtime': {'version': '1.0.158', 'schema_sha256': 'schema'},
                'officecli_commands_sha256': file_hash(out/'candidate.officecli.batch.json')}
            write_json(out/'native.json', {'renderer': 'powerpoint', 'artifact_sha256': qa['artifact_sha256'],
                'pdf_sha256': file_hash(out/'native.pdf'), 'visual_review': visual_review})
            write_qa(out, qa, ir, layout)
            acknowledge_reviews(out, 'Reviewer', 'Candidate checked.', [i['id'] for i in qa['items']])
            self.assertEqual(show_qa(out)['unacked_count'], 0)
            with self.assertRaisesRegex(ValueError, 'artifact-bound reviewer acknowledgement'):
                promote(out)
            self.assertFalse((out/'final.pptx').exists())
