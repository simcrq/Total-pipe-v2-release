import { createViolation } from "../../content-model.mjs";

export function evaluateElementRelations(facts) {
  const violations = facts.issues.map((issue) => createViolation({
    code: issue.code,
    field: `elements.${issue.element_id}.relation`,
    actual: issue,
    capacity: "bound, sourced, non-duplicate decoration",
    severity: ["DECORATIVE_RELATION_TARGET_MISSING", "ORPHAN_DECORATIVE_ELEMENT"].includes(issue.code) ? "error" : "warning",
    recoverable: true,
    recommended_action: "bind_or_remove_decorative_element",
    message: issue.reason,
    details: issue,
  }));
  const status = violations.some((item) => item.severity === "error")
    ? "fail"
    : violations.length ? "warning" : facts.measurable ? "pass" : "not_evaluable";
  const blocking = violations.find((item) => item.severity === "error") ?? violations[0];
  return {
    checks: {
      decorative_element_relations: {
        rule_id: "decorative_element_relations",
        metric: "element_relations",
        status,
        actual: facts.issue_count,
        threshold: { warning: 0, fail: 0, triggered: violations.length ? 0 : null },
        code: blocking?.code ?? null,
        reason: blocking?.message ?? "decorative_elements_are_bound_and_unique",
        recommended_action: blocking?.recommended_action ?? "none",
        evidence: facts,
        disabled: false,
      },
    },
    violations,
  };
}
