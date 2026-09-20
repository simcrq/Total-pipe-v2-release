"""Story Planning contract tests."""

from __future__ import annotations

import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pwf2rpa import (  # noqa: E402
    StoryError,
    Workflow,
    build_story_prompt,
    convert,
    story_to_specs,
)


def make_workflow() -> Workflow:
    return Workflow(
        {
            "schema_version": 4,
            "source": {"source_sha256": "a" * 64, "source_fingerprint": "story-test"},
            "metadata": {"title_guess": "Evidence-grounded paper"},
            "evidence_registry": [
                {
                    "evidence_id": f"EV{index:04d}",
                    "text": f"Observation {index} leaves a distinct unresolved question.",
                    "query_ids": ["results"],
                    "modality": "body_text",
                    "support_type": "direct_observation",
                }
                for index in range(1, 9)
            ],
        }
    )


def make_story() -> dict:
    return {
        "planner": {
            "mode": "subagent",
            "model": "capable-model",
            "reasoning_effort": "high",
            "selected_by_user": True,
        },
        "core_question": "Can the method resolve the target problem?",
        "main_message": "Independent evidence supports the method within a clear boundary.",
        "story": [
            {
                "question": f"Scientific question {index}?",
                "answer": f"Evidence answers question {index}.",
                "evidence": [f"EV{index:04d}"],
                "next": "但是当前证据仍不足以排除另一种解释，需要独立验证。",
            }
            for index in range(1, 6)
        ],
        "ending": {
            "takeaway": "The core claim is supported by a short evidence chain.",
            "limitation": "The mechanism remains bounded by the reported conditions.",
        },
    }


class StoryProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.workflow = make_workflow()
        self.workflow.validate()

    def test_prompt_requires_explicit_user_model_selection(self):
        with self.assertRaises(StoryError) as caught:
            build_story_prompt(
                self.workflow,
                model="capable-model",
                reasoning_effort="high",
                selected_by_user=False,
            )
        self.assertIn("STORY_MODEL_NOT_USER_SELECTED", str(caught.exception))

    def test_prompt_requires_high_reasoning(self):
        with self.assertRaises(StoryError) as caught:
            build_story_prompt(
                self.workflow,
                model="capable-model",
                reasoning_effort="medium",
                selected_by_user=True,
            )
        self.assertIn("STORY_MODEL_NOT_HIGH_REASONING", str(caught.exception))

    def test_story_rejects_main_agent_provenance(self):
        story = make_story()
        story["planner"]["mode"] = "main_agent"
        with self.assertRaises(StoryError) as caught:
            story_to_specs(story, self.workflow)
        self.assertIn("STORY_SUBAGENT_REQUIRED", str(caught.exception))


class StoryChainTests(unittest.TestCase):
    def setUp(self):
        self.workflow = make_workflow()

    def test_valid_story_becomes_reasoning_briefs(self):
        specs, warnings = story_to_specs(make_story(), self.workflow)
        self.assertEqual(warnings, [])
        self.assertEqual(len(specs), 7)  # cover + 5 reasoning nodes + ending
        node = specs[1]
        self.assertEqual(node["narrative_job"], "story_reasoning")
        self.assertTrue(node["allow_auto_split"])
        self.assertEqual(node["metadata"]["story_node_index"], 1)
        self.assertIn("仍不足", node["metadata"]["story_next"])

    def test_story_rejects_unknown_evidence(self):
        story = make_story()
        story["story"][0]["evidence"] = ["EV9999"]
        with self.assertRaises(StoryError) as caught:
            story_to_specs(story, self.workflow)
        self.assertIn("UNKNOWN_EVIDENCE_ID", str(caught.exception))

    def test_story_rejects_figure_walkthrough_transition(self):
        story = make_story()
        story["story"][2]["next"] = "接下来作者介绍 Fig.4"
        with self.assertRaises(StoryError) as caught:
            story_to_specs(story, self.workflow)
        self.assertIn("STORY_NEXT_IS_SEQUENTIAL", str(caught.exception))

    def test_story_node_count_is_bounded(self):
        story = make_story()
        story["story"] = story["story"][:4]
        with self.assertRaises(StoryError) as caught:
            story_to_specs(story, self.workflow)
        self.assertIn("STORY_NODE_COUNT_INVALID", str(caught.exception))

    def test_certainty_escalation_is_reported(self):
        self.workflow.document["evidence_registry"][0]["text"] = "The change likely originates from preparation."
        self.workflow = Workflow(self.workflow.document)
        story = make_story()
        story["story"][0]["answer"] = "Preparation 导致了这一变化。"
        _specs, warnings = story_to_specs(story, self.workflow)
        self.assertIn("STORY_CERTAINTY_ESCALATION_RISK", [warning.code for warning in warnings])

    def test_convert_consumes_story_without_leaking_new_top_level_keys(self):
        payload, _warnings = convert(self.workflow, story=make_story(), strict_fit=False)
        self.assertEqual(set(payload), {"paperworkflow_v4", "slide_briefs"})
        self.assertEqual(payload["slide_briefs"][1]["metadata"]["story_planner"]["mode"], "subagent")


if __name__ == "__main__":
    unittest.main()
