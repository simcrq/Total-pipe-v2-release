"""Recursive regions reuse the existing scientific content and native renderer gates."""
import copy
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from deck_compiler.contracts import digest
from deck_compiler.ir import validate
from deck_compiler.layout import compile_deck
from deck_compiler.layout_tree import capabilities, validate_tree
from deck_compiler.layout_provider import compile_with_provider
from deck_compiler.pipeline import compile_input

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT/'examples/composite-layout.deck_ir.json'


def fixture():
    return json.loads(EXAMPLE.read_text(encoding='utf-8'))


class LayoutTreeTests(unittest.TestCase):
    def compile_ok(self, ir=None):
        ir = ir or fixture()
        before = copy.deepcopy(ir)
        layout, issues = compile_deck(ir, EXAMPLE.parent)
        self.assertFalse([i for i in issues if i['severity'] == 'FAIL'], issues)
        self.assertEqual(before, ir)
        return layout, issues

    def test_example_schema_and_native_objects(self):
        import jsonschema
        ir = fixture()
        jsonschema.validate(ir, json.loads((ROOT/'schemas/deck-ir.schema.json').read_text()))
        layout, _ = self.compile_ok(ir)
        elements = [e for s in layout['slides'] for e in s['elements']]
        self.assertTrue(any(e['kind'] == 'math' and '<m:m>' in e['omml'] for e in elements))
        self.assertTrue(any(e.get('custom_geometry') for e in elements))
        self.assertTrue(any(e['kind'] == 'connector' for e in elements))
        self.assertEqual(sum(e['kind'] == 'image' for e in elements), 5)

    def test_all_leaves_have_local_region_and_no_clipping(self):
        layout, _ = self.compile_ok()
        for slide in layout['slides']:
            for e in slide['elements']:
                if 'layout_region' not in e:
                    continue
                x, y, w, h = e['bbox']
                rx, ry, rw, rh = e['layout_region']
                self.assertGreaterEqual(x+.1, rx)
                self.assertGreaterEqual(y+.1, ry)
                self.assertLessEqual(x+w, rx+rw+.1)
                self.assertLessEqual(y+h, ry+rh+.1)

    def test_native_typeface_matches_the_measured_cjk_font(self):
        from PIL import ImageFont
        layout, _ = self.compile_ok()
        for slide in layout['slides']:
            for e in slide['elements']:
                if e.get('contract'):
                    face = ImageFont.truetype(e['contract']['font_file'], 24)
                    self.assertEqual(e['contract']['font_family'], layout['resolved_font_family'])
                    self.assertEqual(face.getname()[0], layout['resolved_font_family'])

    def test_missing_duplicate_unknown_and_geometry_references_rejected(self):
        for mutation in ('missing', 'duplicate', 'unknown', 'geometry', 'region', 'version'):
            with self.subTest(mutation=mutation):
                ir = fixture()
                comp = ir['slides'][0]['composition']
                tree = comp['layout_tree']
                rows = tree['regions']['body']['children'][0]['body']['children']
                if mutation == 'missing': rows.pop()
                if mutation == 'duplicate': rows.append(copy.deepcopy(rows[-1]))
                if mutation == 'unknown': rows[-1]['ref'] = 'not-present'
                if mutation == 'geometry': rows[-1]['bbox'] = [0, 0, 1, 1]
                if mutation == 'region': tree['regions']['sidebar'] = tree['regions']['body']
                if mutation == 'version': tree['version'] = '999'
                self.assertTrue(validate_tree(tree, comp))
                self.assertIn('LAYOUT_TREE_INVALID', [i['rule'] for i in validate(ir)])

    def test_depth_weights_and_grid_types_rejected(self):
        for mutation in ('depth', 'weights', 'grid'):
            ir = fixture()
            comp = ir['slides'][0]['composition']
            tree = comp['layout_tree']
            if mutation == 'depth':
                for n in range(7):
                    tree['regions']['body'] = {'id': f'wrapper-{n}', 'type': 'stack', 'children': [tree['regions']['body']]}
            elif mutation == 'weights': tree['regions']['body']['weights'] = [1, float('nan'), 1]
            else: tree['regions']['body']['children'][1]['body']['children'][0]['type'] = 'block'
            self.assertTrue(validate_tree(tree, comp), mutation)
            if mutation == 'depth':
                import jsonschema
                with self.assertRaises(jsonschema.ValidationError):
                    jsonschema.validate(ir, json.loads((ROOT/'schemas/deck-ir.schema.json').read_text()))

    def test_explanation_and_formula_are_one_vertical_group(self):
        ir = fixture()
        rows = ir['slides'][0]['composition']['layout_tree']['regions']['body']['children'][0]['body']['children']
        rows.reverse()
        self.assertTrue(validate_tree(ir['slides'][0]['composition']['layout_tree'], ir['slides'][0]['composition']))

    def test_wide_process_in_three_columns_returns_path_and_sizes_atomically(self):
        ir = fixture()
        slide = ir['slides'][1]
        slide['composition']['layout_tree']['regions']['body']['weights'] = [1, 2.5]
        ir['slides'] = [slide]
        layout, issues = compile_deck(ir, EXAMPLE.parent)
        error = next(i for i in issues if i['rule'] == 'INSUFFICIENT_DRAWING_SPACE')
        self.assertEqual(error['source']['component'], 'body.children[0].body')
        self.assertGreaterEqual(error['source']['required_size_px'][0], 728)
        self.assertLess(error['source']['available_size_px'][0], 374)
        self.assertTrue(error['source']['suggested_actions'])
        self.assertFalse(any(e.get('layout_component') for e in layout['slides'][0]['elements']))

    def test_compiler_owns_tree_pages_even_with_external_packer(self):
        class Provider:
            name = 'observation'
            def propose(self, requests):
                self.requests = requests
                return {}
        provider = Provider()
        layout, issues = compile_with_provider(EXAMPLE, provider, ROOT)
        self.assertFalse([i for i in issues if i['severity'] == 'FAIL'])
        self.assertFalse(hasattr(provider, 'requests'))
        self.assertTrue(all(r['reason'] == 'recursive_regions' for r in layout['layout_provider']['slides']))

    def test_feedback_is_sha_bound_and_replaces_previous_success(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            ir = fixture()
            for asset in ir['assets'].values():
                asset['path'] = str((EXAMPLE.parent/asset['path']).resolve())
            source = root/'input.json'
            source.write_text(json.dumps(ir))
            compile_input(source, root)
            self.assertTrue((root/'layout.json').is_file())
            ir['slides'][0]['composition']['layout_tree']['regions']['extra'] = {}
            source.write_text(json.dumps(ir))
            _, layout, qa = compile_input(source, root)
            self.assertIsNone(layout)
            self.assertFalse((root/'layout.json').exists())
            feedback = json.loads((root/'layout_feedback.json').read_text())
            import jsonschema
            jsonschema.validate(feedback, json.loads((ROOT/'schemas/layout-feedback.schema.json').read_text()))
            self.assertEqual(feedback['ir_sha256'], digest(ir))
            self.assertEqual(feedback['slides'][0]['status'], 'layout_failed')
            self.assertEqual(feedback['automatic_retries'], 0)

    def test_complete_scientific_terms_are_preserved_on_text_overflow(self):
        ir = fixture()
        comp = ir['slides'][0]['composition']
        title = '各向异性介电响应张量及其非线性耦合边界条件'*24
        comp['layout_tree']['regions']['body']['children'][0]['title'] = title
        ir['slides'] = ir['slides'][:1]
        layout, issues = self.compile_ok(ir)
        element = next(e for e in layout['slides'][0]['elements'] if e['id'] == 'region:math-panel:title')
        self.assertEqual(element['source_text'], title)
        self.assertIn('SCIENTIFIC_TEXT_OVERFLOW', [i['rule'] for i in issues])

    def test_tree_still_requires_deck_design(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            ir = fixture()
            ir.pop('presentation')
            for asset in ir['assets'].values(): asset['path'] = str((EXAMPLE.parent/asset['path']).resolve())
            source = root/'input.json'
            source.write_text(json.dumps(ir))
            _, layout, qa = compile_input(source, root)
            self.assertIsNone(layout)
            self.assertIn('VISUAL_DESIGN_REQUIRED', [i['rule'] for i in qa['items']])

    def test_dense_tree_rows_hug_content(self):
        ir = fixture()
        slide = ir['slides'][0]
        blocks = [{'id': 'explanation', 'component': 'body', 'text': '完整公式按原有顺序推导，保留解释。'}]
        blocks += [{'id': f'eq-{n}', 'component': 'formula', 'text': f'x_{{{n}}}=y_{{{n}}}^{{2}}', 'anchor': 'explanation'} for n in range(6)]
        slide['composition'] = {'archetype': 'composite-research', 'blocks': blocks, 'figure_refs': [],
            'layout_tree': {'version': '1.0', 'regions': {'body': {'id': 'derivation', 'type': 'stack', 'gap': 'compact',
                'children': [{'id': f'row-{n}', 'type': 'block', 'ref': b['id']} for n, b in enumerate(blocks)]}}}}
        ir['slides'] = [slide]
        layout, _ = self.compile_ok(ir)
        math = [e for e in layout['slides'][0]['elements'] if e['kind'] == 'math']
        self.assertEqual(len(math), 6)
        self.assertTrue(all(0 <= b['bbox'][1]-a['bbox'][1]-a['bbox'][3] < 40 for a, b in zip(math, math[1:])))

    def test_rpa_composition_compiles_without_content_changes(self):
        ir = fixture()
        comp = ir['slides'][0]['composition']
        groups = []
        for panel in comp['layout_tree']['regions']['body']['children']:
            body = panel['body']
            groups.append({'id': panel['id'], 'title': panel['title'], 'arrangement': body['type'],
                **({'columns': body['columns']} if body['type'] == 'image_grid' else {}),
                'items': [{'kind': n['type'], 'ref': n['ref']} for n in body['children']]})
        request = {'sublayout_id': 'three-panels', 'groups': groups,
            'content_refs': {'blocks': [{k: b[k] for k in ('id', 'component', 'anchor') if k in b} for b in comp['blocks']],
                'figure_count': len(comp['figure_refs']), 'graphics': [{k: g[k] for k in ('id', 'type')} for g in comp['graphics']]},
            'consumer_capabilities': {'layout_tree': capabilities()}}
        script = 'import {composeSublayout} from "./research-ppt-assistant/server/sublayouts.mjs"; let s=""; for await(const c of process.stdin)s+=c; console.log(JSON.stringify(composeSublayout(JSON.parse(s))));'
        result = subprocess.run(['node', '--input-type=module', '-e', script], cwd=ROOT.parent,
            input=json.dumps(request), text=True, capture_output=True, check=True)
        proposal = json.loads(result.stdout)
        self.assertEqual(proposal['status'], 'structure_planned', proposal)
        comp.update(proposal['composition_patch'])
        self.compile_ok(ir)

    @unittest.skipUnless(shutil.which('officecli'), 'OfficeCLI required')
    def test_native_backend_structural_roundtrip(self):
        from deck_compiler.pipeline import build
        from deck_compiler.structural import verify
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root/'input.json'
            ir = fixture()
            for asset in ir['assets'].values(): asset['path'] = str((EXAMPLE.parent/asset['path']).resolve())
            source.write_text(json.dumps(ir, ensure_ascii=False))
            qa = build(source, root, native_render=False, officecli_executable=shutil.which('officecli'))
            self.assertEqual(qa['counts']['FAIL'], 0)
            layout = json.loads((root/'layout.json').read_text())
            self.assertFalse([i for i in verify(root/'candidate.pptx', layout) if i['severity'] == 'FAIL'])
            feedback = json.loads((root/'layout_feedback.json').read_text())
            self.assertTrue(all(any(e['code'] == 'NATIVE_RENDER_SKIPPED' for e in s['errors']) for s in feedback['slides']))


if __name__ == '__main__':
    unittest.main()
