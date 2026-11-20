"""Regression tests for the first hardening batch (recipes, MCP surface, provenance, telemetry)."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from agent import telemetry
from agent.page_recipes import compose, expand_page
from deck_compiler import provenance

ROOT = Path(__file__).resolve().parents[1]


def object_ids(page):
    return {obj['id'] for obj in page['objects']}


class RecipeDefaultsTests(unittest.TestCase):
    def test_no_demo_content_leaks_into_recipes(self):
        cover = compose({'recipe': 'cover', 'id': 'A', 'title': 't', 'take': 'k'})
        self.assertFalse([i for i in object_ids(cover) if i.startswith('stat_')])
        contrast = compose({'recipe': 'contrast', 'id': 'B', 'title': 't', 'take': 'k'})
        self.assertNotIn('wave_digital', object_ids(contrast))
        waves = compose({'recipe': 'contrast', 'id': 'B', 'title': 't', 'take': 'k', 'waves': True})
        self.assertIn('wave_digital', object_ids(waves))
        closing = compose({'recipe': 'closing', 'id': 'C', 'title': 't', 'take': 'k'})
        self.assertNotIn('big_stat', object_ids(closing))
        text = json.dumps(closing, ensure_ascii=False)
        self.assertNotIn('种功能', text)

    def test_table_compare_matches_any_column_count(self):
        for columns in (2, 3, 5):
            rows = [['h'] * columns, ['v'] * columns]
            page = compose({'recipe': 'table_compare', 'id': 'T', 'title': 't', 'take': 'k',
                            'table': {'rows': rows}})
            table = next(o for o in page['objects'] if o['type'] == 'table')
            self.assertEqual(len(table['col_widths']), columns)

    def test_svg_path_is_confined(self):
        svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><rect width="5" height="5"/></svg>'
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as outside:
            inside = Path(root) / 'ok.svg'
            inside.write_text(svg, encoding='utf-8')
            stray = Path(outside) / 'secret.svg'
            stray.write_text(svg, encoding='utf-8')
            page = {'recipe': 'svg_diagram', 'id': 'S', 'title': 't', 'take': 'k'}
            expand_page({**page, 'svg_path': str(inside)}, {}, svg_root=root)
            with self.assertRaises(ValueError):
                expand_page({**page, 'svg_path': str(stray)}, {}, svg_root=root)
            with self.assertRaises(ValueError):
                expand_page({**page, 'svg_path': str(inside)}, {})
            with self.assertRaises(ValueError):
                compose({**page, 'svg_path': str(inside)})


class McpSurfaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import deck_compiler.mcp_server as server
        cls.server = server

    def test_refresh_capacity_is_not_exposed(self):
        self.assertNotIn('pwf2rpa_refresh_capacity', self.server.transport.TOOLS)
        self.assertIn('pwf2rpa_check', self.server.transport.TOOLS)

    def test_external_provider_and_foreign_executable_are_rejected(self):
        check = self.server._check_executables
        check({'layout_provider': 'packer', 'officecli': 'officecli'})
        check({'officecli': r'C:\tools\OfficeCLI.exe'})
        with self.assertRaises(ValueError):
            check({'layout_provider': '/tmp/evil.py:factory'})
        with self.assertRaises(ValueError):
            check({'layout_provider': 'os:system'})
        with self.assertRaises(ValueError):
            check({'officecli': 'powershell'})


class ProvenanceTests(unittest.TestCase):
    @staticmethod
    def deck(**block):
        return {'slides': [{'semantic': {}, 'composition': {'blocks': [{'id': 'b1', **block}]}}]}

    def test_all_paper_deck_still_validates_basis(self):
        codes = {p['rule'] for p in provenance.validate(self.deck(basis='typo'))}
        self.assertIn('SUPPLEMENT_BASIS_INVALID', codes)
        codes = {p['rule'] for p in provenance.validate(self.deck(supplement={'kind': 'derivation'}))}
        self.assertIn('SUPPLEMENT_ON_PAPER_BLOCK', codes)
        self.assertEqual(provenance.validate(self.deck(basis='paper')), [])


class TelemetryTests(unittest.TestCase):
    def test_events_use_lf_line_endings(self):
        with tempfile.TemporaryDirectory() as out:
            telemetry.emit(out, 'probe')
            telemetry.emit(out, 'probe')
            data = (Path(out) / 'logs/events.jsonl').read_bytes()
            self.assertNotIn(b'\r', data)
            self.assertEqual(data.count(b'\n'), 2)


class PaperWorkflowSafetyTests(unittest.TestCase):
    @staticmethod
    def load(name, relative):
        spec = importlib.util.spec_from_file_location(name, ROOT.parent / relative)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_zip_slip_is_rejected(self):
        import zipfile
        try:
            handler = self.load('pdf_api_handler_under_test', 'PaperWorkflow/utils/pdf_api_handler.py')
        except ModuleNotFoundError as error:
            self.skipTest(str(error))
        with tempfile.TemporaryDirectory() as root:
            archive = Path(root) / 'bad.zip'
            with zipfile.ZipFile(archive, 'w') as z:
                z.writestr('../escape.txt', 'x')
            target = Path(root) / 'out'
            target.mkdir()
            with self.assertRaises(ValueError):
                handler._safe_extract(archive, target)
            self.assertFalse((Path(root) / 'escape.txt').exists())
            good = Path(root) / 'good.zip'
            with zipfile.ZipFile(good, 'w') as z:
                z.writestr('full.md', 'ok')
            handler._safe_extract(good, target)
            self.assertTrue((target / 'full.md').is_file())


if __name__ == '__main__':
    unittest.main()
