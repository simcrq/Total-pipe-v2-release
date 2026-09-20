import { createViolation } from "../../content-model.mjs";

export function evaluateLayoutRegression(facts) {
  const violations = facts.issues.map((issue) => createViolation({
    code: "LAYOUT_RELATION_REGRESSION",
    field: `visuals.${issue.visual_id}`,
    actual: issue,
    capacity: "preserve baseline parent, sibling, and placement relations",
    severity: "error",
    recoverable: true,
    recommended_action: "restore_baseline_layout_relation",
    message: `${issue.code}: existing-deck visual relation changed without an explicit override.`,
    details: issue,
  }));
  return {
    checks: {
      layout_relation_regression: {
        rule_id: "layout_relation_regression",
        metric: "layout_regression",
        status: violations.length ? "fail" : facts.applicable ? "pass" : "not_evaluable",
        actual: facts.issue_count,
        threshold: { warning: null, fail: 0, triggered: violations.length ? 0 : null },
        code: violations.length ? "LAYOUT_RELATION_REGRESSION" : null,
        reason: violations.length ? "baseline_layout_relations_changed" : facts.applicable ? "baseline_layout_relations_preserved" : "baseline_not_supplied",
        recommended_action: violations.length ? "restore_baseline_layout_relation" : "none",
        evidence: facts,
        disabled: !facts.applicable,
      },
    },
    violations,
  };
}
