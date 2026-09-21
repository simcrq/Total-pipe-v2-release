import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from main import process_single_paper
from utils.agent_tools import get_document_outline, retrieve_evidence
from utils.paper_tools import search_markdown, split_markdown_sections
from utils.pdf_official_handler import OfficialMinerUProcessor
from utils.prompt_builder import PromptBuilder
from utils.workflow_utils import determine_mode, find_pdf_files


class CoreWorkflowTests(unittest.TestCase):
    def test_find_pdf_files_is_recursive_and_deterministic(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "4668" / "supplement").mkdir(parents=True)
            (root / "4668" / "main.PDF").write_bytes(b"pdf")
            (root / "4668" / "supplement" / "extra.pdf").write_bytes(b"pdf")
            (root / "loose.pdf").write_bytes(b"pdf")

            papers = find_pdf_files(root)

            self.assertEqual([paper["file_name"] for paper in papers], ["main.PDF", "extra.pdf"])
            self.assertEqual({paper["id"] for paper in papers}, {"4668"})

    def test_section_manifest_and_search_have_evidence_locations(self):
        markdown = "# Abstract\nA short abstract.\n\n# Methods\nWe used Raman spectroscopy.\n\n# Conclusions\nThe result is stable."
        chunks = split_markdown_sections(markdown, max_chars=600)
        self.assertEqual([chunk["chunk_id"] for chunk in chunks], ["E001", "E002", "E003"])
        results = search_markdown(markdown, "Raman spectroscopy")
        self.assertEqual(results[0]["heading"], "Methods")
        self.assertGreaterEqual(results[0]["line_start"], 4)

    def test_prompt_preserves_conclusion_when_document_is_long(self):
        markdown = "# Introduction\n" + ("context " * 500) + "\n\n# Conclusions\nThe decisive conclusion is retained."
        prompt = PromptBuilder.build_summary_prompt(markdown, mode="deep_read", max_chars=3000)
        self.assertIn("[E", prompt)
        self.assertIn("decisive conclusion", prompt)

    def test_mode_rules_accept_numeric_ids(self):
        rules = {"deep_read_ids": [4668], "skim_ids": ["4586"], "default_mode": "skim"}
        self.assertEqual(determine_mode("4668", rules), "deep_read")
        self.assertEqual(determine_mode(4586, rules), "skim")

    def test_official_cli_adapter_builds_precision_command(self):
        config = {
            "api": {
                "mineru": {
                    "mode": "official_cli",
                    "cli_command": "mineru-open-api",
                    "extract_mode": "precision",
                    "model": "vlm",
                    "timeout": 30,
                    "api_key": "token-for-child-process",
                }
            }
        }
        with tempfile.TemporaryDirectory() as tmp:
            pdf = Path(tmp) / "paper.pdf"
            pdf.write_bytes(b"pdf")
            with patch("utils.pdf_official_handler.subprocess.run") as run:
                run.return_value.returncode = 0
                run.return_value.stdout = ""
                run.return_value.stderr = ""
                OfficialMinerUProcessor(config).process(str(pdf), str(Path(tmp) / "out"))

                command = run.call_args.args[0]
                self.assertEqual(command[:2], ["mineru-open-api", "extract"])
                self.assertIn("--model", command)
                self.assertIn("vlm", command)
                self.assertEqual(run.call_args.kwargs["env"]["MINERU_TOKEN"], "token-for-child-process")

    def test_official_cli_config_token_overrides_inherited_environment(self):
        config = {
            "api": {
                "mineru": {
                    "mode": "official_cli",
                    "cli_command": "mineru-open-api",
                    "api_key": "token-from-config",
                }
            }
        }
        with tempfile.TemporaryDirectory() as tmp:
            pdf = Path(tmp) / "paper.pdf"
            pdf.write_bytes(b"pdf")
            with (
                patch.dict(os.environ, {"MINERU_TOKEN": "stale-parent-token"}),
                patch("utils.pdf_official_handler.subprocess.run") as run,
            ):
                run.return_value.returncode = 0
                run.return_value.stdout = ""
                run.return_value.stderr = ""
                OfficialMinerUProcessor(config).process(str(pdf), str(Path(tmp) / "out"))

            self.assertEqual(run.call_args.kwargs["env"]["MINERU_TOKEN"], "token-from-config")

    def test_agent_wrappers_return_json_friendly_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            markdown_path = Path(tmp) / "paper.md"
            markdown_path.write_text("# Results\nThe coercive field is 2.1 V/m.", encoding="utf-8")
            evidence = retrieve_evidence(str(markdown_path), "coercive field")
            outline = get_document_outline(str(markdown_path))
            self.assertEqual(evidence["results"][0]["heading"], "Results")
            self.assertEqual(outline["sections"][0]["chunk_id"], "E001")

    def test_process_writes_summary_and_manifest(self):
        class FakePDFProcessor:
            def convert_to_markdown(self, _path):
                return "# Methods\nThe sample was measured.\n\n# Conclusions\nThe effect is reproducible."

        class FakeLLM:
            def summarize(self, _prompt):
                return "结论 [E002]"

        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "4668"
            folder.mkdir()
            pdf = folder / "paper.pdf"
            pdf.write_bytes(b"pdf")
            config = {
                "paths": {"output_dir": str(Path(tmp) / "out")},
                "processing_rules": {
                    "deep_read_ids": ["4668"],
                    "skim_ids": [],
                    "default_mode": "skim",
                    "remove_references": False,
                    "chunk_chars": 6000,
                    "max_prompt_chars": 3000,
                },
            }
            paper = {
                "id": "4668",
                "folder_path": str(folder),
                "file_path": str(pdf),
                "file_name": pdf.name,
            }
            output = process_single_paper(paper, config, FakePDFProcessor(), FakeLLM())
            manifest = Path(output).with_suffix(".manifest.json")
            self.assertTrue(Path(output).is_file())
            self.assertTrue(manifest.is_file())
            self.assertEqual(json.loads(manifest.read_text(encoding="utf-8"))["chunk_count"], 2)


if __name__ == "__main__":
    unittest.main()
