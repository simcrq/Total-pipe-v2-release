"""A versioned PPTX and its portable IR exercise the mixed-content contract together."""
import copy
import hashlib
import json
from pathlib import Path
import unittest
import zipfile
from xml.etree import ElementTree as ET

import jsonschema

from deck_compiler.layout import compile_deck

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT/'examples/complex-mixed'


class ComplexMixedExampleTests(unittest.TestCase):
    def test_ir_compiles_one_page_with_all_native_content_and_measured_list(self):
        ir = json.loads((EXAMPLE/'complex-mixed.deck_ir.json').read_text())
        before = copy.deepcopy(ir)
        jsonschema.validate(ir, json.loads((ROOT/'schemas/deck-ir.schema.json').read_text()))
        layout, issues = compile_deck(ir, EXAMPLE)
        self.assertFalse([i for i in issues if i['severity'] == 'FAIL'], issues)
        self.assertEqual(ir, before)
        self.assertEqual(len(layout['slides']), 1)
        elements = {e['id']: e for e in layout['slides'][0]['elements']}
        self.assertEqual(sum(e['kind'] == 'image' for e in elements.values()), 2)
        self.assertEqual(sum(bool(e.get('custom_geometry')) for e in elements.values()), 22)
        self.assertEqual(elements['factorization']['kind'], 'math')
        self.assertIn('<m:m>', elements['factorization']['omml'])
        self.assertTrue(elements['response']['inline_xml'])
        self.assertTrue(elements['takeaway']['inline_xml'])
        self.assertEqual(elements['constraints']['kind'], 'list')
        self.assertLess(elements['constraints']['bbox'][3], 220)
        for name in ('figure-1', 'figure-2'):
            self.assertEqual(elements[name]['origin'], 'reference')
            self.assertTrue(elements[name]['reference_source'])
            self.assertNotIn('source_figure', elements[name])
            self.assertGreater(elements[name]['bbox'][3], 200)

    def test_versioned_pptx_is_hash_bound_and_contains_editable_math_paths_and_bullets(self):
        record = json.loads((EXAMPLE/'validation.json').read_text())
        for name in ('complex-mixed.deck_ir.json', 'complex-mixed.pptx'):
            self.assertEqual(hashlib.sha256((EXAMPLE/name).read_bytes()).hexdigest(), record['files'][name])
        ns = {'p': 'http://schemas.openxmlformats.org/presentationml/2006/main',
              'a': 'http://schemas.openxmlformats.org/drawingml/2006/main',
              'm': 'http://schemas.openxmlformats.org/officeDocument/2006/math'}
        with zipfile.ZipFile(EXAMPLE/'complex-mixed.pptx') as archive:
            slides = [name for name in archive.namelist()
                      if name.startswith('ppt/slides/slide') and name.endswith('.xml')]
            self.assertEqual(len(slides), 1)
            slide = ET.fromstring(archive.read(slides[0]))
            self.assertGreaterEqual(len(slide.findall('.//m:m', ns)), 2)
            self.assertGreaterEqual(len(slide.findall('.//m:rad', ns)), 2)
            self.assertEqual(len(slide.findall('.//a:custGeom', ns)), 22)
            self.assertEqual(len(slide.findall('.//p:pic', ns)), 2)
            self.assertEqual(len(slide.findall('.//a:buChar', ns)), 3)
            self.assertFalse(slide.findall('.//a:buSzPct', ns))
            self.assertFalse(slide.findall('.//a:buSzPts', ns))
            media_hashes = {hashlib.sha256(archive.read(name)).hexdigest() for name in archive.namelist()
                            if name.startswith('ppt/media/')}
            for image in (EXAMPLE/'assets').glob('*.jpg'):
                self.assertIn(hashlib.sha256(image.read_bytes()).hexdigest(), media_hashes)
