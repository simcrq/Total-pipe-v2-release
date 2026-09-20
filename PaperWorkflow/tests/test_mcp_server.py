import importlib.util
import tempfile
import unittest
from pathlib import Path

import mcp_server

BRIDGE_PATH = (
    Path(__file__).resolve().parents[1]
    / "integrations"
    / "deepseek-harness"
    / "bridge.py"
)


def load_bridge():
    spec = importlib.util.spec_from_file_location("paperworkflow_test_bridge", BRIDGE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load DeepSeek bridge")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class MCPServerTests(unittest.TestCase):
    def test_workflow_accepts_source_and_output_outside_project(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source_dir = root / "external-source"
            output_dir = root / "external-output"
            source_dir.mkdir()
            source = source_dir / "paper.md"
            source.write_text(
                "# External paper\n\n"
                "# Methods\nThe sample was measured at 300 K.\n\n"
                "# Results\nThe measured response increased by 20 percent.\n\n"
                "# Conclusion\nThe method supports the reported result.\n",
                encoding="utf-8",
            )

            result = mcp_server.tool_literature_workflow(
                {
                    "source_path": str(source),
                    "output_dir": str(output_dir),
                    "queries": ["measured response"],
                    "include_default_queries": False,
                }
            )

            self.assertEqual(Path(result["bundle_dir"]), output_dir.resolve())
            self.assertEqual(
                Path(result["workflow_path"]), (output_dir / "workflow.json").resolve()
            )
            self.assertTrue((output_dir / "paper.md").is_file())
            self.assertTrue((output_dir / "bundle.manifest.json").is_file())

    def test_prompt_builder_indexes_arbitrary_source_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            source_dir = Path(temporary) / "papers"
            source_dir.mkdir()
            paper = source_dir / "outside.pdf"
            paper.write_bytes(b"pdf")

            result = mcp_server.tool_prompt_builder({"source_dir": str(source_dir)})

            self.assertEqual(result["pdf_count"], 1)
            self.assertEqual(result["pdf_index"][0]["source_path"], str(paper.resolve()))

    def test_deepseek_bridge_uses_the_same_external_path_contract(self):
        bridge = load_bridge()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "paper.md"
            output = root / "bundle"
            source.write_text(
                "# Bridge paper\n\n# Results\nThe measured value increased by 20 percent.\n",
                encoding="utf-8",
            )

            workflow = bridge.run(
                {
                    "operation": "literature_workflow",
                    "source_path": str(source),
                    "output_dir": str(output),
                    "queries": ["measured value"],
                    "include_default_queries": False,
                }
            )

            self.assertEqual(workflow["schema_version"], 4)
            self.assertEqual(workflow["artifacts"]["artifact_dir"], ".")
            self.assertEqual(
                Path(workflow["runtime_artifacts"]["bundle_dir"]), output.resolve()
            )
            self.assertTrue((output / "bundle.manifest.json").is_file())


if __name__ == "__main__":
    unittest.main()
