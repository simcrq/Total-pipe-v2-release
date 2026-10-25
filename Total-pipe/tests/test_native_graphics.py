"""Graphic content, layout, and the actual native objects emitted by OfficeCLI."""
import copy
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest
import zipfile
from lxml import etree as ET

from deck_compiler.graphic_layout import compile_graphic, intentional_overlap, SHAPES
from deck_compiler.ir import validate
from deck_compiler.layout import compile_deck, intersect
from deck_compiler.layout_provider import compile_with_provider, PackerProvider
from deck_compiler.officecli import preflight, render
from deck_compiler.structural import verify
from deck_compiler.ooxml import NS

ROOT = Path(__file__).resolve().parents[1]


def fixture():
    return json.loads((ROOT/'examples/native-graphic.deck_ir.json').read_text(encoding='utf-8'))


def graphic(ir):
    return ir['slides'][0]['composition']['graphics'][0]


class GraphicTests(unittest.TestCase):
    def assert_valid(self, ir):
        self.assertFalse([i for i in validate(ir) if i['severity'] == 'FAIL'])

    def test_valid_old_and_new_ir(self):
        self.assert_valid(fixture())
        self.assert_valid(json.loads((ROOT/'examples/research.deck_ir.json').read_text(encoding='utf-8')))

    def test_invalid_graphic_content_is_rejected(self):
        mutations = {
            'duplicate node': lambda g: g['nodes'][1].update(id='input'),
            'unknown endpoint': lambda g: g['edges'][0].update(to='missing'),
            'unsupported shape': lambda g: g['nodes'][0].update(shape='cloud'),
            'wrong shape type': lambda g: g['nodes'][0].update(shape=[]),
            'coordinates': lambda g: g['nodes'][0].update(x=50),
            'unsafe id': lambda g: g['nodes'][0].update(id="bad'id"),
            'blank title': lambda g: g['nodes'][0].update(title='  '),
            'title too long': lambda g: g['nodes'][0].update(title='x'*81),
            'body too long': lambda g: g['nodes'][0].update(body='x'*181),
            'unsupported direction': lambda g: g.update(direction='diagonal'),
            'unsupported type': lambda g: g.update(type='cycle'),
            'too few nodes': lambda g: g.update(nodes=g['nodes'][:2]),
            'backward edge': lambda g: g['edges'][0].update(**{'from': 'check', 'to': 'input'}),
            'duplicate edge': lambda g: g['edges'].append(g['edges'][0]),
            'missing edge': lambda g: g['edges'].pop(),
            'unsupported edge': lambda g: g['edges'][0].update(kind='curve'),
            'missing nodes': lambda g: g.update(nodes=None),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                ir = fixture()
                mutate(graphic(ir))
                self.assertTrue(any(i['rule'] == 'GRAPHIC_INVALID' for i in validate(ir)))
                self.assertIsNone(compile_deck(ir, ROOT)[0])

    def test_graphics_cannot_be_silently_ignored(self):
        for value in (None, {}, [], [graphic(fixture()), graphic(fixture())]):
            ir = fixture()
            ir['slides'][0]['composition']['graphics'] = value
            self.assertTrue(any(i['rule'] == 'GRAPHIC_INVALID' for i in validate(ir)))
        ir = fixture()
        ir['slides'][0]['composition']['archetype'] = 'cover-hero'
        self.assertTrue(any(i['rule'] == 'GRAPHIC_INVALID' for i in validate(ir)))
        ir = fixture()
        ir['slides'][0]['composition']['blocks'] = [{'id': 'body', 'component': 'body', 'text': 'extra'}]
        self.assertTrue(any(i['severity'] == 'FAIL' for i in validate(ir)))

    def test_deterministic_layout_preserves_content(self):
        ir = fixture()
        before = copy.deepcopy(ir)
        layout, issues = compile_deck(ir, ROOT)
        self.assertFalse([i for i in issues if i['severity'] == 'FAIL'], issues)
        self.assertEqual((layout, issues), compile_deck(ir, ROOT))
        self.assertEqual(ir, before)
        for slide, page in zip(ir['slides'], layout['slides']):
            g = slide['composition']['graphics'][0]
            labels = [e for e in page['elements'] if e.get('graphic_id') and e['kind'] == 'text']
            self.assertEqual([e['source_text'] for e in labels],
                             [node[key] for node in g['nodes'] for key in ('title', 'body')])
            self.assertTrue(all(e['contract']['font_size'] >= 24 for e in labels))
            self.assertTrue(all(e['align'] == 'center' for e in labels))

    def test_all_five_presets_and_native_connectors(self):
        layout, _ = compile_deck(fixture(), ROOT)
        self.assertEqual({e['geometry'] for page in layout['slides'] for e in page['elements']
                          if e.get('role') == 'graphic-node'}, set(SHAPES.values()))
        self.assertEqual(sum(e.get('role') == 'graphic-edge' for page in layout['slides']
                             for e in page['elements']), 5)
        self.assertFalse(any(e['kind'] == 'image' for page in layout['slides'] for e in page['elements']))
        edges = [e for page in layout['slides'] for e in page['elements'] if e['kind'] == 'connector']
        self.assertEqual([(e['start_site'], e['end_site']) for e in edges],
                         [(6, 1), (3, 1), (3, 1), (3, 3), (0, 2)])
        for e in edges:
            self.assertEqual(e['start'][1], e['end'][1])
            self.assertEqual(e['bbox'], [*e['start'], e['end'][0]-e['start'][0], 0])
            self.assertEqual((e['head_end'], e['tail_end']), ('none', 'triangle'))

    def test_vertical_process_flows_top_down(self):
        ir = fixture()
        ir['slides'] = [ir['slides'][0]]
        g = graphic(ir)
        g['direction'] = 'vertical'
        g.pop('layout', None)
        for node in g['nodes']:
            node.pop('body', None)
            node['shape'] = 'rounded-rect'
        layout, issues = compile_deck(ir, ROOT)
        self.assertFalse([i for i in issues if i['severity'] == 'FAIL'], issues)
        nodes = [e for e in layout['slides'][0]['elements'] if e.get('role') == 'graphic-node']
        self.assertEqual(len(nodes), 3)
        self.assertLess(nodes[0]['bbox'][1], nodes[1]['bbox'][1])
        self.assertLess(nodes[1]['bbox'][1], nodes[2]['bbox'][1])
        edges = [e for e in layout['slides'][0]['elements'] if e.get('role') == 'graphic-edge']
        for edge in edges:
            self.assertAlmostEqual(edge['start'][0], edge['end'][0])
            self.assertGreater(edge['end'][1], edge['start'][1])

    def test_staggered_process_alternates_nodes_and_keeps_diagonal_edges(self):
        ir = fixture()
        ir['slides'] = [ir['slides'][1]]
        g = graphic(ir)
        g['layout'] = 'staggered'
        layout, issues = compile_deck(ir, ROOT)
        self.assertFalse([i for i in issues if i['severity'] == 'FAIL'], issues)
        nodes = [e for e in layout['slides'][0]['elements'] if e.get('role') == 'graphic-node']
        self.assertEqual(len(nodes), 4)
        self.assertNotEqual(nodes[0]['bbox'][1], nodes[1]['bbox'][1])
        self.assertNotEqual(nodes[1]['bbox'][1], nodes[2]['bbox'][1])
        edges = [e for e in layout['slides'][0]['elements'] if e.get('role') == 'graphic-edge']
        self.assertTrue(all(edge['bbox'][3] > 0 for edge in edges))

    def test_process_layout_rejects_incompatible_combinations_and_tones(self):
        for name, mutate in {
            'vertical staggered': lambda g: g.update(direction='vertical', layout='staggered'),
            'dag staggered': lambda g: g.update(type='dag', layout='staggered'),
            'unknown tone': lambda g: g['nodes'][0].update(tone='bold'),
        }.items():
            with self.subTest(name=name):
                ir = fixture()
                mutate(graphic(ir))
                self.assertTrue(any(i['rule'] == 'GRAPHIC_INVALID' for i in validate(ir)))

    def test_emphasis_tone_changes_only_the_node_fill_and_rule(self):
        plain = fixture()
        plain_layout, _ = compile_deck(plain, ROOT)
        plain_node = next(e for e in plain_layout['slides'][0]['elements']
                          if e.get('role') == 'graphic-node')
        emphasised = copy.deepcopy(plain)
        graphic(emphasised)['nodes'][0]['tone'] = 'emphasis'
        emphasised_layout, issues = compile_deck(emphasised, ROOT)
        self.assertFalse([i for i in issues if i['severity'] == 'FAIL'], issues)
        strong_node = next(e for e in emphasised_layout['slides'][0]['elements']
                           if e.get('role') == 'graphic-node')
        self.assertNotEqual(plain_node['fill'], strong_node['fill'])
        self.assertGreater(strong_node['line_width'], plain_node['line_width'])

    def test_no_unintended_overlap_or_out_of_bounds(self):
        layout, _ = compile_deck(fixture(), ROOT)
        for page in layout['slides']:
            elements = page['elements']
            for index, e in enumerate(elements):
                x, y, w, h = e['bbox']
                self.assertTrue(x >= 0 and y >= 0 and w > 0 and
                                (h >= 0 if e['kind'] == 'connector' else h > 0) and x+w <= 1280 and y+h <= 720)
                for other in elements[:index]:
                    if not intentional_overlap(e, other):
                        self.assertFalse(intersect(e['bbox'], other['bbox']), (e['id'], other['id']))

    def test_small_regions_and_long_labels_fail_without_losing_text(self):
        with self.assertRaises(ValueError):
            compile_graphic(graphic(fixture()), [0, 0, 500, 180], fixture()['theme'])
        ir = fixture()
        ir['slides'] = ir['slides'][1:]
        node = graphic(ir)['nodes'][2]
        node['shape'] = 'diamond'
        node['title'] = '密'*80
        before = copy.deepcopy(ir)
        _, issues = compile_deck(ir, ROOT)
        self.assertTrue(any(i['rule'] == 'SPLIT_REQUIRED' and i['severity'] == 'FAIL' for i in issues))
        self.assertEqual(ir, before)

    def test_label_only_and_shared_node_ids_on_different_pages(self):
        ir = fixture()
        ir['slides'] = [ir['slides'][0], copy.deepcopy(ir['slides'][0])]
        ir['slides'][1]['id'] = 'second'
        for page in ir['slides']:
            for node in page['composition']['graphics'][0]['nodes']:
                node.pop('body')
        layout, issues = compile_deck(ir, ROOT)
        self.assertFalse([i for i in issues if i['severity'] == 'FAIL'])
        self.assertEqual(len([e for e in layout['slides'][0]['elements']
                              if e.get('graphic_id') and e['kind'] == 'text']), 3)

    def test_default_packer_and_legacy_slides_coexist(self):
        ir = fixture()
        old = json.loads((ROOT/'examples/research.deck_ir.json').read_text(encoding='utf-8'))
        ir['slides'].append(old['slides'][0])
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'deck_ir.json'
            path.write_text(json.dumps(ir, ensure_ascii=False), encoding='utf-8')
            layout, issues = compile_with_provider(path, PackerProvider())
        self.assertFalse([i for i in issues if i['severity'] == 'FAIL'], issues)
        self.assertEqual(len(layout['slides']), 3)
        self.assertEqual(len(layout['slides'][0]['elements']), 13)


@unittest.skipUnless(shutil.which('officecli'), 'OfficeCLI executable required')
class NativeGraphicExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        cls.path = Path(cls.folder.name)/'graphic.pptx'
        ir = fixture()
        old = json.loads((ROOT/'examples/research.deck_ir.json').read_text(encoding='utf-8'))
        old['slides'][0]['composition']['blocks'][0]['id'] = 'graphic:legacy'
        ir['slides'].append(old['slides'][0])
        cls.layout, issues = compile_deck(ir, ROOT)
        assert not any(i['severity'] == 'FAIL' for i in issues), issues
        cls.runtime = preflight(connectors=True)
        lp = Path(cls.folder.name)/'layout.json'
        lp.write_text(json.dumps(cls.layout, ensure_ascii=False), encoding='utf-8')
        render(lp, cls.path)

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def test_real_pptx_passes_structure_and_has_no_graphic_images(self):
        self.assertFalse(verify(self.path, self.layout))
        with zipfile.ZipFile(self.path) as z:
            for number in (1, 2):
                root = ET.fromstring(z.read(f'ppt/slides/slide{number}.xml'))
                self.assertFalse(root.findall('.//p:pic', NS))
                count = len([e for e in self.layout['slides'][number-1]['elements'] if e.get('graphic_id')])
                shapes = [s for s in root.findall('p:cSld/p:spTree/p:sp', NS)
                          if s.find('p:nvSpPr/p:cNvPr', NS).get('name', '').startswith('graphic:')]
                connectors = root.findall('p:cSld/p:spTree/p:cxnSp', NS)
                self.assertEqual(len(connectors), number+1)
                self.assertEqual(len(shapes)+len(connectors), count)
                self.assertFalse(any(s.find('p:spPr/a:prstGeom', NS).get('prst') == 'rightArrow' for s in shapes
                                     if s.find('p:spPr/a:prstGeom', NS) is not None))

    def test_tampering_with_native_objects_is_detected(self):
        def change(pptx, mutate, connector=False):
            output = io.BytesIO()
            with zipfile.ZipFile(pptx) as src, zipfile.ZipFile(output, 'w') as dst:
                for item in src.infolist():
                    data = src.read(item.filename)
                    if item.filename == 'ppt/slides/slide1.xml':
                        root = ET.fromstring(data)
                        if connector:
                            shape = root.find('p:cSld/p:spTree/p:cxnSp', NS)
                        else:
                            shapes = root.findall('p:cSld/p:spTree/p:sp', NS)
                            shape = next(s for s in shapes if s.find('p:nvSpPr/p:cNvPr', NS).get('name') ==
                                         'graphic:data-process:node:input')
                        mutate(shape)
                        data = ET.tostring(root)
                    dst.writestr(item, data)
            return io.BytesIO(output.getvalue())

        cases = [
            ('GRAPHIC_PRESET_MISMATCH', lambda s: s.find('p:spPr/a:prstGeom', NS).set('prst', 'rect')),
            ('GRAPHIC_STYLE_MISMATCH', lambda s: s.find('p:spPr/a:solidFill/a:srgbClr', NS).set('val', 'FF0000')),
            ('GEOMETRY_MISMATCH', lambda s: s.find('p:spPr/a:xfrm/a:off', NS).set('x', '0')),
            ('GRAPHIC_OBJECT_MISMATCH', lambda s: s.getparent().append(copy.deepcopy(s))),
            ('MISSING_SHAPE', lambda s: s.getparent().remove(s)),
        ]
        for rule, mutate in cases:
            with self.subTest(rule=rule):
                findings = verify(change(self.path, mutate), self.layout)
                self.assertTrue(any(i['rule'] == rule for i in findings), findings)

        def floating_arrow(c):
            root = c.getparent()
            arrow = copy.deepcopy(root.find('p:sp', NS))
            arrow.find('p:nvSpPr/p:cNvPr', NS).set('name', c.find('p:nvCxnSpPr/p:cNvPr', NS).get('name'))
            root.remove(c)
            root.append(arrow)

        cases = [
            ('CONNECTOR_MISSING', floating_arrow),
            ('CONNECTOR_REFERENCE_INVALID', lambda c: c.find('p:nvCxnSpPr/p:cNvCxnSpPr/a:stCxn', NS).set('id', '999999')),
            ('CONNECTOR_REFERENCE_INVALID', lambda c: c.find('p:nvCxnSpPr/p:cNvCxnSpPr', NS).remove(
                c.find('p:nvCxnSpPr/p:cNvCxnSpPr/a:stCxn', NS))),
            ('CONNECTOR_BINDING_MISMATCH', lambda c: c.find('p:nvCxnSpPr/p:cNvCxnSpPr/a:endCxn', NS).set('idx', '0')),
            ('CONNECTOR_DIRECTION_MISMATCH', lambda c: c.find('p:spPr/a:ln/a:tailEnd', NS).set('type', 'none')),
            ('CONNECTOR_STYLE_MISMATCH', lambda c: c.find('p:spPr/a:ln/a:solidFill/a:srgbClr', NS).set('val', 'FF0000')),
            ('GRAPHIC_ID_COLLISION', lambda c: c.find('p:nvCxnSpPr/p:cNvPr', NS).set('id', '1')),
            ('CONNECTOR_COUNT_MISMATCH', lambda c: c.getparent().remove(c)),
        ]
        for rule, mutate in cases:
            with self.subTest(rule=rule):
                findings = verify(change(self.path, mutate, connector=True), self.layout)
                self.assertTrue(any(i['rule'] == rule for i in findings), findings)


if __name__ == '__main__':
    unittest.main()
