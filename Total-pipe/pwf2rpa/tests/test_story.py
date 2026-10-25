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
        self.assertNotIn("key_points", node)

    def test_english_story_generates_english_ending_and_consistent_title_count(self):
        story = make_story()
        specs, _ = story_to_specs(story, self.workflow)
        self.assertEqual(specs[-1]["title"], "Conclusions and scope")
        payload, _ = convert(self.workflow, story=story, strict_fit=False)
        ending = payload["slide_briefs"][-1]
        self.assertEqual(ending["title"], "Conclusions and scope")
        self.assertEqual(ending["title_chars"], 21)

    def test_chinese_story_keeps_chinese_ending(self):
        story = make_story()
        story["core_question"] = "该方法能否解决目标问题？"
        story["main_message"] = "独立证据在明确边界内支持该方法。"
        story["ending"] = {"takeaway": "主要结论得到支持。", "limitation": "机制仍受测试条件限制。"}
        for node in story["story"]:
            node["question"] = "这一结果说明什么？"
            node["answer"] = "结果支持当前解释，但仍需验证。"
        specs, _ = story_to_specs(story, self.workflow)
        self.assertEqual(specs[-1]["title"], "结论与边界")

    def test_four_key_points_reach_rpa_brief_in_order(self):
        story = make_story()
        points = [
            "First observation stays complete.",
            "Second analysis preserves its qualifier.",
            "Third result identifies a boundary.",
            "Fourth point names the remaining alternative.",
        ]
        story["story"][0]["key_points"] = points
        specs, warnings = story_to_specs(story, self.workflow)
        self.assertEqual(warnings, [])
        self.assertEqual(specs[1]["key_points"], points)
        payload, warnings = convert(self.workflow, story=story, strict_fit=False)
        self.assertEqual(warnings, [])
        brief = payload["slide_briefs"][1]
        self.assertEqual(brief["takeaway"], story["story"][0]["answer"])
        self.assertEqual(brief["key_points"], points)

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
        for count in (3, 11):
            story = make_story()
            story["story"] = (story["story"] * 3)[:count]
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


    def test_node_title_reaches_brief_and_metadata(self):
        story = make_story()
        story["story"][0]["title"] = "A plain declarative slide title"
        specs, _warnings = story_to_specs(story, self.workflow)
        self.assertTrue(specs[1]["title"].startswith("A plain declarative slide"))
        self.assertEqual(specs[1]["metadata"]["story_title"], "A plain declarative slide title")

    def test_title_falls_back_to_question(self):
        specs, _warnings = story_to_specs(make_story(), self.workflow)
        self.assertEqual(specs[1]["metadata"]["story_title"], "Scientific question 1?")

    def test_last_node_needs_no_next_question(self):
        story = make_story()
        story["story"][-1].pop("next")
        specs, _warnings = story_to_specs(story, self.workflow)
        self.assertEqual(specs[-2]["metadata"]["story_next"], "")

    def test_missing_next_inside_chain_is_rejected(self):
        story = make_story()
        story["story"][1].pop("next")
        with self.assertRaises(StoryError) as caught:
            story_to_specs(story, self.workflow)
        self.assertIn("STORY_TEXT_MISSING", str(caught.exception))

    def test_limitation_is_optional(self):
        story = make_story()
        story["ending"].pop("limitation")
        specs, _warnings = story_to_specs(story, self.workflow)
        self.assertNotIn("body", specs[-1])

    def test_four_node_story_is_allowed(self):
        story = make_story()
        story["story"] = story["story"][:4]
        specs, _warnings = story_to_specs(story, self.workflow)
        self.assertEqual(len(specs), 6)

    def test_declared_form_selects_structural_category(self):
        # Without a form the keyword fallback only ever reaches the prose pools, so a
        # procedure or a comparison lost the structure it needed before reaching RPA.
        story = make_story()
        story["story"][1]["form"] = "sequence"
        story["story"][1]["process_steps"] = ["Measure at each temperature", "Fit the slope"]
        story["story"][2]["form"] = "compare"
        story["story"][2]["comparison_dimensions"] = ["Contact resistance", "Barrier symmetry"]
        specs, warnings = story_to_specs(story, self.workflow)
        self.assertEqual(warnings, [])
        self.assertEqual(specs[2]["category_hint"], "workflow")
        self.assertEqual(specs[3]["category_hint"], "table")
        self.assertEqual(specs[2]["metadata"]["story_form"], "sequence")
        self.assertEqual(specs[2]["process_steps"], ["Measure at each temperature", "Fit the slope"])

    def test_form_slots_reach_rpa_brief_as_counts(self):
        # RPA derives process_step_count from the brief and treats it as a hard
        # retrieval constraint; an empty list is what kept every page off the pools
        # that carry a process or table region.
        story = make_story()
        story["story"][1]["form"] = "sequence"
        story["story"][1]["process_steps"] = ["Step one", "Step two", "Step three"]
        payload, warnings = convert(self.workflow, story=story, strict_fit=False)
        self.assertEqual(warnings, [])
        brief = payload["slide_briefs"][2]
        self.assertEqual(brief["process_steps"], ["Step one", "Step two", "Step three"])
        self.assertEqual(brief["process_step_count"], 3)
        self.assertEqual(brief["metadata"]["story_form"], "sequence")

    def test_unknown_form_warns_without_failing(self):
        story = make_story()
        story["story"][1]["form"] = "mindmap"
        specs, warnings = story_to_specs(story, self.workflow)
        self.assertIn("STORY_FORM_UNKNOWN", [warning.code for warning in warnings])
        self.assertNotIn("story_form", specs[2]["metadata"])

    def test_form_without_its_slots_is_flagged(self):
        story = make_story()
        story["story"][1]["form"] = "sequence"
        _specs, warnings = story_to_specs(story, self.workflow)
        self.assertIn("STORY_FORM_UNFILLED", [warning.code for warning in warnings])


class StoryExplanationTests(unittest.TestCase):
    def setUp(self):
        self.workflow = make_workflow()

    def test_parallel_items_reach_brief_as_native_list_material(self):
        story = make_story()
        items = ["Contact resistance", "Device conductance", "Source-drain swap"]
        story["story"][0]["explain"] = {
            "reader_task": "distinguish",
            "must_show": [{
                "kind": "parallel_items",
                "required": True,
                "content": {"items": items},
                "evidence": ["EV0001"],
                "source_quote": "Observation 1 leaves a distinct unresolved question.",
            }],
            "must_not_lose": ["units"],
        }
        specs, warnings = story_to_specs(story, self.workflow)
        self.assertEqual(warnings, [])
        self.assertEqual(specs[1]["key_points"], items)
        self.assertEqual(specs[1]["metadata"]["story_explain"]["must_show"][0]["kind"],
                         "parallel_items")
        self.assertTrue(specs[1]["metadata"]["story_explain"]["must_show"][0]["primary"])
        payload, convert_warnings = convert(self.workflow, story=story, strict_fit=False)
        self.assertEqual(convert_warnings, [])
        self.assertEqual(payload["slide_briefs"][1]["key_points"], items)

    def test_ordered_steps_without_form_selects_workflow_category(self):
        story = make_story()
        story["story"][1]["explain"] = {
            "must_show": [{
                "kind": "ordered_steps",
                "content": {"items": ["Expose the device", "Record the waveform", "Fit the edge"]},
                "evidence": ["EV0002"],
            }],
        }
        specs, warnings = story_to_specs(story, self.workflow)
        self.assertEqual(warnings, [])
        self.assertEqual(specs[2]["category_hint"], "workflow")
        self.assertEqual(specs[2]["process_steps"],
                         ["Expose the device", "Record the waveform", "Fit the edge"])
        self.assertEqual(specs[2]["metadata"]["story_form"], "sequence")

    def test_eight_step_explain_stays_out_of_rpa_process_slots(self):
        story = make_story()
        items = [f"Step {index}" for index in range(1, 9)]
        story["story"][1]["explain"] = {
            "must_show": [{
                "kind": "ordered_steps",
                "content": {"items": items},
                "evidence": ["EV0002"],
            }],
        }
        specs, warnings = story_to_specs(story, self.workflow)
        self.assertEqual(warnings, [])
        self.assertNotIn("process_steps", specs[2])
        self.assertNotIn("story_form", specs[2]["metadata"])
        self.assertEqual(len(specs[2]["metadata"]["story_explain"]["must_show"][0]["content"]["items"]), 8)

    def test_comparison_without_form_selects_table_category(self):
        story = make_story()
        story["story"][1]["explain"] = {
            "must_show": [{
                "kind": "comparison",
                "content": {
                    "objects": ["80 Mbps", "110 Mbps"],
                    "dimensions": ["BER", "eye opening"],
                },
                "evidence": ["EV0002"],
            }],
        }
        specs, warnings = story_to_specs(story, self.workflow)
        self.assertEqual(warnings, [])
        self.assertEqual(specs[2]["category_hint"], "table")
        self.assertEqual(specs[2]["comparison_dimensions"], ["BER", "eye opening"])

    def test_explain_rejects_evidence_not_listed_on_its_node(self):
        story = make_story()
        story["story"][0]["explain"] = {
            "must_show": [{
                "kind": "quantity",
                "content": {"latex": "\\\\varepsilon_A \\\\approx 0.21"},
                "evidence": ["EV0002"],
            }],
        }
        with self.assertRaises(StoryError) as caught:
            story_to_specs(story, self.workflow)
        self.assertIn("STORY_EXPLAIN_EVIDENCE_NOT_ON_NODE", str(caught.exception))

    def test_explain_rejects_unknown_kind(self):
        story = make_story()
        story["story"][0]["explain"] = {
            "must_show": [{
                "kind": "mindmap",
                "content": {"items": ["a", "b"]},
                "evidence": ["EV0001"],
            }],
        }
        with self.assertRaises(StoryError) as caught:
            story_to_specs(story, self.workflow)
        self.assertIn("STORY_EXPLAIN_KIND_UNKNOWN", str(caught.exception))

    def test_curve_must_declare_schematic(self):
        story = make_story()
        story["story"][0]["explain"] = {
            "must_show": [{
                "kind": "curve",
                "content": {"shape": "rise-then-plateau"},
                "evidence": ["EV0001"],
            }],
        }
        _specs, warnings = story_to_specs(story, self.workflow)
        self.assertIn("STORY_EXPLAIN_CURVE_SCHEMATIC_UNMARKED",
                      [warning.code for warning in warnings])

    def test_empty_explain_needs_a_prose_reason(self):
        story = make_story()
        story["story"][0]["explain"] = {"must_show": []}
        _specs, warnings = story_to_specs(story, self.workflow)
        self.assertIn("STORY_EXPLAIN_PROSE_REASON_MISSING",
                      [warning.code for warning in warnings])

    def test_prompt_carries_capability_card_and_explain_shape(self):
        prompt = build_story_prompt(
            self.workflow,
            model="capable-model",
            reasoning_effort="high",
            selected_by_user=True,
        )
        card = prompt["capability_card"]
        self.assertEqual(card["contract"], "totalpipe.explanation-contract")
        self.assertEqual([move["kind"] for move in card["moves"]],
                         ["quantity", "parallel_items", "grouped_panels", "comparison",
                          "ordered_steps", "relation", "curve", "image_evidence"])
        self.assertIn("explain", prompt["output_shape"]["story"][0])
        self.assertIn("parallel_items", prompt["instructions"])
        self.assertIn("must_show", prompt["instructions"])
        self.assertNotIn("\\\\n", prompt["instructions"])


if __name__ == "__main__":
    unittest.main()
