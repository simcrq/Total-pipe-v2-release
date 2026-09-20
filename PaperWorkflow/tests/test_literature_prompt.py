import tempfile
import unittest
from pathlib import Path

from utils.literature_prompt import (
    build_prompt_builder_result,
    build_workflow_prompt,
    index_input_pdfs,
    resolve_pdf_selection,
)


class LiteraturePromptTests(unittest.TestCase):
    def test_recursive_index_contains_only_relative_pdf_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "INput"
            nested = root / "4668"
            nested.mkdir(parents=True)
            (root / "Li.pdf").write_bytes(b"li")
            (nested / "paper.PDF").write_bytes(b"paper")
            (nested / "notes.md").write_text("ignore", encoding="utf-8")

            index = index_input_pdfs(root)

            self.assertEqual(
                [item["relative_path"] for item in index],
                ["4668/paper.PDF", "Li.pdf"],
            )
            self.assertEqual(
                [item["selection_id"] for item in index],
                ["P001", "P002"],
            )
            self.assertTrue(
                all(not item["relative_path"].startswith("/") for item in index)
            )
            self.assertTrue(
                all(
                    item["project_relative_path"].startswith("INput/")
                    for item in index
                )
            )

    def test_selection_id_generates_prompt_with_project_relative_path(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "INput"
            root.mkdir()
            (root / "Li.pdf").write_bytes(b"li")

            result = build_prompt_builder_result(
                root,
                selected_pdf="P001",
                research_goal="解释结构色的物理机制",
                focus_questions=["样品如何制备？", "物理图像是什么？"],
            )

            self.assertEqual(result["mode"], "prompt_ready")
            self.assertEqual(result["selected_pdf"]["relative_path"], "Li.pdf")
            self.assertIn("INput/Li.pdf", result["prompt"])
            self.assertIn("解释结构色的物理机制", result["prompt"])
            self.assertNotIn(str(root), result["prompt"])

    def test_selection_accepts_input_prefixed_relative_path(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "INput"
            nested = root / "group"
            nested.mkdir(parents=True)
            pdf = nested / "paper.pdf"
            pdf.write_bytes(b"pdf")

            resolved, relative = resolve_pdf_selection(
                root,
                "INput/group/paper.pdf",
            )

            self.assertEqual(resolved, pdf.resolve())
            self.assertEqual(relative, "group/paper.pdf")

    def test_selection_rejects_path_traversal(self):
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            root = parent / "INput"
            root.mkdir()
            (parent / "outside.pdf").write_bytes(b"outside")

            with self.assertRaisesRegex(ValueError, "inside INput"):
                resolve_pdf_selection(root, "../outside.pdf")

    def test_default_prompt_contains_evidence_contract_requirements(self):
        prompt = build_workflow_prompt("Li.pdf")

        self.assertIn("paperworkflow_literature_workflow", prompt)
        self.assertIn("claim_ledger_contract", prompt)
        self.assertIn("synthesis_readiness", prompt)
        self.assertIn("E###", prompt)


if __name__ == "__main__":
    unittest.main()
