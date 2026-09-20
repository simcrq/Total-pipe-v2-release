import assert from "node:assert/strict";
import test from "node:test";
import {
  computeCreditsRegression,
  computeGroupFitMetrics,
  evaluateCandidateGeometry,
  generateAsymmetricCandidates,
  normalizeGroupFitInput,
  runGroupFitPreflight,
} from "../server/group-fit/index.mjs";

const credits = (current = 108) => ({
  v045: { median_credits_per_deck: 100, credits_per_slide: 1, credits_per_accepted_slide: 1, model_calls_per_slide: 1, replan_count: 1, escalation_rate: 0.05 },
  v046: { median_credits_per_deck: current, credits_per_slide: 1.05, credits_per_accepted_slide: 1.04, model_calls_per_slide: 1, replan_count: 1, escalation_rate: 0.05 },
});

function equalGrid(ids, width = 12, height = 4) {
  const gap = 0.2;
  const cellWidth = (width - gap) / 2;
  const cellHeight = (height - gap) / 2;
  return ids.map((visualId, index) => ({
    visual_id: visualId,
    allocated_visual_bbox: { x: index % 2 ? cellWidth + gap : 0, y: index > 1 ? cellHeight + gap : 0, width: cellWidth, height: cellHeight },
  }));
}

function groupInput(overrides = {}) {
  const ids = ["uv-aging", "dye-comparison", "temperature", "stretching"];
  const sources = [[310, 100], [290, 100], [100, 100], [220, 100]];
  return {
    visual_group: { group_id: "robustness-evidence", semantic_relation: "parallel", relation_strength: "soft", children: ids },
    layout_relation: { shared_alignment: true, shared_container_style: true, equal_size: true, equal_width: true, equal_height: true, preserve_order: true },
    children: ids.map((visualId, index) => ({ visual_id: visualId, source: { width: sources[index][0], height: sources[index][1] } })),
    baseline_candidate: { layout_id: "RM-FOUR_PANEL-03", group_bbox: { x: 0, y: 0, width: 12, height: 4 }, allocations: equalGrid(ids) },
    feature_flags: { relation_arbitration: true },
    credits: credits(),
    max_relation_replan_attempts: 1,
    ...overrides,
  };
}

test("parallel siblings with similar aspect ratios preserve the v0.4.5 equal-size candidate", () => {
  const input = groupInput();
  input.children = input.children.map((child) => ({ ...child, source: { width: 300, height: 100 } }));
  const result = runGroupFitPreflight(input);
  assert.equal(result.status, "pass");
  assert.equal(result.decision, "preserve_v045_baseline");
  assert.equal(result.selected_candidate.layout_id, "RM-FOUR_PANEL-03");
  assert.equal(result.relation_fit.conflict, false);
  assert.equal(result.layout_churn.changed, false);
});

test("one severe aspect-ratio outlier produces VISUAL_RELATION_FIT_CONFLICT", () => {
  const input = groupInput({ feature_flags: { relation_arbitration: "shadow" } });
  const result = runGroupFitPreflight(input);
  assert.equal(result.status, "warning");
  assert.equal(result.decision, "shadow_preserve_v045");
  assert.equal(result.issue.code, "VISUAL_RELATION_FIT_CONFLICT");
  assert.ok(result.issue.actual.conflicting_children.includes("temperature"));
  assert.ok(result.baseline_candidate.metrics.fit_equity < 0.55);
  assert.notEqual(result.constraint_arbitration.would_select_candidate, null);
  assert.equal(result.selected_candidate.layout_id, "RM-FOUR_PANEL-03");
});

test("soft parallel relation may relax equal-size geometry exactly once", () => {
  const result = runGroupFitPreflight(groupInput({ baseline_qa_passed: true }));
  assert.equal(result.status, "pass");
  assert.equal(result.decision, "select_relation_aware_candidate");
  assert.notEqual(result.selected_candidate.layout_id, "RM-FOUR_PANEL-03");
  assert.ok(result.constraint_arbitration.relaxed_constraints.includes("equal_size"));
  assert.deepEqual(result.constraint_arbitration.preserved_constraints.slice(0, 3), ["group_membership", "semantic_level", "reading_order"]);
  assert.equal(result.constraint_arbitration.replan_attempts, 1);
  assert.equal(result.layout_churn.justified_by_conflict, true);
  assert.equal(result.resolved_issues[0].code, "VISUAL_RELATION_FIT_CONFLICT");
});

test("hard comparison preserves the relation and requests replan", () => {
  const input = groupInput();
  input.visual_group = { ...input.visual_group, semantic_relation: "control_treatment", relation_strength: "hard" };
  const result = runGroupFitPreflight(input);
  assert.equal(result.status, "fail");
  assert.equal(result.decision, "needs_replan");
  assert.equal(result.selected_candidate.layout_id, "RM-FOUR_PANEL-03");
  assert.deepEqual(result.constraint_arbitration.relaxed_constraints, []);
  assert.equal(result.recommended_action, "replan_preserving_relation");
});

test("sequence candidates that alter reading order are rejected", () => {
  const input = groupInput({ feature_flags: { relation_arbitration: true, non_uniform_siblings: false } });
  input.visual_group = { ...input.visual_group, semantic_relation: "sequence" };
  input.relation_aware_candidates = [{
    layout_id: "SEQUENCE-SWAPPED",
    allocations: equalGrid(input.visual_group.children).map((allocation, index, allocations) => ({ ...allocation, allocated_visual_bbox: allocations[(index + 2) % 4].allocated_visual_bbox })),
    child_order: ["temperature", "stretching", "uv-aging", "dye-comparison"],
  }];
  const result = runGroupFitPreflight(input);
  assert.equal(result.decision, "fallback_to_v045");
  assert.ok(result.constraint_arbitration.candidate_comparisons[0].rejections.includes("reading_order_changed"));
});

test("the real v0.4.5 robustness page keeps intentional unequal visual weight", () => {
  const ids = ["uv-aging", "dye-comparison", "temperature", "stretching"];
  const source = [[709, 228], [662, 225], [487, 376], [471, 251]];
  const boxes = [
    { x: 1, y: 1.771, width: 5.312, height: 1.708 },
    { x: 7.164, y: 1.771, width: 5.026, height: 1.708 },
    { x: 2.552, y: 4.231, width: 2.208, height: 1.705 },
    { x: 8.074, y: 4.229, width: 3.205, height: 1.708 },
  ];
  const result = runGroupFitPreflight(groupInput({
    layout_relation: { shared_alignment: true, shared_container_style: true, equal_size: false, equal_width: false, equal_height: false, preserve_order: true, intentional_unequal_weight: true },
    children: ids.map((visualId, index) => ({ visual_id: visualId, source: { width: source[index][0], height: source[index][1] } })),
    baseline_candidate: { layout_id: "V045-ROBUSTNESS-PAGE-13", group_bbox: { x: 1, y: 1.771, width: 11.19, height: 4.166 }, allocations: ids.map((visualId, index) => ({ visual_id: visualId, allocated_visual_bbox: boxes[index] })) },
    baseline_qa_passed: true,
  }));
  assert.equal(result.status, "pass");
  assert.equal(result.decision, "preserve_v045_baseline");
  assert.equal(result.baseline_candidate.conflict.reason, "intentional_unequal_visual_weight");
  assert.ok(result.baseline_candidate.metrics.group_min_fill > 0.99);
  assert.equal(result.layout_churn.changed, false);
});

test("marginal candidate gain falls back to v0.4.5", () => {
  const input = groupInput({ feature_flags: { relation_arbitration: true, non_uniform_siblings: false } });
  input.relation_aware_candidates = [{
    layout_id: "MARGINAL-CANDIDATE",
    allocations: equalGrid(input.visual_group.children, 11.6, 4),
  }];
  const result = runGroupFitPreflight(input);
  assert.equal(result.decision, "fallback_to_v045");
  assert.equal(result.fallback_to_v045, true);
  assert.ok(result.constraint_arbitration.candidate_comparisons[0].rejections.some((reason) => ["minimum_gain_not_met", "relation_fit_conflict_unresolved"].includes(reason)));
});

test("candidate introducing a higher-priority issue is rejected", () => {
  const input = groupInput({ feature_flags: { relation_arbitration: true, non_uniform_siblings: false } });
  const generated = generateAsymmetricCandidates({ group_bbox: input.baseline_candidate.group_bbox, child_ids: input.visual_group.children });
  const improving = generated.find((candidate) => candidate.layout_id === "ASYM-2X2-RIGHT_WIDE");
  input.relation_aware_candidates = [{ ...improving, higher_priority_issues: { content_integrity: 1, legibility: 0 } }];
  const result = runGroupFitPreflight(input);
  assert.equal(result.decision, "fallback_to_v045");
  assert.ok(result.constraint_arbitration.candidate_comparisons[0].rejections.includes("content_integrity_regression"));
});

test("candidate geometry rejects allocations outside the group and undeclared sibling overlap", () => {
  const input = groupInput({ feature_flags: { relation_arbitration: true, non_uniform_siblings: false } });
  input.relation_aware_candidates = [{
    layout_id: "INVALID-GEOMETRY",
    group_bbox: input.baseline_candidate.group_bbox,
    allocations: [
      { visual_id: "uv-aging", allocated_visual_bbox: { x: 0, y: 0, width: 5.8, height: 2 } },
      { visual_id: "dye-comparison", allocated_visual_bbox: { x: 5.7, y: 0, width: 6.3, height: 2 } },
      { visual_id: "temperature", allocated_visual_bbox: { x: 0, y: 2.2, width: 5.8, height: 2 } },
      { visual_id: "stretching", allocated_visual_bbox: { x: 6.2, y: 2, width: 5.8, height: 2 } },
    ],
  }];
  const result = runGroupFitPreflight(input);
  assert.equal(result.decision, "fallback_to_v045");
  assert.equal(result.selected_candidate.layout_id, "RM-FOUR_PANEL-03");
  assert.ok(result.constraint_arbitration.candidate_comparisons[0].rejections.includes("allocation_out_of_group_bounds"));
  assert.ok(result.constraint_arbitration.candidate_comparisons[0].rejections.includes("sibling_allocations_overlap"));
});

test("group geometry rejects contained and crossing sibling overlap", () => {
  const base = {
    group_bbox: { x: 0, y: 0, width: 10, height: 10 },
    allocations: [
      { visual_id: "host", allocated_visual_bbox: { x: 0, y: 0, width: 8, height: 8 } },
      { visual_id: "overlay", allocated_visual_bbox: { x: 1, y: 1, width: 2, height: 2 } },
    ],
  };
  assert.equal(evaluateCandidateGeometry(base).valid, false);
  assert.equal(evaluateCandidateGeometry({
    ...base,
    allocations: [
      { ...base.allocations[0], allocated_visual_bbox: { x: 0, y: 0, width: 6, height: 6 } },
      { ...base.allocations[1], allocated_visual_bbox: { x: 4, y: 4, width: 6, height: 6 } },
    ],
  }).valid, false);
});

test("invalid v0.4.5 baseline geometry requests a replan", () => {
  const input = groupInput({ feature_flags: { relation_arbitration: true, non_uniform_siblings: false } });
  input.baseline_candidate.allocations[2].allocated_visual_bbox.y = 2.101;
  const result = runGroupFitPreflight(input);
  assert.equal(result.status, "fail");
  assert.equal(result.decision, "needs_replan");
  assert.equal(result.selected_candidate.layout_id, "RM-FOUR_PANEL-03");
  assert.equal(result.issue.code, "VISUAL_RELATION_GEOMETRY_INVALID");
  assert.equal(result.issues[0].code, "VISUAL_RELATION_GEOMETRY_INVALID");
});

test("feature flags preserve the immutable v0.4.5 baseline and expose shadow mode", () => {
  const disabled = runGroupFitPreflight(groupInput({ feature_flags: { relation_contract_v046: false } }));
  assert.equal(disabled.status, "not_evaluable");
  assert.equal(disabled.decision, "feature_disabled");
  assert.equal(disabled.selected_candidate.layout_id, "RM-FOUR_PANEL-03");
  const arbitrationOff = runGroupFitPreflight(groupInput({ feature_flags: { relation_arbitration: false } }));
  assert.equal(arbitrationOff.decision, "relation_arbitration_disabled");
  assert.equal(arbitrationOff.selected_candidate.layout_id, "RM-FOUR_PANEL-03");
  const noAttempt = runGroupFitPreflight(groupInput({ max_relation_replan_attempts: 0 }));
  assert.equal(noAttempt.constraint_arbitration.replan_attempts, 0);
});

test("credits gate enforces the v0.4.5 plus ten-percent budget", () => {
  assert.equal(computeCreditsRegression(credits(110), 1.1).status, "pass");
  assert.equal(computeCreditsRegression(credits(111), 1.1).status, "fail");
  assert.equal(computeCreditsRegression(null, 1.1).status, "not_evaluable");
  const failed = runGroupFitPreflight(groupInput({ credits: credits(111) }));
  assert.equal(failed.status, "fail");
  assert.equal(failed.recommended_action, "review_credits_regression");
  assert.ok(failed.issues.some((issue) => issue.code === "CREDITS_REGRESSION"));
});

test("group metrics contain facts only and profile thresholds remain configurable", () => {
  const facts = computeGroupFitMetrics([
    { metrics: { visual_fill: { area_ratio: 0.9 }, allocated_bbox: { width: 1, height: 1 } } },
    { metrics: { visual_fill: { area_ratio: 0.3 }, allocated_bbox: { width: 1, height: 1 } } },
  ]);
  assert.deepEqual(facts, { group_min_fill: 0.3, group_max_fill: 0.9, group_mean_fill: 0.6, group_fill_variance: 0.09, fit_equity: 0.333333, visual_weight_deviation: 0, child_count: 2 });
  const input = groupInput({
    quality_profile: {
      visual_fit_rules: { scientific_figure: { visual_types: ["scientific_figure"], aspect_mismatch_warning: 10, aspect_mismatch_fail: 20, minimum_axis_fill_warning: 0.01, minimum_axis_fill_fail: 0.001, gap_symmetry_tolerance: 0.05 } },
      relation_fit_rules: { group_fit: { minimum_child_fill_warning: 0.1, minimum_child_fill_fail: 0.05, fit_equity_warning: 0.1, fit_equity_fail: 0.05, group_fill_variance_warning: 1 }, arbitration: { minimum_gain: 0.08, maximum_visual_weight_deviation: 0.75, max_relation_replan_attempts: 1, template_gap_ratio: 0.02 }, credits: { maximum_regression_ratio: 1.1 } },
    },
  });
  const result = runGroupFitPreflight(input);
  assert.equal(result.decision, "preserve_v045_baseline");
});

test("relation contract rejects implicit geometry, child mismatch, duplicates, and unbounded loops", () => {
  assert.throws(() => normalizeGroupFitInput({}), /visual_group/);
  const missingRelation = groupInput();
  delete missingRelation.layout_relation;
  assert.throws(() => normalizeGroupFitInput(missingRelation), /layout_relation/);
  const wrongChildren = groupInput();
  wrongChildren.visual_group.children = ["uv-aging", "dye-comparison"];
  assert.throws(() => normalizeGroupFitInput(wrongChildren), /exactly match/);
  const nonFiniteGeometry = groupInput();
  nonFiniteGeometry.baseline_candidate.allocations[0].allocated_visual_bbox.x = Number.NaN;
  assert.throws(() => normalizeGroupFitInput(nonFiniteGeometry), /finite numbers/);
  assert.throws(() => normalizeGroupFitInput(groupInput({ max_relation_replan_attempts: 3 })), /must not exceed 2/);
  assert.throws(() => computeGroupFitMetrics([]), /at least two/);
});
