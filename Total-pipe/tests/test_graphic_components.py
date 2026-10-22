"""Scientific component semantics, composition, pipeline integration and native object identity."""
import copy
import io
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

from deck_compiler.dag_layout import connector_points
from deck_compiler.graphic_layout import compile_graphic, validate_graphics
from deck_compiler.ir import validate
from deck_compiler.layout import compile_deck
from deck_compiler.officecli import commands, render
from deck_compiler.ooxml import NS
from deck_compiler.structural import verify

ROOT = Path(__file__).resolve().parents[1]


def example():
    return json.loads((ROOT/'examples/native-components.deck_ir.json').read_text(encoding='utf-8'))


def graph(ir, index=0):
    return ir['slides'][index]['composition']['graphics'][0]


class GraphicComponentTests(unittest.TestCase):
    def compile_ok(self, ir):
        before = copy.deepcopy(ir)
        layout, issues = compile_deck(ir, ROOT/'examples')
        self.assertFalse([i for i in issues if i['severity'] == 'FAIL'], issues)
        self.assertEqual(ir, before)
        self.assertEqual(sum(i['rule'] == 'SCHEMATIC_REVIEW' for i in issues), len(ir['slides']))
        return layout

    def test_all_components_compile_deterministically_without_rewriting_content(self):
        ir = example()
        layout = self.compile_ok(ir)
        self.assertEqual(layout, self.compile_ok(ir))
        for source, slide in zip(ir['slides'], layout['slides']):
            self.assertIn(source['semantic']['speaker_notes'], slide['notes'])
            self.assertTrue(all(e['contract']['font_size'] >= 24 for e in slide['elements'] if e['kind'] == 'text'))

    def test_mechanism_edges_distinguish_activation_inhibition_hypotheses_and_feedback(self):
        ir = example()
        layout = self.compile_ok(ir)
        items = layout['slides'][0]['elements']
        edges = [e for e in items if e['kind'] == 'connector']
        self.assertEqual(len(edges), 3)
        for relation in graph(ir)['edges']:
            edge = next(e for e in edges if e['id'].endswith(':'+relation['from']+':'+relation['to']))
            self.assertEqual(edge['tail_end'], 'triangle' if relation['kind'] == 'activate' else 'none')
            self.assertEqual(edge['line_dash'], 'dash')
            self.assertEqual(edge['basis'], 'hypothesis')
            self.assertEqual(edge['route'][0], edge['start'])
            self.assertAlmostEqual(edge['route'][-1][0], edge['end'][0])
            self.assertAlmostEqual(edge['route'][-1][1], edge['end'][1])
            self.assertEqual(edge['route'], connector_points(edge['bbox'], edge['geometry'],
                edge['adjustments'], edge['flip_v'], edge.get('flip_h', False)))
        self.assertEqual(sum(e.get('role') == 'graphic-mark' for e in items), 2)
        self.assertTrue(next(e for e in edges if e['id'].endswith(':C:A'))['flip_h'])
        labels = [e for e in items if e.get('edge_id') and e['kind'] == 'text']
        self.assertEqual(len(labels), 3)
        self.assertTrue(all(e['source_text'].startswith('假设') for e in labels))

    def test_evidence_edges_require_refs_bound_to_the_slide(self):
        ir = example()
        edge = graph(ir)['edges'][0]
        edge['basis'] = 'evidence'
        self.assertTrue(any(i['severity'] == 'FAIL' for i in validate(ir)))
        edge['evidence_refs'] = ['fixture:relation']
        self.assertIn('GRAPHIC_EVIDENCE_INVALID', {i['rule'] for i in validate(ir)})
        ir['slides'][0]['semantic']['evidence_refs'] = ['fixture:relation']
        layout = self.compile_ok(ir)
        actual = next(e for e in layout['slides'][0]['elements'] if e['kind'] == 'connector' and e['id'].endswith(':A:B'))
        self.assertNotIn('line_dash', actual)
        self.assertEqual(actual['evidence_refs'], ['fixture:relation'])

    def test_cycles_are_not_automatically_reclassified_as_feedback(self):
        ir = example()
        graph(ir)['edges'][-1].pop('feedback')
        self.assertIsNone(compile_deck(ir, ROOT)[0])
        ir = example()
        graph(ir)['edges'][0]['feedback'] = True
        self.assertTrue(any(i['severity'] == 'FAIL' for i in validate(ir)))

    def test_architecture_containers_hold_the_declared_nodes_and_only_explicit_edges(self):
        ir = example()
        page = self.compile_ok(ir)['slides'][1]
        containers = [e for e in page['elements'] if e.get('role') == 'graphic-container']
        self.assertEqual(len(containers), 3)
        for container, layer in zip(containers, graph(ir, 1)['layers']):
            members = [e for e in page['elements'] if e.get('role') == 'graphic-node' and e.get('container_id') == container['id']]
            self.assertEqual({e['node_id'] for e in members}, {n['id'] for n in layer['nodes']})
            for member in members:
                x, y, w, h = member['bbox']
                cx, cy, cw, ch = container['bbox']
                self.assertTrue(cx <= x and cy <= y and x+w <= cx+cw and y+h <= cy+ch)
        self.assertEqual(sum(e['kind'] == 'connector' for e in page['elements']), 4)

    def test_funnels_and_pyramids_are_native_polygons_with_independent_complete_labels(self):
        ir = example()
        layout = self.compile_ok(ir)
        for index in (2, 3):
            shapes = [e for e in layout['slides'][index]['elements'] if e.get('role') == 'graphic-node']
            self.assertTrue(all('custom_geometry' in e for e in shapes))
            widths = [e['bbox'][2] for e in shapes]
            self.assertEqual(widths, sorted(widths, reverse=index == 2))
            labels = [e['source_text'] for e in layout['slides'][index]['elements'] if e.get('node_id') and e['kind'] == 'text']
            self.assertEqual(labels, [level['title'] for level in graph(ir, index)['levels']])

    def test_composition_scopes_ids_and_obeys_region_weights(self):
        ir = example()
        comp = graph(ir, 5)
        comp['weights'] = [2, 1]
        layout = self.compile_ok(ir)
        items = layout['slides'][5]['elements']
        self.assertEqual(len({e['id'] for e in items}), len(items))
        regions = {e['graphic_id']: e['graphic_region'] for e in items if e.get('graphic_id')}
        self.assertEqual(set(regions), {'combined.selection', 'combined.regions'})
        self.assertAlmostEqual(regions['combined.selection'][2], 2*regions['combined.regions'][2])
        self.assertLessEqual(regions['combined.selection'][0]+regions['combined.selection'][2], regions['combined.regions'][0])

    def test_bad_components_are_rejected_with_explicit_errors(self):
        cases = [
            (0, lambda g: g['edges'][0].pop('basis')),
            (0, lambda g: g['edges'][0].update(kind='invented')),
            (0, lambda g: g['edges'].append(copy.deepcopy(g['edges'][0]))),
            (1, lambda g: g['edges'][0].update(to='missing')),
            (1, lambda g: g['edges'].append({'from': 'report', 'to': 'collect'})),
            (1, lambda g: g['layers'][0]['nodes'].append(copy.deepcopy(g['layers'][0]['nodes'][0]))),
            (2, lambda g: g.update(levels=[])),
            (2, lambda g: g.update(end_width=0)),
            (2, lambda g: g['levels'][0].update(x=20)),
            (5, lambda g: g['components'][1].update(id=g['components'][0]['id'])),
            (5, lambda g: g.update(weights=[1])),
            (5, lambda g: g['components'].append({'id':'nested','type':'composite','components':[]})),
        ]
        for index, mutate in cases:
            ir = example()
            mutate(graph(ir, index))
            self.assertIsNone(compile_deck(ir, ROOT)[0])

    def test_long_text_and_small_regions_fail_without_truncation(self):
        ir = example()
        graph(ir, 2)['levels'][0]['title'] = 'This full scientific level label is too long for a narrow component.'
        before = copy.deepcopy(graph(ir, 2))
        with self.assertRaises(ValueError):
            compile_graphic(graph(ir, 2), [0, 0, 100, 100], ir['theme'])
        self.assertEqual(graph(ir, 2), before)
        graph(ir, 4)['labels'][0].update(text='Original text '*10, box=[10, 10, 20, 10])
        _, issues = compile_deck(ir, ROOT/'examples')
        self.assertTrue(any(i['rule'] == 'SPLIT_REQUIRED' and i['severity'] == 'FAIL' for i in issues))

    def test_v4_mixed_pages_accept_components_and_keep_source_figures(self):
        ir = example()
        ir['slides'] = ir['slides'][2:3]
        comp = ir['slides'][0]['composition']
        comp.update(archetype='figure-parameters', blocks=[{'id':'context','component':'body','text':'Keep the source measurement.'}])
        with tempfile.TemporaryDirectory() as folder:
            image = Path(folder)/'panel.png'
            Image.new('RGB', (640, 480), '#FFFFFF').save(image)
            ir['assets'] = {'panel': {'path': str(image), 'source_figure': '1'}}
            comp['figure_refs'] = [{'asset_id':'panel','source_figure':'1','caption':'Fig. 1. Original control.'}]
            layout = self.compile_ok(ir)
            objects = {e['id']:e for e in layout['slides'][0]['elements']}
            self.assertEqual(objects['figure-1']['source_figure'], '1')
            self.assertEqual(objects['context']['source_text'], 'Keep the source measurement.')
            self.assertTrue(any(e.get('custom_geometry') for e in objects.values()))

    def test_officecli_commands_replace_geometry_and_preserve_native_connector_bindings(self):
        layout = self.compile_ok(example())
        batch = commands(layout)
        custom = [c for c in batch if c.get('command') == 'raw-set' and '<a:custGeom' in c.get('xml','')]
        self.assertEqual(len(custom), sum(bool(e.get('custom_geometry')) for p in layout['slides'] for e in p['elements']))
        self.assertTrue(all(c['action'] == 'replace' and c['xpath'].endswith('/a:prstGeom') for c in custom))
        self.assertFalse([c for c in batch if c.get('type') == 'picture'])
        self.assertTrue(any(c.get('xml') == 'flipH=1' for c in batch))
        self.assertTrue(all('fromIdx' in c['props'] and 'toIdx' in c['props'] for c in batch if c.get('type') == 'connector'))

    def test_mcp_compile_entry_exports_components_and_custom_geometry(self):
        with tempfile.TemporaryDirectory() as folder:
            source, out = Path(folder)/'deck.json', Path(folder)/'build'
            source.write_text(json.dumps(example(), ensure_ascii=False), encoding='utf-8')
            request = {'jsonrpc':'2.0','id':1,'method':'tools/call','params':{
                'name':'totalpipe_compile','arguments':{'ir':str(source),'out':str(out)}}}
            process = subprocess.run([sys.executable,'-X','utf8','-m','deck_compiler.mcp_server'],
                cwd=ROOT,input=json.dumps(request)+'\n',capture_output=True,text=True,encoding='utf-8',timeout=40)
            self.assertEqual(process.returncode, 0, process.stderr)
            response = json.loads(process.stdout)['result']
            self.assertFalse(response.get('isError'), response)
            qa = json.loads((out/'qa_report.json').read_text(encoding='utf-8'))
            self.assertEqual(qa['counts']['FAIL'], 0, qa)
            layout = json.loads((out/'layout.json').read_text(encoding='utf-8'))
            self.assertEqual(len(layout['slides']), 6)
            self.assertTrue(any(e.get('custom_geometry') for p in layout['slides'] for e in p['elements']))


@unittest.skipUnless(shutil.which('officecli'), 'OfficeCLI executable required')
class ComponentNativeExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        folder = Path(cls.temp.name)
        cls.layout, issues = compile_deck(example(), ROOT/'examples')
        if any(i['severity'] == 'FAIL' for i in issues):
            raise AssertionError(issues)
        source = folder/'layout.json'
        source.write_text(json.dumps(cls.layout, ensure_ascii=False), encoding='utf-8')
        cls.pptx = folder/'components.pptx'
        render(source, cls.pptx)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_native_shapes_custom_paths_and_connector_references_pass_structure(self):
        self.assertFalse([i for i in verify(self.pptx, self.layout) if i['severity'] == 'FAIL'])
        with zipfile.ZipFile(self.pptx) as package:
            roots = [ET.fromstring(package.read(f'ppt/slides/slide{i}.xml')) for i in range(1, 7)]
            self.assertGreater(sum(len(r.findall('.//a:custGeom', NS)) for r in roots), 10)
            self.assertEqual(sum(len(r.findall('.//p:pic', NS)) for r in roots), 0)
            for root in roots:
                ids = [e.get('id') for e in root.findall('.//p:cNvPr', NS)]
                self.assertEqual(len(ids), len(set(ids)))

    def test_tampered_path_dash_and_connector_identity_are_rejected(self):
        mutations = [
            (5, './/a:custGeom//a:pt', 'x', '999999', 'GRAPHIC_PATH_MISMATCH'),
            (1, './/p:cxnSp//a:prstDash', 'val', 'solid', 'CONNECTOR_STYLE_MISMATCH'),
            (1, './/p:cxnSp//a:stCxn', 'id', '999999', 'CONNECTOR_REFERENCE_INVALID'),
        ]
        for page, xpath, attribute, value, rule in mutations:
            with zipfile.ZipFile(self.pptx) as src:
                part = f'ppt/slides/slide{page}.xml'
                root = ET.fromstring(src.read(part))
                root.find(xpath, NS).set(attribute, value)
                output = io.BytesIO()
                with zipfile.ZipFile(output, 'w') as dst:
                    for item in src.infolist():
                        dst.writestr(item, ET.tostring(root) if item.filename == part else src.read(item.filename))
            target = Path(self.temp.name)/'tampered.pptx'
            target.write_bytes(output.getvalue())
            self.assertIn(rule, {i['rule'] for i in verify(target, self.layout)})
