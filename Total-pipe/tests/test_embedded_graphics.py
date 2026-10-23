"""Native graphics share a research page without losing evidence or source content."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from PIL import Image

from deck_compiler.contracts import file_hash
from deck_compiler.graphic_layout import graphic_obstacle_collisions
from deck_compiler.ir import derive, validate
from deck_compiler.layout import compile_deck, intersect
from deck_compiler.layout_provider import PackerProvider, compile_with_provider
from deck_compiler.overflow_repair import repair_overflow

ROOT = Path(__file__).resolve().parents[1]


class EmbeddedGraphicTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.panel = self.base/'panel.png'
        Image.new('RGB', (640, 480), '#E8EDF0').save(self.panel)

    def deck(self, archetype='process-flow', dag=False, figure=True):
        ir = json.loads((ROOT/'examples/native-graphic.deck_ir.json').read_text(encoding='utf-8'))
        ir['slides'] = ir['slides'][:1]
        page = ir['slides'][0]
        page['id'] = 'mixed'
        page['semantic'].update(title='A controlled measurement workflow',
            purpose='Keep the procedure and original evidence together',
            takeaway='Controls constrain the interpretation.', evidence_refs=['fixture:control'],
            caveats=[], speaker_notes='Synthetic test data; no scientific claim is asserted.')
        comp = page['composition']
        comp['archetype'] = archetype
        comp['blocks'] = [{'id': 'context', 'component': 'body',
                           'text': 'Calibrate before comparing the signals.'}]
        graph = comp['graphics'][0]
        graph.update(id='method', type='dag' if dag else 'process', nodes=[
            {'id': 'input', 'shape': 'ellipse', 'title': 'Input', 'body': 'Signal'},
            {'id': 'control', 'shape': 'rounded-rect', 'title': 'Control', 'body': 'Baseline'},
            {'id': 'result', 'shape': 'rect', 'title': 'Output', 'body': 'Compare'}],
            edges=[{'from': 'input', 'to': 'control'}, {'from': 'control', 'to': 'result'}])
        ir['assets'] = {'panel': {'path': str(self.panel), 'source_figure': '1'}} if figure else {}
        comp['figure_refs'] = [{'asset_id': 'panel', 'source_figure': '1', 'panel_count': 1,
                               'caption': 'Fig. 1. Original control panel.'}] if figure else []
        return ir

    def compile_ok(self, ir):
        original = copy.deepcopy(ir)
        layout, issues = compile_deck(ir, self.base)
        self.assertFalse([i for i in issues if i['severity'] == 'FAIL'], issues)
        self.assertEqual(ir, original)
        self.assertIn('SCHEMATIC_REVIEW', {i['rule'] for i in issues})
        return layout, issues

    def test_both_research_archetypes_preserve_context_evidence_caption_and_notes(self):
        for archetype in ('process-flow', 'figure-parameters'):
            with self.subTest(archetype=archetype):
                ir = self.deck(archetype)
                layout, issues = self.compile_ok(ir)
                page = layout['slides'][0]
                objects = {e['id']: e for e in page['elements']}
                for key in ('title', 'takeaway'):
                    self.assertEqual(objects[key]['source_text'], ir['slides'][0]['semantic'][key])
                self.assertEqual(objects['context']['source_text'], ir['slides'][0]['composition']['blocks'][0]['text'])
                self.assertEqual(objects['figure-1:caption']['source_text'], 'Fig. 1. Original control panel.')
                self.assertEqual(objects['figure-1']['source_figure'], '1')
                self.assertGreaterEqual(objects['figure-1']['actual_panel_extent'], 220)
                self.assertEqual(layout['assets']['panel']['sha256'], file_hash(self.panel))
                self.assertIn(ir['slides'][0]['semantic']['speaker_notes'], page['notes'])
                self.assertIn('fixture:control', page['notes'])
                self.assertIn('SCIENTIFIC_PANEL_REVIEW', {i['rule'] for i in issues})
                self.assertEqual(sum(e['kind'] == 'connector' for e in page['elements']), 2)
                for e in page['elements']:
                    if e.get('graphic_id'):
                        self.assertFalse(intersect(e['bbox'], objects['figure-1']['bbox']))
                        self.assertFalse(intersect(e['bbox'], objects['context']['bbox']))

    def test_branch_merge_graph_uses_explicit_edges_inside_shared_page(self):
        ir = self.deck(dag=True)
        graph = ir['slides'][0]['composition']['graphics'][0]
        graph['nodes'].insert(2, {'id': 'condition', 'title': 'Test', 'body': 'Repeat'})
        graph['edges'] = [{'from': s, 'to': t} for s, t in
            [('input', 'control'), ('input', 'condition'), ('control', 'result'), ('condition', 'result')]]
        layout, _ = self.compile_ok(ir)
        edges = [e for e in layout['slides'][0]['elements'] if e['kind'] == 'connector']
        self.assertEqual(len(edges), 4)
        self.assertEqual({(e['source_id'].split(':')[-1], e['target_id'].split(':')[-1]) for e in edges},
                         {(e['from'], e['to']) for e in graph['edges']})
        self.assertTrue(all(e['route'] for e in edges))

    def test_optional_figure_and_empty_context_are_supported(self):
        for figure in (False, True):
            for context in (False, True):
                ir = self.deck(figure=figure)
                if not context:
                    ir['slides'][0]['composition']['blocks'] = []
                layout, _ = self.compile_ok(ir)
                self.assertEqual(sum(e['kind'] == 'image' for e in layout['slides'][0]['elements']), int(figure))

    def test_wide_evidence_can_share_a_template_frame_with_a_graph_above_it(self):
        Image.new('RGB', (1300, 500), '#FFFFFF').save(self.panel)
        ir = self.deck(dag=True)
        ir['presentation'] = {'frame_variant': 'template'}
        graph = ir['slides'][0]['composition']['graphics'][0]
        graph['edges'] = [{'from': 'input', 'to': 'control'}, {'from': 'input', 'to': 'result'}]
        layout, _ = self.compile_ok(ir)
        elements = layout['slides'][0]['elements']
        image = next(e for e in elements if e['kind'] == 'image')
        self.assertTrue(all(e['bbox'][1]+e['bbox'][3] <= image['bbox'][1]
                            for e in elements if e.get('role') == 'graphic-node'))

    def test_geometry_is_repeatable_and_derived_manifest_keeps_both_visual_types(self):
        ir = self.deck(dag=True)
        result = self.compile_ok(ir)
        self.assertEqual(result, compile_deck(ir, self.base))
        manifest = derive(ir, result[0])['visual_manifest.json']
        self.assertEqual(manifest['visuals'][0]['asset_id'], 'panel')
        self.assertEqual(manifest['graphics'][0]['nodes'], ir['slides'][0]['composition']['graphics'][0]['nodes'])

    def test_provider_cannot_replace_or_omit_the_graph(self):
        class SpyProvider:
            name = 'spy'
            def propose(self, requests):
                self.requests = requests
                return {'mixed': {'units': {'context': {'bbox': [56, 260, 1168, 380]}}}}
        ir = self.deck(dag=True)
        path = self.base/'deck.json'
        path.write_text(json.dumps(ir), encoding='utf-8')
        for provider in (SpyProvider(), PackerProvider()):
            layout, issues = compile_with_provider(path, provider, ROOT)
            self.assertFalse([i for i in issues if i['severity'] == 'FAIL'], issues)
            reference, _ = compile_deck(ir, self.base)
            self.assertEqual(layout['slides'], reference['slides'])
            record = layout['layout_provider']['slides'][0]
            self.assertEqual(record['reason'], 'native_graphic_composition')
            if isinstance(provider, SpyProvider):
                self.assertEqual(provider.requests, [])

    def test_capacity_failures_preserve_ir_instead_of_shrinking_evidence_or_truncating(self):
        for target in ('context', 'node', 'image'):
            ir = self.deck(dag=True)
            comp = ir['slides'][0]['composition']
            if target == 'context':
                comp['blocks'] = [{'id': f'body{i}', 'component': 'body', 'text': 'Long context. '*40}
                                  for i in range(4)]
            elif target == 'node':
                comp['graphics'][0]['nodes'][0]['title'] = 'Wide scientific label '*3
                comp['graphics'][0]['nodes'][0]['body'] = 'Full explanation '*10
            else:
                comp['figure_refs'][0]['min_panel_extent'] = 1000
            original = copy.deepcopy(ir)
            _, issues = compile_deck(ir, self.base)
            self.assertIn('GRAPHIC_PAGE_CAPACITY', {i['rule'] for i in issues if i['severity'] == 'FAIL'})
            self.assertEqual(ir, original)

    def test_invalid_or_ambiguous_topology_is_never_ignored(self):
        for mutation in ('unsupported', 'multiple', 'intent', 'cycle'):
            ir = self.deck(dag=True)
            comp = ir['slides'][0]['composition']
            if mutation == 'unsupported':
                comp['archetype'] = 'cover-hero'
            elif mutation == 'multiple':
                comp['graphics'].append(copy.deepcopy(comp['graphics'][0]))
            elif mutation == 'intent':
                comp['visual_intent'] = {'relation': 'process'}
            else:
                comp['graphics'][0]['edges'].append({'from': 'result', 'to': 'input'})
            self.assertTrue(any(i['rule'] == 'GRAPHIC_INVALID' for i in validate(ir)))
            self.assertIsNone(compile_deck(ir, self.base)[0])

    def test_segments_crossing_context_captions_or_images_are_detected(self):
        edge = {'id': 'edge', 'kind': 'connector', 'graphic_id': 'g',
                'route': [[10, 40], [80, 40]], 'start': [10, 40], 'end': [80, 40]}
        obstacles = [{'id': kind, 'kind': kind, 'bbox': [30, 20, 20, 40]} for kind in ('image', 'text', 'math')]
        self.assertEqual(graphic_obstacle_collisions([edge], obstacles),
                         [('edge', kind) for kind in ('image', 'text', 'math')])
        self.assertEqual(graphic_obstacle_collisions([edge], [{'id': 'clear', 'kind': 'image',
                                                               'bbox': [30, 41, 20, 40]}]), [])

    def test_text_overflow_repair_does_not_split_a_graph_from_its_context(self):
        ir = self.deck()
        layout, _ = self.compile_ok(ir)
        qa = {'items': [{'rule': 'OFFICECLI_FORMAT', 'severity': 'WARNING', 'slide': 1,
                         'shape': 'context', 'message': 'text overflow: need 180pt, usable 60pt.'}]}
        repaired, modified = repair_overflow(ir, layout, qa)
        self.assertFalse(modified)
        self.assertEqual(repaired, ir)

    def test_mcp_compile_keeps_graph_and_evidence_on_the_same_page(self):
        ir = self.deck(dag=True)
        path = self.base/'deck.json'
        path.write_text(json.dumps(ir), encoding='utf-8')
        out = self.base/'build'
        request = {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {
            'name': 'totalpipe_compile', 'arguments': {'ir': str(path), 'out': str(out),
                                                     'skip_visual_design': True}}}
        process = subprocess.run([sys.executable, '-X', 'utf8', '-m', 'deck_compiler.mcp_server'],
            cwd=ROOT, input=json.dumps(request)+'\n', capture_output=True, text=True, encoding='utf-8', timeout=40)
        self.assertEqual(process.returncode, 0, process.stderr)
        response = json.loads(process.stdout)['result']
        self.assertFalse(response.get('isError'), response)
        qa = json.loads((out/'qa_report.json').read_text(encoding='utf-8'))
        self.assertEqual(qa['counts']['FAIL'], 0, qa)
        elements = json.loads((out/'layout.json').read_text(encoding='utf-8'))['slides'][0]['elements']
        self.assertEqual(sum(e['kind'] == 'image' for e in elements), 1)
        self.assertEqual(sum(e['kind'] == 'connector' for e in elements), 2)
