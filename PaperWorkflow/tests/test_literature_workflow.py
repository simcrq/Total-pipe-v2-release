import json
import tempfile
import unittest
from pathlib import Path

from utils.literature_workflow import (
    audit_extraction,
    audit_quantities,
    build_evidence_queries,
    build_literature_workflow,
    discover_related_documents,
    extract_metadata,
)
from utils.paper_tools import search_markdown


class LiteratureWorkflowTests(unittest.TestCase):
    def test_build_workflow_writes_traceable_handoff_artifacts(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "paper.md"
            supplement = root / "paper-supplement.pdf"
            images = root / "images"
            images.mkdir()
            (images / "figure-1.png").write_bytes(b"png-data")
            (root / "cover.svg").write_text("<svg/>", encoding="utf-8")
            output = root / "output"
            source.write_text(
                "# A traceable paper\n"
                "DOI: 10.1234/example.1\n\n"
                "# Abstract\nWe test a Raman spectroscopy workflow.\n\n"
                "# Methods\nThe sample was measured by Raman spectroscopy at 300 K.\n\n"
                f"# Results\n![Cover]({(root / 'cover.svg').resolve()})\n"
                "![Raman result](images/figure-1.png)\n"
                "The Raman peak shifted by 4 cm-1 and the result was reproducible.\n\n"
                "# Conclusion\nThe measurement supports the proposed mechanism.\n",
                encoding="utf-8",
            )
            supplement.write_bytes(b"%PDF-test")

            result = build_literature_workflow(
                markdown_path=source,
                source_path=source,
                project_root=root,
                output_dir=output,
                custom_queries=["sample measured Raman spectroscopy"],
                include_default_queries=False,
                top_k=3,
                chunk_chars=600,
            )

            self.assertEqual(result["schema_version"], 4)
            self.assertEqual(result["metadata"]["dois"], ["10.1234/example.1"])
            self.assertEqual(result["evidence"][0]["results"][0]["heading"], "Methods")
            self.assertEqual(result["related_documents"][0]["role"], "supplementary_candidate")
            self.assertTrue(
                (output / result["artifacts"]["workflow_manifest_path"]).is_file()
            )
            self.assertIn("retrieval", result["quality_dimensions"])
            self.assertIn("synthesis_readiness", result)
            self.assertTrue(result["evidence_registry"])
            self.assertIn(
                "support_span_exposure",
                {item["gate"] for item in result["synthesis_readiness"]["gates"]},
            )
            self.assertIn("required_claim_fields", result["claim_ledger_contract"])
            self.assertTrue(
                (output / result["artifacts"]["document_manifest_path"]).is_file()
            )
            self.assertTrue((output / result["artifacts"]["evidence_report_path"]).is_file())
            self.assertEqual(result["source"]["markdown_path"], "paper.md")
            self.assertTrue((output / "images" / "figure-1.png").is_file())
            self.assertTrue((output / "cover.svg").is_file())
            bundle_manifest = json.loads(
                (output / "bundle.manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(bundle_manifest["contract"], "total-pipe.paperworkflow-v4")
            self.assertEqual(bundle_manifest["entrypoint"], "workflow.json")
            self.assertIn(
                "figure_asset",
                {item["role"] for item in bundle_manifest["files"]},
            )
            for publishable in (
                output / "workflow.json",
                output / "document.manifest.json",
                output / "evidence.md",
                output / "bundle.manifest.json",
                output / "paper.md",
            ):
                self.assertNotIn(
                    str(root.resolve()),
                    publishable.read_text(encoding="utf-8"),
                )
            persisted = json.loads((output / "workflow.json").read_text(encoding="utf-8"))
            self.assertEqual(persisted["workflow_id"], result["workflow_id"])
            self.assertIn("line ranges", persisted["handoff"]["instruction"])

    def test_audit_marks_unusable_short_ocr_for_review(self):
        audit = audit_extraction("broken \ufffd text", chunk_count=1)
        codes = {warning["code"] for warning in audit["warnings"]}
        self.assertEqual(audit["readiness"], "blocked")
        self.assertIn("document_too_short", codes)
        self.assertIn("no_headings", codes)
        self.assertIn("replacement_characters_high", codes)

    def test_title_extraction_skips_layout_boilerplate(self):
        metadata = extract_metadata(
            "# ARTICLE TYPE\n\n# A Real Scientific Paper Title\n\n# 1 Introduction\nText.",
            Path("full.md"),
        )
        self.assertEqual(metadata["title_guess"], "A Real Scientific Paper Title")

    def test_default_and_custom_queries_are_addressable(self):
        queries = build_evidence_queries(["coercive field"], include_defaults=True)
        self.assertEqual(queries[0]["query_id"], "objective")
        self.assertEqual(queries[-1]["query_id"], "custom-01")
        self.assertEqual(queries[-1]["query"], "coercive field")

    def test_chinese_sample_question_is_expanded_and_ranks_methods(self):
        markdown = (
            "# Methods\n"
            "PS nanoparticles were synthesized by emulsion polymerization, then printed and cured.\n\n"
            "# Data availability\nAll performance data are available in the paper."
        )
        query = build_evidence_queries(
            ["样品如何制备？样品制备方法、合成流程"], include_defaults=False
        )[0]
        results = search_markdown(
            markdown,
            query["expanded_query"],
            intent=query["intent"],
        )
        self.assertEqual(query["intent"], "sample_preparation")
        self.assertTrue(query["language_bridge_applied"])
        self.assertEqual(results[0]["heading"], "Methods")

    def test_key_results_deprioritize_data_availability(self):
        markdown = (
            "# Results\nThe device achieves high stability and 98 percent yield.\n\n"
            "# Data availability\nAll performance data and results are available."
        )
        query = build_evidence_queries(
            ["Key results and performance data"], include_defaults=False
        )[0]
        results = search_markdown(
            markdown,
            query["expanded_query"],
            intent=query["intent"],
        )
        self.assertEqual(results[0]["heading"], "Results")
        self.assertNotIn("Data availability", {item["heading"] for item in results})

    def test_related_documents_require_a_filename_relationship(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "Li.pdf"
            source.write_bytes(b"main")
            (root / "Li-supplement.pdf").write_bytes(b"supp")
            (root / "e1.pdf").write_bytes(b"unrelated")
            nested = root / "4668"
            nested.mkdir()
            (nested / "other.pdf").write_bytes(b"unrelated")

            related = discover_related_documents(source, root)

            self.assertEqual([Path(item["path"]).name for item in related], ["Li-supplement.pdf"])
            self.assertEqual(related[0]["match_reason"], "supplement_filename")

    def test_quantity_audit_preserves_differing_temperature_ranges(self):
        audit = audit_quantities(
            "The hotplate ranged from 50 to 250 °C.\n"
            "The figure reports stability from -18 to 240 °C."
        )
        self.assertEqual(audit["readiness"], "review")
        self.assertEqual(len(audit["temperature_ranges"]), 2)
        self.assertEqual(audit["warnings"][0]["code"], "multiple_temperature_ranges")


if __name__ == "__main__":
    unittest.main()
