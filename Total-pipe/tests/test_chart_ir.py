"""Chart IR v1 contract: structure, domains and evidence binding, without a renderer."""
import copy
import json
import unittest
from pathlib import Path

import jsonschema

from deck_compiler.chart_layout import validate_charts

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT/'schemas/chart-ir.schema.json').read_text(encoding='utf-8'))
EXAMPLE = json.loads((ROOT/'examples/chart-ir.example.json').read_text(encoding='utf-8'))


class ChartContractTests(unittest.TestCase):
    def chart(self):
        return copy.deepcopy(EXAMPLE)

    def test_example_satisfies_schema_and_rules(self):
        jsonschema.validate(self.chart(), SCHEMA)
        self.assertEqual(validate_charts([self.chart()], ['EV0012']), [])

    def test_series_length_must_match_the_shared_x_domain(self):
        chart = self.chart()
        chart['series'][0]['values'] = chart['series'][0]['values'][:-1]
        self.assertTrue(any('length must match' in message for message in validate_charts([chart], ['EV0012'])))

    def test_log_axis_rejects_nonpositive_values(self):
        chart = self.chart()
        chart['x']['values'][0] = 0
        self.assertTrue(any('log axis' in message for message in validate_charts([chart], ['EV0012'])))

    def test_evidence_chart_needs_refs_source_and_slide_binding(self):
        chart = self.chart()
        chart['series'][0]['evidence_refs'] = []
        self.assertTrue(any('needs evidence_refs' in message for message in validate_charts([chart], [])))
        chart = self.chart()
        chart['series'][0]['evidence_refs'] = ['EV9999']
        self.assertTrue(any('not on semantic.evidence_refs' in message
                            for message in validate_charts([chart], ['EV0012'])))
        chart = self.chart()
        chart.pop('source')
        self.assertTrue(any('provenance' in message for message in validate_charts([chart], ['EV0012'])))

    def test_explanatory_chart_must_be_marked_illustrative(self):
        chart = self.chart()
        chart['basis'] = 'explain'
        chart.pop('source')
        chart['series'][0]['evidence_refs'] = []
        self.assertTrue(any('illustrative=true' in message for message in validate_charts([chart], [])))
        chart['illustrative'] = True
        self.assertEqual(validate_charts([chart], []), [])

    def test_line_x_must_be_strictly_increasing(self):
        chart = self.chart()
        chart['x']['values'] = [40, 100, 100, 1000]
        self.assertTrue(any('strictly increasing' in message for message in validate_charts([chart], ['EV0012'])))

    def test_schema_rejects_unknown_fields_and_missing_series_refs(self):
        chart = self.chart()
        chart['axis'] = 'x'
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(chart, SCHEMA)
        chart = self.chart()
        chart['series'][0].pop('evidence_refs')
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(chart, SCHEMA)


    def test_scatter_uses_per_series_x(self):
        chart = self.chart()
        chart['kind'] = 'scatter'
        chart['x'].pop('values')
        self.assertTrue(any('x_values' in message for message in validate_charts([chart], ['EV0012'])))
        chart['series'][0]['x_values'] = [10, 20, 30, 40]
        self.assertEqual(validate_charts([chart], ['EV0012']), [])
        self.assertEqual(jsonschema.Draft202012Validator(SCHEMA).is_valid(chart), True)

    def test_error_bars_match_points_and_cannot_be_negative(self):
        chart = self.chart()
        chart['series'][0]['y_error'] = [1, 1]
        self.assertTrue(any('y_error' in message for message in validate_charts([chart], ['EV0012'])))
        chart['series'][0]['y_error'] = [1, -1, 1, 1]
        self.assertTrue(any('negative' in message for message in validate_charts([chart], ['EV0012'])))
        chart['series'][0]['y_error'] = [1, 1, 1, 1]
        self.assertEqual(validate_charts([chart], ['EV0012']), [])

    def test_annotations_must_index_real_points(self):
        chart = self.chart()
        chart['annotations'] = [{'text': '拐点', 'series': 0, 'point': 9}]
        self.assertTrue(any('point' in message for message in validate_charts([chart], ['EV0012'])))
        chart['annotations'] = [{'text': '拐点', 'series': 0, 'point': 2, 'dx': 20, 'dy': -30}]
        self.assertEqual(validate_charts([chart], ['EV0012']), [])

    def test_chart_leaf_compiles_as_a_native_plot(self):
        from deck_compiler.layout import compile_deck
        deck = json.loads((ROOT/'examples/composite-layout.deck_ir.json').read_text(encoding='utf-8'))
        deck['slides'] = [deck['slides'][0]]
        slide = deck['slides'][0]
        slide['semantic'] = {'title': '编程窗口随沟道长度变化', 'purpose': '验证原生图表渲染。',
                             'takeaway': '示意数据，不是论文数值。', 'evidence_refs': ['EV0012'],
                             'caveats': [], 'speaker_notes': 'chart contract test'}
        slide['composition'] = {
            'archetype': 'composite-research', 'blocks': [], 'figure_refs': [],
            'charts': [self.chart()],
            'layout_tree': {'version': '1.2', 'regions': {'body': {'id': 'body-chart',
                                                                   'type': 'chart', 'ref': 'window'}}}}
        layout, issues = compile_deck(deck, ROOT/'examples')
        self.assertFalse([issue for issue in issues if issue['severity'] == 'FAIL'], issues)
        elements = layout['slides'][0]['elements']
        self.assertTrue(any(element['id'].startswith('chart:window:line:') for element in elements))
        self.assertTrue(any(element['id'] == 'chart:window:badge' for element in elements)
                        if self.chart().get('basis') == 'explain' else True)


if __name__ == '__main__':
    unittest.main()
