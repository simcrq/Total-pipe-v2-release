"""Frames participate in measurement, recursive allocation and native OOXML acceptance."""
import copy
import json
from pathlib import Path
import shutil
import tempfile
import unittest
import zipfile
from lxml import etree as ET

from deck_compiler.container_frames import containment_errors
from deck_compiler.ir import validate
from deck_compiler.layout import compile_deck, geometry_issues
from deck_compiler.layout_tree import capabilities
from deck_compiler.officecli import render
from deck_compiler.structural import verify

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT/'examples/framed-containers.deck_ir.json'
NS = {'a': 'http://schemas.openxmlformats.org/drawingml/2006/main',
      'p': 'http://schemas.openxmlformats.org/presentationml/2006/main'}


def fixture():
    ir = json.loads(EXAMPLE.read_text())
    ir['slides'] = ir['slides'][:1]
    slide = ir['slides'][0]
    slide['composition']['figure_refs'] = []
    ir['assets'] = {}
    panels = slide['composition']['layout_tree']['regions']['body']['children'][0]
    panels['children'][0]['body'] = {'id': 'context-ref', 'type': 'block', 'ref': 'capabilities'}
    slide['composition']['layout_tree']['regions']['body'] = panels
    for block in slide['composition']['blocks']:
        block.update(text_flow='plain', text='各向异性介电响应张量保留完整的空间方向与边界条件。')
        block.pop('bullet_style', None)
        block.pop('bullet_color', None)
    return ir


class ContainerFrameTests(unittest.TestCase):
    def compile_ok(self, ir):
        before = copy.deepcopy(ir)
        layout, issues = compile_deck(ir, EXAMPLE.parent)
        self.assertFalse([i for i in issues if i['severity'] == 'FAIL'], issues)
        self.assertEqual(ir, before)
        self.assertFalse(containment_errors(layout['slides'][0]['elements']))
        return layout, issues

    def test_example_schema_and_stroke_bounded_native_frames(self):
        import jsonschema
        ir = json.loads(EXAMPLE.read_text())
        jsonschema.validate(ir, json.loads((ROOT/'schemas/deck-ir.schema.json').read_text()))
        layout, issues = self.compile_ok(ir)
        self.assertFalse([i for i in issues if i['rule'] == 'FRAME_EXPANDED_FOR_TERMS'])
        for slide in layout['slides']:
            self.assertFalse(containment_errors(slide['elements']))
            self.assertTrue(any(e.get('container_frame') for e in slide['elements']))
            plan = next(a for a in slide['adaptation_log'] if a['action'] == 'layout_tree')
            for node in plan['nodes']:
                if not node.get('frame'): continue
                frame = next(e for e in slide['elements'] if e['id'] == 'region:'+node['node_id']+':frame')
                self.assertEqual(node['bbox'], node['frame_bbox'])
                self.assertAlmostEqual(frame['bbox'][0]-frame['line_width']/2, node['bbox'][0])
                self.assertGreater(len(frame['frame_members']), 1)

    def test_styles_are_opt_in_and_old_trees_keep_geometry(self):
        ir = fixture()
        for node in ir['slides'][0]['composition']['layout_tree']['regions']['body']['children']:
            node.pop('frame')
        ir['slides'][0]['presentation'].pop('takeaway_frame')
        layouts = []
        for version in ('1.0', '1.1', '1.2'):
            ir['slides'][0]['composition']['layout_tree']['version'] = version
            layout, _ = self.compile_ok(ir)
            self.assertFalse(any(e.get('container_frame') for e in layout['slides'][0]['elements']))
            layouts.append([(e['id'], e['bbox']) for e in layout['slides'][0]['elements']])
        self.assertEqual(layouts[0], layouts[1])
        self.assertEqual(layouts[1], layouts[2])

    def test_padding_and_outline_are_deducted_before_leaf_measurement(self):
        layout, _ = self.compile_ok(fixture())
        plan = next(a for a in layout['slides'][0]['adaptation_log'] if a['action'] == 'layout_tree')
        panel = next(n for n in plan['nodes'] if n['node_id'] == 'evidence-panel')
        leaf = next(n for n in plan['nodes'] if n['node_id'] == 'context-ref')
        self.assertAlmostEqual(panel['bbox'][2]-leaf['bbox'][2], 2*(12+1.5))
        self.assertGreater(leaf['bbox'][1], panel['title_band_bbox'][1]+panel['title_band_bbox'][3])

    def test_takeaway_frame_is_independent_of_optional_marker_and_moves_body(self):
        ir = fixture()
        slide = ir['slides'][0]
        slide['presentation'].pop('takeaway_marker')
        slide['semantic']['takeaway'] = '各向异性介电响应张量及其非线性耦合边界条件。'*6
        layout, _ = self.compile_ok(ir)
        elements = layout['slides'][0]['elements']
        text = next(e for e in elements if e['id'] == 'takeaway')
        self.assertNotIn('bullet', text)
        self.assertEqual(text['source_text'], slide['semantic']['takeaway'])
        plan = next(a for a in layout['slides'][0]['adaptation_log'] if a['action'] == 'takeaway_frame')
        tree = next(a for a in layout['slides'][0]['adaptation_log'] if a['action'] == 'layout_tree')
        self.assertGreaterEqual(tree['regions']['body'][1], plan['bbox'][1]+plan['bbox'][3]+20-.1)
        self.assertGreater(plan['bbox'][3], 70)

    def test_inline_math_uses_reduced_inner_width_and_keeps_native_xml(self):
        ir = fixture()
        slide = ir['slides'][0]
        slide['semantic'].update(takeaway='在 \\(x>0\\) 时，保留 \\(q(x)=\\sqrt{1+x^2}\\) 的完整定义。', inline_math=['takeaway'])
        layout, _ = self.compile_ok(ir)
        text = next(e for e in layout['slides'][0]['elements'] if e['id'] == 'takeaway')
        self.assertIn('<m:rad', text['inline_xml'])
        self.assertEqual(text['inline_xml'].count('<a:buChar'), 1)
        for line in text['inline_layout']['lines']:
            self.assertLessEqual(line['width'], text['bbox'][2]-text['bullet']['gutter']+.1)

    def test_geometry_changes_move_the_frame_and_content_together(self):
        ir = fixture()
        first, _ = self.compile_ok(ir)
        ir['slides'][0]['composition']['layout_tree']['regions']['body']['weights'] = [1, 2]
        second, _ = self.compile_ok(ir)
        a = next(e for e in first['slides'][0]['elements'] if e['id'] == 'region:evidence-panel:frame')
        b = next(e for e in second['slides'][0]['elements'] if e['id'] == a['id'])
        self.assertLess(b['bbox'][2], a['bbox'][2])
        self.assertFalse(containment_errors(second['slides'][0]['elements']))

    def test_full_title_and_border_expand_under_preserve_terms(self):
        ir = fixture()
        panel = ir['slides'][0]['composition']['layout_tree']['regions']['body']['children'][0]
        panel['title'] = '各向异性介电响应张量及其非线性耦合边界条件'*30
        layout, issues = self.compile_ok(ir)
        frame = next(e for e in layout['slides'][0]['elements'] if e['id'] == 'region:evidence-panel:frame')
        title = next(e for e in layout['slides'][0]['elements'] if e['id'] == 'region:evidence-panel:title')
        self.assertEqual(title['source_text'], panel['title'])
        self.assertIn('scientific_text_overflow', frame)
        self.assertIn('FRAME_EXPANDED_FOR_TERMS', [i['rule'] for i in issues])
        self.assertFalse([i for i in issues if i['severity'] == 'FAIL'])

    def test_strict_oversized_title_fails_instead_of_clipping(self):
        ir = fixture()
        ir['presentation']['text_capacity_policy'] = 'strict'
        ir['slides'][0]['composition']['layout_tree']['regions']['body']['children'][0]['title'] *= 80
        layout, issues = compile_deck(ir, EXAMPLE.parent)
        self.assertTrue([i for i in issues if i['severity'] == 'FAIL'])
        self.assertFalse(any(e.get('layout_component') for e in layout['slides'][0]['elements']))

    def test_frame_overlap_exemption_does_not_hide_unrelated_content(self):
        layout, _ = self.compile_ok(fixture())
        elements = layout['slides'][0]['elements']
        frame = next(e for e in elements if e.get('container_frame') and e['id'].startswith('region:'))
        alien = {'id': 'unrelated', 'kind': 'shape', 'role': 'body',
                 'bbox': [frame['bbox'][0]+4, frame['bbox'][1]+4, 10, 10]}
        findings = geometry_issues([frame, alien], 1)
        self.assertIn('CRITICAL_COLLISION', [i['rule'] for i in findings])

    def test_malformed_styles_and_old_version_frames_are_rejected(self):
        import jsonschema
        schema = json.loads((ROOT/'schemas/deck-ir.schema.json').read_text())
        for mutation in ('color', 'width', 'boolean', 'geometry', 'legacy', 'takeaway-title', 'missing-border'):
            with self.subTest(mutation=mutation):
                ir = fixture()
                tree = ir['slides'][0]['composition']['layout_tree']
                style = tree['regions']['body']['children'][0]['frame']
                if mutation == 'color': style['border']['color'] = 'blue'
                if mutation == 'width': style['border']['width'] = 100
                if mutation == 'boolean': style['border']['width'] = True
                if mutation == 'geometry': style['bbox'] = [0, 0, 100, 100]
                if mutation == 'legacy': tree['version'] = '1.1'
                if mutation == 'takeaway-title': ir['slides'][0]['presentation']['takeaway_frame']['title_fill'] = '#FFFFFF'
                if mutation == 'missing-border': style.pop('border')
                self.assertTrue([i for i in validate(ir) if i['severity'] == 'FAIL'])
                with self.assertRaises(jsonschema.ValidationError): jsonschema.validate(ir, schema)

    def test_capability_declares_frames_and_all_supported_versions(self):
        value = capabilities()
        self.assertEqual(value['supported_versions'], ['1.0', '1.1', '1.2'])
        self.assertEqual(value['container_frames']['panel']['min_tree_version'], '1.2')

    def test_legacy_header_variants_reserve_the_measured_takeaway_frame(self):
        for variant in ('default', 'spacious', 'template'):
            with self.subTest(variant=variant):
                ir = fixture()
                ir['presentation'].pop('academic_design')
                ir['presentation']['frame_variant'] = variant
                layout, _ = self.compile_ok(ir)
                log = layout['slides'][0]['adaptation_log']
                frame = next(a for a in log if a['action'] == 'takeaway_frame')
                tree = next(a for a in log if a['action'] == 'layout_tree')
                self.assertGreaterEqual(tree['regions']['body'][1], frame['bbox'][1]+frame['bbox'][3]+20-.1)

    def test_native_flowchart_and_bezier_keep_their_local_regions_in_frames(self):
        from deck_compiler.layout_tree import walk
        ir = json.loads((ROOT/'examples/composite-layout.deck_ir.json').read_text())
        ir['slides'] = [ir['slides'][1]]
        tree = ir['slides'][0]['composition']['layout_tree']
        tree['version'] = '1.2'
        for _, node in walk(tree):
            if node['type'] == 'panel':
                node.update(frame={'border': {'color': '#A7B5C5', 'width': 1}}, padding='compact')
        layout, _ = self.compile_ok(ir)
        elements = layout['slides'][0]['elements']
        self.assertTrue(any(e['kind'] == 'connector' for e in elements))
        ir = json.loads((ROOT/'examples/composite-layout.deck_ir.json').read_text())
        ir['slides'] = ir['slides'][:1]
        comp = ir['slides'][0]['composition']
        comp['blocks'], comp['figure_refs'] = [], []
        comp['layout_tree'] = {'version': '1.2', 'regions': {'body': {
            'id': 'curve-panel', 'type': 'panel', 'title': '原生贝塞尔曲线', 'padding': 'compact',
            'frame': {'border': {'color': '#A7B5C5', 'width': 1}},
            'body': {'id': 'curve-ref', 'type': 'graphic', 'ref': 'curve'}}}}
        layout, _ = self.compile_ok(ir)
        self.assertTrue(any(e.get('custom_geometry') for e in layout['slides'][0]['elements']))

    def test_native_table_and_display_equation_coexist_with_a_frame(self):
        ir = fixture()
        slide = ir['slides'][0]
        comp = slide['composition']
        comp['blocks'] = [{'id': 'matrix', 'component': 'formula', 'text': r'A=\begin{bmatrix}1&0\\0&\sqrt{x^2+1}\end{bmatrix}'}]
        comp['tables'] = [{'id': 'measurements', 'row_count': 1, 'column_count': 2, 'origin': 'generated',
                          'cells': [{'id': 'term', 'row': 0, 'column': 0, 'text': '各向异性介电响应张量'},
                                    {'id': 'value', 'row': 0, 'column': 1, 'text': '1.25 nm'}]}]
        comp['layout_tree']['regions']['body'] = {'id': 'math-table-panel', 'type': 'panel', 'title': '矩阵与测量说明',
            'frame': {'border': {'color': '#A7B5C5', 'width': 1}}, 'gap': 'compact',
            'body': {'id': 'math-table-stack', 'type': 'stack', 'gap': 'compact', 'children': [
                {'id': 'equation-ref', 'type': 'block', 'ref': 'matrix'},
                {'id': 'table-ref', 'type': 'table', 'ref': 'measurements'}]}}
        layout, _ = self.compile_ok(ir)
        self.assertTrue(any(e['kind'] == 'math' and '<m:m>' in e['omml'] for e in layout['slides'][0]['elements']))
        self.assertTrue(any(e['kind'] == 'table' for e in layout['slides'][0]['elements']))

    @unittest.skipUnless(shutil.which('officecli'), 'OfficeCLI native writer unavailable')
    def test_native_roundtrip_and_frame_geometry_color_and_layer_tampering(self):
        layout, _ = self.compile_ok(fixture())
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root/'layout.json').write_text(json.dumps(layout))
            render(root/'layout.json', root/'candidate.pptx', shutil.which('officecli'))
            self.assertFalse([i for i in verify(root/'candidate.pptx', layout) if i['severity'] == 'FAIL'])
            with zipfile.ZipFile(root/'candidate.pptx') as z:
                source = {name: z.read(name) for name in z.namelist()}
            for mutation, rule in [('color', 'GRAPHIC_STYLE_MISMATCH'), ('width', 'GRAPHIC_STYLE_MISMATCH'),
                                   ('outside', 'FRAME_CONTENT_OUT_OF_BOUNDS'), ('order', 'FRAME_LAYER_ORDER')]:
                parts = dict(source)
                slide = ET.fromstring(parts['ppt/slides/slide1.xml'])
                shapes = {s.find('p:nvSpPr/p:cNvPr', NS).get('name'): s for s in slide.findall('.//p:sp', NS)}
                frame = shapes['region:evidence-panel:frame']
                if mutation == 'color': frame.find('p:spPr/a:ln/a:solidFill/a:srgbClr', NS).set('val', 'FF0000')
                if mutation == 'width': frame.find('p:spPr/a:ln', NS).set('w', '95250')
                if mutation == 'outside': shapes['capabilities'].find('p:spPr/a:xfrm/a:off', NS).set('x', '11000000')
                if mutation == 'order': frame.getparent().append(frame)
                parts['ppt/slides/slide1.xml'] = ET.tostring(slide)
                output = root/(mutation+'.pptx')
                with zipfile.ZipFile(output, 'w') as z:
                    for name, content in parts.items(): z.writestr(name, content)
                self.assertIn(rule, [i['rule'] for i in verify(output, layout)], mutation)


if __name__ == '__main__':
    unittest.main()
