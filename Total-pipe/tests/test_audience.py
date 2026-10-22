"""Presenter-side provenance stays off the page."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from deck_compiler import audience  # noqa: E402


class CaveatSplitTests(unittest.TestCase):
    def test_mixed_caveat_keeps_the_scientific_half(self):
        visible, moved = audience.split_caveats(
            ["文中接触对照转述自补充信息；本次没有 SI 可供独立核查。"])
        self.assertEqual(visible, ["文中接触对照转述自补充信息"])
        self.assertEqual(moved, ["本次没有 SI 可供独立核查。"])

    def test_scientific_caveat_stays_whole(self):
        caveat = "D* 按散粒噪声估算，未由完整噪声谱确认。"
        self.assertEqual(audience.split_caveats([caveat]), ([caveat], []))

    def test_paper_limitation_is_not_run_state(self):
        self.assertFalse(audience.is_run_state("作者未提供误差棒，样本仅三个器件。"))
        self.assertTrue(audience.is_run_state("本次输入仅有主文 PDF。"))

    def test_join_does_not_double_punctuation(self):
        self.assertEqual(audience.join_caveats(["确认。", "再按面积换算。"]), "确认。再按面积换算。")
        self.assertEqual(audience.join_caveats(["甲", "乙"]), "甲；乙")


class HitTests(unittest.TestCase):
    def test_evidence_ids_and_paths_are_hits(self):
        kinds = dict(audience.hits("EV0014 · tools/demo.py"))
        self.assertIn("evidence id", kinds)
        self.assertIn("repository path", kinds)

    def test_plain_scientific_copy_is_clean(self):
        self.assertEqual(audience.hits("R≈0.17 A/W，EQE≈42%，测试于 500 nm。"), [])

    def test_figure_reference_is_not_a_file_path(self):
        self.assertEqual(audience.hits("Fig. 2c 给出暗态 I–V。"), [])


if __name__ == "__main__":
    unittest.main()
