import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from subprocess import CompletedProcess

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
                     'vertical_anchor': 'top'}},
                {'id': 'figure-1', 'kind': 'image', 'bbox': [60, 260, 400, 300],
                 'asset_id': 'fig', 'alt': 'Fig.3e'},
            ]}]}

    def test_compiled_layout_maps_to_officecli_batch(self):
        operations = officecli.commands(self.layout)
        self.assertEqual(operations[0]['props'], {'slideWidth': '1280px', 'slideHeight': '720px'})
        self.assertEqual(operations[1]['props']['layout'], 'blank')
        self.assertEqual(operations[2]['props']['x'], '0px')
        self.assertEqual(operations[3]['props']['size'], '33pt')
        self.assertEqual(operations[3]['props']['text'], '第一行\n第二行')
        self.assertEqual(operations[4]['type'], 'picture')
        self.assertEqual(operations[5]['type'], 'notes')

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


if __name__ == '__main__':
    unittest.main()
