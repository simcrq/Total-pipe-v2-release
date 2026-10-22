"""Generated schematics: a drawn figure is allowed, a fake paper figure is not.

When a page has no usable paper figure the pipeline may draw one (flow, trend or mermaid). The
provenance rules are the interesting part: a generated asset must say who drew it, must not borrow a
paper figure number, and its caption has to admit it is a schematic. Everything else — size, caption
height, collision — is checked exactly like a paper figure.
"""
import json
import tempfile
import unittest
import sys
from pathlib import Path

from PIL import Image

from deck_compiler.ir import validate
from deck_compiler.layout import compile_deck

from test_deck_compiler import ROOT, fixture


def schematic_deck(base, caption="示意图 A. 交接点（自绘）。", asset_extra=None, ref_extra=None):
    Image.new('RGB', (1300, 500), (230, 236, 242)).save(base/'flow.png')
    asset = {'path': 'flow.png', 'origin': 'generated', 'generator': 'tools/make_schematic.py/flow'}
    asset.update(asset_extra or {})
    ref = {'asset_id': 'flow', 'caption': caption, 'panel_count': 1}
    ref.update(ref_extra or {})
    ir = fixture()
    slide = ir['slides'][1]
    slide['composition'] = {'archetype': 'cover-hero',
                            'blocks': [{'id': 'c1', 'component': 'body', 'text': '上下文。'},
                                       {'id': 'c2', 'component': 'source', 'text': '来源。'}],
                            'figure_refs': [ref]}
    return {**ir, 'assets': {'flow': asset}, 'slides': [slide]}


class SchematicProvenanceTests(unittest.TestCase):
    def with_dir(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        return Path(folder.name)

    def rules(self, ir):
        return [issue['rule'] for issue in validate(ir)]

    def test_generated_asset_compiles(self):
        base = self.with_dir()
        layout, issues = compile_deck(schematic_deck(base), base)
        self.assertEqual([i for i in issues if i['severity'] == 'FAIL'], [])
        image = [e for e in layout['slides'][0]['elements'] if e['kind'] == 'image'][0]
        self.assertNotIn('source_figure', image)
        self.assertEqual(image['schematic'], {'generator': 'tools/make_schematic.py/flow'})
        self.assertIn('SCHEMATIC_REVIEW', [i['rule'] for i in issues])
        self.assertNotIn('SCIENTIFIC_PANEL_REVIEW', [i['rule'] for i in issues])

    def test_generated_asset_requires_a_generator(self):
        base = self.with_dir()
        ir = schematic_deck(base, asset_extra={'generator': ''})
        self.assertIn('SCHEMATIC_GENERATOR_REQUIRED', self.rules(ir))

    def test_generated_asset_must_not_claim_a_paper_figure(self):
        base = self.with_dir()
        ir = schematic_deck(base, asset_extra={'source_figure': '3a'},
                            ref_extra={'source_figure': '3a'})
        self.assertIn('FIGURE_PROVENANCE_FORBIDDEN', self.rules(ir))

    def test_caption_must_say_it_is_a_schematic(self):
        base = self.with_dir()
        ir = schematic_deck(base, caption='Fig. 3a. 交接点。')
        self.assertIn('SCHEMATIC_CAPTION_REQUIRED', self.rules(ir))

    def test_english_caption_also_counts(self):
        base = self.with_dir()
        ir = schematic_deck(base, caption='Schematic A. Handoffs in the pipeline.')
        self.assertNotIn('SCHEMATIC_CAPTION_REQUIRED', self.rules(ir))

    def test_paper_figure_still_needs_its_number(self):
        base = self.with_dir()
        ir = schematic_deck(base, caption='示意图 A. 交接点。',
                            asset_extra={'origin': 'paper', 'generator': None})
        ir['assets']['flow'] = {'path': 'flow.png'}          # no source_figure at all
        self.assertIn('FIGURE_PROVENANCE_REQUIRED', self.rules(ir))


class SchematicToolTests(unittest.TestCase):
    def test_flow_and_trend_render_png(self):
        sys.path.insert(0, str(ROOT))
        from tools.make_schematic import render
        base = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: [p.unlink(missing_ok=True) for p in base.glob('*')] or base.rmdir())
        flow = render({'kind': 'flow', 'nodes': ['一', '二', '三', '四']}, base/'flow.png')
        self.assertEqual(flow['backend'], 'native')
        with Image.open(base/'flow.png') as image:
            self.assertGreaterEqual(image.width, 1200)
            self.assertLess(abs(image.width / image.height - 2.6), .15)
        render({'kind': 'trend', 'series': [{'label': 'a', 'points': [[1, 2], [2, 5]]}]},
               base/'trend.png')
        self.assertTrue((base/'trend.png').is_file())

    def test_mermaid_without_cli_fails_loudly(self):
        sys.path.insert(0, str(ROOT))
        from tools.make_schematic import mermaid
        import shutil
        if shutil.which('mmdc'):
            self.skipTest('mermaid-cli is installed on this machine')
        with self.assertRaises(SystemExit):
            mermaid({'source': 'graph LR; A-->B'}, Path(tempfile.mkdtemp())/'x.png', 'auto')


if __name__ == '__main__':
    unittest.main()
