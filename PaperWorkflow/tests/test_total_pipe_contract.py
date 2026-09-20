import sys
import tempfile
import unittest
from pathlib import Path

from utils.literature_workflow import build_literature_workflow

PWF2RPA_ROOT = Path(__file__).resolve().parents[2] / "Total-pipe" / "pwf2rpa"
if str(PWF2RPA_ROOT) not in sys.path:
    sys.path.insert(0, str(PWF2RPA_ROOT))

from pwf2rpa.workflow import Workflow  # noqa: E402


class TotalPipeContractTests(unittest.TestCase):
    def test_generated_bundle_is_accepted_by_pwf2rpa(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "paper.md"
            output = root / "bundle"
            source.write_text(
                "# Total-pipe contract paper\n\n"
                "# Methods\nA thin film was deposited and measured at 300 K.\n\n"
                "# Results\nThe measured signal increased by 20 percent.\n\n"
                "# Conclusion\nThe experiment supports the reported mechanism.\n",
                encoding="utf-8",
            )
            build_literature_workflow(
                markdown_path=source,
                source_path=source,
                project_root=root,
                output_dir=output,
                custom_queries=["measured signal"],
                include_default_queries=False,
            )

            workflow = Workflow.from_path(output / "workflow.json")
            workflow.validate()

            self.assertTrue(workflow.evidence_ids)
            self.assertEqual(workflow.document["schema_version"], 4)


if __name__ == "__main__":
    unittest.main()
