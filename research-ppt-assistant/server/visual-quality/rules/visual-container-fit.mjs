import { createViolation } from "../../content-model.mjs";
import { evaluateContainerChildFit } from "../../visual-fit/rules.mjs";

function violation(code, field, actual, capacity, severity, recommendedAction, message, details) {
  return createViolation({ code, field, actual, capacity, severity, recoverable: true, recommended_action: recommendedAction, message, details });
}

export function evaluateVisualContainerFit(facts, profile) {
  const violations = [];
  let blocking = null;
  for (const observation of facts.observations) {
    const contract = {
      visual_type: observation.visual_type,
      container_role: observation.container_role,
      fit_policy: observation.fit_policy,
      crop_policy: observation.crop_policy,
      whitespace_policy: observation.whitespace_policy,
      mismatch_policy: observation.mismatch_policy,
      semantic_crop_allowed: observation.crop_policy === "semantic_crop_allowed",
    };
    const result = evaluateContainerChildFit(observation.metrics, contract, profile.visual_fit_rules);
    if (result.status === "pass") continue;
    const item = violation(
      "VISUAL_CONTAINER_CHILD_MISMATCH",
      `visual_containers.${observation.container_id}`,
      observation.metrics,
      profile.visual_fit_rules.scientific_figure,
      result.status === "fail" ? "error" : "warning",
      result.recommended_action,
      result.reason,
      observation,
    );
    violations.push(item);
    if (!blocking || item.severity === "error") blocking = item;
  }
  if (facts.missing_fields.length) {
    const item = violation(
      "VISUAL_CONTAINER_RELATION_NOT_EVALUABLE",
      "metrics.visual_container_fit.missing_fields",
      facts.missing_fields,
      "complete_parent_child_contract",
      "warning",
      "provide_required_input",
      "Visual container QA requires explicit, resolvable parent-child facts.",
      { missing_fields: facts.missing_fields },
    );
    violations.push(item);
    blocking ??= item;
  }
  const status = violations.some((item) => item.severity === "error")
    ? "fail"
    : violations.length ? "warning"
      : facts.applicable ? "pass" : "pass";
  return {
    checks: {
      visual_container_child_fit: {
        rule_id: "visual_container_child_fit",
        metric: "visual_container_fit",
        status,
        actual: violations.length,
        threshold: { warning: null, fail: null, triggered: null },
        code: blocking?.code ?? null,
        reason: violations.length ? "visual_container_contract_violations" : "within_profile_thresholds",
        recommended_action: blocking?.recommended_action ?? "none",
        evidence: facts,
        disabled: false,
      },
    },
    violations,
  };
}
