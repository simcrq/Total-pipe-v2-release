import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
from subprocess import CompletedProcess
import xml.etree.ElementTree as ET
import zipfile

from deck_compiler import officecli


class OfficeCliProtocolTests(unittest.TestCase):
    def setUp(self):
        self.layout = {
            'slide_size': [1280, 720], 'assets': {
                'fig': {'path': 'C:/figures/panel.png'}},
            'slides': [{'background': '#FFFFFF', 'notes': '讲解要点', 'elements': [
                {'id': 'panel', 'kind': 'shape', 'bbox': [0, 12, 300, 200],
                 'geometry': 'rect', 'fill': '#F4F8FA', 'line': '#D6E4EA'},
                {'id': 'title', 'kind': 'text', 'bbox': [56, 34, 1168, 120],
                 'text': '第一行\n第二行', 'color': '#142735', 'contract': {
                     'font_family': 'Arial', 'font_size': 44, 'font_weight': 700,
                     'line_height': 1.25, 'vertical_anchor': 'top',
                     'inset': {'left': 0, 'right': 0, 'top': 0, 'bottom': 0}}},
                {'id': 'figure-1', 'kind': 'image', 'bbox': [60, 260, 400, 300],
                 'asset_id': 'fig', 'alt': 'Fig.3e'},
            ]}]}

    def test_compiled_layout_maps_to_officecli_batch(self):
        operations = officecli.commands(self.layout)
        self.assertEqual(operations[0]['props'], {'slideWidth': '1280px', 'slideHeight': '720px'})
        self.assertEqual(operations[1]['props']['layout'], 'blank')
        self.assertEqual(operations[2]['props']['x'], '0px')
        self.assertEqual(operations[3]['props']['size'], '33pt')
        self.assertEqual(operations[3]['props']['lineSpacing'], '41.25pt')
        self.assertEqual(operations[3]['props']['font.ea'], 'Arial')
        self.assertEqual(operations[3]['props']['text'], '第一行\n第二行')
        self.assertEqual(operations[4]['type'], 'picture')
        self.assertEqual(operations[5]['command'], 'raw-set')
        self.assertEqual(operations[5]['xml'], 'wrap=none')
        self.assertEqual(operations[6]['type'], 'notes')

    @unittest.skipUnless(shutil.which('officecli'), 'OfficeCLI executable required')
    def test_officecli_writes_text_contract_without_package_finalizer(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            layout = {'slide_size': [1280, 720], 'assets': {}, 'slides': [{
                'background': '#FFFFFF', 'notes': '说明', 'elements': [{
                    'id': 'text:1', 'kind': 'text', 'bbox': [10, 20, 300, 120],
                    'text': '第一行\n第二行', 'color': '#142735', 'contract': {
                        'font_family': 'Arial', 'font_size': 32, 'font_weight': 400,
                        'line_height': 1.2, 'vertical_anchor': 'top',
                        'inset': {'left': 1, 'right': 3, 'top': 2, 'bottom': 4}}}]}]}
            layout_path = root/'layout.json'
            layout_path.write_text(json.dumps(layout, ensure_ascii=False), encoding='utf-8')
            output = root/'candidate.pptx'
            officecli.render(layout_path, output)
            with zipfile.ZipFile(output) as deck:
                slide = ET.fromstring(deck.read('ppt/slides/slide1.xml'))
            ns = {'p': 'http://schemas.openxmlformats.org/presentationml/2006/main',
                  'a': 'http://schemas.openxmlformats.org/drawingml/2006/main'}
            body = slide.find('.//p:sp/p:txBody/a:bodyPr', ns)
            self.assertEqual(body.get('wrap'), 'none')
            self.assertEqual([body.get(name) for name in ('lIns', 'tIns', 'rIns', 'bIns')],
                             ['9525', '19050', '28575', '38100'])
            spacing = slide.find('.//p:sp/p:txBody/a:p/a:pPr/a:lnSpc/a:spcPts', ns)
            self.assertEqual(spacing.get('val'), '2880')

    def test_batch_rejects_partial_success_or_warnings(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            layout_path = root/'layout.json'
            layout_path.write_text(json.dumps(self.layout), encoding='utf-8')
            output = root/'candidate.pptx'

            def fake_run(executable, *args, **kwargs):
                if args[0] == 'create':
                    output.write_bytes(b'fake')
                    return {'success': True}
                if args[0] == 'batch':
                    count = len(officecli.commands(self.layout))
                    return {'success': True, 'data': {'summary': {'total': count, 'succeeded': count},
                            'results': [{'success': True, 'warnings': [{'message': 'dropped prop'}]}]
                                       + [{'success': True}] * (count - 1)}}
                return {'success': True}

            with patch.object(officecli, '_run', side_effect=fake_run):
                with self.assertRaisesRegex(ValueError, 'every property'):
                    officecli.render(layout_path, output)

    def test_json_envelope_and_warning_exit_are_strict(self):
        clean = CompletedProcess([], 0, '{"success":true,"data":{"count":0}}', '')
        warned = CompletedProcess([], 2, '{"success":true,"warnings":[{"message":"bad prop"}]}', '')
        with patch.object(officecli.subprocess, 'run', return_value=clean) as run:
            self.assertEqual(officecli._run('officecli', 'validate', 'deck.pptx')['data']['count'], 0)
            self.assertEqual(run.call_args.args[0][-1], '--json')
        with patch.object(officecli.subprocess, 'run', return_value=warned):
            with self.assertRaisesRegex(ValueError, 'failed'):
                officecli._run('officecli', 'batch', 'deck.pptx')

    def test_spilled_batch_result_is_read_for_per_item_warnings(self):
        with tempfile.TemporaryDirectory() as directory:
            spill = Path(directory)/'full.json'
            full = {'results': [{'success': True, 'output': 'WARNING: UNSUPPORTED props: typo'}],
                    'summary': {'total': 1, 'succeeded': 1}}
            spill.write_text(json.dumps(full), encoding='utf-8')
            slim = {'success': True, 'data': {'outputFile': str(spill),
                    'outputSize': spill.stat().st_size, 'results': [{'success': True}]}}
            response = CompletedProcess([], 0, json.dumps(slim), '')
            with patch.object(officecli.subprocess, 'run', return_value=response):
                self.assertIn('WARNING:', officecli._run('officecli', 'batch', 'deck.pptx')
                              ['data']['results'][0]['output'])

    def test_issue_report_count_is_checked(self):
        with patch.object(officecli, '_run', side_effect=[{'data': {'count': 0}},
                                                       {'data': {'count': 1, 'issues': []}}]):
            with self.assertRaisesRegex(ValueError, 'count'):
                officecli.inspect('staging.pptx')

    def test_only_heuristic_text_warnings_become_info(self):
        findings = [{'severity': severity, 'type': 0, 'path': '/slide[2]/shape[@id=7]',
                     'message': message, 'id': index}
                    for index, (severity, message) in enumerate([
                        ('warning', 'Text overflow: 3 lines need 79pt, usable 52pt.'),
                        ('error', 'text overflow: corrupt text contract'),
                        (1, 'Objects overlap'), (2, 'Unused style')])]
        before = json.dumps(findings)
        items = officecli.qa_findings(findings)
        self.assertEqual([i['severity'] for i in items], ['INFO', 'FAIL', 'WARNING', 'INFO'])
        self.assertEqual(items[0]['source']['original_severity'], 'warning')
        self.assertTrue(items[0]['source']['native_verification_required'])
        self.assertIn('verify in PowerPoint', items[0]['message'])
        self.assertEqual(items[0]['slide'], 2)
        self.assertEqual(json.dumps(findings), before)

    def test_review_export_does_not_reject_advisory_estimates(self):
        from deck_compiler.officecli_review import review
        from deck_compiler.contracts import digest, file_hash
        from deck_compiler.pipeline import write_json
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            (out/'staging.pptx').write_bytes(b'candidate')
            ir = {'slides': [{'id': 'one'}]}
            layout = {'ir_sha256': digest(ir), 'slides': [{'id': 'one'}]}
            write_json(out/'deck_ir.json', ir)
            write_json(out/'layout.json', layout)
            write_json(out/'qa_report.json', {'artifact_sha256': file_hash(out/'staging.pptx'),
                'layout_sha256': file_hash(out/'layout.json'), 'ir_sha256': digest(ir), 'checks': {}})
            for message, expected in [('text overflow: need 79pt, usable 52pt', 'AWAITING_VISUAL_REVIEW'),
                                      ('Objects overlap', 'REJECT')]:
                def run(argv, **kwargs):
                    data = {}
                    if argv[1] == 'validate': data = {'count': 0}
                    if argv[1] == 'view' and argv[3] == 'issues':
                        data = {'count': 1, 'issues': [{'severity': 1, 'type': 0, 'message': message}]}
                    if '-o' in argv: Path(argv[argv.index('-o')+1]).write_bytes(b'\x89PNG\r\n\x1a\n')
                    return CompletedProcess(argv, 0, json.dumps({'success': True, 'data': data}), '')
                with patch('deck_compiler.officecli_review.subprocess.run', side_effect=run), \
                     patch('deck_compiler.officecli_review.verify', return_value=[]):
                    result = review(out)
                self.assertEqual(result['status'], expected)
                self.assertEqual(result['issue_count'], 1)
                self.assertEqual(result['issue_counts']['INFO' if expected == 'AWAITING_VISUAL_REVIEW' else 'WARNING'], 1)


if __name__ == '__main__':
    unittest.main()
