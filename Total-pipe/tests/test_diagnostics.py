import unittest
from pathlib import Path

from deck_compiler import diagnostics as diag

FIXTURES = Path(__file__).resolve().parent/'fixtures'

# Codes that carry the everyday maintenance load; they must never fall back to
# a bare raise-site listing.
MUST_BE_AUTHORED = (
    'INSUFFICIENT_DRAWING_SPACE', 'INSUFFICIENT_LIST_SPACE', 'INSUFFICIENT_FIGURE_SPACE',
    'INSUFFICIENT_TABLE_SPACE', 'INSUFFICIENT_FORMULA_SPACE', 'INSUFFICIENT_CHART_SPACE',
    'INSUFFICIENT_TEXT_SPACE', 'TEXT_ONLY_PAGE', 'CHART_CAPACITY', 'GRAPHIC_CAPACITY',
    'GRAPHIC_PAGE_CAPACITY', 'GRAPHIC_LABEL_CAPACITY', 'GRAPHIC_TEXT_OVERFLOW',
    'TYPOGRAPHY_FLOOR', 'CRITICAL_COLLISION', 'VISUAL_DESIGN_REQUIRED',
    'VISUAL_PLAN_UNSATISFIABLE', 'COMPILATION_FAILED', 'FONT_UNAVAILABLE',
    'CONTENT_PROJECTION_FAILED',
    'FORMULA_MISSING', 'FORMULA_CONTENT_MISMATCH', 'SPLIT_REQUIRED', 'IR_INVALID',
)


class DiscoveryTests(unittest.TestCase):
    def test_every_discovered_code_explains_itself(self):
        found = diag.discover()
        self.assertGreater(len(found), 50, 'the scanner should see the package gate codes')
        for code in found:
            row = diag.explain(code)
            self.assertEqual(row['code'], code)
            self.assertTrue(row['summary'], code)
            self.assertTrue(row['sites'], code)

    def test_catalog_has_no_dead_entries(self):
        found, composed = diag.discover(), diag.families()
        stray = []
        for code in diag.CATALOG:
            if code.endswith('_'):
                if not composed.get(code) and not any(key.startswith(code) for key in found):
                    stray.append(code)
            elif code not in found and not diag.mentions(code):
                stray.append(code)
        self.assertEqual(sorted(stray), [],
                         'authored guidance for codes nothing in the package names')

    def test_core_codes_stay_authored(self):
        for code in MUST_BE_AUTHORED:
            self.assertIn(code, diag.CATALOG, f'{code} lost its authored guidance')
            row = diag.explain(code)
            self.assertTrue(row['authored'], code)
            self.assertTrue(row['cause'], code)
            self.assertGreaterEqual(len(row['fixes']), 2, code)

    def test_every_fix_names_a_cost(self):
        for code, entry in diag.CATALOG.items():
            for action, cost, detail in entry['fixes']:
                self.assertIn(cost, ('cheap', 'medium', 'expensive'), code)
                self.assertTrue(action and detail, code)

    def test_sites_carry_a_grounded_reference(self):
        for code, sites in diag.discover().items():
            for site in sites:
                self.assertTrue(site['module'], code)
                self.assertGreater(site['line'], 0, code)
                grounded = site['message'] or site['snippet'] or site['function']
                self.assertTrue(grounded, f'{code} site has nothing to show')

    def test_documented_paths_exist(self):
        repo = Path(__file__).resolve().parents[2]
        for code, entry in diag.CATALOG.items():
            for path in entry.get('see', ()):
                candidates = [repo/path, repo/'Total-pipe'/path]
                self.assertTrue(any(p.exists() for p in candidates),
                                f'{code} points at a missing doc: {path}')


class ScanTests(unittest.TestCase):
    def test_a_new_gate_is_discovered_without_touching_the_scanner(self):
        self.assertIn('FRESH_GATE', diag.discover(FIXTURES))
        row = diag.explain('FRESH_GATE', FIXTURES)
        self.assertFalse(row['authored'])
        self.assertEqual(row['summary'], 'the reason is spelled out here')
        self.assertEqual(row['severity'], 'FAIL')
        self.assertEqual(row['sites'][0]['function'], 'raises_a_literal_gate')

    def test_fstring_messages_reduce_to_a_template(self):
        row = diag.explain('TEMPLATE_GATE', FIXTURES)
        self.assertEqual(row['summary'], '{} rows do not fit the box')
        self.assertEqual(row['severity'], 'WARNING')

    def test_severity_is_the_worst_site(self):
        self.assertEqual(diag.explain('MIXED', FIXTURES)['severity'], 'FAIL')

    def test_a_code_held_in_a_local_variable_is_resolved(self):
        found = diag.discover(FIXTURES)
        for code in ('COMPUTED_FIGURE_GATE', 'COMPUTED_OTHER_GATE'):
            self.assertIn(code, found)
            self.assertEqual(found[code][0]['function'], 'raises_a_computed_gate')

    def test_a_composed_code_resolves_through_its_prefix(self):
        self.assertNotIn('COMPOSED_SLOW', diag.discover(FIXTURES))
        self.assertIn('COMPOSED_', diag.families(FIXTURES))
        row = diag.explain('COMPOSED_SLOW', FIXTURES)
        self.assertEqual(row['family'], 'COMPOSED_')
        self.assertEqual(row['severity'], 'WARNING', 'the worst arm of the conditional')
        self.assertIn('composed at runtime', diag.render(row))

    def test_a_dict_finding_is_discovered(self):
        row = diag.explain('DICT_GATE', FIXTURES)
        self.assertEqual(row['severity'], 'REVIEW')
        self.assertEqual(row['summary'], 'a dict notice')
        self.assertEqual(row['sites'][0]['function'], 'reports_a_dict_gate')

    def test_unknown_code_is_a_key_error(self):
        with self.assertRaises(KeyError):
            diag.explain('NO_SUCH_GATE_ANYWHERE')


class QuestionTests(unittest.TestCase):
    def test_plain_words_find_the_code(self):
        self.assertIn('INSUFFICIENT_DRAWING_SPACE', diag.search('drawing space'))

    def test_exact_code_wins(self):
        self.assertEqual(diag.search('text_only_page')[0], 'TEXT_ONLY_PAGE')

    def test_empty_query_finds_nothing(self):
        self.assertEqual(diag.search('   '), [])

    def test_unauthored_only_reports_gaps(self):
        gaps = diag.unauthored()
        self.assertNotIn('INSUFFICIENT_DRAWING_SPACE', gaps)
        self.assertTrue(set(gaps).issubset(set(diag.discover())))

    def test_render_shows_cause_and_cheapest_fix_first(self):
        text = diag.render(diag.explain('INSUFFICIENT_LIST_SPACE'))
        self.assertIn('Why', text)
        self.assertIn('Fix, cheapest first', text)
        self.assertIn('Raised at', text)
        self.assertIn('520 px', text)

    def test_inventory_is_sorted_and_complete(self):
        rows = diag.inventory()
        codes = [row['code'] for row in rows]
        self.assertEqual(codes, sorted(codes))
        self.assertEqual(len(rows), len(diag.discover()))


if __name__ == '__main__':
    unittest.main()
