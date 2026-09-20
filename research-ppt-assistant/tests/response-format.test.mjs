import assert from "node:assert/strict";
import test from "node:test";
import { createDeckPlan } from "../server/core.mjs";
import { formatStructuredContent, normalizeDetailLevel, summarizeToolResult } from "../server/response-format.mjs";

test("compact deck output remains actionable while materially reducing payload size", async () => {
  const plan = await createDeckPlan({
    topic: "可信多模态学习",
    presentation_type: "group_meeting",
    slide_count: 12,
  });
  const compact = formatStructuredContent("create_deck_plan", plan, "compact");
  const standard = formatStructuredContent("create_deck_plan", plan, "standard");
  const full = formatStructuredContent("create_deck_plan", plan, "full");
  const compactLength = JSON.stringify(compact).length;
  const fullLength = JSON.stringify(full).length;

  assert.equal(compact.detail_level, "compact");
  assert.equal(compact.pipeline_status, "plan_complete");
  assert.equal(compact.slides.length, 12);
  assert.ok(Object.keys(compact.slides[0].slot_assignments).length > 0);
  assert.equal(compact.slides[0].design_context.design_ir.schema_version, "1.0.0");
  assert.ok(compact.slides[0].design_context.deck_state_before.recent_history);
  assert.equal("slot_specs" in compact.slides[0], false);
  assert.equal(standard.detail_level, "standard");
  assert.equal("planning_contexts" in standard, false);
  assert.equal("slot_specs" in standard.slides[0], true);
  assert.equal("planning_contexts" in full, true);
  assert.ok(compactLength < fullLength * 0.55, `compact=${compactLength}, full=${fullLength}`);
});

test("tool text is a concise summary instead of duplicated structured JSON", async () => {
  const plan = await createDeckPlan({ presentation_type: "custom", slide_briefs: [{ title: "结论", category_hint: "summary" }] });
  const text = summarizeToolResult("create_deck_plan", plan, "compact");
  assert.match(text, /plan_complete/);
  assert.match(text, /slide\(s\) planned/);
  assert.equal(text.trimStart().startsWith("{"), false);
  assert.ok(text.length < JSON.stringify(plan).length * 0.05);
});

test("detail levels are explicit and reject unsupported values", () => {
  assert.equal(normalizeDetailLevel(undefined), "compact");
  assert.equal(normalizeDetailLevel(undefined, "standard"), "standard");
  assert.throws(() => normalizeDetailLevel("verbose"), /Unsupported detail_level/);
});

test("compact stability outputs preserve gates and omit benchmark case payloads", () => {
  const auditPayload = {
    audit_version: "1.0.0",
    status: "invalid",
    layout_count: 320,
    category_count: 40,
    theme_count: 16,
    preview_count: 320,
    issue_count: 25,
    issue_counts: { SAMPLE: 25 },
    issues: Array.from({ length: 25 }, (_, index) => ({ code: "SAMPLE", path: `layouts[${index}]` })),
  };
  const compactAudit = formatStructuredContent("audit_layout_library", auditPayload, "compact");
  assert.equal(compactAudit.issues.length, 20);
  assert.match(summarizeToolResult("audit_layout_library", auditPayload), /25 issue/);

  const benchmarkPayload = {
    benchmark_version: "1.0.0",
    dataset: { name: "fixture", case_count: 2 },
    status: "passed",
    metrics: { top_1_valid_rate: { passed: 1, total: 2, rate: 0.5 } },
    determinism: { passed: true },
    performance: { single_slide_p95_ms: 12 },
    thresholds: {},
    checks: [],
    expectation_failures: [],
    cases: [{ id: "one" }, { id: "two" }],
  };
  const compactBenchmark = formatStructuredContent("run_benchmark", benchmarkPayload, "compact");
  assert.equal("cases" in compactBenchmark, false);
  assert.match(summarizeToolResult("run_benchmark", benchmarkPayload), /Top-1 50%/);
});

test("response formatting covers every compact projection and summary family", () => {
  const longText = "x".repeat(300);
  const issue = {
    code: "CAPACITY",
    field: "body",
    severity: "error",
    recoverable: true,
    recommended_action: "split",
    message: longText,
    path: "$.body",
    details: { slot_id: "body" },
  };
  const plan = {
    pipeline_status: "plan_complete",
    status: "adapted",
    deck_title: "Deck",
    presentation_type: "custom",
    theme_id: "paper_blue",
    requested_slide_count: 2,
    content_model: { schema_version: "1", status: "valid", sources: [], citations: [], evidence: [], slide_briefs: [], violations: [issue] },
    slides: [{
      index: 1,
      slide_id: "SLIDE0001",
      title: "Result",
      category: "summary",
      layout_id: "RM-SUMMARY-01",
      binding_status: "adapted",
      contract_valid: true,
      planning_decision: "accepted",
      slot_assignments: {
        title: { type: "text", content_id: "title", text: longText, asset_uri: "asset.png", steps: [1], items: [1, 2], rows: [1], series: [1], events: [1], value: 3 },
        empty: null,
        primitive: "text",
      },
      violations: [issue],
      adaptation_log: [{ action: "trim" }],
    }],
    unplanned_slide_briefs: [{ slide_id: "SLIDE0002", slide_type: "result", title: "Later", category_hint: "summary" }],
    warnings: [longText],
  };
  const compactPlan = formatStructuredContent("create_deck_plan", plan);
  assert.equal(compactPlan.slides[0].slot_assignments.title.text.endsWith("…"), true);
  assert.equal(compactPlan.slides[0].slot_assignments.title.items_count, 2);
  assert.equal(compactPlan.slides[0].slot_assignments.title.value, 3);
  assert.equal(compactPlan.slides[0].violations[0].slot_id, "body");
  assert.equal(compactPlan.warnings[0].endsWith("…"), true);

  const samples = [
    ["search_layouts", { query: {}, compatibility: { candidate_count: 2, compatible_count: 1 }, results: [{ id: "L", category: "summary", family: "text", density: "低", score: 1, capacity: {}, preview_uri: "p" }] }],
    ["normalize_content", { schema_version: "1", status: "valid", sources: [], citations: [], evidence: [], slide_briefs: [], violations: [issue], adaptation_log: [] }],
    ["validate_slide", { status: "invalid", pipeline_status: "preflight_complete", slide_number: 1, layout_id: "L", category: "summary", issues: [issue] }],
    ["validate_deck_plan", { status: "invalid", pipeline_status: "preflight_complete", slide_count: 1, invalid_slides: [1], warning_slides: [], issue_counts: {}, deck_issues: [issue], slides: [{ index: 1, slide_number: 1, layout_id: "L", category: "summary", status: "invalid", issues: [issue] }], next_action: "fix" }],
    ["validate_renderer_inputs", { status: "warning", requested_renderer: "slidep", effective_renderer: "slidep", compatibility_mode: false, project_path: "F:/deck", source_files: ["01.slide"], issues: [issue] }],
    ["run_preflight", { pipeline_status: "preflight_complete", status: "invalid", invalid_slides: [1], warning_slides: [], renderer_guard: { status: "valid", source_count: 1, issues: [] }, deck_validation: { status: "invalid", slides: [], deck_issues: [issue] } }],
    ["evaluate_visual_quality", { report_version: "1", telemetry_version: "1", profile_id: "default", profile_version: "1", slide_id: "S", renderer: "slidep", status: "warning", checks: { contrast: { status: "not_evaluable", metric: "contrast", reason: "missing" } }, violations: [issue], recommended_action: "provide_required_input", reasons: ["missing"] }],
    ["assemble_render_telemetry", { pipeline_status: "render_telemetry_assembled", readiness_status: "blocked", canonical_telemetry: { slide_id: "S", renderer: "artifact-tool" }, missing_facts: [{ field: "visual_manifest", reason: "missing" }], manual_review: [], geometry_provenance: null }],
    ["run_figure_placement", { pipeline_status: "figure_placement_complete", status: "fail", trace_id: "T", stages: { region_resolution: { status: "resolved", selected_region: { region_id: "d" } }, placement: { status: "resolved", fit_mode: "contain", source_region: {}, final_placement: {} }, renderer_effective: { status: "modified", placement_modified: true, modification_reason: "placement_changed" } }, metrics: { letterbox_ratio: 0.5 }, artifacts: { "qa_report.json": { checks: { letterbox: { status: "fail", code: "IMAGE_UNDERFILLED_SLOT", recommended_action: "reconsider_visual_placement" } }, violations: [issue], recommended_action: "reconsider_visual_placement" } } }],
    ["run_group_fit_preflight", { pipeline_status: "group_fit_preflight_complete", status: "warning", decision: "shadow_preserve_v045", group_id: "g", selected_candidate: { layout_id: "BASE", source: "v0.4.5_baseline", metrics: {}, conflict: {} }, fallback_to_v045: false, relation_fit: {}, constraint_arbitration: {}, credits_regression: {}, issues: [issue], recommended_action: "review_shadow_candidate" }],
  ];
  for (const [toolName, payload] of samples) {
    assert.equal(formatStructuredContent(toolName, payload).detail_level, "compact", toolName);
  }
  assert.equal(formatStructuredContent("unknown", { ok: true }).ok, true);
  assert.equal(formatStructuredContent("unknown", { ok: true }, "standard").ok, true);
  assert.equal(formatStructuredContent("unknown", { ok: true }, "full").ok, true);

  const summaries = [
    ["catalog_summary", { layout_count: 320, themes: [] }],
    ["normalize_content", { status: "valid" }],
    ["search_layouts", {}],
    ["get_layout", { layout_id: "L" }],
    ["run_preflight", { status: "valid" }],
    ["validate_deck_plan", { status: "invalid", deck_issues: [issue], slides: [{ issues: [issue] }] }],
    ["validate_rendered_deck", { status: "valid", invalid_slides: [], warning_slides: [] }],
    ["validate_slide", { status: "invalid", issues: [issue] }],
    ["validate_rendered_slide", { status: "valid" }],
    ["validate_renderer_inputs", { status: "valid" }],
    ["evaluate_visual_quality", { status: "pass", profile_id: "default", violations: [] }],
    ["assemble_render_telemetry", { readiness_status: "ready", missing_facts: [], manual_review: [] }],
    ["run_figure_placement", { status: "pass", trace_id: "T", artifacts: { "qa_report.json": { violations: [] } } }],
    ["run_group_fit_preflight", { status: "pass", decision: "preserve_v045_baseline", selected_candidate: { layout_id: "BASE" } }],
    ["unknown", {}],
  ];
  for (const [toolName, payload] of summaries) assert.equal(typeof summarizeToolResult(toolName, payload), "string");
});

test("response formatting keeps sparse payloads safe", () => {
  const sparsePlan = formatStructuredContent("create_deck_plan", {
    status: "valid",
    theme: { id: "theme" },
    slides: [{ slot_assignments: [], violations: "none" }],
    warnings: [],
  });
  assert.equal(sparsePlan.theme_id, "theme");
  assert.deepEqual(sparsePlan.slides[0].slot_assignments, {});

  const issueVariants = [null, "plain", { code: "SHORT", message: "short" }];
  const compactSlide = formatStructuredContent("validate_rendered_slide", { status: "warning", issues: issueVariants });
  assert.deepEqual(compactSlide.issues.slice(0, 2), [null, "plain"]);
  assert.equal(formatStructuredContent("search_layouts", { candidate_count: 0, compatible_count: 0 }).candidate_count, 0);
  assert.equal(formatStructuredContent("validate_renderer_inputs", { page_count: 0 }).page_count, 0);
  assert.equal(formatStructuredContent("validate_renderer_inputs", { source_count: 2 }).page_count, 2);
  assert.equal(formatStructuredContent("run_preflight", {}).renderer_guard.status, undefined);
  assert.deepEqual(formatStructuredContent("audit_layout_library", {}).issues, []);
  assert.match(summarizeToolResult("run_benchmark", { status: "skipped", dataset: {}, metrics: {} }), /not measured/);
  assert.match(summarizeToolResult("get_layout", {}), /unknown/);
  assert.match(summarizeToolResult("catalog_summary", {}), /0 layouts/);
});
