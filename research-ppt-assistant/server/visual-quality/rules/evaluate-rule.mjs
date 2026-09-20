function normalizeMetric(metric) {
  if (metric && typeof metric === "object" && !Array.isArray(metric)) {
    return {
      measurable: metric.measurable !== false && metric.value !== null && metric.value !== undefined,
      value: metric.value,
      unavailable_reason: metric.unavailable_reason,
      evidence: metric.evidence,
    };
  }
  return { measurable: metric !== null && metric !== undefined, value: metric };
}

function exceeds(value, threshold, operator) {
  if (threshold === null || threshold === undefined) return false;
  if (operator === "minimum") return value < threshold;
  if (operator === "maximum" || operator === "count") return value > threshold;
  if (operator === "truthy") return Boolean(value) === Boolean(threshold);
  throw new RangeError(`Unsupported visual quality rule operator: ${operator}`);
}

export function evaluateRule(metric, ruleDefinition, options = {}) {
  const ruleId = options.rule_id ?? options.ruleId ?? "rule";
  if (!ruleDefinition || typeof ruleDefinition !== "object") throw new TypeError("ruleDefinition must be an object");
  const threshold = {
    warning: ruleDefinition.warning ?? null,
    fail: ruleDefinition.fail ?? null,
    triggered: null,
  };
  if (ruleDefinition.enabled === false) {
    return {
      rule_id: ruleId,
      metric: ruleDefinition.metric,
      status: "not_evaluable",
      actual: null,
      threshold,
      code: null,
      reason: "rule_disabled",
      recommended_action: "none",
      evidence: null,
      disabled: true,
    };
  }
  const normalized = normalizeMetric(metric);
  if (!normalized.measurable || !Number.isFinite(Number(normalized.value))) {
    return {
      rule_id: ruleId,
      metric: ruleDefinition.metric,
      status: "not_evaluable",
      actual: null,
      threshold,
      code: ruleDefinition.not_evaluable_code ?? null,
      reason: normalized.unavailable_reason ?? "metric_unavailable",
      recommended_action: "provide_required_input",
      evidence: normalized.evidence ?? null,
      disabled: false,
    };
  }

  const actual = Number(normalized.value);
  if (exceeds(actual, ruleDefinition.fail, ruleDefinition.operator)) {
    return {
      rule_id: ruleId,
      metric: ruleDefinition.metric,
      status: "fail",
      actual,
      threshold: { ...threshold, triggered: ruleDefinition.fail },
      code: ruleDefinition.fail_code ?? null,
      reason: ruleDefinition.reason,
      recommended_action: ruleDefinition.recommended_action,
      evidence: normalized.evidence ?? null,
      disabled: false,
    };
  }
  if (exceeds(actual, ruleDefinition.warning, ruleDefinition.operator)) {
    return {
      rule_id: ruleId,
      metric: ruleDefinition.metric,
      status: "warning",
      actual,
      threshold: { ...threshold, triggered: ruleDefinition.warning },
      code: ruleDefinition.warning_code ?? null,
      reason: ruleDefinition.reason,
      recommended_action: ruleDefinition.recommended_action,
      evidence: normalized.evidence ?? null,
      disabled: false,
    };
  }
  return {
    rule_id: ruleId,
    metric: ruleDefinition.metric,
    status: "pass",
    actual,
    threshold,
    code: null,
    reason: "within_profile_thresholds",
    recommended_action: "none",
    evidence: normalized.evidence ?? null,
    disabled: false,
  };
}
