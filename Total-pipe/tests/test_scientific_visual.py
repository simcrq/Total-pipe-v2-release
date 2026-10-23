"""Visual decisions change geometry while the scientific input and hard gates stay intact."""
import copy
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile

from lxml import etree as ET
from PIL import Image

from deck_compiler.contracts import digest, file_hash
from deck_compiler.ir import derive, validate
from deck_compiler.layout import compile_deck, geometry_issues
from deck_compiler.layout_provider import compile_with_provider
from deck_compiler.officecli import render
from deck_compiler.ooxml import NS
from deck_compiler.overflow_repair import repair_overflow
from deck_compiler.structural import verify
from deck_compiler.visual_planner import apply_proposal, make_prompt

ROOT = Path(__file__).resolve().parents[1]
DESIGN = {'style': 'research-seminar', 'title_treatment': 'thin-rule', 'density': 'balanced',
          'figure_treatment': 'unframed', 'decoration_policy': 'minimal'}


class ScientificVisualTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.panel = self.base/'panel.png'
        Image.new('RGB', (1200, 500), '#DAE8EE').save(self.panel)

    def deck(self, job='measurement-evidence', composition=None):
        ir = json.loads((ROOT/'examples/research.deck_ir.json').read_text(encoding='utf-8'))
        ir['slides'] = ir['slides'][:1]
        ir['presentation'] = {'academic_design': copy.deepcopy(DESIGN)}
        page = ir['slides'][0]
        page['id'] = 'measurement'
        page['semantic'].update(title='A controlled measurement', takeaway='A measured step is 2 units.',
            caveats=[], evidence_refs=['fixture:control'], speaker_notes='Synthetic fixture, no scientific result.')
        comp = page['composition']
        comp.update(archetype='figure-parameters', blocks=[
            {'id': 'conditions', 'component': 'parameter', 'label': 'Conditions', 'text': 'Keep power and dwell fixed.'},
            {'id': 'result', 'component': 'direct-evidence', 'label': 'Measurement', 'text': 'The step is 2 units.'}],
            figure_refs=[{'asset_id': 'panel', 'source_figure': '1', 'caption': 'Fig. 1. Control panel.',
                          'min_panel_extent': 140}])
        ir['assets'] = {'panel': {'path': str(self.panel), 'source_figure': '1'}}
        if job == 'mechanism-explanation':
            native = json.loads((ROOT/'examples/native-components.deck_ir.json').read_text(encoding='utf-8'))
            graphic = copy.deepcopy(native['slides'][0]['composition']['graphics'][0])
            graphic['edges'] = graphic['edges'][:2]
            graphic['edges'][0].update(basis='evidence', evidence_refs=['fixture:control'])
            comp.update(archetype='native-graphic', blocks=[], figure_refs=[], graphics=[graphic])
            ir['assets'] = {}
        elif job == 'evidence-comparison':
            comp['archetype'] = 'hero-dual-evidence'
            comp['figure_refs'].append(copy.deepcopy(comp['figure_refs'][0]))
        default = {'measurement-evidence': 'figure-left', 'mechanism-explanation': 'graphic-top',
                   'evidence-comparison': 'evidence-columns'}[job]
        page['presentation'] = {'visual_plan': {'visual_job': job,
            'primary': {'kind': 'graphic' if job == 'mechanism-explanation' else 'figure', 'index': 0},
            'composition': composition or default}}
        return ir

    def compile_ok(self, ir):
        before = copy.deepcopy(ir)
        layout, issues = compile_deck(ir, self.base)
        self.assertFalse([item for item in issues if item['severity'] == 'FAIL'], issues)
        self.assertEqual(ir, before)
        self.assertFalse(geometry_issues(layout['slides'][0]['elements'], 1))
        return layout, issues

    def objects(self, layout):
        return {e['id']: e for e in layout['slides'][0]['elements']}

    def test_plans_change_position_and_proportion_without_changing_content(self):
        ir = self.deck()
        plan = ir['slides'][0]['presentation']['visual_plan']
        results = []
        for position, ratio in [('figure-left', .64), ('figure-right', .64), ('figure-top', .64), ('figure-left', .70)]:
            plan.update(composition=position, figure_width_ratio=ratio)
            layout, _ = self.compile_ok(ir)
            objects = self.objects(layout)
            results.append(objects)
            self.assertEqual(objects['result']['source_text'], 'The step is 2 units.')
            self.assertEqual(objects['figure-1:caption']['source_text'], 'Fig. 1. Control panel.')
            self.assertEqual(layout['assets']['panel']['sha256'], file_hash(self.panel))
            self.assertGreaterEqual(objects['figure-1']['actual_panel_extent'], 140)
            selected = next(a['selected'] for a in layout['slides'][0]['adaptation_log'] if a['action'] == 'scientific_visual_plan')
            self.assertEqual(selected['pattern'], position)
        self.assertLess(results[0]['figure-1']['bbox'][0], results[0]['conditions']['bbox'][0])
        self.assertGreater(results[1]['figure-1']['bbox'][0], results[1]['conditions']['bbox'][0])
        self.assertLess(results[2]['figure-1']['bbox'][1], results[2]['conditions']['bbox'][1])
        self.assertNotEqual(results[0]['conditions']['bbox'], results[3]['conditions']['bbox'])

    def test_style_changes_native_header_and_typography_deck_wide(self):
        ir = self.deck()
        ir['slides'].append(copy.deepcopy(ir['slides'][0]))
        ir['slides'][1]['id'] = 'peer'
        design = ir['presentation']['academic_design']
        design.update(type_scale='compact', accent_color='#2563A6', figure_treatment='ruled-caption')
        layout, _ = self.compile_ok(ir)
        for slide in layout['slides']:
            objects = {e['id']: e for e in slide['elements']}
            self.assertEqual(objects['title']['contract']['font_size'], 40)
            self.assertEqual(objects['visual:title-rule']['fill'], '#2563A6')
            self.assertTrue(objects['figure-1:caption-rule']['visual_decoration'])
            self.assertNotIn('collision_mode', objects['visual:title-rule'])
        compact_top = self.objects(layout)['conditions']['bbox'][1]
        design['header_variant'] = 'standard'
        standard, _ = self.compile_ok(ir)
        self.assertGreater(self.objects(standard)['conditions']['bbox'][1], compact_top)

    def test_exact_emphasis_is_a_modest_editable_annotation(self):
        ir = self.deck()
        plan = ir['slides'][0]['presentation']['visual_plan']
        plan['emphasis'] = {'source': 'semantic.takeaway', 'text': '2 units', 'treatment': 'inline-callout'}
        layout, _ = self.compile_ok(ir)
        e = self.objects(layout)['visual:emphasis']
        self.assertEqual(e['source_text'], '2 units')
        self.assertEqual(e['kind'], 'text')
        self.assertLessEqual(e['contract']['font_size'], 28)
        self.assertEqual(self.objects(layout)['takeaway']['source_text'], ir['slides'][0]['semantic']['takeaway'])
        plan['emphasis'].update(source='composition.blocks.result.text')
        self.compile_ok(ir)

    def test_comparison_orders_evidence_and_aligns_captions(self):
        ir = self.deck('evidence-comparison')
        plan = ir['slides'][0]['presentation']['visual_plan']
        plan.update(primary={'kind': 'figure', 'index': 1}, evidence_order=[1, 0], figure_width_ratio=.55)
        layout, _ = self.compile_ok(ir)
        objects = self.objects(layout)
        self.assertLess(objects['figure-2']['bbox'][0], objects['figure-1']['bbox'][0])
        self.assertEqual(objects['figure-1:caption']['bbox'][1], objects['figure-2:caption']['bbox'][1])
        plan.update(composition='evidence-rows')
        plan.pop('figure_width_ratio')
        ir['slides'][0]['composition']['blocks'] = []
        layout, _ = self.compile_ok(ir)
        self.assertLess(self.objects(layout)['figure-2']['bbox'][1], self.objects(layout)['figure-1']['bbox'][1])

    def test_mechanism_reuses_v5_edges_and_review_gates(self):
        ir = self.deck('mechanism-explanation')
        layout, issues = self.compile_ok(ir)
        edges = [e for e in layout['slides'][0]['elements'] if e['kind'] == 'connector']
        self.assertEqual(len(edges), 2)
        evidence = next(e for e in edges if e['basis'] == 'evidence')
        hypothesis = next(e for e in edges if e['basis'] == 'hypothesis')
        self.assertEqual(evidence['evidence_refs'], ['fixture:control'])
        self.assertNotIn('line_dash', evidence)
        self.assertEqual(hypothesis['line_dash'], 'dash')
        self.assertIn('SCHEMATIC_REVIEW', {i['rule'] for i in issues})
        self.assertIn('fixture:control', layout['slides'][0]['notes'])

    def test_mechanism_with_source_evidence_obeys_left_and_right(self):
        ir = self.deck('mechanism-explanation', 'graphic-left')
        comp = ir['slides'][0]['composition']
        comp['archetype'] = 'figure-parameters'
        comp['blocks'] = [{'id': 'conditions', 'component': 'body', 'text': 'Keep conditions fixed.'}]
        ir['assets'] = {'panel': {'path': str(self.panel), 'source_figure': '1'}}
        comp['figure_refs'] = [{'asset_id': 'panel', 'source_figure': '1', 'caption': 'Fig. 1. Control.', 'min_panel_extent': 140}]
        Image.new('RGB', (500, 600), '#DAE8EE').save(self.panel)
        for position in ('graphic-left', 'graphic-right'):
            plan = ir['slides'][0]['presentation']['visual_plan']
            plan.update(composition=position, graphic_width_ratio=.64, context_placement='with-evidence')
            layout, _ = self.compile_ok(ir)
            objects = self.objects(layout)
            node = next(e for e in objects.values() if e.get('role') == 'graphic-node')
            image = objects['figure-1']
            self.assertEqual(node['bbox'][0] < image['bbox'][0], position == 'graphic-left')

    def test_unknown_fields_geometry_and_wrong_scientific_references_are_rejected(self):
        for mutation in ('extra', 'primary', 'bool', 'nan', 'job', 'source', 'text', 'treatment', 'order', 'ratio', 'style', 'decoration', 'tokens', 'location'):
            with self.subTest(mutation=mutation):
                ir = self.deck()
                page = ir['slides'][0]
                plan = page['presentation']['visual_plan']
                if mutation == 'extra': plan['bbox'] = [0, 0, 100, 100]
                elif mutation == 'primary': plan['primary']['index'] = 7
                elif mutation == 'bool': plan['primary']['index'] = True
                elif mutation == 'nan': plan['figure_width_ratio'] = float('nan')
                elif mutation == 'job': plan['visual_job'] = 'advertising'
                elif mutation in ('source', 'text', 'treatment'):
                    plan['emphasis'] = {'source': 'semantic.takeaway', 'text': '2 units', 'treatment': 'inline-callout'}
                    plan['emphasis'][mutation] = {'source': 'semantic.speaker_notes', 'text': '2 Å', 'treatment': 'poster'}[mutation]
                elif mutation == 'order': plan['evidence_order'] = [0, 1]
                elif mutation == 'ratio': plan['graphic_width_ratio'] = .5
                elif mutation == 'style': ir['presentation']['academic_design']['color'] = '#FFFFFF'
                elif mutation == 'decoration': ir['presentation']['academic_design']['decoration_policy'] = 'none'
                elif mutation == 'tokens': page['presentation']['theme_tokens'] = {'font': 'Other'}
                elif mutation == 'location': page['presentation']['academic_design'] = DESIGN
                self.assertTrue(any(i['severity'] == 'FAIL' for i in validate(ir)))
                self.assertIsNone(compile_deck(ir, self.base)[0])

    def test_plan_requires_deck_style_and_existing_resources(self):
        for mutation in ('style', 'figure', 'mechanism'):
            ir = self.deck()
            if mutation == 'style': ir.pop('presentation')
            elif mutation == 'figure': ir['slides'][0]['composition']['figure_refs'] = []
            else: ir['slides'][0]['presentation']['visual_plan']['visual_job'] = 'mechanism-explanation'
            self.assertIsNone(compile_deck(ir, self.base)[0])

    def test_capacity_failure_is_explicit_and_never_drops_content(self):
        ir = self.deck()
        ir['slides'][0]['composition']['figure_refs'][0]['min_panel_extent'] = 1000
        before = copy.deepcopy(ir)
        _, issues = compile_deck(ir, self.base)
        self.assertIn('VISUAL_PLAN_UNSATISFIABLE', {i['rule'] for i in issues})
        self.assertEqual(ir, before)
        ir = self.deck()
        ir['presentation']['text_capacity_policy'] = 'strict'
        for block in ir['slides'][0]['composition']['blocks']:
            block['text'] = 'Large full context. '*28
        _, issues = compile_deck(ir, self.base)
        self.assertIn('VISUAL_PLAN_UNSATISFIABLE', {i['rule'] for i in issues})

    def terminology_deck(self):
        ir = self.deck()
        page = ir['slides'][0]
        page['presentation'] = {}
        page['composition']['archetype'] = 'three-conclusions'
        page['composition']['figure_refs'] = []
        page['composition']['blocks'] = [{'id': 'terms', 'component': 'body', 'text':
            'X-ray photoelectron spectroscopy of molybdenum(VI) oxide preserves the chemical-state assignment. '*8}]
        page['semantic']['title'] = 'X-ray photoelectron spectroscopy and atomic force microscopy preserve the chemical-state assignment of molybdenum(VI) oxide'
        ir['assets'] = {}
        return ir

    def test_complete_scientific_terms_exceed_nominal_budgets_without_abbreviation(self):
        ir = self.terminology_deck()
        ir['slides'][0]['semantic']['title'] += ' under the stated conditions'
        layout, issues = self.compile_ok(ir)
        objects = self.objects(layout)
        self.assertEqual(objects['title']['source_text'], ir['slides'][0]['semantic']['title'])
        self.assertEqual(objects['terms']['source_text'], ir['slides'][0]['composition']['blocks'][0]['text'])
        self.assertIn('SCIENTIFIC_TEXT_CAPACITY_REVIEW', {i['rule'] for i in issues})
        self.assertGreater(objects['title']['bbox'][3], 64)
        ir['presentation']['text_capacity_policy'] = 'strict'
        self.assertIsNone(compile_deck(ir, self.base)[0])

    def test_text_overflow_is_released_for_review_with_all_terms_and_original_slot_recorded(self):
        ir = self.terminology_deck()
        ir['slides'][0]['composition']['blocks'][0]['text'] *= 3
        layout, issues = compile_deck(ir, self.base)
        self.assertFalse([i for i in issues if i['severity'] == 'FAIL'], issues)
        element = self.objects(layout)['terms']
        self.assertIn('molybdenum(VI) oxide', element['source_text'])
        self.assertEqual(element['source_text'], ir['slides'][0]['composition']['blocks'][0]['text'])
        self.assertEqual(element['contract']['overflow_policy'], 'preserve_terms_review')
        self.assertTrue(element['scientific_text_overflow']['original_bbox'])
        self.assertIn('SCIENTIFIC_TEXT_OVERFLOW', {i['rule'] for i in issues})
        self.assertFalse([i for i in geometry_issues(layout['slides'][0]['elements'], 1) if i['severity'] == 'FAIL'])

    @unittest.skipUnless(importlib.util.find_spec('jsonschema'), 'Optional JSON Schema checker unavailable')
    def test_json_schema_matches_long_term_policy_and_strict_design_fields(self):
        from jsonschema import Draft202012Validator
        schema = json.loads((ROOT/'schemas/deck-ir.schema.json').read_text())
        validator = Draft202012Validator(schema)
        ir = self.terminology_deck()
        ir['slides'][0]['semantic']['title'] += ' under the stated conditions'
        self.assertFalse(list(validator.iter_errors(ir)))
        ir['presentation']['text_capacity_policy'] = 'strict'
        self.assertTrue(list(validator.iter_errors(ir)))
        ir = self.deck()
        self.assertFalse(list(validator.iter_errors(ir)))
        ir['slides'][0]['presentation']['visual_plan']['bbox'] = [0, 0, 100, 100]
        self.assertTrue(list(validator.iter_errors(ir)))

    def test_provider_cannot_override_a_plan(self):
        class Provider:
            name = 'spy'
            def propose(self, requests):
                self.requests = requests
                return {'measurement': {'units': {}}}
        ir = self.deck()
        path = self.base/'deck.json'
        path.write_text(json.dumps(ir), encoding='utf-8')
        provider = Provider()
        layout, issues = compile_with_provider(path, provider, ROOT)
        self.assertFalse([i for i in issues if i['severity'] == 'FAIL'])
        self.assertEqual(provider.requests, [])
        self.assertEqual(layout['slides'], self.compile_ok(ir)[0]['slides'])
        self.assertEqual(layout['layout_provider']['slides'][0]['reason'], 'scientific_visual_plan')

    def test_overflow_repair_cannot_split_a_visual_plan(self):
        ir = self.deck()
        qa = {'items': [{'severity': 'WARNING', 'rule': 'OFFICECLI_FORMAT', 'slide': 1, 'shape': 'conditions',
                         'message': 'text overflow: need 200pt, usable 40pt'}]}
        repaired, changed = repair_overflow(ir, self.compile_ok(ir)[0], qa)
        self.assertFalse(changed)
        self.assertEqual(repaired, ir)

    def test_pages_without_a_visual_plan_keep_the_provider_path(self):
        class Provider:
            name = 'spy'
            def propose(self, requests):
                self.requests = requests
                return {}
        ir = self.deck()
        ir['slides'][0]['presentation'].pop('visual_plan')
        path = self.base/'deck.json'
        path.write_text(json.dumps(ir), encoding='utf-8')
        provider = Provider()
        layout, issues = compile_with_provider(path, provider, ROOT)
        self.assertEqual(len(provider.requests), 1)
        self.assertEqual(provider.requests[0]['slide_id'], 'measurement')
        self.assertNotIn('compiler_owned', provider.requests[0])
        self.assertFalse([i for i in issues if i['severity'] == 'FAIL'])
        self.assertEqual(layout['slides'], self.compile_ok(ir)[0]['slides'])

    def test_legacy_ir_is_unchanged_and_style_only_does_not_select_a_visual_job(self):
        ir = self.deck()
        ir['slides'][0]['presentation'].pop('visual_plan')
        styled, _ = self.compile_ok(ir)
        self.assertFalse(any(a['action'] == 'scientific_visual_plan' for a in styled['slides'][0]['adaptation_log']))
        ir.pop('presentation')
        legacy, _ = self.compile_ok(ir)
        self.assertNotIn('academic_design', legacy)
        self.assertNotIn('visual:title-rule', self.objects(legacy))
        self.assertEqual(compile_deck(ir, self.base)[0], legacy)

    def test_prompt_is_full_deck_and_merge_changes_presentation_only(self):
        ir = self.deck()
        ir['slides'][0]['presentation'].pop('visual_plan')
        ir.pop('presentation')
        before = copy.deepcopy(ir)
        prompt = make_prompt(ir, self.base, 'Lab seminar', ['measurement'])
        self.assertEqual(prompt['deck_ir'], ir)
        self.assertEqual(prompt['available_assets']['panel']['sha256'], file_hash(self.panel))
        proposal = {'ir_sha256': digest(ir), 'academic_design': copy.deepcopy(DESIGN),
            'slides': [{'slide_id': 'measurement', 'visual_plan': self.deck()['slides'][0]['presentation']['visual_plan']}]}
        merged = apply_proposal(ir, proposal)
        self.assertEqual(ir, before)
        self.assertEqual(merged['theme'], ir['theme'])
        self.assertEqual(merged['assets'], ir['assets'])
        self.assertEqual(merged['slides'][0]['semantic'], ir['slides'][0]['semantic'])
        self.assertEqual(merged['slides'][0]['composition'], ir['slides'][0]['composition'])
        self.compile_ok(merged)
        proposal['academic_design']['title_treatment'] = 'plain'
        self.assertEqual(merged['presentation']['academic_design']['title_treatment'], 'thin-rule')

    def test_stale_duplicate_unknown_and_content_bearing_proposals_fail_atomically(self):
        ir = self.deck()
        for mutation in ('sha', 'duplicate', 'unknown', 'content', 'nested', 'empty'):
            proposal = {'ir_sha256': digest(ir), 'academic_design': DESIGN,
                'slides': [{'slide_id': 'measurement', 'visual_plan': ir['slides'][0]['presentation']['visual_plan']}]}
            proposal = copy.deepcopy(proposal)
            if mutation == 'sha': proposal['ir_sha256'] = 'outdated'
            elif mutation == 'duplicate': proposal['slides'] *= 2
            elif mutation == 'unknown': proposal['slides'][0]['slide_id'] = 'missing'
            elif mutation == 'content': proposal['semantic'] = {'takeaway': 'different result'}
            elif mutation == 'nested': proposal['slides'][0]['composition'] = {}
            else: proposal['slides'] = []
            before = copy.deepcopy(ir)
            with self.assertRaises(ValueError): apply_proposal(ir, proposal)
            self.assertEqual(ir, before)

    def test_derived_trace_records_requested_and_selected_geometry(self):
        ir = self.deck()
        derived = derive(ir, self.compile_ok(ir)[0])['plan_to_layout.json']
        self.assertTrue(derived['read_only'])
        trace = derived['slides'][0]['visual_plan']
        self.assertEqual(trace['requested'], ir['slides'][0]['presentation']['visual_plan'])
        self.assertEqual(trace['selected']['pattern'], 'figure-left')
        self.assertEqual(derived['ir_sha256'], digest(ir))

    def test_cli_prompt_apply_and_failed_apply_preserves_output(self):
        ir = self.deck()
        source = self.base/'source.json'
        source.write_text(json.dumps(ir), encoding='utf-8')
        prompt = self.base/'prompt.json'
        command = [sys.executable, '-m', 'deck_compiler']
        subprocess.run([*command, 'visual-prompt', '--ir', str(source), '--out', str(prompt), '--slides', 'measurement'],
                       cwd=ROOT, check=True, capture_output=True)
        self.assertEqual(json.loads(prompt.read_text())['deck_ir'], ir)
        proposal = self.base/'proposal.json'
        proposal.write_text(json.dumps({'ir_sha256': digest(ir), 'academic_design': DESIGN,
            'slides': [{'slide_id': 'measurement', 'visual_plan': ir['slides'][0]['presentation']['visual_plan']}]}))
        target = self.base/'merged.json'
        apply = [*command, 'apply-visual-plan', '--ir', str(source), '--out', str(target), '--proposal', str(proposal)]
        subprocess.run(apply, cwd=ROOT, check=True, capture_output=True)
        before = target.read_bytes()
        proposal.write_text('{}')
        self.assertNotEqual(subprocess.run(apply, cwd=ROOT, capture_output=True).returncode, 0)
        self.assertEqual(target.read_bytes(), before)

    @unittest.skipUnless(shutil.which('officecli'), 'OfficeCLI unavailable')
    def test_native_output_keeps_editable_annotations_and_checks_actual_rules(self):
        ir = self.deck()
        ir['presentation']['academic_design']['figure_treatment'] = 'ruled-caption'
        ir['slides'][0]['presentation']['visual_plan']['emphasis'] = {
            'source': 'semantic.takeaway', 'text': '2 units', 'treatment': 'inline-callout'}
        layout, _ = self.compile_ok(ir)
        path = self.base/'layout.json'
        path.write_text(json.dumps(layout), encoding='utf-8')
        pptx = self.base/'candidate.pptx'
        render(path, pptx)
        self.assertFalse([i for i in verify(pptx, layout) if i['severity'] == 'FAIL'])
        with zipfile.ZipFile(pptx) as z:
            root = ET.fromstring(z.read('ppt/slides/slide1.xml'))
            named = {s.find('p:nvSpPr/p:cNvPr', NS).get('name'): s for s in root.findall('p:cSld/p:spTree/p:sp', NS)}
            self.assertIsNotNone(named['visual:emphasis'].find('p:txBody', NS))
            self.assertIn('visual:title-rule', named)
            # Actual decoration geometry is audited, including collisions, rather than exempted.
            named['visual:title-rule'].find('p:spPr/a:xfrm/a:off', NS).set('y', '0')
            parts = {name: z.read(name) for name in z.namelist()}
        parts['ppt/slides/slide1.xml'] = ET.tostring(root)
        with zipfile.ZipFile(pptx, 'w') as z:
            for name, content in parts.items(): z.writestr(name, content)
        self.assertIn('GEOMETRY_MISMATCH', {i['rule'] for i in verify(pptx, layout)})


if __name__ == '__main__':
    unittest.main()
