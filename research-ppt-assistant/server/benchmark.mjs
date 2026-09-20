import { createHash } from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";
import { performance } from "node:perf_hooks";
import { fileURLToPath } from "node:url";
import { normalizeContentModel } from "./content-model.mjs";
import {
  createDeckPlan,
  getLayout,
  loadCatalog,
  normalizeMetrics,
  runPreflight,
  searchLayouts,
  validateRenderedSlide,
} from "./core.mjs";
import { evaluateLayoutCompatibility } from "./layout-retriever.mjs";
import { bindSlideToLayout } from "./slot-binding.mjs";
import { evaluateVisualQuality } from "./visual-quality/index.mjs";
import { runVisualFitPreflight } from "./visual-fit/index.mjs";
import { generateAsymmetricCandidates, runGroupFitPreflight } from "./group-fit/index.mjs";

export const BENCHMARK_VERSION = "1.1.0";

const MODULE_DIR = path.dirname(fileURLToPath(import.meta.url));
const DEFAULT_DATASET_PATH = path.resolve(MODULE_DIR, "..", "benchmarks", "dataset.json");

const hasOwn = (value, key) => Object.prototype.hasOwnProperty.call(value, key);

function round(value, digits = 4) {
  const factor = 10 ** digits;
  return Math.round(value * factor) / factor;
}

function rate(passed, total) {
  return { passed, total, rate: total ? round(passed / total) : 0 };
}

function digest(value) {
  return createHash("sha256").update(JSON.stringify(value)).digest("hex");
}

function p95(values) {
  if (!values.length) return 0;
  const sorted = [...values].sort((left, right) => left - right);
  return sorted[Math.max(0, Math.ceil(sorted.length * 0.95) - 1)];
}

function timeCall(callback, samples, name) {
  const started = performance.now();
  callback();
  samples[name].push(performance.now() - started);
}

function foundationTelemetry() {
  return {
    telemetry_version: "1.0.0",
    slide_id: "benchmark-visual-quality",
    renderer: "slidep",
    slide: {
      width: 200,
      height: 100,
      render_width_px: 2000,
      render_height_px: 1000,
      background: { kind: "solid", color: "#ffffff" },
    },
    elements: [{
      element_id: "body",
      type: "text",
      quality_role: "content",
      bbox: { x: 0, y: 40, width: 20, height: 20 },
      render_bbox_px: { x: 0, y: 400, width: 200, height: 200 },
      text: {
        content: "Benchmark", language: "en", script: "Latin", font_family: "Arial", font_size: 20,
        font_weight: 400, line_count: 1, overflow: false, foreground_color: "#111111", intended_single_line: false, role: "body",
      },
      image: null,
      fill_color: null,
      background_color: "#ffffff",
      theme_token: "text",
      theme_usage: "body_text",
    }],
    theme: { id: "benchmark", tokens: { text: { color: "#111111", allowed_usage: ["body_text"], forbidden_usage: [] } } },
    unavailable: [],
    provided_metrics: {},
  };
}

function coverOcclusionTelemetry() {
  const base = foundationTelemetry();
  base.slide_id = "benchmark-cover-occlusion";
  base.slide.layout_id = "RM-COVER-03";
  base.slide.category = "cover";
  base.elements = [
    {
      element_id: "cover-image", type: "image", quality_role: "content", z_index: 1, opacity: 1,
      bbox: { x: 0, y: 0, width: 200, height: 100 }, render_bbox_px: { x: 0, y: 0, width: 2000, height: 1000 },
      text: null, image: { display_bbox: { x: 0, y: 0, width: 200, height: 100 }, source_width_px: null, source_height_px: null },
      fill_color: null, background_color: null, theme_token: null, theme_usage: null,
    },
    {
      element_id: "title-surface", type: "shape", quality_role: "decoration", z_index: 2, opacity: 1,
      bbox: { x: 10, y: 50, width: 120, height: 24 }, render_bbox_px: { x: 100, y: 500, width: 1200, height: 240 },
      text: null, image: null, fill_color: "#061826", background_color: null, theme_token: null, theme_usage: null,
    },
    {
      element_id: "title", type: "text", quality_role: "content", z_index: 3, opacity: null,
      bbox: { x: 12, y: 52, width: 116, height: 20 }, render_bbox_px: { x: 120, y: 520, width: 1160, height: 200 },
      text: { content: "Cover", language: "en", script: "Latin", font_family: "Arial", font_size: 42, font_weight: 700, line_count: 1, overflow: false, foreground_color: "#ffffff", local_contrast_ratio: null, intended_single_line: true, role: "title" },
      image: null, fill_color: null, background_color: null, theme_token: null, theme_usage: null,
    },
    {
      element_id: "subtitle", type: "text", quality_role: "content", z_index: 4, opacity: null,
      bbox: { x: 12, y: 76, width: 90, height: 10 }, render_bbox_px: { x: 120, y: 760, width: 900, height: 100 },
      text: { content: "Unprotected", language: "en", script: "Latin", font_family: "Arial", font_size: 24, font_weight: 400, line_count: 1, overflow: false, foreground_color: "#ffffff", local_contrast_ratio: null, intended_single_line: true, role: "subtitle" },
      image: null, fill_color: null, background_color: null, theme_token: null, theme_usage: null,
    },
  ];
  base.theme = null;
  return base;
}

async function evaluateVisualQualityFoundation() {
  const nonSquare = await evaluateVisualQuality({ telemetry: foundationTelemetry() });
  const expectedOffset = 90 / Math.hypot(200, 100);

  const pixelOobTelemetry = foundationTelemetry();
  pixelOobTelemetry.slide_id = "benchmark-pixel-oob";
  pixelOobTelemetry.elements[0].bbox = { x: 1, y: 1, width: 20, height: 20 };
  pixelOobTelemetry.elements[0].render_bbox_px = { x: 1900, y: 100, width: 200, height: 200 };
  const pixelOob = await evaluateVisualQuality({ telemetry: pixelOobTelemetry });

  const incompleteTelemetry = foundationTelemetry();
  incompleteTelemetry.slide_id = "benchmark-incomplete";
  const incompleteElement = structuredClone(incompleteTelemetry.elements[0]);
  incompleteElement.element_id = "body-incomplete";
  incompleteElement.bbox = null;
  incompleteElement.text.overflow = null;
  incompleteTelemetry.elements.push(incompleteElement);
  incompleteTelemetry.unavailable.push(
    { field: "elements[1].bbox", reason: "benchmark_missing_logical_bbox" },
    { field: "elements[1].text.overflow", reason: "benchmark_missing_overflow" },
  );
  const incomplete = await evaluateVisualQuality({ telemetry: incompleteTelemetry });
  const coverOcclusion = await evaluateVisualQuality({ telemetry: coverOcclusionTelemetry() });
  const fitBase = {
    visual_id: "extended-data-fig-1",
    source: { width: 1432, height: 1189 },
    source_region: { x: 0, y: 0, width: 1432, height: 1189 },
    visual_intent: { visual_type: "scientific_figure", crop_policy: "full_figure", fit_policy: "contain", whitespace_policy: "minimal" },
    allocated_visual_bbox: { x: 72, y: 156, width: 1136, height: 292 },
    visual_container: {
      container_id: "s4-figure-panel",
      role: "image_only",
      fit_policy: "contain",
      crop_policy: "full_figure",
      whitespace_policy: "minimal",
      mismatch_policy: "replan",
    },
  };
  const incompatibleFit = runVisualFitPreflight(fitBase);
  const intentionalFit = runVisualFitPreflight({
    ...fitBase,
    visual_intent: { ...fitBase.visual_intent, whitespace_policy: "intentional" },
    visual_container: { ...fitBase.visual_container, whitespace_policy: "intentional" },
  });
  const semanticFit = runVisualFitPreflight({
    ...fitBase,
    visual_intent: { ...fitBase.visual_intent, crop_policy: "semantic_crop_allowed", semantic_crop_allowed: true },
    visual_container: { ...fitBase.visual_container, crop_policy: "semantic_crop_allowed", mismatch_policy: "resolve_region" },
  });

  return [
    {
      id: "non_square_visual_center",
      passed: Math.abs(nonSquare.metrics.visual_center.offset - expectedOffset) < 1e-12,
      actual: nonSquare.metrics.visual_center.offset,
      expected: expectedOffset,
    },
    {
      id: "render_pixel_out_of_bounds",
      passed: pixelOob.violations.some((violation) => violation.code === "ELEMENT_OUT_OF_BOUNDS"),
      actual: pixelOob.checks.element_out_of_bounds.status,
      expected: "fail",
    },
    {
      id: "partial_telemetry_not_evaluable",
      passed: incomplete.status !== "pass"
        && incomplete.checks.element_area_ratio.status === "not_evaluable"
        && incomplete.checks.text_overflow.status === "not_evaluable",
      actual: incomplete.status,
      expected: "not_pass_with_incomplete_checks",
    },
    {
      id: "cover_text_image_protection_not_evaluable",
      passed: coverOcclusion.status !== "pass"
        && coverOcclusion.checks.cover_text_over_image.status === "not_evaluable"
        && coverOcclusion.violations.some((violation) => violation.code === "TEXT_IMAGE_PROTECTION_NOT_EVALUABLE"),
      actual: coverOcclusion.checks.cover_text_over_image.status,
      expected: "not_evaluable",
    },
    {
      id: "meta_assembly_visual_fit_blocked",
      passed: incompatibleFit.status === "fail"
        && incompatibleFit.decision === "needs_replan"
        && incompatibleFit.issue?.code === "VISUAL_SLOT_FIT_INCOMPATIBLE",
      actual: { status: incompatibleFit.status, decision: incompatibleFit.decision, width_fill: incompatibleFit.metrics.visual_fill.width_ratio },
      expected: { status: "fail", decision: "needs_replan", width_fill_approximately: 0.31 },
    },
    {
      id: "intentional_whitespace_not_false_failed",
      passed: intentionalFit.status === "pass",
      actual: intentionalFit.status,
      expected: "pass",
    },
    {
      id: "semantic_crop_routes_to_region_resolution",
      passed: semanticFit.status === "fail" && semanticFit.decision === "needs_region_resolution",
      actual: { status: semanticFit.status, decision: semanticFit.decision },
      expected: { status: "fail", decision: "needs_region_resolution" },
    },
  ];
}

function relationCredits(current = 108) {
  return {
    v045: { median_credits_per_deck: 100, credits_per_slide: 1, credits_per_accepted_slide: 1, model_calls_per_slide: 1, replan_count: 1, escalation_rate: 0.05 },
    v046: { median_credits_per_deck: current, credits_per_slide: 1.05, credits_per_accepted_slide: 1.04, model_calls_per_slide: 1, replan_count: 1, escalation_rate: 0.05 },
  };
}

function relationFixture(overrides = {}) {
  const ids = ["uv-aging", "dye-comparison", "temperature", "stretching"];
  const sources = [[310, 100], [290, 100], [100, 100], [220, 100]];
  const allocations = ids.map((visualId, index) => ({
    visual_id: visualId,
    allocated_visual_bbox: { x: index % 2 ? 6.1 : 0, y: index > 1 ? 2.1 : 0, width: 5.9, height: 1.9 },
  }));
  return {
    visual_group: { group_id: "robustness-evidence", semantic_relation: "parallel", relation_strength: "soft", children: ids },
    layout_relation: { shared_alignment: true, shared_container_style: true, equal_size: true, equal_width: true, equal_height: true, preserve_order: true },
    children: ids.map((visualId, index) => ({ visual_id: visualId, source: { width: sources[index][0], height: sources[index][1] } })),
    baseline_candidate: { layout_id: "RM-FOUR_PANEL-03", group_bbox: { x: 0, y: 0, width: 12, height: 4 }, allocations },
    feature_flags: { relation_arbitration: true },
    max_relation_replan_attempts: 1,
    credits: relationCredits(),
    ...overrides,
  };
}

function evaluateRelationFitFoundation() {
  const similarInput = relationFixture();
  similarInput.children = similarInput.children.map((child) => ({ ...child, source: { width: 300, height: 100 } }));
  const similar = runGroupFitPreflight(similarInput);
  const outlier = runGroupFitPreflight(relationFixture({ feature_flags: { relation_arbitration: "shadow" } }));
  const soft = runGroupFitPreflight(relationFixture());
  const hardInput = relationFixture();
  hardInput.visual_group = { ...hardInput.visual_group, semantic_relation: "control_treatment", relation_strength: "hard" };
  const hard = runGroupFitPreflight(hardInput);
  const sequenceInput = relationFixture({ feature_flags: { relation_arbitration: true, non_uniform_siblings: false } });
  sequenceInput.visual_group = { ...sequenceInput.visual_group, semantic_relation: "sequence" };
  sequenceInput.relation_aware_candidates = [{ ...generateAsymmetricCandidates({ group_bbox: sequenceInput.baseline_candidate.group_bbox, child_ids: sequenceInput.visual_group.children })[1], child_order: [...sequenceInput.visual_group.children].reverse() }];
  const sequence = runGroupFitPreflight(sequenceInput);
  const realIds = ["uv-aging", "dye-comparison", "temperature", "stretching"];
  const realSources = [[709, 228], [662, 225], [487, 376], [471, 251]];
  const realBoxes = [{ x: 1, y: 1.771, width: 5.312, height: 1.708 }, { x: 7.164, y: 1.771, width: 5.026, height: 1.708 }, { x: 2.552, y: 4.231, width: 2.208, height: 1.705 }, { x: 8.074, y: 4.229, width: 3.205, height: 1.708 }];
  const intentional = runGroupFitPreflight(relationFixture({
    layout_relation: { shared_alignment: true, shared_container_style: true, equal_size: false, equal_width: false, equal_height: false, preserve_order: true, intentional_unequal_weight: true },
    children: realIds.map((visualId, index) => ({ visual_id: visualId, source: { width: realSources[index][0], height: realSources[index][1] } })),
    baseline_candidate: { layout_id: "V045-ROBUSTNESS-PAGE-13", group_bbox: { x: 1, y: 1.771, width: 11.19, height: 4.166 }, allocations: realIds.map((visualId, index) => ({ visual_id: visualId, allocated_visual_bbox: realBoxes[index] })) },
    baseline_qa_passed: true,
  }));
  const marginalInput = relationFixture({ feature_flags: { relation_arbitration: true, non_uniform_siblings: false } });
  marginalInput.relation_aware_candidates = [{ layout_id: "MARGINAL", allocations: marginalInput.baseline_candidate.allocations.map((allocation) => ({ ...allocation, allocated_visual_bbox: { ...allocation.allocated_visual_bbox, width: allocation.allocated_visual_bbox.width * 0.98 } })) }];
  const marginal = runGroupFitPreflight(marginalInput);
  const priorityInput = relationFixture({ feature_flags: { relation_arbitration: true, non_uniform_siblings: false } });
  const improving = generateAsymmetricCandidates({ group_bbox: priorityInput.baseline_candidate.group_bbox, child_ids: priorityInput.visual_group.children })[1];
  priorityInput.relation_aware_candidates = [{ ...improving, higher_priority_issues: { content_integrity: 1, legibility: 0 } }];
  const priority = runGroupFitPreflight(priorityInput);
  return [
    { id: "relation_similar_ar_preserves_equal_size", expected_conflict: false, actual_conflict: similar.baseline_candidate.conflict.conflict, layout_changed: similar.layout_churn.changed, passed: similar.decision === "preserve_v045_baseline" && !similar.layout_churn.changed },
    { id: "relation_outlier_conflict_detected", expected_conflict: true, actual_conflict: outlier.baseline_candidate.conflict.conflict, passed: outlier.issue?.code === "VISUAL_RELATION_FIT_CONFLICT" && outlier.decision === "shadow_preserve_v045" },
    { id: "soft_relation_relaxes_equal_size", expected_conflict: true, actual_conflict: soft.baseline_candidate.conflict.conflict, credits_per_deck_ratio: soft.credits_regression.credits_per_deck_ratio, passed: soft.decision === "select_relation_aware_candidate" && soft.constraint_arbitration.relaxed_constraints.includes("equal_size") },
    { id: "hard_relation_preserved", expected_conflict: true, actual_conflict: hard.baseline_candidate.conflict.conflict, passed: hard.decision === "needs_replan" && hard.constraint_arbitration.relaxed_constraints.length === 0 },
    { id: "sequence_reading_order_preserved", expected_conflict: true, actual_conflict: sequence.baseline_candidate.conflict.conflict, passed: sequence.decision === "fallback_to_v045" && sequence.constraint_arbitration.candidate_comparisons[0].rejections.includes("reading_order_changed") },
    { id: "v045_real_unequal_weight_page_unchanged", expected_conflict: false, actual_conflict: intentional.baseline_candidate.conflict.conflict, layout_changed: intentional.layout_churn.changed, passed: intentional.decision === "preserve_v045_baseline" && !intentional.layout_churn.changed },
    { id: "marginal_gain_falls_back", expected_conflict: true, actual_conflict: marginal.baseline_candidate.conflict.conflict, passed: marginal.decision === "fallback_to_v045" },
    { id: "higher_priority_regression_rejected", expected_conflict: true, actual_conflict: priority.baseline_candidate.conflict.conflict, passed: priority.decision === "fallback_to_v045" && priority.constraint_arbitration.candidate_comparisons[0].rejections.includes("content_integrity_regression") },
  ];
}

async function evaluateCase(benchmarkCase) {
  const query = { ...benchmarkCase.query, k: benchmarkCase.query?.k ?? 5 };
  const search = await searchLayouts(query);
  const acceptedCategories = new Set(benchmarkCase.acceptable_categories ?? []);
  const candidates = [];
  for (const candidate of search.results) {
    const resolved = await getLayout(candidate.id, undefined, query.viewing_mode);
    const binding = bindSlideToLayout({
      layout_spec: resolved.layout,
      slide_brief: {
        ...benchmarkCase.slide_brief,
        metadata: { ...(benchmarkCase.slide_brief?.metadata ?? {}), planning_mode: "guidance" },
      },
    });
    const categoryAccepted = !acceptedCategories.size || acceptedCategories.has(candidate.category);
    candidates.push({
      layout_id: candidate.id,
      category: candidate.category,
      score: candidate.score,
      contract_valid: binding.contract_valid === true,
      category_accepted: categoryAccepted,
      valid: binding.contract_valid === true && categoryAccepted,
    });
  }

  const plan = await createDeckPlan({
    presentation_type: "custom",
    allow_auto_split: true,
    max_replan_attempts: 3,
    slide_briefs: [benchmarkCase.slide_brief],
  });
  const replan = (plan.planning_contexts ?? []).some((context) =>
    (context.replan_context?.replan_attempt ?? 0) > 0
      || (context.replan_context?.rejected_layout_ids?.length ?? 0) > 0);
  const autoSplit = plan.slides.some((slide) => slide.planning_decision === "split")
    || (plan.planning_contexts ?? []).some((context) => context.planning_decision === "split");
  const contractFailure = ["failed", "needs_replan"].includes(plan.status)
    || plan.slides.some((slide) => slide.contract_valid !== true);

  let preflightStatus = "invalid";
  if (plan.slides.length) {
    const preflight = await runPreflight({
      renderer_inputs: benchmarkCase.renderer_inputs,
      deck_plan: { theme_id: plan.theme.id, slides: plan.slides },
      verify_filesystem: false,
    });
    preflightStatus = preflight.status;
  }
  const renderQa = await validateRenderedSlide(benchmarkCase.rendered_slide);
  return {
    id: benchmarkCase.id,
    tags: benchmarkCase.tags ?? [],
    top_1_valid: candidates[0]?.valid === true,
    top_k_valid: candidates.some((candidate) => candidate.valid),
    candidate_count: candidates.length,
    candidates,
    planning_status: plan.status,
    planned_slide_count: plan.slide_count,
    replan,
    auto_split: autoSplit,
    contract_failure: contractFailure,
    preflight_status: preflightStatus,
    preflight_failure: preflightStatus === "invalid",
    render_qa_status: renderQa.status,
    render_qa_failure: renderQa.status === "invalid",
  };
}

async function evaluateDataset(dataset) {
  const results = [];
  for (const benchmarkCase of dataset.cases) results.push(await evaluateCase(benchmarkCase));
  return results;
}

async function measurePerformance(dataset, iterations) {
  const catalog = await loadCatalog();
  const samples = { content_normalizer: [], layout_fit: [], slot_binding: [], visual_fit: [], group_fit: [] };
  const visualFitInput = {
    visual_id: "benchmark-figure",
    source: { width: 1432, height: 1189 },
    source_region: { x: 0, y: 0, width: 1432, height: 1189 },
    visual_intent: { visual_type: "scientific_figure", crop_policy: "full_figure", fit_policy: "contain", whitespace_policy: "minimal" },
    allocated_visual_bbox: { x: 72, y: 156, width: 1136, height: 292 },
    visual_container: { role: "image_only", fit_policy: "contain", crop_policy: "full_figure", whitespace_policy: "minimal", mismatch_policy: "replan" },
  };
  const prepared = dataset.cases.map((benchmarkCase) => {
    const preferredCategory = benchmarkCase.slide_brief?.category_hint;
    const layout = catalog.layouts.find((candidate) => candidate.category === preferredCategory) ?? catalog.layouts[0];
    const brief = {
      ...benchmarkCase.slide_brief,
      metadata: { ...(benchmarkCase.slide_brief?.metadata ?? {}), planning_mode: "guidance" },
    };
    return { benchmarkCase, layout, brief, metrics: normalizeMetrics(benchmarkCase.query) };
  });

  for (const item of prepared) {
    normalizeContentModel({ slide_briefs: [item.brief] });
    evaluateLayoutCompatibility(item.layout, item.metrics);
    bindSlideToLayout({ layout_spec: item.layout, slide_brief: item.brief });
  }
  runVisualFitPreflight(visualFitInput);
  const groupFitInput = relationFixture();
  runGroupFitPreflight(groupFitInput);
  for (let iteration = 0; iteration < iterations; iteration += 1) {
    for (const item of prepared) {
      timeCall(() => normalizeContentModel({ slide_briefs: [item.brief] }), samples, "content_normalizer");
      timeCall(() => evaluateLayoutCompatibility(item.layout, item.metrics), samples, "layout_fit");
      timeCall(() => bindSlideToLayout({ layout_spec: item.layout, slide_brief: item.brief }), samples, "slot_binding");
      timeCall(() => runVisualFitPreflight(visualFitInput), samples, "visual_fit");
      timeCall(() => runGroupFitPreflight(groupFitInput), samples, "group_fit");
    }
  }
  const operations = Object.fromEntries(Object.entries(samples).map(([name, values]) => [name, {
    sample_count: values.length,
    p95_ms: round(p95(values), 3),
    max_ms: round(Math.max(...values), 3),
  }]));
  return {
    iterations,
    operations,
    single_slide_p95_ms: Math.max(...Object.values(operations).map((item) => item.p95_ms)),
  };
}

function expectationFailures(dataset, results) {
  const failures = [];
  for (let index = 0; index < dataset.cases.length; index += 1) {
    const expected = dataset.cases[index].expect ?? {};
    const actual = results[index];
    for (const field of ["auto_split", "preflight_failure", "render_qa_failure"]) {
      if (hasOwn(expected, field) && expected[field] !== actual[field]) {
        failures.push({ case_id: actual.id, field, expected: expected[field], actual: actual[field] });
      }
    }
  }
  return failures;
}

function metricChecks(metrics, thresholds, deterministic, performanceResult, failures) {
  const definitions = [
    ["top_1_valid_rate", metrics.top_1_valid_rate.rate, ">=", thresholds.top_1_valid_rate_min],
    ["top_k_valid_rate", metrics.top_k_valid_rate.rate, ">=", thresholds.top_k_valid_rate_min],
    ["contract_failure_rate", metrics.contract_failure_rate.rate, "<=", thresholds.contract_failure_rate_max],
    ["preflight_failure_rate", metrics.preflight_failure_rate.rate, "<=", thresholds.preflight_failure_rate_max],
  ];
  if (performanceResult) definitions.push(["single_slide_p95_ms", performanceResult.single_slide_p95_ms, "<", thresholds.single_slide_p95_ms_max]);
  const checks = definitions.map(([name, actual, operator, expected]) => ({
    name,
    actual,
    operator,
    expected,
    passed: operator === ">=" ? actual >= expected : operator === "<=" ? actual <= expected : actual < expected,
  }));
  checks.push({ name: "determinism", actual: deterministic, operator: "===", expected: true, passed: deterministic === true });
  checks.push({ name: "case_expectations", actual: failures.length, operator: "===", expected: 0, passed: failures.length === 0 });
  return checks;
}

export async function loadBenchmarkDataset(datasetPath = DEFAULT_DATASET_PATH) {
  const dataset = JSON.parse(await fs.readFile(path.resolve(datasetPath), "utf8"));
  if (!Array.isArray(dataset.cases) || !dataset.cases.length) throw new TypeError("Benchmark dataset must contain at least one case.");
  return dataset;
}

export async function runBenchmark(options = {}) {
  const dataset = options.dataset ?? await loadBenchmarkDataset(options.dataset_path ?? options.datasetPath);
  if (!Array.isArray(dataset.cases) || !dataset.cases.length) throw new TypeError("Benchmark dataset must contain at least one case.");
  const iterations = Number(options.iterations ?? 20);
  if (!Number.isInteger(iterations) || iterations < 1 || iterations > 200) {
    throw new RangeError("Benchmark iterations must be an integer from 1 to 200.");
  }
  const first = await evaluateDataset(dataset);
  const firstVisualQuality = await evaluateVisualQualityFoundation();
  const firstRelationFit = evaluateRelationFitFoundation();
  const second = await evaluateDataset(dataset);
  const secondVisualQuality = await evaluateVisualQualityFoundation();
  const secondRelationFit = evaluateRelationFitFoundation();
  const firstDigest = digest({ cases: first, visual_quality_foundation: firstVisualQuality, relation_fit_foundation: firstRelationFit });
  const secondDigest = digest({ cases: second, visual_quality_foundation: secondVisualQuality, relation_fit_foundation: secondRelationFit });
  const deterministic = firstDigest === secondDigest;
  const caseCount = first.length;
  const metrics = {
    top_1_valid_rate: rate(first.filter((item) => item.top_1_valid).length, caseCount),
    top_k_valid_rate: rate(first.filter((item) => item.top_k_valid).length, caseCount),
    replan_rate: rate(first.filter((item) => item.replan).length, caseCount),
    auto_split_rate: rate(first.filter((item) => item.auto_split).length, caseCount),
    contract_failure_rate: rate(first.filter((item) => item.contract_failure).length, caseCount),
    preflight_failure_rate: rate(first.filter((item) => item.preflight_failure).length, caseCount),
    render_qa_failure_rate: rate(first.filter((item) => item.render_qa_failure).length, caseCount),
  };
  const performanceResult = options.include_performance === false ? undefined : await measurePerformance(dataset, iterations);
  const failures = expectationFailures(dataset, first);
  const thresholds = {
    top_1_valid_rate_min: 0,
    top_k_valid_rate_min: 0,
    contract_failure_rate_max: 1,
    preflight_failure_rate_max: 1,
    single_slide_p95_ms_max: 50,
    ...(dataset.thresholds ?? {}),
  };
  const checks = metricChecks(metrics, thresholds, deterministic, performanceResult, failures);
  checks.push({
    name: "visual_quality_foundation",
    actual: firstVisualQuality.filter((probe) => !probe.passed).length,
    operator: "===",
    expected: 0,
    passed: firstVisualQuality.every((probe) => probe.passed),
  });
  checks.push({
    name: "relation_fit_foundation",
    actual: firstRelationFit.filter((probe) => !probe.passed).length,
    operator: "===",
    expected: 0,
    passed: firstRelationFit.every((probe) => probe.passed),
  });
  const predictedPositive = firstRelationFit.filter((probe) => probe.actual_conflict).length;
  const actualPositive = firstRelationFit.filter((probe) => probe.expected_conflict).length;
  const truePositive = firstRelationFit.filter((probe) => probe.actual_conflict && probe.expected_conflict).length;
  const noConflictGolden = firstRelationFit.filter((probe) => !probe.expected_conflict);
  const relationMetrics = {
    conflict_detection_precision: predictedPositive ? round(truePositive / predictedPositive) : 1,
    conflict_detection_recall: actualPositive ? round(truePositive / actualPositive) : 1,
    layout_churn_rate_on_v045_good: rate(noConflictGolden.filter((probe) => probe.layout_changed).length, noConflictGolden.length),
    credits_per_deck_ratio: firstRelationFit.find((probe) => probe.id === "soft_relation_relaxes_equal_size")?.credits_per_deck_ratio ?? null,
  };
  return {
    benchmark_version: BENCHMARK_VERSION,
    dataset: { schema_version: dataset.schema_version, name: dataset.name, case_count: caseCount },
    status: checks.every((check) => check.passed) ? "passed" : "failed",
    metrics,
    determinism: {
      passed: deterministic,
      first_digest: firstDigest,
      second_digest: secondDigest,
    },
    performance: performanceResult,
    thresholds,
    checks,
    expectation_failures: failures,
    visual_quality_foundation: firstVisualQuality,
    relation_fit_foundation: firstRelationFit,
    relation_metrics: relationMetrics,
    cases: first,
  };
}
