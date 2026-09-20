import tempfile
import unittest
from pathlib import Path

from utils.literature_workflow import audit_extraction, build_literature_workflow
from utils.paper_tools import document_manifest, search_markdown
from utils.workflow_audits import (
    audit_quantities_enhanced,
    audit_source_dependencies,
    audit_structure_enhanced,
    build_evidence_registry,
    synthesis_gate,
)


class EvidenceGraphV4Tests(unittest.TestCase):
    def test_layout_heading_inherits_semantic_owner_and_empty_container_is_explicit(self):
        markdown = (
            "# Real paper title\n\n"
            "The model has a hemispherical\n\n"
            "## Article\n\n"
            "configuration with a photonic lattice.\n\n"
            "## Methods\n\n"
            "## Materials\nReagent A was used.\n"
        )
        manifest = document_manifest(markdown, chunk_chars=600)
        article = next(item for item in manifest["chunks"] if item["heading"] == "Article")
        methods = next(item for item in manifest["chunks"] if item["heading"] == "Methods")

        self.assertEqual(manifest["schema_version"], 2)
        self.assertEqual(article["heading_kind"], "boilerplate")
        self.assertEqual(article["semantic_heading"], "Real paper title")
        self.assertTrue(methods["empty_node"])

    def test_retrieval_returns_matching_local_span_not_chunk_prefix(self):
        markdown = (
            "# Results\n"
            "This opening sentence only describes administration. "
            "Several unrelated details follow. "
            "The decisive Raman peak shifted by 4 cm-1 after cooling."
        )
        result = search_markdown(markdown, "decisive Raman peak shifted cooling", top_k=1)[0]

        self.assertIn("Raman peak shifted", result["snippet"])
        self.assertNotIn("administration", result["snippet"])
        self.assertEqual(result["supporting_spans"][0]["source_chars"]["start"], result["char_start"])

    def test_evidence_registry_deduplicates_text_across_queries(self):
        span = {
            "span_id": "S0001",
            "chunk_id": "E001",
            "source_lines": {"start": 2, "end": 2},
            "source_chars": {"start": 10, "end": 40},
            "modality": "body_text",
            "support_type": "measurement",
            "text": "The measured peak shifted by 4 cm-1.",
        }
        result = {
            "chunk_id": "E001",
            "span_id": "S0001",
            "heading": "Results",
            "line_start": 2,
            "line_end": 2,
            "char_start": 10,
            "char_end": 40,
            "score": 10.0,
            "relevance": "high",
            "section_fit": "preferred",
            "snippet": span["text"],
            "supporting_spans": [span],
        }
        groups = [
            {"query_id": "q1", "results": [result]},
            {"query_id": "q2", "results": [result]},
        ]
        registry = build_evidence_registry(groups)

        self.assertEqual(len(registry), 1)
        self.assertEqual(groups[0]["evidence_ids"], groups[1]["evidence_ids"])
        self.assertNotIn("snippet", groups[0]["results"][0])
        self.assertEqual(registry[0]["query_ids"], ["q1", "q2"])

    def test_reading_order_and_chunk_coherence_are_independent_from_capture(self):
        markdown = (
            "# A complete scientific title\n"
            "10.1234/example\n\n"
            "The device has a hemispherical\n\n"
            "## Article\n\n"
            "configuration that confines light,\n"
            "![](images/a.jpg)\n"
            "Fig. 1 | A caption.\n\n"
            "whereas the centre remains stable.\n\n"
            "## Methods\nThe sample was prepared.\n\n"
            "## Conclusion\nThe result is reproducible.\n"
        )
        manifest = document_manifest(markdown, chunk_chars=600)
        extraction = audit_extraction(markdown, manifest["chunk_count"])
        structure = audit_structure_enhanced(markdown, extraction, manifest)

        self.assertNotEqual(extraction["score"], structure["reading_order_integrity"]["score"])
        self.assertEqual(structure["readiness"], "review")
        self.assertTrue(structure["reading_order_integrity"]["heading_interruptions"])
        self.assertTrue(structure["chunk_coherence"]["mixed_chunks"])

    def test_extended_data_caption_has_figure_parent(self):
        markdown = (
            "# Results\nText.\n\n"
            "## Article\n"
            "![](images/a.jpg)  \n"
            "Extended Data Fig. 6 | Stability tests of the sample. "
            "a, The sample survives ultraviolet exposure.\n"
        )
        manifest = document_manifest(markdown, chunk_chars=600)
        caption_spans = [item for item in manifest["spans"] if item["parent_figure"]]
        article = next(item for item in manifest["chunks"] if item["heading"] == "Article")

        self.assertTrue(any(item["parent_figure"] == "Extended Data Fig. 6" for item in caption_spans))
        self.assertIn("Extended Data Fig. 6", article["figure_parents"])
        self.assertEqual(article["semantic_heading"], "Extended Data Fig. 6")

    def test_quantity_relations_and_symbol_drift_require_review(self):
        markdown = (
            "Printing speed (2 mm s $^{-1}$); winding speed "
            "(synchronized with the printing speed, 3 mm s $^{-1}$).\n"
            "$D_{n}$ is the photonic lattice constant, 220 nm.\n"
            "A library varies nanoparticle size ($D_{n}$) from 180 to 240 nm.\n"
        )
        audit = audit_quantities_enhanced(markdown)
        codes = {item["code"] for item in audit["warnings"]}

        self.assertIn("potential_relational_inconsistency", codes)
        self.assertIn("symbol_definition_drift", codes)
        self.assertEqual(audit["readiness"], "review")

    def test_missing_supplement_is_detected_and_fails_gate(self):
        markdown = "# Results\nThe mechanism is detailed in Supplementary Discussions and Supplementary Fig. 4."
        dependencies = audit_source_dependencies(markdown, [])
        extraction = {
            "score": 100,
            "readiness": "ready",
        }
        structure = {
            "score": 100,
            "reading_order_integrity": {"score": 100},
        }
        retrieval = {
            "score": 100,
            "readiness": "ready",
            "support_span_exposure_ratio": 1.0,
            "mean_coverage_ratio": 1.0,
        }
        quantities = {"score": 100, "readiness": "ready"}
        gate = synthesis_gate(extraction, structure, retrieval, quantities, dependencies)

        self.assertGreater(dependencies["missing_required_count"], 0)
        self.assertEqual(gate["readiness"], "review")
        self.assertEqual(gate["mechanism_completeness"], "partial")

    def test_workflow_uses_query_registry_and_hard_gates(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "paper.md"
            source.write_text(
                "# Paper title\n\n"
                "## Methods\nThe sample was prepared by thermal curing.\n\n"
                "## Results\nThe sample remained stable after testing.\n\n"
                "## Conclusion\nThe result supports the mechanism.\n",
                encoding="utf-8",
            )
            workflow = build_literature_workflow(
                markdown_path=source,
                source_path=source,
                project_root=root,
                output_dir=root / "out",
                custom_queries=["关键结果是什么？", "最关键结果是什么？"],
                include_default_queries=False,
                top_k=5,
                chunk_chars=600,
            )

            self.assertEqual(workflow["schema_version"], 4)
            self.assertEqual(workflow["evidence"][0]["canonical_query_id"], workflow["evidence"][1]["canonical_query_id"])
            texts = [item["text"] for item in workflow["evidence_registry"]]
            self.assertEqual(len(texts), len(set(texts)))
            self.assertTrue(all(item["evidence_ids"] for item in workflow["evidence"] if item["results"]))
            self.assertIn("gates", workflow["synthesis_readiness"])

    def test_li_regression_exposes_known_layout_and_dependency_risks(self):
        root = Path(__file__).resolve().parents[1]
        markdown_path = root / "temp_markdowns" / "de757544d02c10b7" / "Li.md"
        if not markdown_path.is_file():
            self.skipTest("Li Markdown regression fixture is not available")
        markdown = markdown_path.read_text(encoding="utf-8")
        manifest = document_manifest(markdown, chunk_chars=6000)
        extraction = audit_extraction(markdown, manifest["chunk_count"])
        structure = audit_structure_enhanced(markdown, extraction, manifest)
        quantities = audit_quantities_enhanced(markdown)
        dependencies = audit_source_dependencies(markdown, [])

        self.assertEqual(structure["semantic_structure_integrity"]["fake_heading_count"], 7)
        self.assertIn("E005", {item["chunk_id"] for item in structure["chunk_coherence"]["mixed_chunks"]})
        self.assertIn("E033", {item["chunk_id"] for item in structure["chunk_coherence"]["mixed_chunks"]})
        self.assertEqual(structure["reading_order_integrity"]["readiness"], "review")
        self.assertIn("potential_relational_inconsistency", {item["code"] for item in quantities["warnings"]})
        self.assertIn("symbol_definition_drift", {item["code"] for item in quantities["warnings"]})
        self.assertGreater(dependencies["missing_required_count"], 0)


if __name__ == "__main__":
    unittest.main()
