"""Semantic grids remain editable native tables, including merged headers and OMML cells."""
import copy
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import zipfile

from lxml import etree as ET

from deck_compiler.ir import validate
from deck_compiler.layout import compile_deck, break_lines
from deck_compiler.layout_tree import LayoutTreeError, capabilities
from deck_compiler.native_table import compile_table, measure_table, validate_tables
from deck_compiler.officecli import commands, render
from deck_compiler.pipeline import write_json
from deck_compiler.structural import MATH_NS, verify

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT/'examples/native-table.deck_ir.json'


def fixture():
    return json.loads(EXAMPLE.read_text())


def font_paths(layout):
    elements = layout['slides'][0]['elements']
    return {key: next(e['contract']['font_file'] for e in elements if e['role'] == role)
            for key, role in (('font_file', 'takeaway'), ('bold_font_file', 'title'))}


class NativeTableTests(unittest.TestCase):
    def compile_ok(self, ir=None):
        ir = ir or fixture()
        before = copy.deepcopy(ir)
        layout, items = compile_deck(ir, EXAMPLE.parent)
        self.assertFalse([i for i in items if i['severity'] == 'FAIL'], items)
        self.assertEqual(ir, before)
        return layout, items

    def test_schema_and_table_contract_preserve_legacy_tree_version(self):
        import jsonschema
        ir = fixture()
        schema = json.loads((ROOT/'schemas/deck-ir.schema.json').read_text())
        jsonschema.validate(ir, schema)
        self.assertEqual(capabilities()['supported_versions'], ['1.0', '1.1'])
        ir['slides'][0]['composition']['layout_tree']['version'] = '1.0'
        self.assertIn('LAYOUT_TREE_INVALID', [i['rule'] for i in validate(ir)])
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(ir, schema)

    def test_full_merged_grid_validates_but_overlap_missing_and_outside_reject(self):
        table = fixture()['slides'][0]['composition']['tables'][0]
        self.assertEqual(validate_tables([table], []), [])
        for mutation in ('overlap', 'missing', 'outside', 'geometry', 'duplicate', 'weights', 'bool'):
            with self.subTest(mutation=mutation):
                bad = copy.deepcopy(table)
                if mutation == 'overlap': bad['cells'][1]['column'] = 0
                if mutation == 'missing': bad['cells'].pop()
                if mutation == 'outside': bad['cells'][0]['row_span'] = 50
                if mutation == 'geometry': bad['cells'][0]['width'] = 400
                if mutation == 'duplicate': bad['cells'][1]['id'] = bad['cells'][0]['id']
                if mutation == 'weights': bad['column_weights'] = [1, 2]
                if mutation == 'bool': bad['cells'][0]['row'] = False
                self.assertTrue(validate_tables([bad], []))

    def test_source_evidence_and_formula_syntax_are_mandatory(self):
        table = fixture()['slides'][0]['composition']['tables'][0]
        table['origin'] = 'paper'
        self.assertTrue(validate_tables([table], ['EV1']))
        table['evidence_refs'] = ['EV1']
        self.assertFalse(validate_tables([table], ['EV1']))
        self.assertTrue(validate_tables([table], ['EV2']))
        table['cells'][6]['text'] = r'\unknown{x}'
        self.assertTrue(validate_tables([table], ['EV1']))

    def test_native_xml_has_all_logical_cells_merges_and_matrix_math(self):
        layout, items = self.compile_ok()
        table = next(e for e in layout['slides'][0]['elements'] if e['kind'] == 'table')
        root = ET.fromstring(table['table_xml'])
        rows = root.findall('a:tr', MATH_NS)
        self.assertEqual([len(r.findall('a:tc', MATH_NS)) for r in rows], [4]*4)
        self.assertEqual(rows[0][0].get('rowSpan'), '2')
        self.assertEqual(rows[1][0].get('vMerge'), '1')
        self.assertEqual(rows[0][1].get('gridSpan'), '2')
        self.assertEqual(rows[0][2].get('hMerge'), '1')
        self.assertEqual(len(root.findall('.//m:m', MATH_NS)), 2)
        self.assertEqual(len(root.findall('.//m:oMath', MATH_NS)), 4)
        self.assertTrue(all(c.get('anchor') == 'ctr' for c in root.findall('.//a:tcPr', MATH_NS)))
        self.assertIn('FORMULA_MEASURE_APPROXIMATE', [i['rule'] for i in items])
        self.assertGreaterEqual(table['font_size_px'], 24)
        batch = commands(layout)
        self.assertEqual(sum(c.get('type') == 'table' for c in batch), 2)
        self.assertTrue(any(c.get('command') == 'raw-set' and c.get('xml') == table['table_xml'] for c in batch))

    def test_two_dimensional_merge_and_explicit_blank_cell(self):
        table = {'id': 'merged', 'row_count': 2, 'column_count': 3, 'origin': 'generated',
            'cells': [{'id': 'merged-header', 'row': 0, 'column': 0, 'row_span': 2, 'column_span': 2, 'text': '完整合并标题'},
                      {'id': 'right-top', 'row': 0, 'column': 2, 'text': '右列'},
                      {'id': 'blank', 'row': 1, 'column': 2, 'text': ''}]}
        self.assertEqual(validate_tables([table], []), [])
        layout, _ = self.compile_ok()
        result = compile_table(table, [0, 0, 600, 200], font_paths(layout), {'font_family': layout['resolved_font_family']})
        rows = ET.fromstring(result['table_xml']).findall('a:tr', MATH_NS)
        self.assertEqual(rows[0][0].get('rowSpan'), '2')
        self.assertEqual(rows[0][0].get('gridSpan'), '2')
        self.assertEqual(rows[0][1].get('rowSpan'), '2')
        self.assertEqual(rows[1][0].get('gridSpan'), '2')
        self.assertEqual(rows[1][1].get('hMerge'), '1')
        self.assertEqual(rows[1][1].get('vMerge'), '1')
        self.assertEqual(result['cells'][-1]['text'], '')

    def test_transpose_suffix_stays_with_its_scientific_notation(self):
        from deck_compiler.fonts import load_font_file
        layout, _ = self.compile_ok()
        font = load_font_file(font_paths(layout)['font_file'], 28)
        for text in ('改进平方根法（LDLᵀ 分解）', '密度 10³ cm⁻³ 与 α-Al₂O₃'):
            lines = break_lines(text, font, 245)
            self.assertEqual(''.join(lines).replace(' ', ''), text.replace(' ', ''))
            self.assertFalse(any(line.startswith(('ᵀ', '³', '₂', '⁻')) for line in lines), lines)

    def test_exact_references_and_tree_requirement(self):
        for mutation in ('absent-tree', 'duplicate', 'unknown'):
            ir = fixture(); comp = ir['slides'][0]['composition']
            if mutation == 'absent-tree': comp.pop('layout_tree')
            elif mutation == 'unknown': comp['layout_tree']['regions']['body']['ref'] = 'missing'
            else:
                leaf = comp['layout_tree']['regions']['body']
                comp['layout_tree']['regions']['body'] = {'id': 'twice', 'type': 'stack',
                    'children': [leaf, {**leaf, 'id': 'other'}]}
            self.assertTrue([i for i in validate(ir) if i['severity'] == 'FAIL'], mutation)

    def test_measure_uses_complete_text_and_native_formulas_not_source_length(self):
        layout, _ = self.compile_ok()
        table = fixture()['slides'][0]['composition']['tables'][0]
        fonts = font_paths(layout)
        narrow, wide = (measure_table(table, width, fonts) for width in (700, 1168))
        self.assertGreaterEqual(narrow['height'], wide['height'])
        self.assertTrue(any(c.get('measured_exact') is False for c in wide['cells']))
        self.assertEqual({c['id']: c['text'] for c in wide['cells']}, {c['id']: c['text'] for c in table['cells']})
        table['cells'].reverse()
        reordered = measure_table(table, 1168, fonts)
        self.assertEqual(reordered, wide)

    def test_text_only_overflow_preserves_terms_as_review_but_formula_floor_is_hard(self):
        layout, _ = self.compile_ok()
        table = fixture()['slides'][0]['composition']['tables'][0]
        fonts = font_paths(layout); theme = {**fixture()['theme'], 'font_family': layout['resolved_font_family']}
        with self.assertRaises(LayoutTreeError) as caught:
            compile_table(table, [56, 150, 1168, 50], fonts, theme, True)
        self.assertEqual(caught.exception.detail['code'], 'INSUFFICIENT_TABLE_SPACE')
        for cell in table['cells']:
            cell['kind'] = 'text'; cell['text'] = '各向异性介电响应张量与非线性耦合边界条件'*8
        result = compile_table(table, [56, 150, 1168, 50], fonts, theme, True)
        self.assertIn('scientific_text_overflow', result)
        self.assertEqual([c['text'] for c in result['cells']], [c['text'] for c in table['cells']])
        self.assertEqual(result['font_size_px'], 24)
        with self.assertRaises(LayoutTreeError): compile_table(table, [56, 150, 1168, 50], fonts, theme, False)

    def test_native_table_theme_and_formula_alignment(self):
        layout, _ = self.compile_ok(); table = fixture()['slides'][0]['composition']['tables'][0]
        table['cells'][6]['align'] = 'right'
        compiled = compile_table(table, [0, 0, 1168, 460], font_paths(layout),
            {'font_family': layout['resolved_font_family'], 'background': '#142735', 'foreground': '#FFFFFF'})
        root = ET.fromstring(compiled['table_xml'])
        self.assertEqual(root.find('.//m:jc', MATH_NS).get('{'+MATH_NS['m']+'}val'), 'right')
        self.assertEqual(root.findall('a:tr', MATH_NS)[2][0].find('a:tcPr/a:solidFill/a:srgbClr', MATH_NS).get('val'), '142735')

    def test_rpa_automatic_table_composition_compiles_across_language_boundary(self):
        ir = fixture(); comp = ir['slides'][0]['composition']
        request = {'consumer_capabilities': {'layout_tree': capabilities()}, 'groups': [
            {'id': 'table-panel', 'title': '完整科研表格', 'items': [{'kind': 'table', 'ref': 'methods'}]}],
            'content_refs': {'blocks': [], 'figure_count': 0, 'graphics': [], 'tables': [{'id': 'methods', 'has_formulas': True}]}}
        script = 'import {planSublayout} from "./research-ppt-assistant/server/automatic-sublayouts.mjs"; let s=""; for await(const c of process.stdin)s+=c; console.log(JSON.stringify(planSublayout(JSON.parse(s))));'
        process = subprocess.run(['node', '--input-type=module', '-e', script], input=json.dumps(request), text=True,
            capture_output=True, cwd=ROOT.parent, check=True)
        proposal = json.loads(process.stdout)
        self.assertEqual(proposal['status'], 'structure_planned', proposal)
        comp.update(proposal['composition_patch'])
        self.compile_ok(ir)

    @unittest.skipUnless(shutil.which('officecli'), 'OfficeCLI required')
    def test_native_backend_and_corruption_detection(self):
        layout, _ = self.compile_ok()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); path = root/'candidate.pptx'
            write_json(root/'layout.json', layout)
            render(root/'layout.json', path, executable=shutil.which('officecli'))
            self.assertFalse([i for i in verify(path, layout) if i['severity'] == 'FAIL'])
            with zipfile.ZipFile(path) as source:
                parts = {n: source.read(n) for n in source.namelist()}
            slide = ET.fromstring(parts['ppt/slides/slide1.xml'])
            slide.find('.//a:tbl/a:tr/a:tc', MATH_NS).set('rowSpan', '1')
            parts['ppt/slides/slide1.xml'] = ET.tostring(slide)
            with zipfile.ZipFile(root/'corrupt.pptx', 'w') as dest:
                for name, data in parts.items(): dest.writestr(name, data)
            self.assertIn('TABLE_CONTENT_MISMATCH', [i['rule'] for i in verify(root/'corrupt.pptx', layout)])


if __name__ == '__main__':
    unittest.main()
