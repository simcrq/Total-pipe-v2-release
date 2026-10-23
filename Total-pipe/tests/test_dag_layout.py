"""Observable DAG behavior, native routes, failure gates, and the real MCP entry."""
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

from deck_compiler.dag_layout import audit_scene, layered_order
from deck_compiler.ir import validate
from deck_compiler.layout import compile_deck
from deck_compiler.officecli import commands, preflight, render
from deck_compiler.structural import verify
from deck_compiler.ooxml import NS

ROOT = Path(__file__).resolve().parents[1]


def example():
    return json.loads((ROOT/'examples/native-dag.deck_ir.json').read_text(encoding='utf-8'))


def graph_deck(ids, pairs):
    ir = example()
    ir['slides'] = ir['slides'][1:2]
    ir['slides'][0]['composition']['graphics'][0].update(
        nodes=[{'id':nid, 'title':nid} for nid in ids],
        edges=[{'from':a, 'to':b} for a, b in pairs])
    return ir


class DAGLayoutTests(unittest.TestCase):
    def compile(self, ir):
        layout, issues = compile_deck(ir, ROOT)
        self.assertIsNotNone(layout, issues)
        self.assertFalse([i for i in issues if i['severity']=='FAIL'], issues)
        return layout

    def test_linear_three_node_positions_and_commands_remain_v2(self):
        ir = example(); ir['slides'] = ir['slides'][:1]
        layout = self.compile(ir)
        nodes = [e for e in layout['slides'][0]['elements'] if e.get('role')=='graphic-node']
        for node, x in zip(nodes, (56, 466.6666666666667, 877.3333333333334)):
            self.assertAlmostEqual(node['bbox'][0], x)
            self.assertEqual(node['bbox'][1:], [314.0, 346.6666666666667, 272.0])
        edges = [c for c in commands(layout) if c.get('type')=='connector']
        self.assertEqual(len(edges), 2)
        self.assertTrue(all(c['props']['shape']=='straightConnector1' and c['props']['height']=='0px' for c in edges))
        self.assertFalse(any(c.get('command')=='raw-set' and 'cxnSp' in c.get('xpath', '') for c in commands(layout)))

    def test_branch_merge_and_multilevel_use_only_declared_edges(self):
        ir = example()
        layout = self.compile(ir)
        for slide, page in zip(ir['slides'][1:], layout['slides'][1:]):
            graphic = slide['composition']['graphics'][0]
            expected = {(e['from'], e['to']) for e in graphic['edges']}
            edges = [e for e in page['elements'] if e['kind']=='connector']
            self.assertEqual({(e['source_id'].split(':')[-1], e['target_id'].split(':')[-1]) for e in edges}, expected)
            nodes = [e for e in page['elements'] if e.get('role')=='graphic-node']
            region = next(a['region'] for a in page['adaptation_log'] if a['action']=='native_graphic')
            self.assertFalse(audit_scene(nodes, edges, region))
            for edge in edges:
                self.assertEqual(edge['route'][0], edge['start'])
                self.assertEqual(edge['route'][-1], edge['end'])
                self.assertTrue(all(abs(a[0]-b[0])<.01 or abs(a[1]-b[1])<.01
                                    for a, b in zip(edge['route'], edge['route'][1:])))
        self.assertTrue(any(e.get('geometry')=='bentConnector5' for e in layout['slides'][-1]['elements']))

    def test_parallel_components_and_isolated_nodes_do_not_gain_edges(self):
        for pairs in ([], [('A','C'),('B','D')]):
            ids = ['A','B','C'] if not pairs else ['A','B','C','D']
            layout = self.compile(graph_deck(ids, pairs))
            self.assertEqual(sum(e['kind']=='connector' for e in layout['slides'][0]['elements']), len(pairs))
        self.compile(graph_deck(['only'], []))

    def test_topological_order_does_not_require_sorted_input(self):
        layers, ranks = layered_order(['result','right','input','left'],
                                     [('input','left'),('input','right'),('left','result'),('right','result')])
        self.assertEqual(layers[0], ['input'])
        self.assertEqual(layers[-1], ['result'])
        self.assertEqual(ranks['result'], 2)

    def test_repeat_layout_and_permuted_edge_order_are_deterministic(self):
        ir = example(); before = copy.deepcopy(ir)
        a = self.compile(ir)
        self.assertEqual(a, self.compile(ir))
        self.assertEqual(ir, before)
        for slide in ir['slides'][1:]:
            slide['composition']['graphics'][0]['edges'].reverse()
        b = self.compile(ir)
        self.assertEqual(a['slides'], b['slides'])

    def test_mixed_presets_and_different_text_lengths_are_preserved(self):
        ir = example(); ir['slides'] = ir['slides'][-1:]
        node = ir['slides'][0]['composition']['graphics'][0]['nodes'][2]
        node['body'] = 'Independent samples under two conditions.'
        layout = self.compile(ir)
        elements = layout['slides'][0]['elements']
        self.assertEqual(len({e['geometry'] for e in elements if e.get('role')=='graphic-node'}), 5)
        body = next(e for e in elements if e['id'].endswith(':node:b:body'))
        self.assertEqual(body['source_text'], node['body'])
        self.assertGreaterEqual(body['contract']['font_size'], 24)
        nodes = [e for e in elements if e.get('role')=='graphic-node']
        self.assertGreater(len({e['bbox'][3] for e in nodes}), 1)

    def test_cycles_self_loops_duplicate_and_invalid_edges_are_rejected(self):
        cases = [([('A','B'),('B','A')], 'cycle'),
                 ([('A','A')], 'Self-loop'),
                 ([('A','B'),('A','B')], 'Duplicate'),
                 ([('A','missing')], 'existing node')]
        for pairs, message in cases:
            with self.subTest(pairs=pairs):
                ir = graph_deck(['A','B'], pairs)
                issues = validate(ir)
                self.assertTrue(any(message.lower() in i['message'].lower() for i in issues), issues)
                self.assertIsNone(compile_deck(ir, ROOT)[0])

    def test_text_and_geometry_capacity_fail_explicitly_without_mutation(self):
        for overflow in ('text', 'height', 'layers'):
            ir = graph_deck(['A','B','C','D'], [('A','B'),('A','C'),('B','D'),('C','D')])
            g = ir['slides'][0]['composition']['graphics'][0]
            if overflow=='text':
                g['nodes'][1]['body']='密'*180
            elif overflow=='height':
                g['nodes']=[{'id':str(i),'title':str(i)} for i in range(8)]
                g['edges']=[{'from':'0','to':str(i)} for i in range(1,8)]
            else:
                g['nodes']=[{'id':str(i),'title':str(i)} for i in range(7)]
                g['edges']=[{'from':str(i),'to':str(i+1)} for i in range(6)]
            before=copy.deepcopy(ir)
            _, issues=compile_deck(ir,ROOT)
            self.assertTrue(any(i['severity']=='FAIL' and i['rule'] in
                                ('GRAPHIC_TEXT_OVERFLOW','GRAPHIC_CAPACITY') for i in issues), issues)
            self.assertEqual(ir,before)

    def test_node_overlap_routes_through_nodes_bounds_and_conflicts_are_detected(self):
        nodes=[{'id':'obstacle','bbox':[45,35,10,30]}]
        route={'id':'edge1','source_id':'a','target_id':'b','route':[[0,50],[100,50]]}
        self.assertIn('GRAPHIC_ROUTE_THROUGH_NODE',{r for r,_,_ in audit_scene(nodes,[route],[0,0,100,100])})
        crossing={'id':'edge2','source_id':'c','target_id':'d','route':[[50,0],[50,100]]}
        self.assertIn('GRAPHIC_ROUTE_CONFLICT',{r for r,_,_ in audit_scene([], [route,crossing],[0,0,100,100])})
        collinear={**crossing,'route':[[25,50],[75,50]]}
        self.assertIn('GRAPHIC_ROUTE_CONFLICT',{r for r,_,_ in audit_scene([], [route,collinear],[0,0,100,100])})
        out={**route,'route':[[-5,50],[100,50]]}
        self.assertIn('GRAPHIC_OUT_OF_BOUNDS',{r for r,_,_ in audit_scene([], [out],[0,0,100,100])})
        overlap=[nodes[0],{'id':'second','bbox':[46,36,10,30]}]
        self.assertIn('GRAPHIC_NODE_OVERLAP',{r for r,_,_ in audit_scene(overlap,[],[0,0,100,100])})

    def test_unroutable_dense_crossing_is_a_failure(self):
        ir=graph_deck(['A','B','C','D'],[('A','C'),('A','D'),('B','C'),('B','D')])
        _,issues=compile_deck(ir,ROOT)
        self.assertTrue(any(i['rule']=='GRAPHIC_ROUTE_CONFLICT' and i['severity']=='FAIL' for i in issues))

    def test_mcp_compile_entry(self):
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'deck.json';out=Path(directory)/'build'
            source.write_text(json.dumps(example(),ensure_ascii=False),encoding='utf-8')
            request={'jsonrpc':'2.0','id':1,'method':'tools/call','params':{
                'name':'totalpipe_compile','arguments':{'ir':str(source),'out':str(out),'skip_visual_design':True}}}
            process=subprocess.run([sys.executable,'-X','utf8','-m','deck_compiler.mcp_server'],
                cwd=ROOT,input=json.dumps(request)+'\n',capture_output=True,text=True,encoding='utf-8',timeout=40)
            self.assertEqual(process.returncode,0,process.stderr)
            response=json.loads(process.stdout)['result']
            self.assertFalse(response.get('isError'),response)
            payload=json.loads(response['content'][0]['text'])
            self.assertEqual(payload['counts']['FAIL'],0)
            layout=json.loads((out/'layout.json').read_text(encoding='utf-8'))
            self.assertEqual(len(layout['slides']),4)


@unittest.skipUnless(shutil.which('officecli'),'OfficeCLI executable required')
class DAGNativeExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder=tempfile.TemporaryDirectory()
        cls.path=Path(cls.folder.name)/'dag.pptx'
        cls.layout,issues=compile_deck(example(),ROOT)
        assert not any(i['severity']=='FAIL' for i in issues),issues
        preflight(connectors=True)
        layout_path=Path(cls.folder.name)/'layout.json'
        layout_path.write_text(json.dumps(cls.layout,ensure_ascii=False),encoding='utf-8')
        render(layout_path,cls.path)

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def test_native_identity_references_and_orthogonal_paths(self):
        self.assertFalse(verify(self.path,self.layout))
        with zipfile.ZipFile(self.path) as z:
            for number in (2,3,4):
                root=ET.fromstring(z.read(f'ppt/slides/slide{number}.xml'))
                self.assertFalse(root.findall('.//p:pic',NS))
                nodes={s.find('p:nvSpPr/p:cNvPr',NS).get('id'):s.find('p:nvSpPr/p:cNvPr',NS).get('name')
                       for s in root.findall('p:cSld/p:spTree/p:sp',NS)}
                for connector in root.findall('p:cSld/p:spTree/p:cxnSp',NS):
                    for tag in ('stCxn','endCxn'):
                        ref=connector.find('p:nvCxnSpPr/p:cNvCxnSpPr/a:'+tag,NS)
                        self.assertIn(ref.get('id'),nodes)
                        self.assertIn(':node:',nodes[ref.get('id')])

    def test_native_route_tampering_is_rejected(self):
        output=io.BytesIO()
        with zipfile.ZipFile(self.path) as src,zipfile.ZipFile(output,'w') as dst:
            for item in src.infolist():
                data=src.read(item.filename)
                if item.filename=='ppt/slides/slide4.xml':
                    root=ET.fromstring(data)
                    preset=next(p for p in root.findall('.//p:cxnSp/p:spPr/a:prstGeom',NS)
                                if p.get('prst')=='bentConnector5')
                    preset.find("a:avLst/a:gd[@name='adj2']",NS).set('fmla','val 0')
                    data=ET.tostring(root)
                dst.writestr(item,data)
        issues=verify(io.BytesIO(output.getvalue()),self.layout)
        self.assertIn('CONNECTOR_ROUTE_MISMATCH',{i['rule'] for i in issues})
