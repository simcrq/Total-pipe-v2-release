"""Regression tests for enhanced numeric, bilingual, figure-ref, and formula evidence retrieval."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from utils.evidence_graph import expand_query_terms, search_spans, terms


SAMPLE_PAPER = """# Title
Field-modulated photonic transport study

# Abstract
We achieve an accuracy of 98.58% at 300 K with a 15nm dielectric barrier.

# Methods
Samples were prepared via atomic layer deposition on silicon wafers at 300 K.
Independent baseline control devices without the barrier were measured under identical bias.

# Theoretical Model
The effective barrier conductance obeys the analytical relation:

$$G(V) = G_0 \\exp\\left(-\\frac{\\Phi_B - \\alpha V}{k_B T}\\right)$$

In Fig. 3a, the exponential slope matches Eq. 2 across three orders of magnitude.

# Limitations and Discussion
Performance degrades above 350 K due to thermal leakage; the sample size limits generalization.
"""


class EnhancedEvidenceSearchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.md = Path(self.tmp.name) / "paper.md"
        self.md.write_text(SAMPLE_PAPER, encoding="utf-8")

    def test_terms_capture_numeric_units_and_refs(self):
        toks = terms("See Fig. 3a and Eq. 2 with 98.58% yield at 15nm thickness.")
        self.assertIn("98.58%", toks)
        self.assertIn("98.58", toks)
        self.assertIn("15nm", toks)
        self.assertIn("15", toks)
        self.assertIn("fig:3a", toks)
        self.assertIn("eq:2", toks)

    def test_bilingual_query_expansion_matches_english_paper(self):
        expanded = expand_query_terms("对照实验 基线 误差 局限")
        self.assertIn("control", expanded)
        self.assertIn("baseline", expanded)
        self.assertIn("limitation", expanded)

        hits = search_spans(self.md, "对照基线实验", top_k=3)
        self.assertTrue(hits)
        self.assertTrue(any("baseline control" in h["snippet"].lower() for h in hits), hits)

        lim_hits = search_spans(self.md, "局限 适用条件", top_k=3)
        self.assertTrue(lim_hits)
        self.assertTrue(any("350 k" in h["snippet"].lower() or "limits generalization" in h["snippet"].lower() for h in lim_hits), lim_hits)

    def test_numeric_and_fig_ref_queries_rank_exact_passages(self):
        num_hits = search_spans(self.md, "98.58% 15nm", top_k=3)
        self.assertTrue(num_hits)
        self.assertIn("98.58%", num_hits[0]["snippet"])

        ref_hits = search_spans(self.md, "Fig. 3a Eq. 2", top_k=3)
        self.assertTrue(ref_hits)
        self.assertIn("Fig. 3a", ref_hits[0]["snippet"])

    def test_formula_modality_and_section_filters(self):
        formula_hits = search_spans(self.md, "公式 推导 conductance", top_k=4, modality="formula")
        self.assertTrue(formula_hits, "Formula spans should be searchable when modality='formula'")
        self.assertTrue(any("\\Phi_B" in h["snippet"] for h in formula_hits), formula_hits)

        methods_only = search_spans(self.md, "300 K", top_k=5, section="Methods")
        self.assertTrue(methods_only)
        self.assertTrue(all("methods" in (h["heading"] or "").lower() for h in methods_only), methods_only)


if __name__ == "__main__":
    unittest.main()
