"""The workshop tools must stay lossless: they read a deck, and writing it back changes nothing."""
import json
import unittest
from pathlib import Path

from deck_compiler.workshop import assembly

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / 'examples/native-bullets.deck_ir.json'


def example():
    return json.loads(EXAMPLE.read_text(encoding='utf-8'))


class AssemblyTests(unittest.TestCase):
    def test_export_then_build_reproduces_every_box(self):
        base = example()
        spec = assembly.export(base)
        self.assertEqual([page['id'] for page in spec['pages']],
                         [slide['id'] for slide in base['slides']])
        assembled, problems = assembly.assemble(base, spec)
        self.assertEqual(problems, [])
        before, _ = assembly.geometry(base, EXAMPLE.parent)
        after, _ = assembly.geometry(assembled, EXAMPLE.parent)
        self.assertTrue(before and after, 'both decks must compile for the comparison to mean anything')
        rows = assembly.diff(before, after)
        self.assertEqual(max(row['max_delta_px'] for row in rows), 0)
        self.assertTrue(all(row['only_before'] == 0 and row['only_after'] == 0 for row in rows))

    def test_a_dropped_leaf_is_named_not_silently_tolerated(self):
        base = example()
        spec = assembly.export(base)
        parent, node = assembly.leaf_slots(spec['pages'][0]['frame'])[0]
        parent.remove(node)
        _, problems = assembly.assemble(base, spec)
        self.assertTrue(any('被引用 0 次' in problem for problem in problems), problems)

    def test_a_duplicated_leaf_is_named(self):
        base = example()
        spec = assembly.export(base)
        parent, node = assembly.leaf_slots(spec['pages'][0]['frame'])[0]
        parent.append(json.loads(json.dumps(node)))
        _, problems = assembly.assemble(base, spec)
        self.assertTrue(any('被引用 2 次' in problem for problem in problems), problems)


if __name__ == '__main__':
    unittest.main()
