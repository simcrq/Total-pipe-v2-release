"""Path geometry, quadratic conversion and bounded native DrawingML output."""
import copy
import math
import unittest
import xml.etree.ElementTree as ET

from deck_compiler.graphic_layout import GraphicLayoutError, validate_graphics
from deck_compiler.graphic_paths import (custom_geometry, geometry_signature, parse_path,
                                          path_bounds, render_paths)

A = '{http://schemas.openxmlformats.org/drawingml/2006/main}'
THEME = {'accent': '#2563A6', 'foreground': '#142735', 'background': '#FFFFFF'}


def scene():
    return {'id': 'region', 'type': 'path', 'view_box': [0, 0, 200, 100],
            'paths': [{'id': 'shape', 'd': 'M 0 50 Q 50 0 100 50 C 130 90 170 10 200 50 L 200 100 L 0 100 Z',
                       'fill': 'background'}],
            'labels': [{'id': 'name', 'text': 'Boundary', 'box': [50, 60, 100, 30]}]}


class GraphicPathTests(unittest.TestCase):
    def test_string_and_array_forms_compile_all_five_commands_identically(self):
        string = 'M0,0 20,0 L30 20 C40 30 50 20 60 0 Q80 30 100 0 Z'
        commands = [['M', 0, 0], ['L', 20, 0], ['L', 30, 20],
                    ['C', 40, 30, 50, 20, 60, 0], ['Q', 80, 30, 100, 0], ['Z']]
        original = copy.deepcopy(commands)
        self.assertEqual(parse_path(string), parse_path(commands))
        self.assertEqual(commands, original)
        self.assertNotIn('Q', [c[0] for c in parse_path(string)])

    def test_quadratic_to_cubic_preserves_the_curve(self):
        curve = parse_path([['M', 10, 20], ['Q', 70, 100, 130, 20]])[1][1:]
        for t in (0, .1, .25, .5, .75, .9, 1):
            for axis in (0, 1):
                start, control, end = (10, 70, 130) if axis == 0 else (20, 100, 20)
                quadratic = (1-t)**2*start+2*(1-t)*t*control+t*t*end
                cubic = (1-t)**3*start+3*(1-t)**2*t*curve[axis]+3*(1-t)*t*t*curve[axis+2]+t**3*curve[axis+4]
                self.assertAlmostEqual(quadratic, cubic)

    def test_exact_bounds_use_cubic_extrema_and_support_multiple_subpaths(self):
        commands = parse_path('M 0 0 C 0 100 100 100 100 0 M 120 20 L 160 40')
        self.assertEqual(path_bounds(commands), [0, 0, 160, 75])

    def test_normalized_geometry_is_translation_and_scale_invariant(self):
        commands = parse_path('M 0 0 L 100 0 L 100 100 Z')
        translated = [[c[0], *[v*2+(10 if i % 2 == 0 else 20) for i, v in enumerate(c[1:])]] for c in commands]
        a = custom_geometry(commands, [0, 0, 100, 100])
        b = custom_geometry(translated, [10, 20, 200, 200])
        self.assertEqual(geometry_signature(a), geometry_signature(b))
        root = ET.fromstring(a)
        self.assertEqual(root.tag, A+'custGeom')
        self.assertEqual([c.tag for c in root], [A+t for t in ('avLst', 'gdLst', 'ahLst', 'cxnLst', 'rect', 'pathLst')])
        self.assertEqual(root.find(A+'pathLst/'+A+'path').get('w'), '100000')

    def test_path_and_label_layout_are_deterministic_and_stay_in_the_region(self):
        data = scene()
        original = copy.deepcopy(data)
        self.assertEqual(validate_graphics([data], 'native-graphic'), [])
        elements = render_paths(data, THEME, [10, 20, 600, 300])
        self.assertEqual(elements, render_paths(data, THEME, [10, 20, 600, 300]))
        self.assertEqual(data, original)
        for element in elements:
            x, y, w, h = element['bbox']
            self.assertGreaterEqual(x, 10)
            self.assertGreaterEqual(y, 20)
            self.assertLessEqual(x+w, 610)
            self.assertLessEqual(y+h, 320)
        label = next(e for e in elements if e['kind'] == 'text')
        self.assertEqual(label['text'], 'Boundary')
        self.assertTrue(all('custom_geometry' in e for e in elements if e['kind'] == 'shape'))

    def test_horizontal_and_vertical_open_paths_keep_positive_native_extents(self):
        for d in ('M 0 50 L 200 50', 'M 100 0 L 100 100'):
            data = scene()
            data['paths'] = [{'id': 'line', 'd': d}]
            self.assertFalse(validate_graphics([data], 'native-graphic'))
            element = render_paths(data, THEME, [0, 0, 600, 300])[0]
            self.assertGreater(min(element['bbox'][2:]), 0)

    def test_invalid_or_unsupported_paths_fail_explicitly(self):
        values = ['M 0 0 A 1 1 0 0 0 20 20', 'm 0 0 l 1 1', 'M 0 0 H 100', 'L 0 0 L 1 1',
                  'M 0 0 C 1 2 3 4', 'M 0 0 Q NaN 1 2 3', 'M 0 0 L 1e999 0',
                  'M 0 0 Z 5 6', 'M 0 0 <script>', [], [['M', 0, 0], ['L', math.inf, 2]],
                  [['M', 0, 0], ['L', 10**1000, 2]],
                  [['M', 0, 0], ['L', True, 2]], [['M', 0, 0], ['L', 1, 2]]*300]
        for value in values:
            with self.subTest(value=str(value)[:55]):
                with self.assertRaises(GraphicLayoutError):
                    parse_path(value)

    def test_view_box_styles_labels_and_geometry_are_strictly_validated(self):
        mutations = [lambda d: d.update(view_box=[0, 0, 0, 100]),
                     lambda d: d.update(view_box=[0, 0, math.nan, 100]),
                     lambda d: d['paths'][0].update(d='M 0 0 L 300 100'),
                     lambda d: d['paths'][0].update(d='M 10 10 L 10 10'),
                     lambda d: d['paths'][0].update(commands=[['M', 0, 0], ['L', 1, 1]]),
                     lambda d: d['paths'][0].update(fill='url(#gradient)'),
                     lambda d: d['paths'][0].update(mask='anything'),
                     lambda d: d['labels'][0].update(box=[-1, 0, 100, 20]),
                     lambda d: d['labels'][0].update(box=[0, 0, True, 20]),
                     lambda d: d['labels'].append(copy.deepcopy(d['labels'][0]))]
        for mutation in mutations:
            data = scene()
            mutation(data)
            self.assertTrue(validate_graphics([data], 'native-graphic'))

    def test_extreme_normalization_reports_a_capacity_error_instead_of_crashing(self):
        with self.assertRaises(GraphicLayoutError):
            custom_geometry(parse_path('M 0 0 L 100 100'), [0, 0, 1e-320, 1])
        data = {'id': 'tiny', 'type': 'path', 'view_box': [0, 0, 1e-320, 1e-320],
                'paths': [{'id': 'line', 'commands': [['M', 0, 0], ['L', 1e-320, 1e-320]]}]}
        with self.assertRaises(GraphicLayoutError):
            render_paths(data, THEME, [0, 0, 100, 100])
