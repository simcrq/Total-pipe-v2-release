"""Native PowerPoint bullets: deck defaults and local styles, written as paragraph properties.

The list is no longer a panel plus one shape per row. Each item is a paragraph with a:buChar and
a:buClr, so PowerPoint itself draws the marker, Tab changes the level and the bullet menu shows the
current style. Defaults stay consistent, local styles/colors remain independent of body text, and the XML written
for each paragraph has to keep DrawingML's element order (lnSpc → spcAft → buClr → buFont → buChar).
"""
import unittest
import copy
import json
import shutil
import tempfile
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from deck_compiler.contracts import TextBoxContract
from deck_compiler.layout import DEFAULT_ACCENT, compile_deck
from deck_compiler.officecli import list_paragraph_properties
from deck_compiler.ir import validate
from deck_compiler.structural import verify
from deck_compiler.officecli import render
from deck_compiler.pipeline import write_json
from deck_compiler.text_flow import split_parallel_items

from test_deck_compiler import ROOT, fixture

BODY = ("The first finding establishes the operating regime and its boundary.\n"
        "The second finding connects the measured response to the proposed mechanism.\n"
        "The third finding states the remaining uncertainty and the next experiment.")
PROCEDURE = ("Mount the sample and record the reference spectrum.\n"
             "Ramp the laser to the working power and hold it.\n"
             "Cool the stage and compare the two spectra.")


def list_deck(blocks, presentation=None):
    ir = fixture()
    slide = ir["slides"][1]
    slide["composition"]["blocks"] = blocks
    return {**ir, "slides": [slide], "presentation": presentation or {}}


def block(identifier, component, text):
    return {"id": identifier, "component": component, "text": text}


def styled_deck(blocks=None):
    ir = list_deck(blocks or [{**block('awards', 'body', BODY), 'text_flow': 'distributed_arrow_list'}])
    ir['presentation'] = copy.deepcopy(json.loads((ROOT/'examples/inline-math.deck_ir.json').read_text())['presentation'])
    ir['presentation']['text_capacity_policy'] = 'preserve-terms'
    ir['slides'][0]['presentation']['takeaway_marker'] = {'style': 'large_diamond', 'color': '#000000'}
    return ir


def in_feedback_box(ir, width=572, height=226):
    slide = ir['slides'][0]
    proposal = {slide['id']: {'provider': 'regression', 'status': 'MODEL_PROPOSAL',
        'units': {b['id']: {'bbox': [56+i*596, 280, width, height]}
                  for i, b in enumerate(slide['composition']['blocks'])}}}
    return compile_deck(ir, ROOT, proposals=proposal)


class NativeListTests(unittest.TestCase):
    def compile_lists(self, ir):
        layout, issues = compile_deck(ir, ROOT)
        self.assertFalse([i for i in issues if i["severity"] == "FAIL"], issues)
        return [element for element in layout["slides"][0]["elements"] if element["kind"] == "list"]

    def test_one_marker_style_for_the_whole_deck(self):
        lists = self.compile_lists(list_deck([block("a", "body", BODY),
                                             block("b", "conclusion", BODY)]))
        self.assertEqual(len(lists), 2)
        self.assertEqual({element["bullet"]["style"] for element in lists}, {"large_square"})
        self.assertTrue(all(e['bullet']['char'] in ('\uf06e', '\u25a0', '\u2022') for e in lists))

    def test_procedure_deck_prefers_an_arrow_marker(self):
        lists = self.compile_lists(list_deck([block("a", "process-step", PROCEDURE)]))
        self.assertEqual(lists[0]["bullet"]["style"], "arrowhead")
        self.assertIn(lists[0]["bullet"]["char"], ('\uf0d8', '\u27a2', '\u2022'))

    def test_presentation_can_choose_the_marker(self):
        lists = self.compile_lists(list_deck([block("a", "body", BODY)],
                                             {"bullet_style": "diamond"}))
        self.assertEqual(lists[0]["bullet"]["style"], "diamond")
        # ◆ is not in Arial, so the resolver must move the marker to a face that has it, or degrade.
        self.assertIn(lists[0]["bullet"]["char"], ("\u25c6", "\u2022"))

    def test_unknown_marker_style_is_rejected(self):
        _, issues = compile_deck(list_deck([block("a", "body", BODY)],
                                           {"bullet_style": "star"}), ROOT)
        self.assertEqual([i["rule"] for i in issues], ["BULLET_STYLE_INVALID"])

    def test_marker_uses_the_accent_colour(self):
        ir = list_deck([block("a", "body", BODY)])
        ir["theme"] = {**ir["theme"], "accent": "#2F6F8F"}
        lists = self.compile_lists(ir)
        self.assertEqual(lists[0]["bullet"]["color"], "#2F6F8F")

    def test_marker_defaults_away_from_the_body_colour(self):
        lists = self.compile_lists(list_deck([block("a", "body", BODY)]))
        self.assertEqual(lists[0]["bullet"]["color"], DEFAULT_ACCENT)
        self.assertNotEqual(lists[0]["bullet"]["color"], lists[0]["color"])

    def test_paragraph_properties_keep_drawingml_order(self):
        contract = TextBoxContract("Arial", 24, "arial.ttf", font_floor=22).to_dict()
        bullet = {"char": "\u25aa", "face": "Arial", "color": "#C2410C",
                  "gutter": 42, "space_after": 36}
        middle = list_paragraph_properties(contract, bullet, 0, 2)
        last = list_paragraph_properties(contract, bullet, 1, 2)
        order = [middle.index(tag) for tag in
                 ("<a:lnSpc", "<a:spcAft", "<a:buClr", "<a:buFont", "<a:buChar")]
        self.assertEqual(order, sorted(order))
        self.assertIn('marL="400050"', middle)
        self.assertIn('indent="-400050"', middle)
        self.assertIn('<a:spcAft><a:spcPts val="2700" /></a:spcAft>', middle)
        self.assertNotIn("<a:spcAft", last, "the last item must not add space after itself")
        self.assertIn('<a:buChar char="\u25aa" />', middle)
        self.assertIn('val="C2410C"', middle)

    def test_preserve_terms_keeps_explicit_list_in_572_by_226_box(self):
        ir = styled_deck()
        layout, issues = in_feedback_box(ir)
        self.assertFalse([i for i in issues if i['severity'] == 'FAIL'], issues)
        element = next(e for e in layout['slides'][0]['elements'] if e['id'] == 'awards')
        self.assertEqual(element['kind'], 'list')
        self.assertEqual(element['source_text'], BODY)
        self.assertLessEqual(element['bbox'][3], 226)
        self.assertEqual(element['contract']['font_floor'], 24)
        self.assertNotIn('TEXT_FLOW_FALLBACK', [i['rule'] for i in issues])

    def test_takeaway_and_blocks_have_independent_marker_styles_and_colors(self):
        ir = styled_deck([{**block('a', 'body', BODY), 'text_flow': 'distributed_arrow_list',
                           'bullet_style': 'arrow', 'bullet_color': '#005A9C'},
                          {**block('b', 'body', BODY), 'text_flow': 'distributed_arrow_list'}])
        ir['presentation'].update(bullet_style='check', bullet_color='#7C3AED')
        layout, issues = in_feedback_box(ir)
        self.assertFalse([i for i in issues if i['severity'] == 'FAIL'], issues)
        elements = {e['id']: e for e in layout['slides'][0]['elements']}
        self.assertEqual(elements['takeaway']['bullet']['style'], 'large_diamond')
        self.assertEqual(elements['takeaway']['bullet']['color'], '#000000')
        self.assertEqual(elements['a']['bullet']['style'], 'arrow')
        self.assertEqual(elements['a']['bullet']['color'], '#005A9C')
        self.assertEqual(elements['b']['bullet']['style'], 'check')
        self.assertEqual(elements['b']['bullet']['color'], '#7C3AED')
        self.assertEqual(elements['a']['color'], elements['b']['color'])
        self.assertNotEqual(elements['a']['color'], elements['a']['bullet']['color'])

    def test_vertical_overflow_preserves_all_list_rows_and_markers(self):
        ir = styled_deck()
        source = '\n'.join([row*6 for row in BODY.splitlines()])
        ir['slides'][0]['composition']['blocks'][0]['text'] = source
        layout, issues = in_feedback_box(ir)
        self.assertFalse([i for i in issues if i['severity'] == 'FAIL'], issues)
        element = next(e for e in layout['slides'][0]['elements'] if e['id'] == 'awards')
        self.assertEqual(element['kind'], 'list')
        self.assertEqual(element['source_text'], source)
        self.assertEqual([''.join(lines).replace(' ', '') for lines in element['items']],
                         [row.replace(' ', '') for row in source.splitlines()])
        self.assertGreater(element['bbox'][3], 226)
        self.assertEqual(element['contract']['font_size'], 24)
        self.assertIn('SCIENTIFIC_TEXT_OVERFLOW', [i['rule'] for i in issues])
        ir['presentation']['text_capacity_policy'] = 'strict'
        ir['slides'][0]['composition']['blocks'][0]['text'] = '\n'.join([row*2 for row in BODY.splitlines()])
        _, issues = in_feedback_box(ir)
        self.assertTrue(any(i['rule'] == 'SPLIT_REQUIRED' and i['severity'] == 'FAIL' for i in issues))

    def test_small_explicit_list_fails_instead_of_losing_bullets(self):
        _, issues = in_feedback_box(styled_deck(), 519, 219)
        self.assertTrue(any(i['rule'] == 'SPLIT_REQUIRED' and i['severity'] == 'FAIL' for i in issues))
        self.assertNotIn('TEXT_FLOW_FALLBACK', [i['rule'] for i in issues])

    def test_invalid_marker_and_color_inputs_are_structured_errors(self):
        for target, value, rule in [('global', '#123', 'BULLET_COLOR_INVALID'),
                                    ('block', 'red', 'BULLET_COLOR_INVALID'),
                                    ('takeaway', {'style': 'star'}, 'TAKEAWAY_MARKER_INVALID'),
                                    ('takeaway', {'style': 'diamond', 'color': []}, 'BULLET_COLOR_INVALID')]:
            ir = styled_deck()
            if target == 'global': ir['presentation']['bullet_color'] = value
            if target == 'block': ir['slides'][0]['composition']['blocks'][0]['bullet_color'] = value
            if target == 'takeaway': ir['slides'][0]['presentation']['takeaway_marker'] = value
            self.assertIn(rule, [i['rule'] for i in validate(ir)])
        ir = styled_deck(); ir['slides'][0]['composition']['blocks'][0]['text'] = 'Only one row.'
        self.assertIn('TEXT_FLOW_INVALID', [i['rule'] for i in validate(ir)])

    def test_scientific_decimal_values_and_negative_signs_are_not_bullet_prefixes(self):
        rows = ['1.25 nm is the measured displacement.', '-0.5 eV is the reference energy.',
                '3.14 rad is the reported phase.']
        self.assertEqual(split_parallel_items('\n'.join(rows)), rows)

    def test_takeaway_marker_reserves_width_and_keeps_inline_math(self):
        ir = styled_deck([{**block('context', 'body', 'Context stays complete.'), 'text_flow': 'plain'}])
        sem = ir['slides'][0]['semantic']
        sem['takeaway'] = ('完整各向异性介电响应张量与 $\\sqrt{1+x^2}$ 的关系保持原文。')*3
        sem['inline_math'] = ['takeaway']
        layout, issues = compile_deck(ir, ROOT)
        self.assertFalse([i for i in issues if i['severity'] == 'FAIL'], issues)
        element = next(e for e in layout['slides'][0]['elements'] if e['id'] == 'takeaway')
        self.assertEqual(element['source_text'], sem['takeaway'])
        root = ET.fromstring(element['inline_xml'])
        ns = {'a': 'http://schemas.openxmlformats.org/drawingml/2006/main'}
        self.assertEqual(len(root.findall('.//a:buChar', ns)), 1)
        self.assertGreater(len(element['inline_layout']['lines']), 1)
        self.assertTrue(all(line['width'] <= element['bbox'][2]-42+.01 for line in element['inline_layout']['lines']))

    def test_recursive_regions_measure_explicit_list_width_and_height(self):
        ir = styled_deck([{**block(name, 'body', BODY), 'text_flow': 'distributed_arrow_list'} for name in ('a', 'b')])
        comp = ir['slides'][0]['composition']
        comp['archetype'] = 'composite-research'
        comp['layout_tree'] = {'version': '1.0', 'regions': {'body': {'id': 'columns', 'type': 'columns',
            'children': [{'id': name+'-leaf', 'type': 'block', 'ref': name} for name in ('a', 'b')]}}}
        layout, issues = compile_deck(ir, ROOT)
        self.assertFalse([i for i in issues if i['severity'] == 'FAIL'], issues)
        lists = [e for e in layout['slides'][0]['elements'] if e['id'] in ('a','b')]
        self.assertTrue(all(e['kind'] == 'list' for e in lists))
        self.assertTrue(all(e['layout_region'][2] == 572 and e['layout_region'][3] >= 220 for e in lists))
        comp['blocks'].append({**block('c', 'body', BODY), 'text_flow': 'distributed_arrow_list'})
        comp['layout_tree']['regions']['body']['children'].append({'id': 'c-leaf', 'type': 'block', 'ref': 'c'})
        _, issues = compile_deck(ir, ROOT)
        self.assertIn('INSUFFICIENT_LIST_SPACE', [i['rule'] for i in issues])

    def test_generic_overflow_repair_preserves_native_list_item_boundaries(self):
        from deck_compiler.overflow_repair import repair_overflow
        ir = styled_deck(); ir['presentation']['text_capacity_policy'] = 'strict'
        layout, _ = in_feedback_box(ir)
        qa = {'items': [{'rule':'OFFICECLI_FORMAT','severity':'WARNING','slide':1,'shape':'/slide[1]/shape[@id=1]',
                        'message':'text overflow: 3 lines at 18pt need 160pt, usable 30pt.'}]}
        fixed, changed = repair_overflow(ir, layout, qa)
        self.assertFalse(changed)
        self.assertEqual(fixed, ir)

    @unittest.skipUnless(shutil.which('officecli'), 'OfficeCLI required')
    def test_native_styles_colors_and_single_takeaway_marker_roundtrip(self):
        import jsonschema
        ir = styled_deck()
        ir['slides'][0]['semantic']['takeaway'] = 'Complete scientific terminology remains editable. '*5
        ir['slides'][0]['composition']['blocks'][0].update(bullet_style='arrow', bullet_color='#007F66')
        jsonschema.validate(ir, json.loads((ROOT/'schemas/deck-ir.schema.json').read_text()))
        layout, issues = in_feedback_box(ir)
        self.assertFalse([i for i in issues if i['severity'] == 'FAIL'], issues)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); output = root/'candidate.pptx'
            write_json(root/'layout.json', layout)
            render(root/'layout.json', output, shutil.which('officecli'))
            self.assertFalse([i for i in verify(output, layout) if i['severity'] == 'FAIL'])
            with zipfile.ZipFile(output) as source: parts = {n: source.read(n) for n in source.namelist()}
            slide = ET.fromstring(parts['ppt/slides/slide1.xml'])
            ns = {'a': 'http://schemas.openxmlformats.org/drawingml/2006/main',
                  'p': 'http://schemas.openxmlformats.org/presentationml/2006/main'}
            takeaway = next(s for s in slide.findall('.//p:sp', ns)
                            if s.find('p:nvSpPr/p:cNvPr', ns).get('name') == 'takeaway')
            self.assertEqual(len(takeaway.findall('.//a:buChar', ns)), 1)
            self.assertTrue(takeaway.findall('.//a:br', ns))
            self.assertFalse(slide.findall('.//a:buSzPct', ns), 'Large markers are native glyph choices, not percentage scaling')
            self.assertFalse(slide.findall('.//a:buSzPts', ns))
            award = next(s for s in slide.findall('.//p:sp', ns)
                         if s.find('p:nvSpPr/p:cNvPr', ns).get('name') == 'awards')
            award.find('.//a:buClr/a:srgbClr', ns).set('val', 'FF0000')
            parts['ppt/slides/slide1.xml'] = ET.tostring(slide)
            corrupt = root/'corrupt.pptx'
            with zipfile.ZipFile(corrupt, 'w') as target:
                for name, data in parts.items(): target.writestr(name, data)
            self.assertIn('LIST_BULLET_MISMATCH', [i['rule'] for i in verify(corrupt, layout)])


if __name__ == "__main__":
    unittest.main()
