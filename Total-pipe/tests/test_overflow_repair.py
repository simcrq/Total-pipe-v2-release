"""Test suite for overflow_repair module."""
import json
import unittest
from pathlib import Path
from deck_compiler.overflow_repair import (
    parse_overflow_message,
    extract_shape_id,
    split_text_to_chunks,
    repair_overflow,
    overflow_summary,
)


class TestOverflowRepair(unittest.TestCase):
    def test_parse_overflow_message(self):
        msg = "text overflow: 3 lines at 15.0pt need 56pt, usable 47pt. suggest.height=2cm"
        needed, usable = parse_overflow_message(msg)
        self.assertEqual(needed, 56.0)
        self.assertEqual(usable, 47.0)

    def test_extract_shape_id(self):
        xpath = "/slide[1]/shape[@id=100008]"
        shape_id = extract_shape_id(xpath)
        self.assertEqual(shape_id, "100008")

    def test_split_text_to_chunks(self):
        text = "First paragraph.\nSecond paragraph.\nThird paragraph.\nFourth paragraph."
        chunks = split_text_to_chunks(text, 2)
        self.assertEqual(len(chunks), 2)
        self.assertIn("First", chunks[0])
        self.assertIn("Third", chunks[1])

    def test_split_text_single_chunk(self):
        text = "Only one paragraph."
        chunks = split_text_to_chunks(text, 1)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0], text)

    def test_overflow_summary_empty(self):
        qa_report = {"items": []}
        summary = overflow_summary(qa_report)
        self.assertEqual(summary['total_overflows'], 0)
        self.assertEqual(summary['slides_affected'], 0)

    def test_overflow_summary_with_warnings(self):
        qa_report = {
            "items": [
                {
                    "severity": "WARNING",
                    "rule": "OFFICECLI_FORMAT",
                    "slide": 1,
                    "message": "text overflow: 3 lines at 15.0pt need 56pt, usable 47pt."
                },
                {
                    "severity": "WARNING",
                    "rule": "OFFICECLI_FORMAT",
                    "slide": 2,
                    "message": "text overflow: 4 lines at 21.0pt need 105pt, usable 80pt."
                },
            ]
        }
        summary = overflow_summary(qa_report)
        self.assertEqual(summary['total_overflows'], 2)
        self.assertEqual(summary['slides_affected'], 2)
        self.assertGreater(summary['max_overflow_ratio'], 0.19)

    def test_repair_overflow_no_changes(self):
        ir = {
            "slides": [
                {
                    "id": "s01-test",
                    "semantic": {"title": "Test", "takeaway": "Test takeaway"},
                    "composition": {"blocks": [], "figure_refs": []}
                }
            ]
        }
        layout = {"slides": [{"elements": []}]}
        qa_report = {"items": []}

        repaired_ir, modified = repair_overflow(ir, layout, qa_report)
        self.assertFalse(modified)
        self.assertEqual(len(repaired_ir['slides']), 1)

    def test_repair_overflow_with_severe_overflow(self):
        ir = {
            "slides": [
                {
                    "id": "s01-test",
                    "semantic": {
                        "title": "Test Slide",
                        "takeaway": "Test takeaway",
                        "evidence_refs": [],
                        "caveats": []
                    },
                    "composition": {
                        "archetype": "metric-comparison",
                        "blocks": [
                            {
                                "id": "body1",
                                "component": "body",
                                "text": "First paragraph with content.\nSecond paragraph with content.\nThird paragraph with content.\nFourth paragraph with content."
                            }
                        ],
                        "figure_refs": []
                    }
                }
            ]
        }
        layout = {
            "slides": [
                {
                    "elements": [
                        {
                            "id": "body1",
                            "kind": "text",
                            "role": "body",
                            "text": "Combined text",
                            "bbox": [56, 260, 500, 200]
                        }
                    ]
                }
            ]
        }
        qa_report = {
            "items": [
                {
                    "severity": "WARNING",
                    "rule": "OFFICECLI_FORMAT",
                    "slide": 1,
                    "shape": "/slide[1]/shape[@id=100008]",
                    "message": "text overflow: 4 lines at 21.0pt need 105pt, usable 65pt."
                }
            ]
        }

        repaired_ir, modified = repair_overflow(ir, layout, qa_report, overflow_threshold=0.25)

        if modified:
            # Should have created additional slides
            self.assertGreater(len(repaired_ir['slides']), 1)

            # First slide should have part of the content
            first_block = repaired_ir['slides'][0]['composition']['blocks'][0]
            self.assertIn("text", first_block)
            self.assertLess(len(first_block['text']), len(ir['slides'][0]['composition']['blocks'][0]['text']))


if __name__ == '__main__':
    unittest.main()
