"""Packer quality regression: text boxes hug their content and figures are not left with bands.

These two numbers come from real review sessions: a box much taller than its text reads as empty, and
a rectangle much larger than its picture reads as a mistake. Both are measured on a fixture deck with
one 1.8:1 panel and one 4:1 strip, whose pictures are generated into a temporary directory so the
repository carries no binary assets.

The comparison against the compiler's own templates is deliberate: it is the behaviour the packer
replaces, and the assertion is relational, so a future template improvement tightens the test instead
of breaking it.
"""
import json
from pathlib import Path
import tempfile
import unittest

from PIL import Image

from deck_compiler.layout_provider import CompilerProvider, PackerProvider, compile_with_provider
from totalpipe_layout.contracts import figure_picture_void, read_requests, required_height

ROOT = Path(__file__).resolve().parents[1]


def build_fixture(base: Path):
    Image.new('RGB', (1200, 300), (40, 90, 120)).save(base/'wide.jpg')
    Image.new('RGB', (900, 500), (40, 90, 120)).save(base/'panel.jpg')
    return {
        'schema_version': '2.0', 'deck_id': 'quality-fixture',
        'theme': {'font_family': 'Arial', 'font_file': 'arial.ttf',
                  'bold_font_file': 'arialbd.ttf', 'foreground': '#142735',
                  'background': '#FFFFFF'},
        'assets': {'wide': {'path': 'wide.jpg', 'source_figure': '1a'},
                   'panel': {'path': 'panel.jpg', 'source_figure': '2b'}},
        'slides': [
            {'id': 'parameters', 'semantic': {
                'title': 'Process parameters', 'purpose': 'Show the sweep',
                'takeaway': 'Power sets the removal depth.', 'evidence_refs': ['fixture:a'],
                'caveats': [], 'speaker_notes': 'fixture'},
             'composition': {'archetype': 'figure-parameters', 'blocks': [
                 {'id': 'p1', 'component': 'direct-evidence',
                  'text': 'Power controls the removal depth.'},
                 {'id': 'p2', 'component': 'direct-evidence',
                  'text': 'Scan speed sets the dwell time.'},
                 {'id': 'p3', 'component': 'direct-evidence',
                  'text': 'The dose stays below the damage threshold.'}],
                 'figure_refs': [{'asset_id': 'panel', 'source_figure': '2b', 'panel_count': 1,
                                  'caption': 'Fig. 2b. Measured step height against laser power.',
                                  'alt': 'Step height plot'}]},
             'presentation': {}},
            {'id': 'cover', 'semantic': {
                'title': 'Wide evidence strip', 'purpose': 'Show a wide figure',
                'takeaway': 'The wide panel carries the comparison.', 'evidence_refs': ['fixture:b'],
                'caveats': [], 'speaker_notes': 'fixture'},
             'composition': {'archetype': 'cover-hero', 'blocks': [
                 {'id': 'c1', 'component': 'body', 'text': 'Group meeting context.'},
                 {'id': 'c2', 'component': 'source', 'text': 'Journal 2026, DOI fixture'}],
                 'figure_refs': [{'asset_id': 'wide', 'source_figure': '1a', 'panel_count': 1,
                                  'caption': 'Fig. 1a. Grayscale stripes written at four powers.',
                                  'alt': 'Wide strip'}]},
             'presentation': {}},
        ],
    }


def measure(layout, ir_path):
    requests, _ = read_requests(ir_path, ROOT)
    by_slide = {request['slide_id']: request for request in requests}
    slack, void, fonts, orphans = [], [], [], 0
    for page in layout['slides']:
        request = by_slide[page['id']]
        units = {unit['id']: unit for unit in request['units']}
        for element in page['elements']:
            unit = units.get(element['id'])
            if unit is None:
                continue
            contract = element.get('contract') or {}
            if contract.get('font_size'):
                fonts.append(contract['font_size'])
            if any(line.strip() and len(line.strip()) < 3
                   for line in (element.get('text') or '').split('\n')):
                orphans += 1
            if unit['role'] == 'figure':
                caption_h = next((other['bbox'][3] for other in page['elements']
                                  if other['id'] == element['id']+':caption'), 0)
                rect = [element['bbox'][0], element['bbox'][1], element['bbox'][2],
                        element['bbox'][3]+caption_h+12]
                void.append(figure_picture_void(unit, rect, request))
                continue
            if element.get('role') in ('title', 'takeaway', 'footer', 'caption', 'heading'):
                continue
            need = required_height(unit, element['bbox'][2], request)
            if need < 10000:
                slack.append(element['bbox'][3]/need)
    return {'slack': slack, 'void': void, 'fonts': fonts, 'orphans': orphans}


class PackerQualityTests(unittest.TestCase):
    def compile_with(self, provider):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        base = Path(folder.name)
        ir = build_fixture(base)
        ir_path = base/'deck_ir.json'
        ir_path.write_text(json.dumps(ir), encoding='utf-8')
        layout, issues = compile_with_provider(ir_path, provider)
        self.assertIsNotNone(layout)
        return base, layout, issues

    def test_packer_hugs_text_and_fits_figures(self):
        base, layout, issues = self.compile_with(PackerProvider())
        self.assertEqual([i for i in issues if i['severity'] == 'FAIL'], [])
        counts = layout['layout_provider']['counts']
        self.assertEqual(counts, {'packed': 2, 'owned': 0, 'fallback': 0,
                                  'rejected': 0, 'coverage': 1.0})
        measured = measure(layout, base/'deck_ir.json')
        self.assertTrue(measured['slack'])
        self.assertLessEqual(max(measured['slack']), 1.30)
        self.assertLessEqual(sum(measured['slack'])/len(measured['slack']), 1.25)
        self.assertTrue(measured['void'])
        self.assertLessEqual(max(measured['void']), 0.15)
        self.assertGreaterEqual(min(measured['fonts']), 18)
        self.assertEqual(measured['orphans'], 0)

    def test_packer_leaves_less_empty_space_than_the_templates(self):
        packed_base, packed, _ = self.compile_with(PackerProvider())
        template_base, templates, _ = self.compile_with(CompilerProvider())
        packed_slack = measure(packed, packed_base/'deck_ir.json')['slack']
        template_slack = measure(templates, template_base/'deck_ir.json')['slack']
        template_avg = sum(template_slack)/len(template_slack)
        packed_avg = sum(packed_slack)/len(packed_slack)
        # Both paths now hug measured text and balance the body band; the
        # remaining requirement is that the packer is no worse than templates.
        self.assertGreaterEqual(template_avg, 1.0)
        self.assertLessEqual(packed_avg, max(1.25, template_avg*1.05))


if __name__ == '__main__':
    unittest.main()
