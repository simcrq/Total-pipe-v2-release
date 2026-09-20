"""Contract tests for the PaperWorkflow -> RPA adapter.

Run with::

    python3 -m unittest discover -s tests -v

The suite is hermetic: it builds its own miniature workflow instead of reading
the archived graphene package, so it stays meaningful when that sample moves.
Tests are grouped by the four hard constraints the adapter exists to enforce.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pwf2rpa import (  # noqa: E402
    BriefError,
    Workflow,
    WorkflowError,
    build_briefs,
    category_ids,
    convert,
    fallback_specs,
    write_output,
)
from pwf2rpa.capacity import CATEGORIES  # noqa: E402
from pwf2rpa.fit import (  # noqa: E402
    PageShape,
    TextItem,
    VisualItem,
    crowded_pages,
    evaluate,
)

ROOT = Path(__file__).resolve().parent.parent


def make_workflow(evidence_count: int = 4) -> Workflow:
    """A minimal but structurally faithful v4 document."""
    registry = [
        {
            "evidence_id": f"EV{index + 1:04d}",
            "span_id": f"S{index + 1:04d}",
            "chunk_id": "E001",
            "source_lines": {"start": index + 1, "end": index + 1},
            "source_chars": {"start": 0, "end": 10},
            "modality": "body_text",
            "support_type": "direct_observation",
            "text": f"Finding number {index + 1} about the sample. It holds under load.",
            "query_ids": ["results" if index % 2 else "objective"],
            "queries": ["q"],
        }
        for index in range(evidence_count)
    ]
    return Workflow(
        {
            "schema_version": 4,
            "source": {
                "input_path": "/tmp/paper.pdf",
                "input_type": "pdf",
                "source_sha256": "a" * 64,
                "markdown_sha256": "b" * 64,
                "source_fingerprint": "cafebabe",
            },
            "metadata": {"title_guess": "A Short Paper"},
            "evidence_registry": registry,
        },
        origin="<test>",
    )


class WorkflowValidation(unittest.TestCase):
    """The adapter should reject workflows RPA cannot adapt."""

    def test_valid_workflow_passes(self):
        make_workflow().validate()

    def test_wrong_schema_version_is_rejected(self):
        workflow = make_workflow()
        workflow.document["schema_version"] = 3
        with self.assertRaises(WorkflowError) as caught:
            workflow.validate()
        self.assertIn("WORKFLOW_SCHEMA_UNSUPPORTED", str(caught.exception))

    def test_source_without_identity_is_rejected(self):
        workflow = make_workflow()
        workflow.document["source"] = {"input_type": "pdf"}
        with self.assertRaises(WorkflowError) as caught:
            workflow.validate()
        self.assertIn("WORKFLOW_SOURCE_UNIDENTIFIED", str(caught.exception))

    def test_empty_registry_is_rejected(self):
        workflow = make_workflow(0)
        with self.assertRaises(WorkflowError) as caught:
            workflow.validate()
        self.assertIn("WORKFLOW_REGISTRY_EMPTY", str(caught.exception))

    def test_registry_accepts_object_form(self):
        workflow = make_workflow()
        workflow.document["evidence_registry"] = {
            entry["evidence_id"]: entry for entry in workflow.document["evidence_registry"]
        }
        rebuilt = Workflow(workflow.document)
        rebuilt.validate()
        self.assertEqual(len(rebuilt.evidence_ids), 4)


class Rule1EvidenceMustResolve(unittest.TestCase):
    """evidence_ids must reference real EV#### entries."""

    def setUp(self):
        self.workflow = make_workflow()

    def test_unknown_evidence_id_blocks(self):
        with self.assertRaises(BriefError) as caught:
            build_briefs([{"title": "T", "category_hint": "summary",
                           "evidence_ids": ["EV0001", "EV4242"]}], self.workflow)
        problem = caught.exception.errors[0]
        self.assertEqual(problem.code, "UNKNOWN_EVIDENCE_ID")
        self.assertEqual(problem.actual, "EV4242")

    def test_known_evidence_ids_survive_in_order(self):
        briefs, _ = build_briefs(
            [{"title": "T", "category_hint": "summary", "evidence_ids": ["EV0003", "EV0001"]}],
            self.workflow,
        )
        self.assertEqual(briefs[0]["evidence_ids"], ["EV0003", "EV0001"])

    def test_duplicate_evidence_ids_are_collapsed(self):
        briefs, _ = build_briefs(
            [{"title": "T", "category_hint": "summary", "evidence_ids": ["EV0001", "EV0001"]}],
            self.workflow,
        )
        self.assertEqual(briefs[0]["evidence_ids"], ["EV0001"])

    def test_all_errors_are_reported_together(self):
        """One pass should surface every bad id, not just the first."""
        with self.assertRaises(BriefError) as caught:
            build_briefs(
                [
                    {"title": "A", "category_hint": "summary", "evidence_ids": ["EV9001"]},
                    {"title": "B", "category_hint": "summary", "evidence_ids": ["EV9002"]},
                ],
                self.workflow,
            )
        self.assertEqual(len(caught.exception.errors), 2)


class Rule2CategoryHintMustBeReal(unittest.TestCase):
    """category_hint must be one of the 40 layout category ids."""

    def setUp(self):
        self.workflow = make_workflow()

    def test_library_exposes_forty_categories(self):
        self.assertEqual(len(category_ids()), 40)
        for required in ("cover", "question", "background", "figure_text",
                         "single_figure", "limitations", "summary", "decision", "case"):
            self.assertIn(required, CATEGORIES)

    def test_narrative_job_string_is_flagged(self):
        """The documented trap: a narrative label is not a category id."""
        _, warnings = build_briefs(
            [{"title": "T", "category_hint": "motivation", "evidence_ids": ["EV0001"]}],
            self.workflow,
        )
        codes = [warning.code for warning in warnings]
        self.assertIn("CATEGORY_HINT_UNKNOWN", codes)

    def test_missing_category_hint_is_flagged(self):
        _, warnings = build_briefs([{"title": "T", "evidence_ids": ["EV0001"]}], self.workflow)
        self.assertIn("CATEGORY_HINT_MISSING", [warning.code for warning in warnings])

    def test_typo_gets_a_suggestion(self):
        _, warnings = build_briefs(
            [{"title": "T", "category_hint": "limitation", "evidence_ids": ["EV0001"]}],
            self.workflow,
        )
        hint = next(w.hint for w in warnings if w.code == "CATEGORY_HINT_UNKNOWN")
        self.assertIn("limitations", hint)

    def test_slide_type_defaults_to_category(self):
        briefs, _ = build_briefs(
            [{"title": "T", "category_hint": "summary", "evidence_ids": ["EV0001"]}],
            self.workflow,
        )
        self.assertEqual(briefs[0]["slide_type"], "summary")


class Rule3ContentMustFitSlots(unittest.TestCase):
    """Text must fit the category's slots or RPA raises SLOT_CAPACITY_EXCEEDED."""

    def setUp(self):
        self.workflow = make_workflow()

    def test_short_claims_fit_figure_text(self):
        shape = PageShape(
            category="figure_text",
            title="K1 模激活后应力突降",
            text_items=(TextItem("claims[0]", "原始胞弹性失稳 εA=0.307", ("callout", "text"), False),),
            visuals=(VisualItem("dense_plot", 1, True),),
        )
        self.assertTrue(evaluate(shape).fits)

    def test_oversized_claim_is_detected(self):
        """A lone claim lands in figure_text's 36-char callout, not its 68-char text slot.

        Verified against RPA: a 36-char claim keeps the category, a 37-char
        claim makes RPA relax the hint to a whole-library search.
        """
        shape = PageShape(
            category="figure_text",
            title="短标题",
            text_items=(TextItem("claims[0]", "软" * 69, ("callout", "text"), False),),
            visuals=(VisualItem("dense_plot"),),
        )
        report = evaluate(shape)
        self.assertFalse(report.fits)
        self.assertTrue(any("36" in reason for reason in report.reasons), report.reasons)

    def test_figure_text_boundary_matches_rpa(self):
        def page(size: int) -> PageShape:
            return PageShape(
                category="figure_text",
                title="短标题",
                text_items=(TextItem("claims[0]", "软" * size, ("callout", "text"), False),),
                visuals=(VisualItem("dense_plot"),),
            )
        self.assertTrue(evaluate(page(36)).fits)
        self.assertFalse(evaluate(page(37)).fits)

    def test_second_claim_can_use_the_wider_text_slot(self):
        """Once the callout is taken, the next claim gets the 68-char slot."""
        shape = PageShape(
            category="figure_text",
            title="短标题",
            text_items=(
                TextItem("claims[0]", "软" * 30, ("callout", "text"), False),
                TextItem("claims[1]", "软" * 60, ("callout", "text"), False),
            ),
            visuals=(VisualItem("dense_plot"),),
        )
        self.assertTrue(evaluate(shape).fits)

    def test_capacity_boundary_is_exact(self):
        """single_figure holds 36 chars in its roomiest callout, not 37."""
        def page(size: int) -> PageShape:
            return PageShape(
                category="single_figure",
                title="标题",
                text_items=(TextItem("claims[0]", "软" * size, ("callout", "text"), False),),
                visuals=(VisualItem("simple_plot"),),
            )
        self.assertTrue(evaluate(page(36)).fits)
        self.assertFalse(evaluate(page(37)).fits)

    def test_oversized_page_warns_but_does_not_block(self):
        """RPA still plans these, so blocking would be wrong."""
        briefs, warnings = build_briefs(
            [{"title": "标题", "category_hint": "single_figure",
              "claims": ["软" * 90], "evidence_ids": ["EV0001"],
              "visuals": [{"visual_type": "simple_plot"}]}],
            self.workflow,
        )
        self.assertEqual(len(briefs), 1)
        self.assertIn("CAPACITY_EXCEEDED", [warning.code for warning in warnings])

    def test_strict_fit_can_be_disabled(self):
        _, warnings = build_briefs(
            [{"title": "标题", "category_hint": "single_figure",
              "claims": ["软" * 90], "evidence_ids": ["EV0001"],
              "visuals": [{"visual_type": "simple_plot"}]}],
            self.workflow,
            strict_fit=False,
        )
        self.assertEqual([w.code for w in warnings if w.code == "CAPACITY_EXCEEDED"], [])

    def test_title_capacity_is_checked(self):
        shape = PageShape(category="cover", title="標" * 40, text_items=(), visuals=())
        report = evaluate(shape)
        self.assertFalse(report.fits)
        self.assertTrue(any("title" in reason for reason in report.reasons))

    def test_visual_width_rule_matches_rpa(self):
        """A multi-panel figure needs a wider slot than a photo."""
        wide = VisualItem("multi_panel_figure", panel_count=6)
        narrow = VisualItem("photo")
        self.assertGreater(wide.required_width, narrow.required_width)
        self.assertAlmostEqual(narrow.required_width, 0.25)

    def test_too_many_visuals_for_category(self):
        shape = PageShape(
            category="single_figure",
            title="标题",
            text_items=(),
            visuals=(VisualItem("photo"), VisualItem("photo"), VisualItem("photo")),
        )
        self.assertFalse(evaluate(shape).fits)


class Rule4Determinism(unittest.TestCase):
    """Identical input must produce byte-identical output."""

    def test_repeated_conversion_is_identical(self):
        workflow = make_workflow()
        specs = [{"title": "T", "category_hint": "summary", "evidence_ids": ["EV0002", "EV0001"]}]
        first, _ = convert(workflow, specs)
        second, _ = convert(workflow, specs)
        self.assertEqual(json.dumps(first, sort_keys=False), json.dumps(second, sort_keys=False))

    def test_fallback_is_deterministic(self):
        workflow = make_workflow(8)
        self.assertEqual(json.dumps(fallback_specs(workflow)),
                         json.dumps(fallback_specs(workflow)))

    def test_written_file_has_no_timestamps_or_ids(self):
        workflow = make_workflow()
        payload, _ = convert(workflow, None)
        with tempfile.TemporaryDirectory() as directory:
            path = write_output(payload, Path(directory) / "out.json")
            text = path.read_text(encoding="utf-8")
        self.assertNotIn("generated_at", json.dumps(payload["slide_briefs"]))
        self.assertTrue(text.endswith("\n"))


class OutputShape(unittest.TestCase):
    """The payload must match what normalize_content expects."""

    def setUp(self):
        self.workflow = make_workflow()

    def test_payload_has_exactly_two_keys(self):
        payload, _ = convert(self.workflow, None)
        self.assertEqual(set(payload), {"paperworkflow_v4", "slide_briefs"})

    def test_workflow_is_passed_through_untouched(self):
        payload, _ = convert(self.workflow, None)
        self.assertIs(payload["paperworkflow_v4"], self.workflow.document)

    def test_adapter_does_not_fabricate_sources_or_citations(self):
        """RPA derives these; duplicating them here would risk drift."""
        payload, _ = convert(self.workflow, None)
        self.assertNotIn("sources", payload)
        self.assertNotIn("citations", payload)
        self.assertNotIn("evidence", payload)

    def test_required_slide_brief_fields_present(self):
        payload, _ = convert(self.workflow, None)
        required = {
            "slide_type", "title", "goal", "claims", "process_steps",
            "timeline_events", "comparison_dimensions", "experiment_groups",
            "data_series", "visuals", "citation_ids", "evidence_ids",
            "duration_weight",
        }
        for brief in payload["slide_briefs"]:
            self.assertTrue(required.issubset(brief), required - set(brief))

    def test_counters_are_derived_from_content(self):
        briefs, _ = build_briefs(
            [{
                "title": "四字标题",
                "category_hint": "figure_text",
                "goal": "一二三",
                "claims": ["四五"],
                "visuals": [{"visual_type": "dense_plot", "caption": "图"}],
                "evidence_ids": ["EV0001"],
            }],
            self.workflow,
        )
        brief = briefs[0]
        self.assertEqual(brief["title_chars"], 4)
        self.assertEqual(brief["image_count"], 1)
        self.assertEqual(brief["text_chars"], 5)

    def test_visual_defaults_are_filled(self):
        briefs, _ = build_briefs(
            [{"title": "T", "category_hint": "figure_text",
              "visuals": ["a caption"], "evidence_ids": ["EV0001"]}],
            self.workflow,
        )
        visual = briefs[0]["visuals"][0]
        self.assertEqual(visual["visual_type"], "visual_evidence")
        self.assertEqual(visual["panel_count"], 1)
        self.assertEqual(visual["caption"], "a caption")

    def test_forbidden_planning_fields_are_rejected(self):
        _, warnings = build_briefs(
            [{"title": "T", "category_hint": "summary", "layout_id": "RM-COVER-01",
              "evidence_ids": ["EV0001"]}],
            self.workflow,
        )
        self.assertIn("BRIEF_UNKNOWN_FIELD", [warning.code for warning in warnings])


class Fallback(unittest.TestCase):
    """The no-briefs path must still produce a plannable deck."""

    def test_fallback_covers_every_evidence_entry(self):
        workflow = make_workflow(8)
        payload, warnings = convert(workflow, None)
        cited = {
            evidence_id
            for brief in payload["slide_briefs"]
            for evidence_id in brief["evidence_ids"]
        }
        self.assertEqual(cited, set(workflow.evidence_ids))
        self.assertEqual(warnings, [])

    def test_fallback_uses_only_legal_categories(self):
        payload, _ = convert(make_workflow(8), None)
        for brief in payload["slide_briefs"]:
            self.assertIn(brief["category_hint"], CATEGORIES)

    def test_fallback_pages_all_fit(self):
        payload, warnings = convert(make_workflow(12), None)
        self.assertEqual([w.code for w in warnings], [])
        self.assertGreaterEqual(len(payload["slide_briefs"]), 3)


class BriefsFileHandling(unittest.TestCase):
    """Loading errors should name the file and the location."""

    def test_missing_file(self):
        from pwf2rpa import load_specs
        with self.assertRaises(BriefError) as caught:
            load_specs("/nonexistent/briefs.json")
        self.assertIn("BRIEFS_NOT_FOUND", str(caught.exception))

    def test_malformed_json_reports_position(self):
        from pwf2rpa import load_specs
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "b.json"
            path.write_text("[{,}]", encoding="utf-8")
            with self.assertRaises(BriefError) as caught:
                load_specs(path)
        self.assertIn("BRIEFS_NOT_JSON", str(caught.exception))

    def test_object_wrapper_is_accepted(self):
        """The adapter's own output can be fed back in while editing."""
        from pwf2rpa import load_specs
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "b.json"
            path.write_text(json.dumps({"slide_briefs": [{"title": "T"}]}), encoding="utf-8")
            self.assertEqual(load_specs(path), [{"title": "T"}])

    def test_empty_array_is_rejected(self):
        with self.assertRaises(BriefError) as caught:
            build_briefs([], make_workflow())
        self.assertIn("BRIEFS_EMPTY", str(caught.exception))

    def test_more_than_forty_slides_rejected(self):
        specs = [{"title": f"T{i}", "category_hint": "summary"} for i in range(41)]
        with self.assertRaises(BriefError) as caught:
            build_briefs(specs, make_workflow())
        self.assertIn("BRIEFS_TOO_MANY", str(caught.exception))


class CommandLine(unittest.TestCase):
    """End-to-end behaviour of the documented invocation."""

    def _run(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(ROOT / "pwf_to_rpa.py"), *args],
            capture_output=True, text=True,
        )

    def test_convert_writes_output(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            workflow_path = directory / "workflow.json"
            workflow_path.write_text(json.dumps(make_workflow().document), encoding="utf-8")
            briefs_path = directory / "briefs.json"
            briefs_path.write_text(
                json.dumps([{"title": "T", "category_hint": "summary",
                             "evidence_ids": ["EV0001"]}]),
                encoding="utf-8",
            )
            out_path = directory / "rpa_input.json"
            result = self._run(str(workflow_path), "--briefs", str(briefs_path),
                               "--out", str(out_path), "--quiet")
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertEqual(len(payload["slide_briefs"]), 1)

    def test_bad_evidence_exits_two_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            workflow_path = directory / "workflow.json"
            workflow_path.write_text(json.dumps(make_workflow().document), encoding="utf-8")
            briefs_path = directory / "briefs.json"
            briefs_path.write_text(
                json.dumps([{"title": "T", "category_hint": "summary",
                             "evidence_ids": ["EV9999"]}]),
                encoding="utf-8",
            )
            out_path = directory / "rpa_input.json"
            result = self._run(str(workflow_path), "--briefs", str(briefs_path),
                               "--out", str(out_path))
            self.assertEqual(result.returncode, 2)
            self.assertIn("UNKNOWN_EVIDENCE_ID", result.stderr)
            self.assertFalse(out_path.exists())

    def test_strict_flag_turns_warnings_into_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            workflow_path = directory / "workflow.json"
            workflow_path.write_text(json.dumps(make_workflow().document), encoding="utf-8")
            briefs_path = directory / "briefs.json"
            briefs_path.write_text(
                json.dumps([{"title": "T", "category_hint": "motivation",
                             "evidence_ids": ["EV0001"]}]),
                encoding="utf-8",
            )
            out_path = directory / "rpa_input.json"
            result = self._run(str(workflow_path), "--briefs", str(briefs_path),
                               "--out", str(out_path), "--strict")
            self.assertEqual(result.returncode, 3)
            self.assertFalse(out_path.exists())

    def test_list_categories(self):
        result = self._run("--list-categories")
        self.assertEqual(result.returncode, 0)
        self.assertIn("figure_text", result.stdout)

    def test_output_is_byte_stable_across_runs(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            workflow_path = directory / "workflow.json"
            workflow_path.write_text(json.dumps(make_workflow(6).document), encoding="utf-8")
            digests = set()
            for index in range(3):
                out_path = directory / f"out{index}.json"
                self._run(str(workflow_path), "--out", str(out_path), "--quiet")
                digests.add(out_path.read_bytes())
            self.assertEqual(len(digests), 1)


class DeckLevelLayoutContention(unittest.TestCase):
    """RPA never reuses a layout within a deck, which no per-page check sees."""

    def setUp(self):
        self.workflow = make_workflow()

    def _page(self, category: str, chars: int) -> PageShape:
        return PageShape(
            category=category,
            title="标题",
            text_items=(TextItem("claims[0]", "软" * chars, ("callout", "text"), False),),
            visuals=(),
        )

    def test_two_pages_can_share_a_roomy_category(self):
        """Distinct layouts exist, so sharing a category is fine."""
        self.assertEqual(crowded_pages([self._page("question", 60),
                                        self._page("question", 120)]), [])

    def test_matching_prefers_a_feasible_assignment(self):
        """A page fitting many layouts should yield to one fitting few.

        The 120-char page fits exactly one question layout; the short page
        fits all eight. A greedy count would flag a conflict, matching does not.
        """
        self.assertEqual(crowded_pages([self._page("question", 15),
                                        self._page("question", 120)]), [])

    def test_surplus_pages_are_reported(self):
        pages = [self._page("figure_text", 30) for _ in range(9)]
        crowded = crowded_pages(pages)
        self.assertTrue(crowded)
        self.assertTrue(all(entry[1] == "figure_text" for entry in crowded))

    def test_overuse_beyond_library_size_warns(self):
        specs = [{"title": f"标题{index}", "category_hint": "summary",
                  "evidence_ids": ["EV0001"]} for index in range(9)]
        _, warnings = build_briefs(specs, self.workflow)
        self.assertIn("CATEGORY_EXHAUSTED", [warning.code for warning in warnings])

    def test_normal_deck_produces_no_contention_warning(self):
        specs = [
            {"title": "封面", "category_hint": "cover", "evidence_ids": ["EV0001"]},
            {"title": "问题", "category_hint": "question", "evidence_ids": ["EV0002"]},
            {"title": "总结", "category_hint": "summary", "evidence_ids": ["EV0003"]},
        ]
        _, warnings = build_briefs(specs, self.workflow)
        self.assertEqual([warning.code for warning in warnings], [])


class CapacityTableIntegrity(unittest.TestCase):
    """The generated table must stay consistent with what the code assumes."""

    def test_every_category_has_eight_layouts(self):
        for name, category in CATEGORIES.items():
            self.assertEqual(len(category.layouts), 8, name)

    def test_slot_capacities_are_sane(self):
        for name, category in CATEGORIES.items():
            for layout in category.layouts:
                self.assertGreaterEqual(layout.text_chars, 0, name)
                for slot_type, max_chars in layout.text_slots:
                    self.assertIsInstance(slot_type, str)
                    if max_chars is not None:
                        self.assertGreater(max_chars, 0, f"{name}:{slot_type}")

    def test_visual_widths_are_fractions(self):
        for name, category in CATEGORIES.items():
            for layout in category.layouts:
                for width in layout.visual_widths:
                    self.assertTrue(0 < width <= 1, f"{name}: {width}")


class BodyAndEvidenceTexts(unittest.TestCase):
    """P0/P1: briefs carry full prose (body) and referenced evidence source text."""

    def setUp(self):
        self.workflow = make_workflow(4)

    def test_body_is_preserved_and_counted(self):
        specs = [{
            "category_hint": "theory",
            "title": "方法",
            "body": "全部计算在 VASP 中完成，声子用位移法计算。",
            "claims": ["软模相变前兆"],
            "evidence_ids": ["EV0001"],
        }]
        briefs, warnings = build_briefs(specs, self.workflow)
        self.assertEqual(warnings, [])
        brief = briefs[0]
        self.assertEqual(brief["body"], "全部计算在 VASP 中完成，声子用位移法计算。")
        self.assertGreater(brief["text_chars"], len(brief["body"]))

    def test_body_without_evidence_is_fine(self):
        specs = [{"category_hint": "theory", "title": "方法", "body": "一段正文"}]
        briefs, warnings = build_briefs(specs, self.workflow)
        self.assertEqual(warnings, [])
        self.assertEqual(briefs[0]["body"], "一段正文")
        self.assertNotIn("evidence_texts", briefs[0])

    def test_evidence_texts_are_collected_from_registry(self):
        specs = [{
            "category_hint": "theory",
            "title": "方法",
            "evidence_ids": ["EV0001", "EV0002"],
        }]
        briefs, _ = build_briefs(specs, self.workflow)
        evidence_texts = briefs[0]["evidence_texts"]
        self.assertEqual([entry["evidence_id"] for entry in evidence_texts], ["EV0001", "EV0002"])
        self.assertEqual(evidence_texts[0]["text"], "Finding number 1 about the sample. It holds under load.")

    def test_explicit_evidence_texts_wins(self):
        explicit = [{"evidence_id": "EV0001", "text": "custom text"}]
        specs = [{
            "category_hint": "theory",
            "title": "方法",
            "evidence_ids": ["EV0001"],
            "evidence_texts": explicit,
        }]
        briefs, _ = build_briefs(specs, self.workflow)
        self.assertEqual(briefs[0]["evidence_texts"], explicit)


if __name__ == "__main__":
    unittest.main(verbosity=2)
