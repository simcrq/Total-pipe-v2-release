import assert from "node:assert/strict";
import test from "node:test";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import {
  PIPELINE_STATUS,
  bindSlideContent,
  catalogSummary,
  createDeckPlan,
  getLayout,
  normalizeMetrics,
  planSlideContent,
  readPreview,
  runPreflight,
  searchLayouts,
  validateDeckPlan,
  validateRendererInputs,
  validateRenderedDeck,
  validateRenderedSlide,
  validateSlide,
} from "../server/core.mjs";

async function makeTempDeck(files) {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), "rpa-deck-"));
  await fs.mkdir(path.join(dir, "slides"), { recursive: true });
  for (const name of files) await fs.writeFile(path.join(dir, "slides", name), "");
  return dir;
}

// 把「本机临时目录」当 project_path 的 preflight 用例必须声明宿主平台：写死 win32 时
// 校验器会要求盘符绝对路径（macOS/Linux 的 tmpdir 不满足）并让磁盘校验因 platform_mismatch
// 降级，于是这些用例只能在 Windows 上通过。Windows 上 process.platform 同样是 "win32"，
// 行为与改动前完全一致。合成 F:/... 路径的纯校验用例不受影响，仍显式写 win32。
const HOST_PLATFORM = process.platform;

test("catalog exposes the complete v2 library", async () => {
  const summary = await catalogSummary();
  assert.equal(summary.library.layout_count, 320);
  assert.equal(summary.content_model_contract_version, "0.3.3");
  assert.equal(summary.slot_binding_contract_version, "1.0.1");
  assert.equal(summary.planning_loop_contract_version, "1.0.0");
  assert.equal(summary.pipeline_contract_version, "1.3.0");
  assert.equal(summary.slide_design_ir_contract_version, "1.0.0");
  assert.equal(summary.design_compiler_contract_version, "1.0.0");
  assert.equal(summary.design_registry_contract_version, "1.0.0");
  assert.equal(summary.candidate_factory_contract_version, "1.0.0");
  assert.equal(summary.aesthetic_scorer_contract_version, "1.0.0");
  assert.equal(summary.deck_design_state_contract_version, "1.0.0");
  assert.equal(summary.design_qa_contract_version, "1.0.0");
  assert.equal(summary.visual_observer_contract_version, "1.0.0");
  assert.equal(summary.repair_controller_contract_version, "1.0.0");
  assert.equal(summary.bounded_repair_loop_contract_version, "1.0.0");
  assert.equal(summary.stability_contract_version, "1.1.0");
  assert.equal(summary.library.stability_contract_version, "1.1.0");
  assert.equal(summary.render_telemetry_contract_version, "1.4.0");
  assert.equal(summary.render_evidence_contract_version, "0.4.7");
  assert.equal(summary.visual_quality_contract_version, "0.6.0");
  assert.equal(summary.quality_profile_contract_version, "1.4.0");
  assert.equal(summary.qa_report_contract_version, "1.4.0");
  assert.equal(summary.relation_fit_contract_version, "1.0.0");
  assert.deepEqual(summary.supported_visual_qa_renderers, ["slidep", "tencent-pptx", "artifact-tool"]);
  assert.equal(summary.categories.length, 40);
  assert.equal(summary.themes.length, 16);
});

test("80 characters and two images retrieve dual-figure layouts", async () => {
  const result = await searchLayouts({ text_chars: 80, image_count: 2, table_count: 0, k: 3 });
  assert.deepEqual(
    result.results.map((item) => item.id),
    ["RM-DUAL_FIGURE-01", "RM-DUAL_FIGURE-02", "RM-DUAL_FIGURE-03"],
  );
  assert.ok(result.results.every((item) => item.score > 90));
  assert.ok(result.results.every((item) => item.components.typography_fit === undefined));
  assert.ok(result.results.every((item) => item.components.visual_complexity_fit === undefined));
  assert.ok(result.results.every((item) => item.components.occupancy_fit === undefined));
});

test("material aspect ratios and 10% safety margin can promote the asymmetric dual-figure layout", async () => {
  const result = await searchLayouts({
    text_chars: 40,
    image_count: 2,
    visuals: [
      { visual_type: "simple_plot", visual_aspect_ratio: 1, caption_chars: 20 },
      { visual_type: "simple_plot", visual_aspect_ratio: 1.37, caption_chars: 20 },
    ],
    k: 3,
  });
  assert.equal(result.results[0].id, "RM-DUAL_FIGURE-07");
  assert.ok(result.results[0].components.visual_material_fit > result.results[1].components.visual_material_fit);
  assert.equal(result.query.visual_safety_margin, 0.1);
});

test("a two-region composite figure does not enter a required four-case layout", async () => {
  const result = await searchLayouts({
    categories: ["qualitative"],
    image_count: 2,
    visuals: [
      { visual_type: "composite_figure_region", source_visual_id: "fig-2", region_id: "panel-a", semantic_relation: "parallel_evidence" },
      { visual_type: "composite_figure_region", source_visual_id: "fig-2", region_id: "panel-b", semantic_relation: "parallel_evidence" },
    ],
  });
  assert.equal(result.compatible_candidate_count, 0);
  assert.ok(result.compatibility.excluded_layouts.every((layout) => layout.violations.some((issue) => issue.code === "UNUSED_REQUIRED_VISUAL_SLOT")));
});

test("getLayout returns normalized and PowerPoint-inch coordinates", async () => {
  const result = await getLayout("RM-ABLATION-01", "paper_blue");
  assert.equal(result.layout.category, "ablation");
  assert.equal(result.theme.id, "paper_blue");
  assert.ok(result.layout.slot_specs.every((slot) => slot.box && slot.pptx_in));
  assert.ok(result.layout.constraints.minimum_title_font_pt >= 35);
  assert.equal(result.layout.slot_specs.find((slot) => slot.slot_id === "title").slot_type, "text");
  assert.ok(result.layout.slot_specs.find((slot) => slot.slot_id === "title").capacity.min_font_pt >= 35);
});

test("deck planning creates a coherent unique-layout group meeting", async () => {
  const plan = await createDeckPlan({
    topic: "可信多模态学习",
    presentation_type: "group_meeting",
    slide_count: 12,
  });
  assert.equal(plan.slides.length, 12);
  assert.equal(plan.pipeline_status, PIPELINE_STATUS.plan);
  assert.equal(plan.slides[0].category, "cover");
  assert.ok(plan.slides.some((slide) => slide.category === "summary"));
  assert.equal(plan.slides.at(-1).category, "qa");
  assert.equal(new Set(plan.slides.map((slide) => slide.layout_id)).size, 12);
  assert.ok(plan.slides.every((slide) => Array.isArray(slide.slot_specs) && Object.keys(slide.slot_assignments).length > 0));
});

test("planner emits the shared slot contract and round-trips through validation", async () => {
  const plan = await createDeckPlan({
    presentation_type: "custom",
    slide_briefs: [
      { title: "训练流程", category_hint: "workflow", process_step_count: 3, text_chars: 40 },
    ],
  });
  const slide = plan.slides[0];
  assert.ok(Array.isArray(slide.slot_specs));
  assert.equal(typeof slide.slot_assignments, "object");
  assert.equal(Array.isArray(slide.slot_assignments), false);
  assert.equal(slide.slot_specs[0].slot_id, "title");
  assert.equal(slide.slot_specs[0].slot_type, "text");
  assert.equal(slide.slot_assignments.title.type, "text");
  assert.ok(slide.slot_assignments.title.text);

  const validation = await validateDeckPlan({ theme_id: plan.theme.id, slides: plan.slides });
  assert.deepEqual(validation.invalid_slides, []);
});

test("planner emits public snake-case telemetry that round-trips through MCP schemas", async () => {
  const plan = await createDeckPlan({
    presentation_type: "custom",
    slide_briefs: [{
      title: "主结果",
      category_hint: "single_figure",
      image_count: 1,
      visuals: [{ visual_type: "dense_plot", panel_count: 2, has_embedded_text: true, asset_uri: "figures/result.png" }],
      slot_metrics: [{ slot_id: "caption", role: "caption", text_chars: 20, font_pt: 16, line_count: 1 }],
    }],
  });
  const metrics = plan.slides[0].content_metrics;
  assert.equal(metrics.visuals[0].visual_type, "dense_plot");
  assert.equal("visualType" in metrics.visuals[0], false);
  assert.equal(metrics.slot_metrics[0].slot_id, "caption");
  assert.equal("slotId" in metrics.slot_metrics[0], false);
  const validation = await validateDeckPlan({ slides: plan.slides });
  assert.deepEqual(validation.invalid_slides, []);
});

test("custom slide briefs preserve explicit category hints", async () => {
  const plan = await createDeckPlan({
    presentation_type: "custom",
    slide_briefs: [
      { title: "消融结果定位模块贡献", category_hint: "ablation", text_chars: 180, table_count: 1, chart_count: 1 },
    ],
  });
  assert.equal(plan.slide_count, 1);
  assert.equal(plan.slides[0].category, "ablation");
});

test("planner consumes traceable normalized slide briefs", async () => {
  const plan = await createDeckPlan({
    presentation_type: "custom",
    sources: [{ source_id: "SRC0001", title: "Paper", source_sha256: "b".repeat(64) }],
    citations: [{ citation_id: "CIT0001", source_id: "SRC0001", span_id: "S0001", chunk_id: "E001", source_chars: { start: 10, end: 40 }, source_lines: { start: 2, end: 2 } }],
    evidence: [{ evidence_id: "EV0001", evidence: "Accuracy improved by 4%.", citation_ids: ["CIT0001"], content_role: "primary_evidence", importance: 1, must_keep: true }],
    slide_briefs: [{ title: "Accuracy improved", goal: "Present the primary measurement", category_hint: "single_figure", text_chars: 40, image_count: 1, evidence_ids: ["EV0001"], citation_ids: ["CIT0001"] }],
  });
  assert.equal(plan.content_model.status, "valid");
  assert.deepEqual(plan.slides[0].evidence_ids, ["EV0001"]);
  assert.deepEqual(plan.slides[0].citation_ids, ["CIT0001"]);
  assert.equal(plan.content_model.citations[0].source_id, "SRC0001");
});

test("deck planning auto-splits structural overload without dropping process steps", async () => {
  const processSteps = Array.from({ length: 10 }, (_, index) => ({ id: `step-${index + 1}`, text: `步骤 ${index + 1}` }));
  const plan = await createDeckPlan({
    presentation_type: "custom",
    allow_auto_split: true,
    max_replan_attempts: 0,
    slide_briefs: [{ slide_id: "SLIDE0001", title: "十步流程", goal: "说明完整流程", category_hint: "workflow", process_steps: processSteps, process_step_count: 10 }],
  });
  assert.equal(plan.status, "adapted");
  assert.equal(plan.requested_slide_count, 1);
  assert.equal(plan.slide_count, 2);
  assert.ok(plan.slides.every((slide) => slide.planning_decision === "split" && slide.contract_valid));
  assert.deepEqual(
    plan.slides.flatMap((slide) => Object.values(slide.slot_assignments).map((assignment) => assignment.content_id).filter((id) => id?.startsWith("step-"))),
    processSteps.map((step) => step.id),
  );
});

test("deck planning honors allow_auto_split false and preserves the unplanned brief", async () => {
  const processSteps = Array.from({ length: 10 }, (_, index) => ({ id: `step-${index + 1}`, text: `步骤 ${index + 1}` }));
  const plan = await createDeckPlan({
    presentation_type: "custom",
    allow_auto_split: false,
    max_replan_attempts: 0,
    slide_briefs: [{ slide_id: "SLIDE0001", title: "十步流程", category_hint: "workflow", process_steps: processSteps, process_step_count: 10 }],
  });
  assert.equal(plan.status, "needs_replan");
  assert.equal(plan.slide_count, 0);
  assert.equal(plan.unplanned_slide_briefs.length, 1);
  assert.deepEqual(plan.unplanned_slide_briefs[0].process_steps.map((step) => step.id), processSteps.map((step) => step.id));
  assert.ok(plan.planning_contexts[0].replan_context.violations.some((issue) => issue.code === "REPLAN_EXHAUSTED"));
});

test("slide validation rejects content that exceeds hard capacity", async () => {
  const validation = await validateSlide({
    layout_id: "RM-DUAL_FIGURE-01",
    text_chars: 500,
    image_count: 4,
    table_count: 1,
  });
  assert.equal(validation.status, "invalid");
  for (const code of ["TEXT_CAPACITY_EXCEEDED", "FIGURE_CAPACITY_EXCEEDED", "TABLE_CAPACITY_EXCEEDED"]) {
    assert.equal(validation.issues.filter((issue) => issue.code === code).length, 1, `${code} should be reported exactly once`);
  }
});

test("missing required slot is an error in the shared contract", async () => {
  const validation = await validateSlide({
    layout_id: "RM-SINGLE_FIGURE-01",
    title_chars: 12,
    image_count: 1,
    slot_assignments: {
      title: { type: "text", text: "主结果" },
    },
  });
  assert.equal(validation.status, "invalid");
  assert.ok(validation.issues.some((issue) => issue.code === "MISSING_REQUIRED_SLOT" && issue.details?.slot_id === "figure"));
});

test("provided slot_specs must contain the complete layout definition", async () => {
  const layout = await getLayout("RM-SINGLE_FIGURE-01");
  const validation = await validateSlide({
    layout_id: "RM-SINGLE_FIGURE-01",
    slot_specs: layout.layout.slot_specs.filter((slot) => slot.slot_id === "title"),
    slot_assignments: Object.fromEntries(
      layout.layout.slot_specs
        .filter((slot) => slot.required)
        .map((slot) => [slot.slot_id, { type: "guidance", text: `fill ${slot.slot_id}` }]),
    ),
  });
  assert.equal(validation.status, "invalid");
  assert.ok(validation.issues.some((issue) => issue.code === "INVALID_LAYOUT_SPEC" && issue.details?.slot_id === "figure"));
});

test("provided slot_specs cannot override layout capacity", async () => {
  const layout = await getLayout("RM-SINGLE_FIGURE-01");
  const slotSpecs = structuredClone(layout.layout.slot_specs);
  slotSpecs.find((slot) => slot.slot_id === "title").capacity.max_chars = 9999;
  const validation = await validateSlide({
    layout_id: "RM-SINGLE_FIGURE-01",
    slot_specs: slotSpecs,
    slot_assignments: Object.fromEntries(
      slotSpecs
        .filter((slot) => slot.required)
        .map((slot) => [slot.slot_id, { type: "guidance", text: `fill ${slot.slot_id}` }]),
    ),
  });
  assert.equal(validation.status, "invalid");
  assert.ok(validation.issues.some((issue) => issue.code === "INVALID_LAYOUT_SPEC" && issue.details?.slot_id === "title"));
});

test("structured assignments are checked against actual slot capacity", async () => {
  const layout = await getLayout("RM-SINGLE_FIGURE-01");
  const requiredAssignments = Object.fromEntries(
    layout.layout.slot_specs
      .filter((slot) => slot.required)
      .map((slot) => [slot.slot_id, { type: "guidance", text: `fill ${slot.slot_id}` }]),
  );
  requiredAssignments.title = { type: "text", text: "超".repeat(500) };
  const validation = await validateSlide({
    layout_id: "RM-SINGLE_FIGURE-01",
    slot_specs: layout.layout.slot_specs,
    slot_assignments: requiredAssignments,
  });
  assert.equal(validation.status, "invalid");
  assert.ok(validation.issues.some((issue) => issue.code === "SLOT_CAPACITY_EXCEEDED" && issue.details?.slot_id === "title"));
});

test("layout retrieval excludes a five-step layout for ten process steps", async () => {
  const result = await searchLayouts({ categories: ["workflow"], process_step_count: 10, k: 5 });
  assert.equal(result.results.some((item) => item.id === "RM-WORKFLOW-01"), false);
  const excluded = result.compatibility.excluded_layouts.find((item) => item.layout_id === "RM-WORKFLOW-01");
  assert.ok(excluded);
  assert.deepEqual(
    excluded.violations.find((issue) => issue.code === "PROCESS_CAPACITY_EXCEEDED"),
    {
      code: "PROCESS_CAPACITY_EXCEEDED",
      field: "process_step_count",
      actual: 10,
      capacity: 5,
      severity: "error",
      recoverable: true,
      recommended_action: "replan_or_split",
      message: "需要 10 个流程步骤，但版式只有 5 个流程槽。",
    },
  );
});

test("unknown explicit slot IDs are invalid and never fall back", async () => {
  const validation = await validateSlide({
    layout_id: "RM-SINGLE_FIGURE-01",
    title_chars: 12,
    image_count: 1,
    slot_assignments: {
      title: { type: "text", text: "主结果" },
      not_a_slot: { type: "text", text: "错误绑定" },
      figure: { type: "image", asset_uri: "figure.png" },
      caption: { type: "text", text: "图注" },
      takeaway: { type: "text", text: "结论" },
      annotation: { type: "text", text: "标注" },
    },
    visuals: [{ slot_id: "not_a_visual_slot", visual_type: "dense_plot" }],
  });
  assert.equal(validation.status, "invalid");
  assert.ok(validation.issues.some((issue) => issue.code === "INVALID_EXPLICIT_SLOT" && issue.details?.slot_id === "not_a_slot"));
  assert.ok(validation.issues.some((issue) => issue.code === "INVALID_EXPLICIT_SLOT" && issue.details?.slot_id === "not_a_visual_slot"));
  assert.equal(validation.visual_placements[0].slot_id, undefined);
});

test("explicit visuals reject an existing non-visual slot without fallback", async () => {
  const validation = await validateSlide({
    layout_id: "RM-SINGLE_FIGURE-01",
    slot_assignments: {
      title: { type: "text", text: "主结果" },
      figure: { type: "image", asset_uri: "figure.png" },
      caption: { type: "text", text: "图注" },
      takeaway: { type: "text", text: "结论" },
      annotation: { type: "text", text: "标注" },
    },
    visuals: [{ slot_id: "title", visual_type: "dense_plot" }],
  });
  assert.equal(validation.status, "invalid");
  assert.ok(validation.issues.some((issue) => issue.code === "SLOT_TYPE_MISMATCH" && issue.details?.slot_id === "title"));
  assert.equal(validation.visual_placements[0].slot_id, undefined);
});

test("a generated deck plan passes hard-capacity validation", async () => {
  const plan = await createDeckPlan({ presentation_type: "progress_report", slide_count: 10 });
  const validation = await validateDeckPlan({ theme_id: plan.theme.id, slides: plan.slides });
  assert.deepEqual(validation.invalid_slides, []);
});

test("pre-render slot validation is structural and leaves rendered font/line quality to Visual QA", async () => {
  const validation = await validateSlide({
    layout_id: "RM-WORKFLOW-08",
    title_chars: 12,
    text_chars: 90,
    image_count: 1,
    process_step_count: 5,
    slot_metrics: [
      { slot_id: "step1", text_chars: 30, font_pt: 15, line_count: 4 },
    ],
  });
  assert.equal(validation.status, "invalid");
  assert.ok(validation.issues.some((issue) => issue.code === "SLOT_TEXT_OVERFLOW"));
  assert.ok(!validation.issues.some((issue) => issue.code === "FONT_FLOOR_VIOLATION"));
  assert.ok(!validation.issues.some((issue) => issue.code === "SLOT_LINE_OVERFLOW"));
});

test("pre-render validation rejects a visual slot below structural width capacity", async () => {
  const validation = await validateSlide({
    layout_id: "RM-QUALITATIVE-01",
    title_chars: 12,
    text_chars: 40,
    image_count: 4,
    visuals: [
      { slot_id: "case1", visual_type: "multi_panel_figure", panel_count: 6, has_embedded_text: true },
    ],
  });
  assert.ok(validation.issues.some((issue) => issue.code === "VISUAL_SLOT_CAPACITY_EXCEEDED"));
  assert.ok(!validation.issues.some((issue) => issue.code === "DENSE_FIGURE_TOO_SMALL" || issue.code === "VISUAL_READABILITY_RISK"));
  assert.equal(validation.visual_placements.length, 1);
});

test("P11-style summary visual is rejected before render while P5 layout slots remain structurally eligible", async () => {
  const summary = await validateSlide({
    layout_id: "RM-SUMMARY-08",
    image_count: 1,
    visuals: [{ slot_id: "visual", visual_type: "visual_evidence", has_embedded_text: true }],
  });
  assert.equal(summary.status, "invalid");
  assert.ok(summary.issues.some((issue) => issue.code === "VISUAL_SLOT_CAPACITY_EXCEEDED"));

  const mechanism = await validateSlide({
    layout_id: "RM-METHOD_OVERVIEW-07",
    image_count: 2,
    visuals: [
      { slot_id: "input", visual_type: "multi_panel_figure", panel_count: 2, has_embedded_text: true },
      { slot_id: "output", visual_type: "dense_plot", panel_count: 2, has_embedded_text: true },
    ],
  });
  assert.ok(!mechanism.issues.some((issue) => issue.code === "VISUAL_SLOT_CAPACITY_EXCEEDED"));
});

test("rendered-slide QA detects the real small-font and empty-layout regression", async () => {
  const validation = await validateRenderedSlide({
    layout_id: "RM-WORKFLOW-08",
    viewing_mode: "projector",
    title_font_pt: 30,
    title_line_count: 1,
    body_font_pts: [14, 18],
    content_occupancy: 0.45,
    largest_empty_band: 0.20,
    visuals: [
      {
        visual_type: "multi_panel_figure",
        panel_count: 6,
        has_embedded_text: true,
        display_width_norm: 0.32,
        rendered_embedded_text_px: 8,
      },
    ],
  });
  assert.equal(validation.status, "invalid");
  for (const code of ["FONT_FLOOR_VIOLATION", "LOW_CONTENT_OCCUPANCY", "UNINTENTIONAL_EMPTY_BAND", "DENSE_FIGURE_TOO_SMALL", "EMBEDDED_TEXT_TOO_SMALL"]) {
    assert.ok(validation.issues.some((issue) => issue.code === code), `missing ${code}`);
  }
});

test("legacy rendered-slide wrapper promotes Visual QA uncertainty to the overall status", async () => {
  const result = await validateRenderedSlide({
    slide_id: "legacy-valid",
    viewing_mode: "projector",
    text_elements: [
      { id: "title", role: "title", font_pt: 40, line_count: 1, overflow: false },
      { id: "body", role: "body", font_pt: 20, line_count: 2, overflow: false },
    ],
    content_occupancy: 0.75,
    largest_empty_band: 0.08,
    content_center_x: 0.5,
    content_center_y: 0.5,
  });
  assert.equal(result.status, "warning");
  assert.equal(result.overall_status, "warning");
  assert.equal(result.readability_status, "valid");
  assert.equal(result.checks.legacy_readability.status, "pass");
  assert.equal(result.visual_quality_status, "warning");
});

test("rendered-deck QA includes Visual QA warnings in its aggregate status", async () => {
  const validation = await validateRenderedDeck({
    viewing_mode: "projector",
    slides: [{
      slide_id: "legacy-warning",
      category: "summary",
      text_elements: [
        { id: "title", role: "title", font_pt: 40, line_count: 1, overflow: false },
        { id: "body", role: "body", font_pt: 20, line_count: 2, overflow: false },
      ],
      content_occupancy: 0.75,
      largest_empty_band: 0.08,
      content_center_x: 0.5,
      content_center_y: 0.5,
    }],
  });
  assert.equal(validation.status, "warning");
  assert.equal(validation.overall_status, "warning");
  assert.equal(validation.readability_status, "valid");
  assert.equal(validation.visual_quality_status, "warning");
  assert.deepEqual(validation.warning_slides, [1]);
  assert.equal(validation.issue_counts.CONTRAST_NOT_EVALUABLE, 1);
  assert.match(validation.next_action, /missing renderer telemetry/i);
});

test("rendered-deck QA aggregates slide-level readability failures", async () => {
  const validation = await validateRenderedDeck({
    viewing_mode: "projector",
    slides: [
      {
        category: "summary",
        title_font_pt: 40,
        title_line_count: 1,
        body_font_pts: [20],
        content_occupancy: 0.74,
        largest_empty_band: 0.08,
      },
      {
        category: "workflow",
        title_font_pt: 30,
        title_line_count: 2,
        body_font_pts: [14],
        content_occupancy: 0.42,
        largest_empty_band: 0.22,
      },
    ],
  });
  assert.equal(validation.status, "invalid");
  assert.equal(validation.pipeline_status, PIPELINE_STATUS.renderQa);
  assert.deepEqual(validation.invalid_slides, [2]);
  assert.equal(validation.issue_counts.TITLE_WRAPPED, 1);
});

test("planning, combined preflight, and render QA expose independent pipeline states", async () => {
  const plan = await createDeckPlan({
    presentation_type: "custom",
    slide_briefs: [{ title: "核心结论", category_hint: "summary", text_chars: 40 }],
  });
  const deckDir = await makeTempDeck(["01_summary.slide"]);
  const preflight = await runPreflight({
    renderer_inputs: {
      requested_renderer: "slidep",
      renderer_version: "5.4.4",
      platform: HOST_PLATFORM,
      project_path: deckDir,
      project_exists: true,
      source_files: ["slides/01_summary.slide"],
      live_watch_requested: false,
    },
    deck_plan: { theme_id: plan.theme.id, slides: plan.slides },
  });
  await fs.rm(deckDir, { recursive: true, force: true });
  const renderQa = await validateRenderedDeck({
    viewing_mode: "projector",
    slides: [{
      category: "summary",
      title_font_pt: 40,
      title_line_count: 1,
      body_font_pts: [20],
      content_occupancy: 0.74,
      largest_empty_band: 0.08,
    }],
  });

  assert.equal(plan.pipeline_status, "plan_complete");
  assert.equal(preflight.pipeline_status, "preflight_complete");
  assert.equal(renderQa.pipeline_status, "render_qa_complete");
  assert.equal(new Set([plan.pipeline_status, preflight.pipeline_status, renderQa.pipeline_status]).size, 3);
  assert.equal(preflight.renderer_guard.status, "valid");
  assert.deepEqual(preflight.invalid_slides, []);
});

test("planner traceability-only assignments pass directly through preflight", async () => {
  const plan = await createDeckPlan({
    presentation_type: "custom",
    sources: [{ source_id: "SRC0001", title: "Paper", source_sha256: "a".repeat(64) }],
    citations: [{
      citation_id: "CIT0001",
      source_id: "SRC0001",
      span_id: "S0001",
      chunk_id: "E001",
      source_lines: { start: 2, end: 2 },
      source_chars: { start: 10, end: 40 },
    }],
    evidence: [{
      evidence_id: "EV0001",
      evidence: "Measured peak shifted.",
      citation_ids: ["CIT0001"],
      content_role: "primary_evidence",
      importance: 1,
      must_keep: true,
    }],
    slide_briefs: [{
      slide_id: "SLIDE0001",
      title: "Peak shifted",
      goal: "Present the measurement",
      category_hint: "summary",
      evidence_ids: ["EV0001"],
      citation_ids: ["CIT0001"],
    }],
  });
  assert.ok(plan.slides.some((slide) => Object.values(slide.slot_assignments).some((assignment) => assignment.type === "reference")));

  const deckDir = await makeTempDeck(["01_result.slide"]);
  const preflight = await runPreflight({
    renderer_inputs: {
      requested_renderer: "slidep",
      renderer_version: "5.4.4",
      platform: HOST_PLATFORM,
      project_path: deckDir,
      project_exists: true,
      source_files: ["slides/01_result.slide"],
      live_watch_requested: false,
    },
    deck_plan: { theme_id: plan.theme.id, slides: plan.slides },
  });
  await fs.rm(deckDir, { recursive: true, force: true });
  assert.notEqual(preflight.status, "invalid");
  assert.deepEqual(preflight.invalid_slides, []);
});

test("renderer preflight rejects duplicate page IDs across .slide and .jsx", () => {
  const validation = validateRendererInputs({
    renderer: "slidep",
    renderer_version: "5.4.4",
    platform: "win32",
    project_path: "F:/Workbuddy/deck",
    source_files: ["slides/01_cover.slide", "slides/01_cover.jsx"],
  });
  assert.equal(validation.status, "invalid");
  assert.deepEqual(validation.duplicate_page_ids, [
    { page_id: "01_cover", files: ["slides/01_cover.slide", "slides/01_cover.jsx"] },
  ]);
  assert.ok(validation.issues.some((issue) => issue.code === "DUPLICATE_PAGE_ID"));
  assert.ok(validation.issues.some((issue) => issue.code === "NON_CANONICAL_SLIDE_SOURCE"));
});

test("renderer preflight treats .slide as the only canonical page extension", () => {
  const validation = validateRendererInputs({
    platform: "win32",
    project_path: "F:/Workbuddy/deck",
    source_files: ["slides/01_cover.jsx"],
  });
  assert.equal(validation.status, "invalid");
  assert.ok(validation.issues.some((issue) => issue.code === "NON_CANONICAL_SLIDE_SOURCE"));
  assert.equal(validation.canonical_extension, ".slide");
});

test("renderer preflight converts an MSYS project path into an actionable Windows suggestion", () => {
  const validation = validateRendererInputs({
    platform: "win32",
    project_path: "/f/Workbuddy/outputs/deck",
    source_files: ["slides/01_cover.slide"],
  });
  assert.equal(validation.status, "invalid");
  assert.equal(validation.normalized_project_path, "F:/Workbuddy/outputs/deck");
  assert.ok(validation.issues.some((issue) => issue.code === "MSYS_PROJECT_PATH_UNSUPPORTED"));
});

test("renderer preflight disables reliance on the known-broken Windows 5.4.4 watcher", () => {
  const validation = validateRendererInputs({
    renderer_version: "5.4.4",
    platform: "win32",
    project_path: "F:/Workbuddy/deck",
    source_files: ["slides/01_cover.slide", "slides/02_result.slide"],
    live_watch_requested: true,
  });
  assert.equal(validation.status, "warning");
  assert.equal(validation.safe_execution_plan.compile_mode, "batch_restart_initial_scan");
  assert.equal(validation.safe_execution_plan.rely_on_live_watcher, false);
  assert.ok(validation.issues.some((issue) => issue.code === "SLIDEP_WATCHER_UNRELIABLE"));
});

test("renderer preflight accepts canonical batch inputs", () => {
  const validation = validateRendererInputs({
    renderer_version: "5.4.4",
    platform: "win32",
    project_path: "F:/Workbuddy/deck",
    project_exists: true,
    source_files: ["slides/01_cover.slide", "slides/02_result.slide"],
    live_watch_requested: false,
  });
  assert.equal(validation.status, "valid");
  assert.deepEqual(validation.canonical_sources, ["slides/01_cover.slide", "slides/02_result.slide"]);
  assert.equal(validation.safe_execution_plan.compile_mode, "batch_initial_scan");
});

test("renderer preflight accepts Windows drive paths with backslash sources", () => {
  const validation = validateRendererInputs({
    platform: "win32",
    project_path: "F:\\Workbuddy\\deck",
    project_exists: true,
    source_files: ["slides\\01_cover.slide", "slides\\02_result.slide"],
  });
  assert.equal(validation.status, "valid");
  assert.deepEqual(validation.canonical_sources, ["slides\\01_cover.slide", "slides\\02_result.slide"]);
});

test("renderer preflight accepts absolute POSIX paths including /f prefixes", () => {
  for (const projectPath of ["/srv/research/deck", "/f/research/deck"]) {
    const validation = validateRendererInputs({
      platform: "linux",
      project_path: projectPath,
      project_exists: true,
      source_files: ["slides/01_cover.slide"],
    });
    assert.equal(validation.status, "valid", projectPath);
    assert.equal(validation.normalized_project_path, projectPath);
    assert.equal(validation.issues.some((issue) => issue.code === "MSYS_PROJECT_PATH_UNSUPPORTED"), false);
  }
});

test("renderer preflight rejects relative POSIX project paths", () => {
  const validation = validateRendererInputs({
    platform: "darwin",
    project_path: "outputs/deck",
    source_files: ["slides/01_cover.slide"],
  });
  assert.equal(validation.status, "invalid");
  assert.ok(validation.issues.some((issue) => issue.code === "PROJECT_PATH_NOT_POSIX_ABSOLUTE"));
});

test("renderer preflight distinguishes requested and effective renderers", () => {
  const validation = validateRendererInputs({
    renderer: "tencent-pptx",
    platform: "win32",
    project_path: "F:/Workbuddy/deck",
    project_exists: true,
    source_files: ["slides/01_cover.slide"],
  });
  assert.equal(validation.requested_renderer, "tencent-pptx");
  assert.equal(validation.effective_renderer, "slidep");
  assert.equal(validation.compatibility_mode, true);
});

test("renderer preflight rejects conflicting canonical and legacy renderer fields", () => {
  assert.throws(
    () => validateRendererInputs({
      requested_renderer: "tencent-pptx",
      renderer: "slidep",
      project_path: "F:/Workbuddy/deck",
      source_files: ["slides/01_cover.slide"],
    }),
    /Conflicting renderer fields/,
  );
});

test("metric normalization and direct binding reject malformed input", async () => {
  assert.throws(() => normalizeMetrics({ text_chars: "not-a-number" }), /Expected a number/);
  assert.throws(() => normalizeMetrics({ visual_aspect_ratio: 0 }), /Expected a positive number/);
  assert.throws(() => normalizeMetrics({ text_chars_by_role: [] }), /must be an object/);
  const metrics = normalizeMetrics({
    text_chars_by_role: { body: 20, " ": 99 },
    imageCount: 99,
    contentRoles: ["headline", "headline", ""],
    allowAutoSplit: false,
  });
  assert.equal(metrics.textChars, 20);
  assert.equal(metrics.imageCount, 20);
  assert.deepEqual(metrics.contentRoles, ["headline"]);
  assert.equal(metrics.allowAutoSplit, false);

  await assert.rejects(() => bindSlideContent({}), /layout_id is required/);
  const resolved = await getLayout("RM-SUMMARY-01");
  const binding = await bindSlideContent({
    layout_spec: resolved.layout,
    slide_brief: { title: "结论", category_hint: "summary", metadata: { planning_mode: "guidance" } },
  });
  assert.equal(binding.contract_valid, true);
  await assert.rejects(() => planSlideContent({ slide_brief: [] }), /slide_brief is required/);
  const planned = await planSlideContent({ slide_brief: { title: "结论", category_hint: "summary" } });
  assert.equal(planned.status, "needs_replan");
  assert.ok(planned.replan_context.rejected_layout_ids.length > 0);
});

test("slot contract reports malformed specs and assignments before rendering", async () => {
  const resolved = await getLayout("RM-SINGLE_FIGURE-01");
  const titleSpec = structuredClone(resolved.layout.slot_specs.find((item) => item.slot_id === "title"));
  const malformed = await validateSlide({
    layout_id: resolved.layout.id,
    slot_specs: [
      null,
      { slot_id: "incomplete" },
      titleSpec,
      structuredClone(titleSpec),
      { ...titleSpec, slot_id: "unknown" },
      { ...titleSpec, slot_id: "figure", slot_type: "text", required: false },
    ],
    slot_assignments: {
      title: "plain text",
      figure: { type: "text", text: "wrong type" },
      caption: { type: "text", text: "caption" },
      takeaway: { type: "text", text: "takeaway" },
      annotation: { type: "text", text: "annotation" },
    },
  });
  assert.equal(malformed.status, "invalid");
  assert.ok(malformed.issues.filter((item) => item.code === "INVALID_LAYOUT_SPEC").length >= 4);
  assert.ok(malformed.issues.some((item) => item.code === "INVALID_EXPLICIT_SLOT"));
  assert.ok(malformed.issues.some((item) => item.code === "INVALID_SLOT_ASSIGNMENT"));
  assert.ok(malformed.issues.some((item) => item.code === "SLOT_TYPE_MISMATCH"));

  const invalidMap = await validateSlide({ layout_id: resolved.layout.id, slot_assignments: [] });
  assert.ok(invalidMap.issues.some((item) => item.code === "INVALID_SLOT_ASSIGNMENTS"));
});

test("render QA and deck validators cover missing telemetry and release-blocking limits", async () => {
  const missing = await validateRenderedSlide({ category: "summary" });
  assert.equal(missing.status, "warning");
  assert.ok(missing.issues.some((item) => item.code === "MISSING_TYPOGRAPHY_TELEMETRY"));
  assert.ok(missing.issues.some((item) => item.code === "MISSING_OCCUPANCY_TELEMETRY"));

  const telemetry = await validateRenderedSlide({
    category: "summary",
    text_elements: [
      { id: "sub", role: "subheading", font_pt: 23, line_count: 1 },
      { id: "caption", role: "caption", font_pt: 16, line_count: 1 },
      { id: "body", role: "body", font_pt: 17, line_count: 1 },
    ],
    content_occupancy: 0.99,
    largest_empty_band: 0.01,
    content_center_x: 0.9,
    content_center_y: 0.9,
    visuals: [
      { visual_type: "dense_plot", panel_count: 4, has_embedded_text: true, rendered_embedded_text_px: 12 },
      { visual_type: "multi_panel_figure", panel_count: 6, has_embedded_text: true, display_width_norm: 0.5, rendered_embedded_text_px: 8 },
    ],
  });
  for (const code of ["FONT_BELOW_VIEWING_TARGET", "CONTENT_TOO_DENSE", "UNBALANCED_CONTENT_CENTER", "MISSING_VISUAL_SIZE_TELEMETRY", "EMBEDDED_TEXT_TOO_SMALL", "SPLIT_SLIDE_RECOMMENDED"]) {
    assert.ok(telemetry.issues.some((item) => item.code === code), code);
  }
  await assert.rejects(() => validateRenderedSlide({ layout_id: "UNKNOWN" }), /Unknown layout_id/);
  await assert.rejects(() => validateRenderedSlide({ text_elements: [null] }), /must be an object/);
  await assert.rejects(() => validateRenderedSlide({ title_font_pt: 0 }), /Expected a positive number/);
  await assert.rejects(() => validateRenderedDeck({ slides: [] }), /at least one/);
  await assert.rejects(() => validateRenderedDeck({ slides: Array.from({ length: 201 }, () => ({})) }), /at most 200/);
  await assert.rejects(() => validateDeckPlan({ slides: [] }), /at least one/);
  await assert.rejects(() => validateDeckPlan({ slides: Array.from({ length: 81 }, () => ({})) }), /at most 80/);

  const plan = await createDeckPlan({ presentation_type: "custom", slide_briefs: [{ title: "结论", category_hint: "summary" }] });
  const unknownTheme = await validateDeckPlan({ theme_id: "unknown-theme", slides: plan.slides });
  assert.ok(unknownTheme.deck_issues.some((item) => item.code === "UNKNOWN_THEME"));
  await assert.rejects(() => readPreview("UNKNOWN"), /Unknown layout_id/);
  assert.match(await readPreview("RM-SUMMARY-01"), /<svg/u);
});

test("validate-deck cross-checks declared metrics against the content model", async () => {
  const plan = await createDeckPlan({ presentation_type: "custom", slide_briefs: [{ title: "结论", category_hint: "summary" }] });
  const brief = {
    slide_type: "summary",
    title: "结论",
    title_chars: 2,
    image_count: 3,
    text_chars: 10,
    claims: ["点一", "点二"],
    visuals: [{ visual_type: "dense_plot", caption: "图" }],
    citation_ids: [],
    evidence_ids: [],
  };
  plan.slides[0].content_metrics = { image_count: 1, title_chars: 2, text_chars: 10 };
  const result = await validateDeckPlan({ slides: plan.slides, content_model: { slide_briefs: [brief] } });
  assert.equal(result.metric_provenance, "cross_checked_against_content_model");
  assert.ok(result.cross_check_divergences.length >= 1);
  assert.ok(result.deck_issues.some((item) => item.code === "DECLARED_METRICS_MISMATCH"));

  // 不提供 content_model 时，明确标注为未交叉核验，而非把声明当结论
  const unchecked = await validateDeckPlan({ slides: plan.slides });
  assert.equal(unchecked.metric_provenance, "declared_not_verified");
  assert.equal(unchecked.cross_check_divergences.length, 0);
});

test("rendered-slide QA flags leaked evidence ids and coverage gaps", async () => {
  const result = await validateRenderedSlide({
    viewing_mode: "projector",
    renderer_output: {
      renderer: "slidep",
      slide_id: "leak",
      width: 13.333,
      height: 7.5,
      elements: [
        { id: "title", type: "text", bbox: { x: 0, y: 0, width: 4, height: 1 }, text: { content: "石墨烯拉伸失效机理" } },
        { id: "body", type: "text", bbox: { x: 0, y: 1, width: 4, height: 2 }, text: { content: "软模失稳由 EV0008 与 EV0012 支持" } },
      ],
    },
    declared_evidence: [
      { evidence_id: "EV0012", text: "软模失稳" },
      { evidence_id: "EV9999", text: "完全不存在的内容片段" },
    ],
  });
  assert.ok(result.issues.some((item) => item.code === "EVIDENCE_ID_LEAKED_TO_SLIDE"));
  assert.ok(result.issues.some((item) => item.code === "EVIDENCE_COVERAGE_GAP"));
  const gap = result.issues.find((item) => item.code === "EVIDENCE_COVERAGE_GAP");
  assert.equal(gap.actual, "EV9999");
});

test("slide brief body binds into a text slot", async () => {
  const resolved = await getLayout("RM-BACKGROUND-01");
  const binding = await bindSlideContent({
    layout_spec: resolved.layout,
    slide_brief: { title: "背景", category_hint: "background", body: "石墨烯是已知最强材料，但它在拉伸下何时失效仍是未解问题。" },
  });
  const texts = Object.values(binding.slot_assignments).map((a) => a.text ?? "").join("");
  assert.ok(texts.includes("石墨烯是已知最强材料"));
});

test("render QA flags text sparsity on content pages but not scaffold pages", async () => {
  const base = (slide_id, elements) => ({ renderer: "slidep", slide_id, width: 13.333, height: 7.5, elements });

  // 标签碎片：theory 页只有短标签 → error
  const sparse = await validateRenderedSlide({
    category: "theory",
    renderer_output: base("s1", [
      { id: "t", type: "text", bbox: { x: 0, y: 0, width: 4, height: 1 }, text: { content: "方法：声子" } },
      { id: "a", type: "text", bbox: { x: 0, y: 1, width: 4, height: 1 }, text: { content: "位移法算声子" } },
      { id: "b", type: "text", bbox: { x: 0, y: 2, width: 4, height: 1 }, text: { content: "K1模软化" } },
    ]),
  });
  assert.ok(sparse.issues.some((i) => i.code === "TEXT_SPARSITY" && i.severity === "error"), "sparse theory should error");

  // 浅正文：有句子但无段落 → warning
  const shallow = await validateRenderedSlide({
    category: "theory",
    renderer_output: base("s2", [
      { id: "t", type: "text", bbox: { x: 0, y: 0, width: 4, height: 1 }, text: { content: "方法：声子位移法" } },
      { id: "a", type: "text", bbox: { x: 0, y: 1, width: 4, height: 1 }, text: { content: "VASP计算证实K1软模逼近零频系相变前兆" } },
    ]),
  });
  assert.ok(shallow.issues.some((i) => i.code === "TEXT_SPARSITY" && i.severity === "warning"), "shallow theory should warn");

  // 完整段落 → 无 TEXT_SPARSITY
  const deep = await validateRenderedSlide({
    category: "theory",
    renderer_output: base("s3", [
      { id: "t", type: "text", bbox: { x: 0, y: 0, width: 4, height: 1 }, text: { content: "方法：声子位移法" } },
      { id: "a", type: "text", bbox: { x: 0, y: 1, width: 4, height: 2 }, text: { content: "全部第一性原理计算在 VASP 中完成，力由局域密度近似下的密度泛函理论给出，声子谱采用位移法计算" } },
    ]),
  });
  assert.ok(!deep.issues.some((i) => i.code === "TEXT_SPARSITY"), "deep theory should not flag");

  // cover 豁免
  const cover = await validateRenderedSlide({
    category: "cover",
    renderer_output: base("s4", [
      { id: "t", type: "text", bbox: { x: 0, y: 0, width: 4, height: 1 }, text: { content: "石墨烯拉伸失效机制" } },
    ]),
  });
  assert.ok(!cover.issues.some((i) => i.code === "TEXT_SPARSITY"), "cover should be exempt");
});

test("rendered-slide QA detects shallow body coverage via n-gram overlap", async () => {
  const result = await validateRenderedSlide({
    category: "theory",
    renderer_output: {
      renderer: "slidep", slide_id: "cov", width: 13.333, height: 7.5,
      elements: [
        { id: "b", type: "text", bbox: { x: 0, y: 0, width: 4, height: 2 }, text: { content: "石墨烯是最强材料" } },
      ],
    },
    declared_body: "软模失稳决定机械失效，三条证据链独立互证，误差约百分之十",
  });
  const gap = result.issues.find((i) => i.code === "EVIDENCE_COVERAGE_GAP" && i.field === "declared_body");
  assert.ok(gap, "declared body not covered should flag");
});
