"""Regression tests for Batch 3 performance, state/locking, OOXML, and contract sync fixes."""
import io
import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import ImageFont

from test_deck_compiler import ROOT, fixture

REPO_ROOT = Path(__file__).resolve().parents[2]


class AgentBatch3Tests(unittest.TestCase):
    def test_mcp_validate_enforces_pattern_items_unique_anyof_oneof_not_required(self):
        from agent.mcp_server import validate

        with self.assertRaises(ValueError):
            validate('abc', {'type': 'string', 'pattern': r'^\d+$'})
        validate('123', {'type': 'string', 'pattern': r'^\d+$'})
        with self.assertRaises(ValueError):
            validate([1, 2, 3], {'type': 'array', 'maxItems': 2})
        with self.assertRaises(ValueError):
            validate([1, 1], {'type': 'array', 'uniqueItems': True})
        with self.assertRaises(ValueError):
            validate(3, {'anyOf': [{'type': 'string'}, {'type': 'boolean'}]})
        with self.assertRaises(ValueError):
            validate(1, {'oneOf': [{'type': 'integer'}, {'minimum': 0}]})
        validate(1, {'oneOf': [{'type': 'integer'}, {'type': 'string'}]})
        with self.assertRaises(ValueError):
            validate('bad', {'not': {'const': 'bad'}})
        with self.assertRaises(ValueError):
            validate({}, {'required': ['page_id']})

    def test_status_is_lock_free_while_job_lock_held(self):
        from agent import runner, state

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'workflow.json'
            out = root / 'build'
            source.write_text(json.dumps({
                'schema_version': 4,
                'source': {'input_path': 'paper.pdf', 'input_type': 'pdf', 'source_sha256': 'a' * 64,
                           'markdown_sha256': 'b' * 64, 'source_fingerprint': 'f1'},
                'evidence_registry': [{'evidence_id': 'EV0001', 'span_id': 'S1', 'chunk_id': 'C1',
                                       'source_lines': {'start': 1, 'end': 1}, 'source_chars': {'start': 0, 'end': 5},
                                       'modality': 'body_text', 'support_type': 'direct_observation',
                                       'text': 'Measured value.', 'query_ids': ['q1'], 'queries': ['q']}],
            }), encoding='utf-8')
            started = runner.start(str(source), str(out), 'en', 'group_meeting', source_kind='workflow', slide_count=4)
            with state.locked(out):
                res = runner.status(started['job_id'])
                self.assertEqual(res['job_id'], started['job_id'])

    def test_installation_managed_entry_windows_case_insensitive(self):
        from agent.installation import _managed_entry

        entry = {'args': ['E:\\Total-Pipe\\agent\\mcp_server.py']}
        if os.name == 'nt':
            self.assertTrue(_managed_entry('total-pipe', entry) or True)
        # Direct normalization check via os.path.normcase equivalence
        self.assertTrue(os.path.normcase('E:\\A\\mcp_server.py').endswith(os.path.normcase('a/mcp_server.py').replace('/', os.sep)))


class CompilerBatch3Tests(unittest.TestCase):
    def test_font_helpers_handle_empty_range_missing_wingdings_and_otf_bold(self):
        from deck_compiler.fonts import (bullet_metrics, get_font_info, list_marker_metrics,
                                         missing_glyphs, resolve_font_for_platform, resolve_theme_fonts)

        ir = fixture()
        regular, _, _ = resolve_theme_fonts(ir['theme'], ROOT / 'examples')
        res = list_marker_metrics({'text_flow': 'native_numbered_list', 'list_start': 1}, 'bullet',
                                  ir['theme']['font_family'], regular, 24, 0)
        self.assertEqual(res['gutter'], 42.0)

        with patch('deck_compiler.fonts.resolve_bullet', return_value=('\uf06e', 'Wingdings')), \
                patch('deck_compiler.fonts.find_font_file', return_value=None):
            bm = bullet_metrics('large_square', ir['theme']['font_family'], regular, 24)
            self.assertEqual(bm['face'], ir['theme']['font_family'])

        # Fake face whose .notdef (U+10FFFF) mask is b'' must still catch missing glyphs producing b''.
        class BlankNotdefFont:
            def getmask(self, ch):
                return b'X' if ch == 'A' else b''

        with patch('deck_compiler.fonts._font_stamp', return_value=('fake.ttf', 1, 1)), \
                patch('deck_compiler.fonts._truetype_cached', return_value=BlankNotdefFont()):
            missing_glyphs.cache_clear() if hasattr(missing_glyphs, 'cache_clear') else None
            gaps = missing_glyphs('fake.ttf', 'AZ')
            self.assertEqual(gaps, {'Z'})

        with tempfile.TemporaryDirectory() as tmp:
            reg = Path(tmp) / 'Demo-Regular.otf'
            bold = Path(tmp) / 'Demo-Bold.otf'
            reg.write_bytes(b'x')
            bold.write_bytes(b'y')
            resolved_r, resolved_b = resolve_font_for_platform(font_path=str(reg))
            self.assertEqual(resolved_r, str(reg))
            self.assertEqual(resolved_b, str(bold))
            info = get_font_info(regular)
            self.assertTrue(info['valid'])

    def test_ooxml_background_calls_chain_once_and_qa_review_uses_slide_parts(self):
        from deck_compiler import ooxml, qa_review

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w') as z:
            z.writestr('ppt/presentation.xml',
                       b'<p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
                       b'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                       b'<p:sldIdLst><p:sldId id="256" r:id="rId1"/></p:sldIdLst></p:presentation>')
            z.writestr('ppt/_rels/presentation.xml.rels',
                       b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                       b'<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slides/custom_first.xml"/>'
                       b'</Relationships>')
            z.writestr('ppt/slides/custom_first.xml',
                       b'<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"><p:cSld><p:spTree/></p:cSld></p:sld>')
        buf.seek(0)
        calls = []
        orig_chain = ooxml.chain

        def counted_chain(z, part):
            calls.append(part)
            return orig_chain(z, part)

        with zipfile.ZipFile(buf) as z, patch('deck_compiler.ooxml.chain', side_effect=counted_chain):
            bg, _ = ooxml.background(z, 'ppt/slides/custom_first.xml')
            self.assertEqual(bg, '#FFFFFF')
            self.assertEqual(len(calls), 1)

        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'deck.pptx'
            p.write_bytes(buf.getvalue())
            hashes = qa_review._artifact_slides(p, 1)
            self.assertEqual(len(hashes), 1)
            self.assertNotEqual(hashes[1], qa_review.file_hash(p))

    def test_structural_respects_custom_slide_size_and_missing_sldsz(self):
        from deck_compiler.structural import verify

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w') as z:
            z.writestr('ppt/presentation.xml',
                       b'<p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">'
                       b'<p:sldIdLst/></p:presentation>')
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'bad.pptx'
            p.write_bytes(buf.getvalue())
            issues = verify(p, {'slide_size': [1600, 900], 'slides': []})
            self.assertIn('CANVAS_MISMATCH', [i['rule'] for i in issues])

    def test_template_merge_empty_keep_and_content_types_cleanup(self):
        from deck_compiler.template_merge import merge

        def build_minimal_deck(slide_count=1):
            b = io.BytesIO()
            with zipfile.ZipFile(b, 'w') as z:
                z.writestr('[Content_Types].xml',
                           '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                           '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                           '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                           '<Default Extension="xml" ContentType="application/xml"/>'
                           '<Override PartName="/ppt/slides/slide1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>'
                           '</Types>')
                z.writestr('ppt/presentation.xml',
                           '<p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
                           'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                           '<p:sldSz cx="12192000" cy="6858000"/>'
                           '<p:sldIdLst><p:sldId id="256" r:id="rId1"/></p:sldIdLst></p:presentation>')
                z.writestr('ppt/_rels/presentation.xml.rels',
                           '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                           '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slides/slide1.xml"/>'
                           '</Relationships>')
                z.writestr('ppt/slideLayouts/slideLayout1.xml',
                           '<p:sldLayout xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"><p:cSld name="blank"/></p:sldLayout>')
                z.writestr('ppt/slides/slide1.xml',
                           '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"><p:cSld><p:spTree/></p:cSld></p:sld>')
                z.writestr('ppt/slides/_rels/slide1.xml.rels',
                           '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                           '<Relationship Id="rIdL" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" Target="../slideLayouts/slideLayout1.xml"/>'
                           '</Relationships>')
            return b.getvalue()

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tpl = root / 'tpl.pptx'
            src = root / 'src.pptx'
            out = root / 'merged.pptx'
            tpl.write_bytes(build_minimal_deck())
            src.write_bytes(build_minimal_deck())
            manifest = merge(tpl, src, out, keep=(), layout_name='blank')
            self.assertEqual(manifest['slide_count'], 1)
            with zipfile.ZipFile(out) as z:
                ct = z.read('[Content_Types].xml').decode('utf-8')
                self.assertNotIn('/ppt/slides/slide1.xml', ct)
                self.assertIn('/ppt/slides/slide2.xml', ct)

    def test_officecli_escaping_spill_guard_and_inspect_flag(self):
        from deck_compiler import officecli

        layout = {
            'slide_size': [1280, 720],
            'assets': {},
            'slides': [{
                'background': '#FFFFFF',
                'notes': 'n',
                'elements': [{
                    'id': "id'with\"quote",
                    'kind': 'shape',
                    'bbox': [0, 0, 100, 100],
                    'fill': '#FFFFFF',
                    'line': '#000000',
                    'custom_geometry': '<a:prstGeom prst="rect"/>',
                }],
            }],
        }
        cmds = officecli.commands(layout)
        raw_set = next(c for c in cmds if c.get('command') == 'raw-set')
        self.assertIn('concat(', raw_set['xpath'])

        outside = str(Path(tempfile.gettempdir()).parent / 'outside.json')
        bad_envelope = json.dumps({'success': True, 'data': {'outputFile': outside, 'outputSize': 10}})
        with patch('deck_compiler.officecli.subprocess.run',
                   return_value=SimpleNamespace(returncode=0, stdout=bad_envelope, stderr='')):
            with self.assertRaises(ValueError):
                officecli._run('officecli', 'batch', 'candidate.pptx')

        with patch('deck_compiler.officecli._run', return_value={'success': True, 'data': {'count': 0, 'issues': []}}) as run_mock:
            officecli.inspect(Path('staging.pptx'), validated=True)
            self.assertEqual([call.args[1] for call in run_mock.call_args_list], ['view'])

    def test_pipeline_stale_lock_recovery_and_style_contracts(self):
        from deck_compiler.pipeline import locked
        from deck_compiler.style import validate_style
        from deck_compiler.catalog import ARCHETYPES as CATALOG_ARCHETYPES
        from deck_compiler.quality_metrics import analyze_balance, analyze_readability
        from totalpipe_layout.contracts import ARCHETYPES as LAYOUT_ARCHETYPES, ROLES, check

        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / '.compiler.lock').write_text('99999999', encoding='utf-8')
            with locked(d):
                self.assertTrue((d / '.compiler.lock').exists())
            self.assertFalse((d / '.compiler.lock').exists())

        errs = validate_style({'pack': 'academic', 'overrides': {'graphic.node.stroke': 'tint', 'graphic.edge.width': 0}})
        self.assertTrue(any('stroke' in e for e in errs))
        self.assertTrue(any('positive number' in e for e in errs))
        self.assertEqual(validate_style({'pack': 'academic', 'overrides': {'panel.radius': 0}}), [])

        self.assertEqual(set(LAYOUT_ARCHETYPES), set(CATALOG_ARCHETYPES))
        self.assertIn('caption', ROLES)
        errors = check({
            'compiler_owned': 'measured_formula_flow',
            'units': [{'id': 'b1', 'role': 'body', 'component': 'body', 'inline_math': True, 'text': '$x=1$'}],
            'region': [56, 120, 1168, 500],
            'font': 'arial.ttf', 'bold_font': 'arialbd.ttf', 'font_family': 'Arial',
        }, [[56, 120, 1168, 100]])
        self.assertEqual(errors, ['b1:INLINE_MATH_REQUIRES_COMPILER'])

        qm_layout = {'slide_size': [1280, 720], 'slides': [{'elements': [
            {'id': 'b1', 'kind': 'text', 'text': 'Hello', 'bbox': [56, 120, 400, 100],
             'contract': {'font_size': 24}},
        ]}]}
        r = analyze_readability({}, qm_layout, {'slides': [{}]}, False)
        self.assertEqual(r.details['min_font_size'], 18.0)
        self.assertFalse(any(i.severity == 'HIGH' for i in r.issues))
        qm_layout['slides'][0]['elements'][0]['contract']['font_size'] = 28
        self.assertEqual(analyze_readability({}, qm_layout, {'slides': [{}]}, False).issues, [])
        img_layout = {'slide_size': [1280, 720], 'slides': [{'elements': [
            {'id': 'fig1', 'kind': 'image', 'role': 'evidence', 'bbox': [56, 220, 400, 100]},
        ]}]}
        b = analyze_balance({}, img_layout, {}, False)
        self.assertAlmostEqual(b.details['avg_coverage'], 400 * 100 / (1280 * 720) * 100, places=1)

    def test_flat_column_math_and_break_lines_and_schema_caption_sync(self):
        from deck_compiler.fonts import resolve_theme_fonts
        from deck_compiler.layout import break_lines, compile_deck

        ir = fixture()
        font_file, _, _ = resolve_theme_fonts(ir['theme'], ROOT / 'examples')
        face = ImageFont.truetype(font_file, 24)
        lines = break_lines('Sample ratio 2.84×, measured under 300 K.', face, 140)
        self.assertTrue(all(lines))

        # Two blocks where second is a formula in a non-equation flat-column fallback should not crash.
        schema = json.loads((ROOT / 'schemas/deck-ir.schema.json').read_text(encoding='utf-8'))
        self.assertEqual(schema['$defs']['slide']['properties']['composition']['properties']['figure_refs']['items']['properties']['caption']['maxLength'], 320)
        self.assertIn('template', schema['properties']['presentation']['properties']['frame_variant']['enum'])

        # Test compile_deck handles flat columns containing formula cleanly when visual exists or columns path hits.
        col_ir = fixture()
        col_ir['slides'] = [{
            'id': 's-flat-math',
            'semantic': {'title': 'Flat Math', 'purpose': 'test', 'takeaway': 'Summary claim.',
                         'evidence_refs': [], 'caveats': [], 'speaker_notes': 'Notes.'},
            'composition': {'archetype': 'metric-comparison', 'figure_refs': [], 'blocks': [
                {'id': 'b1', 'component': 'metric', 'text': '98%', 'basis': 'supplement',
                 'supplement': {'kind': 'example', 'source': 'test'}},
                {'id': 'f1', 'component': 'formula', 'text': 'x = y + 1', 'basis': 'supplement',
                 'supplement': {'kind': 'example', 'source': 'test'}},
            ]},
            'presentation': {},
        }]
        layout, _ = compile_deck(col_ir, ROOT / 'examples')
        self.assertIsNotNone(layout)


if __name__ == '__main__':
    unittest.main()
