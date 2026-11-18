import json
from pathlib import Path
import subprocess
import sys
import unittest

from jsonschema import validate

from deck_compiler.layout import compile_deck

ROOT = Path(__file__).resolve().parents[1]
LIBRARY = ROOT/'examples/library'


def catalog(*args):
    return json.loads(subprocess.check_output([sys.executable, '-B', LIBRARY/'catalog.py', *args]))


class ExampleLibraryTests(unittest.TestCase):
    def test_search_ranks_by_visual_intent_and_returns_only_metadata(self):
        for query, expected in (
            ('独立正文块加圆角标题和编号', 'independent-blocks'),
            ('A/B 对照路线 动作标签', 'comparison-lanes'),
            ('directional annotations caption_for', 'directional-notes'),
            ('原图导读 图文并排', 'figure-readout'),
            ('误差棒 y_error', 'chart-uncertainty'),
            ('native table merged headers', 'grouped-table'),
            ('行内公式 独立公式 符号定义', 'equation-explainer'),
            ('机制图 假设虚线', 'mechanism-hypothesis'),
        ):
            rows = catalog('search', query, '--limit', '1')
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]['id'], expected)
            self.assertEqual(set(rows[0]), {'id', 'title', 'summary', 'script'})
            self.assertTrue(Path(rows[0]['script']).is_file())
        self.assertEqual(catalog('search', 'no-such-layout-4837'), [])

    def test_indexed_scripts_emit_valid_compilable_decks(self):
        schema = json.loads((ROOT/'schemas/deck-ir.schema.json').read_text(encoding='utf-8'))
        index = json.loads((LIBRARY/'index.json').read_text(encoding='utf-8'))
        ids = [entry['id'] for entry in index['entries']]
        self.assertEqual(len(ids), len(set(ids)))
        for id in ids:
            with self.subTest(example=id):
                value = catalog('show', id)
                validate(value, schema)
                layout, issues = compile_deck(value, LIBRARY)
                self.assertFalse([issue for issue in issues if issue['severity'] == 'FAIL'], issues)
                if id == 'independent-blocks':
                    blocks = value['slides'][0]['composition']['blocks']
                    actual = [element for element in layout['slides'][0]['elements'] if element['kind'] == 'list']
                    self.assertEqual([element['id'] for element in actual], [block['id'] for block in blocks])
                    self.assertTrue(all(len(element['items']) == 1 for element in actual))
                    self.assertEqual([element['bullet'].get('start') for element in actual], [None, None, 1, 2])
                    self.assertTrue(any(e.get('geometry') == 'roundRect' for e in layout['slides'][0]['elements']))
                    self.assertFalse(any(e.get('container_frame') for e in layout['slides'][0]['elements']))
