"""User reference crops retain their source without impersonating paper evidence or schematics."""
import copy
import json
from pathlib import Path
import shutil
import tempfile
import unittest

import jsonschema
from PIL import Image

from deck_compiler.ir import validate
from deck_compiler.layout import compile_deck
from deck_compiler.officecli import render
from deck_compiler.pipeline import write_json
from deck_compiler.structural import verify
from deck_compiler.visual_planner import make_prompt
from test_deck_compiler import ROOT
from test_schematic import schematic_deck


class ReferenceImageTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.ir = schematic_deck(self.base, caption='Research facilities from the supplied slide.')
        Image.new('RGB', (700, 600), '#DAE8EE').save(self.base/'flow.png')
        self.ir['assets']['flow'] = {'path': 'flow.png', 'origin': 'reference',
                                    'reference_source': 'User-provided feasibility slide, page 8, left panel'}
        self.schema = json.loads((ROOT/'schemas/deck-ir.schema.json').read_text())

    def test_reference_compiles_with_or_without_caption_and_does_not_mutate_input(self):
        for caption in ('Research facilities from the supplied slide.', ''):
            for recursive in (False, True):
                with self.subTest(caption=caption, recursive=recursive):
                    ir = copy.deepcopy(self.ir)
                    comp = ir['slides'][0]['composition']
                    comp['figure_refs'][0]['caption'] = caption
                    comp['blocks'] = []
                    if recursive:
                        comp.update(archetype='composite-research', layout_tree={'version': '1.0',
                            'regions': {'body': {'id': 'crop', 'type': 'figure', 'ref': 0}}})
                    before = copy.deepcopy(ir)
                    jsonschema.validate(ir, self.schema)
                    self.assertFalse([i for i in validate(ir) if i['severity'] == 'FAIL'])
                    layout, issues = compile_deck(ir, self.base)
                    self.assertFalse([i for i in issues if i['severity'] == 'FAIL'], issues)
                    image = next(e for e in layout['slides'][0]['elements'] if e['kind'] == 'image')
                    self.assertEqual(image['reference_source'], ir['assets']['flow']['reference_source'])
                    self.assertEqual(image['origin'], 'reference')
                    self.assertEqual(image['role'], 'reference')
                    self.assertNotIn('source_figure', image)
                    self.assertNotIn('schematic', image)
                    rules = [i['rule'] for i in issues]
                    self.assertIn('REFERENCE_IMAGE_REVIEW', rules)
                    self.assertNotIn('SCHEMATIC_REVIEW', rules)
                    self.assertNotIn('SCIENTIFIC_PANEL_REVIEW', rules)
                    visible = next((e['source_text'] for e in layout['slides'][0]['elements']
                                    if e['id'] == image['id']+':caption'), '')
                    self.assertEqual(visible, caption)
                    self.assertEqual(ir, before)

    def test_source_is_required_by_runtime_and_schema(self):
        for value in (None, '', ' \t\n', 4):
            ir = copy.deepcopy(self.ir)
            if value is None:
                del ir['assets']['flow']['reference_source']
            else:
                ir['assets']['flow']['reference_source'] = value
            self.assertIn('REFERENCE_SOURCE_REQUIRED', [i['rule'] for i in validate(ir)])
            with self.assertRaises(jsonschema.ValidationError):
                jsonschema.validate(ir, self.schema)

    def test_reference_cannot_claim_paper_figure_on_asset_or_reference(self):
        for target in ('asset', 'figure'):
            ir = copy.deepcopy(self.ir)
            value = ir['assets']['flow'] if target == 'asset' else ir['slides'][0]['composition']['figure_refs'][0]
            value['source_figure'] = '3a'
            self.assertIn('FIGURE_PROVENANCE_FORBIDDEN', [i['rule'] for i in validate(ir)])
            layout, _ = compile_deck(ir, self.base)
            self.assertIsNone(layout)
            if target == 'asset':
                with self.assertRaises(jsonschema.ValidationError):
                    jsonschema.validate(ir, self.schema)

    def test_reference_still_enforces_image_readability(self):
        self.ir['slides'][0]['composition']['figure_refs'][0]['min_panel_extent'] = 500
        layout, issues = compile_deck(self.ir, self.base)
        self.assertIsNotNone(layout)
        failure = next(i for i in issues if i['rule'] == 'REFERENCE_IMAGE_TOO_SMALL')
        self.assertEqual(failure['severity'], 'FAIL')
        self.assertEqual(failure['source']['reference_source'], self.ir['assets']['flow']['reference_source'])

    def test_visual_prompt_retains_reference_provenance(self):
        prompt = make_prompt(self.ir, self.base)
        asset = prompt['available_assets']['flow']
        self.assertEqual(asset['origin'], 'reference')
        self.assertEqual(asset['reference_source'], self.ir['assets']['flow']['reference_source'])
        self.assertIsNone(asset['source_figure'])
        self.assertEqual(prompt['deck_ir'], self.ir)

    def test_visual_plan_measures_short_list_with_the_configured_spacing(self):
        from test_native_list import styled_deck
        self.ir['presentation'] = styled_deck()['presentation']
        self.ir['presentation'].update(text_capacity_policy='strict', list_gap=.8, bullet_style='arrowhead')
        slide = self.ir['slides'][0]
        slide['composition'].update(archetype='figure-parameters', blocks=[
            {'id': 'context', 'component': 'body', 'text': 'First complete finding.\nSecond complete finding.',
             'text_flow': 'distributed_arrow_list'}])
        slide['presentation']['visual_plan'] = {'visual_job': 'measurement-evidence',
            'primary': {'kind': 'figure', 'index': 0}, 'composition': 'figure-top'}
        layout, issues = compile_deck(self.ir, self.base)
        self.assertFalse([i for i in issues if i['severity'] == 'FAIL'], issues)
        items = next(e for e in layout['slides'][0]['elements'] if e['id'] == 'context')
        self.assertEqual(items['kind'], 'list')
        self.assertLess(items['bbox'][3], 220)

    @unittest.skipUnless(shutil.which('officecli'), 'OfficeCLI required')
    def test_reference_native_image_roundtrip_keeps_original_bytes(self):
        layout, issues = compile_deck(self.ir, self.base)
        self.assertFalse([i for i in issues if i['severity'] == 'FAIL'], issues)
        write_json(self.base/'layout.json', layout)
        render(self.base/'layout.json', self.base/'candidate.pptx', shutil.which('officecli'))
        self.assertFalse([i for i in verify(self.base/'candidate.pptx', layout) if i['severity'] == 'FAIL'])
