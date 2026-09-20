import { createViolation } from "../content-model.mjs";
import { runVisualFitPreflight, ASPECT_FAIL_POLICY } from "../visual-fit/index.mjs";
import { arbitrateConstraints } from "./arbitrator.mjs";
import { GROUP_FIT_VERSION, normalizeGroupFitInput } from "./contracts.mjs";
import { computeCandidateGain, computeCreditsRegression, computeGroupFitMetrics } from "./metrics.mjs";
import { resolveRelationFitProfile } from "./profile.mjs";
import { evaluateCandidateGeometry, evaluateRelationFitConflict } from "./rules.mjs";
import { generateAsymmetricCandidates } from "./templates.mjs";

const approximatelyEqual = (values, epsilon = 1e-6) => values.every((value) => Math.abs(value - values[0]) <= epsilon);

function relaxedConstraints(candidate, layoutRelation) {
  const boxes = candidate.allocations.map((item) => item.allocated_visual_bbox);
  const equalWidth = approximatelyEqual(boxes.map((box) => box.width));
  const equalHeight = approximatelyEqual(boxes.map((box) => box.height));
  return [
    ...(layoutRelation.equal_size && !(equalWidth && equalHeight) ? ["equal_size"] : []),
    ...(layoutRelation.equal_width && !equalWidth ? ["equal_width"] : []),
    ...(layoutRelation.equal_height && !equalHeight ? ["equal_height"] : []),
  ];
}

function evaluateCandidate(candidate, normalized, profile) {
  const childrenById = new Map(normalized.children.map((child) => [child.visual_id, child]));
  const childFit = candidate.allocations.map((allocation) => {
    const child = childrenById.get(allocation.visual_id);
    const fit = runVisualFitPreflight({
      visual_id: child.visual_id,
      source: child.source,
      ...(child.source_region ? { source_region: child.source_region } : {}),
      visual_intent: child.visual_intent,
      allocated_visual_bbox: allocation.allocated_visual_bbox,
      visual_container: {
        container_id: `${normalized.group_id}:${candidate.layout_id}:${child.visual_id}`,
        role: "image_only",
        content_bbox: allocation.allocated_visual_bbox,
        fit_policy: child.visual_intent.fit_policy,
        crop_policy: child.visual_intent.crop_policy,
        whitespace_policy: child.visual_intent.whitespace_policy,
        mismatch_policy: child.visual_intent.semantic_crop_allowed ? "resolve_region" : "replan",
      },
      quality_profile: normalized.quality_profile,
      // 组内子图是可仲裁的：宽高比失配应由 group-fit 的非对称候选化解，
      // 因此这里用联合条件（失配超阈「且」填充跌破下限）判定 fail，
      // 避免把本可由仲裁修好的子图提前判死、导致非对称候选被整体拒绝。
      aspect_fail_policy: ASPECT_FAIL_POLICY.ASPECT_AND_FILL,
    });
    return {
      visual_id: child.visual_id,
      priority: child.priority,
      status: fit.status,
      decision: fit.decision,
      fill: fit.metrics.visual_fill.area_ratio,
      metrics: fit.metrics,
      issue: fit.issue,
    };
  });
  const evaluated = {
    ...candidate,
    child_fit: childFit,
    metrics: computeGroupFitMetrics(childFit),
    relaxed_constraints: relaxedConstraints(candidate, normalized.layout_relation),
    geometry: evaluateCandidateGeometry(candidate, normalized.baseline_candidate.group_bbox),
  };
  evaluated.conflict = evaluateRelationFitConflict(evaluated, normalized.visual_group, normalized.layout_relation, profile);
  return evaluated;
}

function conflictViolation(normalized, baseline, profile) {
  if (!baseline.conflict.conflict) return null;
  return createViolation({
    code: "VISUAL_RELATION_FIT_CONFLICT",
    field: "visual_group.layout_relation",
    actual: {
      group_id: normalized.group_id,
      relation_type: normalized.visual_group.semantic_relation,
      relation_strength: normalized.visual_group.relation_strength,
      candidate_layout: baseline.layout_id,
      conflicting_children: baseline.conflict.conflicting_children,
      min_fill: baseline.metrics.group_min_fill,
      max_fill: baseline.metrics.group_max_fill,
      fit_equity: baseline.metrics.fit_equity,
      group_fill_variance: baseline.metrics.group_fill_variance,
    },
    capacity: profile.group_fit,
    severity: "error",
    recoverable: true,
    recommended_action: normalized.visual_group.relation_strength === "hard" ? "replan_preserving_relation" : "relax_equal_size",
    message: "Semantic relation geometry causes one or more child visuals to lose effective display capacity.",
    details: { geometry_constraints: baseline.conflict.geometry_constraints },
  });
}

function geometryViolation(normalized, candidate) {
  if (candidate.geometry?.valid !== false) return null;
  return createViolation({
    code: "VISUAL_RELATION_GEOMETRY_INVALID",
    field: "visual_group.layout_relation",
    actual: {
      group_id: normalized.group_id,
      candidate_layout: candidate.layout_id,
      geometry_issues: candidate.geometry.issues,
    },
    capacity: "allocations contained by group_bbox with no undeclared sibling overlap",
    severity: "error",
    recoverable: true,
    recommended_action: "replan",
    message: "Visual group candidate geometry violates group containment or sibling overlap constraints.",
    details: { group_bbox: candidate.geometry.group_bbox, geometry_issues: candidate.geometry.issues },
  });
}

function creditsViolation(creditsRegression, profile) {
  if (creditsRegression.status !== "fail") return null;
  return createViolation({
    code: "CREDITS_REGRESSION",
    field: "credits.v046.median_credits_per_deck",
    actual: creditsRegression.credits_per_deck_ratio,
    capacity: profile.credits.maximum_regression_ratio,
    severity: "error",
    recoverable: true,
    recommended_action: "review_credits_regression",
    message: "Median credits per deck exceeds the v0.4.5 regression budget.",
  });
}

function relationTelemetry(normalized, candidate) {
  return {
    group_id: normalized.group_id,
    relation_type: normalized.visual_group.semantic_relation,
    relation_strength: normalized.visual_group.relation_strength,
    candidate_layout: candidate.layout_id,
    children: candidate.child_fit.map((child) => ({ visual_id: child.visual_id, fill: child.fill, status: child.status })),
    group_min_fill: candidate.metrics.group_min_fill,
    group_max_fill: candidate.metrics.group_max_fill,
    group_mean_fill: candidate.metrics.group_mean_fill,
    group_fill_variance: candidate.metrics.group_fill_variance,
    fit_equity: candidate.metrics.fit_equity,
    visual_weight_deviation: candidate.metrics.visual_weight_deviation,
    conflict: candidate.conflict.conflict,
    conflicting_children: candidate.conflict.conflicting_children,
  };
}

function compactCandidate(candidate) {
  return {
    layout_id: candidate.layout_id,
    source: candidate.source,
    allocations: candidate.allocations,
    child_order: candidate.child_order,
    higher_priority_issues: candidate.higher_priority_issues,
    child_fit: candidate.child_fit.map(({ visual_id, priority, status, decision, fill }) => ({ visual_id, priority, status, decision, fill })),
    metrics: candidate.metrics,
    conflict: candidate.conflict,
    geometry: candidate.geometry,
    relaxed_constraints: candidate.relaxed_constraints,
    ...(candidate.gain ? { gain: candidate.gain } : {}),
  };
}

export function runGroupFitPreflight(input = {}) {
  const normalized = normalizeGroupFitInput(input);
  const profile = resolveRelationFitProfile(normalized.quality_profile);
  const creditsRegression = computeCreditsRegression(normalized.credits, profile.credits.maximum_regression_ratio);
  if (!normalized.feature_flags.visual_fit_v045 || !normalized.feature_flags.relation_contract_v046 || !normalized.feature_flags.group_fit_preflight) {
    const disabledBy = Object.entries(normalized.feature_flags).filter(([key, value]) => key !== "relation_arbitration" && value === false).map(([key]) => key);
    return {
      group_fit_version: GROUP_FIT_VERSION,
      pipeline_status: "group_fit_preflight_complete",
      status: "not_evaluable",
      decision: "feature_disabled",
      group_id: normalized.group_id,
      feature_flags: normalized.feature_flags,
      disabled_by: disabledBy,
      selected_candidate: normalized.baseline_candidate,
      fallback_to_v045: true,
      relation_fit: null,
      constraint_arbitration: { triggered: false, relaxed_constraints: [], preserved_constraints: [], original_candidate: normalized.baseline_candidate.layout_id, selected_candidate: normalized.baseline_candidate.layout_id, fallback_used: true, replan_attempts: 0, shadow_mode: normalized.feature_flags.relation_arbitration === "shadow" },
      credits_regression: creditsRegression,
      issues: [],
      recommended_action: "enable_relation_fit_features",
    };
  }

  const baseline = evaluateCandidate(normalized.baseline_candidate, normalized, profile);
  const issue = geometryViolation(normalized, baseline) ?? conflictViolation(normalized, baseline, profile);
  const creditIssue = creditsViolation(creditsRegression, profile);
  const generated = normalized.feature_flags.non_uniform_siblings
    ? generateAsymmetricCandidates({ group_bbox: baseline.group_bbox, child_ids: normalized.visual_group.children, gap_ratio: profile.arbitration.template_gap_ratio })
    : [];
  const seen = new Set([baseline.layout_id]);
  const alternatives = [...normalized.relation_aware_candidates, ...generated]
    .filter((candidate) => !seen.has(candidate.layout_id) && seen.add(candidate.layout_id))
    .map((candidate) => {
      const evaluated = evaluateCandidate(candidate, normalized, profile);
      evaluated.gain = computeCandidateGain(baseline.metrics, evaluated.metrics);
      return evaluated;
    });
  const arbitration = arbitrateConstraints({
    baseline,
    candidates: alternatives,
    relation: normalized.visual_group,
    layoutRelation: normalized.layout_relation,
    childIds: normalized.visual_group.children,
    flags: normalized.feature_flags,
    maxAttempts: Math.min(normalized.max_relation_replan_attempts, profile.arbitration.max_relation_replan_attempts),
    profile,
  });
  const selected = arbitration.selected;
  const unresolvedConflict = selected.conflict.conflict;
  const selectedGeometryIssue = geometryViolation(normalized, selected);
  let status = unresolvedConflict || selectedGeometryIssue ? "fail" : "pass";
  if (arbitration.decision === "shadow_preserve_v045" && !selectedGeometryIssue) status = "warning";
  if (creditsRegression.status === "fail") status = "fail";
  const unresolvedIssues = [...(selectedGeometryIssue ? [selectedGeometryIssue] : []), ...(unresolvedConflict && issue && !selectedGeometryIssue ? [issue] : []), ...(creditIssue ? [creditIssue] : [])];
  const resolvedIssues = !unresolvedConflict && !selectedGeometryIssue && issue ? [issue] : [];
  const selectedChanged = selected.layout_id !== baseline.layout_id;
  return {
    group_fit_version: GROUP_FIT_VERSION,
    pipeline_status: "group_fit_preflight_complete",
    status,
    decision: arbitration.decision,
    group_id: normalized.group_id,
    visual_group: normalized.visual_group,
    layout_relation: normalized.layout_relation,
    feature_flags: normalized.feature_flags,
    baseline_candidate: compactCandidate(baseline),
    candidate_evaluations: alternatives.map(compactCandidate),
    selected_candidate: compactCandidate(selected),
    fallback_to_v045: arbitration.fallback_used,
    relation_fit: relationTelemetry(normalized, selected),
    constraint_arbitration: {
      triggered: arbitration.triggered,
      relaxed_constraints: arbitration.relaxed_constraints,
      preserved_constraints: arbitration.preserved_constraints,
      original_candidate: baseline.layout_id,
      selected_candidate: selected.layout_id,
      would_select_candidate: arbitration.would_select?.layout_id ?? null,
      fallback_used: arbitration.fallback_used,
      replan_attempts: arbitration.replan_attempts,
      max_relation_replan_attempts: normalized.max_relation_replan_attempts,
      shadow_mode: normalized.feature_flags.relation_arbitration === "shadow",
      candidate_comparisons: arbitration.candidate_comparisons,
    },
    credits_regression: creditsRegression,
    layout_churn: {
      baseline_qa_passed: normalized.baseline_qa_passed,
      changed: selectedChanged,
      justified_by_conflict: selectedChanged && baseline.conflict.conflict,
    },
    issue,
    detected_issues: [...(issue ? [issue] : []), ...(creditIssue ? [creditIssue] : [])],
    resolved_issues: resolvedIssues,
    issues: unresolvedIssues,
    recommended_action: creditsRegression.status === "fail"
      ? "review_credits_regression"
      : arbitration.decision === "needs_replan"
        ? "replan_preserving_relation"
        : arbitration.decision === "fallback_to_v045"
          ? "keep_v045_candidate"
          : arbitration.decision === "shadow_preserve_v045"
            ? "review_shadow_candidate"
            : "proceed",
  };
}

export { arbitrateConstraints } from "./arbitrator.mjs";
export { GROUP_FIT_INPUT_SCHEMA, GROUP_FIT_VERSION, RELATION_STRENGTHS, RELATION_TYPES, normalizeGroupFitInput } from "./contracts.mjs";
export { computeCandidateGain, computeCreditsRegression, computeGroupFitMetrics } from "./metrics.mjs";
export { resolveRelationFitProfile } from "./profile.mjs";
export { compareRelationCandidate, evaluateCandidateGeometry, evaluateRelationFitConflict, GROUP_FIT_GEOMETRY_EPSILON } from "./rules.mjs";
export { PREDEFINED_ASYMMETRIC_TEMPLATES, generateAsymmetricCandidates } from "./templates.mjs";
