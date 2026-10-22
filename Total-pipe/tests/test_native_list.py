"""Native PowerPoint bullets: one marker style per deck, written as paragraph properties.

The list is no longer a panel plus one shape per row. Each item is a paragraph with a:buChar and
a:buClr, so PowerPoint itself draws the marker, Tab changes the level and the bullet menu shows the
current style. These tests pin the three things that made the old approach wrong: the marker must be
one glyph for the whole deck, it must be tinted differently from the body text, and the XML written
for each paragraph has to keep DrawingML's element order (lnSpc → spcAft → buClr → buFont → buChar).
"""
import unittest

from deck_compiler.contracts import TextBoxContract
from deck_compiler.layout import DEFAULT_ACCENT, compile_deck
from deck_compiler.officecli import list_paragraph_properties

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


class NativeListTests(unittest.TestCase):
    def compile_lists(self, ir):
        layout, issues = compile_deck(ir, ROOT)
        self.assertFalse([i for i in issues if i["severity"] == "FAIL"], issues)
        return [element for element in layout["slides"][0]["elements"] if element["kind"] == "list"]

    def test_one_marker_style_for_the_whole_deck(self):
        lists = self.compile_lists(list_deck([block("a", "body", BODY),
                                             block("b", "conclusion", BODY)]))
        self.assertEqual(len(lists), 2)
        self.assertEqual({element["bullet"]["style"] for element in lists}, {"square"})
        self.assertEqual({element["bullet"]["char"] for element in lists}, {"\u25aa"})

    def test_procedure_deck_prefers_an_arrow_marker(self):
        lists = self.compile_lists(list_deck([block("a", "process-step", PROCEDURE)]))
        self.assertEqual(lists[0]["bullet"]["style"], "arrow")
        self.assertEqual(lists[0]["bullet"]["char"], "\u2192")

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


if __name__ == "__main__":
    unittest.main()
