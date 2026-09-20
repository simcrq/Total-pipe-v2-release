import { compareRelationCandidate } from "./rules.mjs";

function rank(left, right) {
  if (left.comparison.severe_issue_count !== right.comparison.severe_issue_count) return left.comparison.severe_issue_count - right.comparison.severe_issue_count;
  if (left.metrics.group_min_fill !== right.metrics.group_min_fill) return right.metrics.group_min_fill - left.metrics.group_min_fill;
  if (left.metrics.fit_equity !== right.metrics.fit_equity) return right.metrics.fit_equity - left.metrics.fit_equity;
  return left.layout_id.localeCompare(right.layout_id);
}

export function arbitrateConstraints({ baseline, candidates, relation, layoutRelation, childIds, flags, maxAttempts, profile }) {
  const preserved = ["group_membership", "semantic_level", ...(layoutRelation.preserve_order ? ["reading_order"] : []), ...(layoutRelation.shared_alignment ? ["shared_alignment"] : [])];
  if (baseline.geometry?.valid === false) {
    return { decision: "needs_replan", selected: baseline, would_select: null, triggered: true, fallback_used: false, replan_attempts: 0, relaxed_constraints: [], preserved_constraints: preserved, candidate_comparisons: [] };
  }
  if (!baseline.conflict.conflict) {
    return { decision: "preserve_v045_baseline", selected: baseline, would_select: null, triggered: false, fallback_used: false, replan_attempts: 0, relaxed_constraints: [], preserved_constraints: preserved, candidate_comparisons: [] };
  }
  if (relation.relation_strength === "hard") {
    return { decision: "needs_replan", selected: baseline, would_select: null, triggered: true, fallback_used: flags.fallback_to_v045, replan_attempts: 0, relaxed_constraints: [], preserved_constraints: preserved, candidate_comparisons: [] };
  }
  if (flags.relation_arbitration === false || maxAttempts === 0) {
    return { decision: "relation_arbitration_disabled", selected: baseline, would_select: null, triggered: true, fallback_used: flags.fallback_to_v045, replan_attempts: 0, relaxed_constraints: [], preserved_constraints: preserved, candidate_comparisons: [] };
  }
  const evaluated = candidates.map((candidate) => {
    const comparison = compareRelationCandidate({ baseline, candidate, relation, layoutRelation, childIds, profile });
    return { ...candidate, comparison };
  });
  const accepted = evaluated.filter((candidate) => candidate.comparison.accepted).sort(rank);
  const preferred = accepted[0] ?? null;
  const comparisons = evaluated.map((candidate) => ({
    layout_id: candidate.layout_id,
    source: candidate.source,
    accepted: candidate.comparison.accepted,
    rejections: candidate.comparison.rejections,
    severe_issue_count: candidate.comparison.severe_issue_count,
    metrics: candidate.metrics,
    gain: candidate.gain,
  }));
  if (!preferred) {
    return { decision: flags.fallback_to_v045 ? "fallback_to_v045" : "needs_replan", selected: baseline, would_select: null, triggered: true, fallback_used: flags.fallback_to_v045, replan_attempts: 1, relaxed_constraints: [], preserved_constraints: preserved, candidate_comparisons: comparisons };
  }
  if (flags.relation_arbitration === "shadow") {
    return { decision: "shadow_preserve_v045", selected: baseline, would_select: preferred, triggered: true, fallback_used: false, replan_attempts: 1, relaxed_constraints: preferred.relaxed_constraints, preserved_constraints: preserved, candidate_comparisons: comparisons };
  }
  return { decision: "select_relation_aware_candidate", selected: preferred, would_select: preferred, triggered: true, fallback_used: false, replan_attempts: 1, relaxed_constraints: preferred.relaxed_constraints, preserved_constraints: preserved, candidate_comparisons: comparisons };
}
