import { createViolation } from "../../content-model.mjs";
import { evaluateRule } from "./evaluate-rule.mjs";

function violationFromCheck(check) {
  if (!check.code || !["warning", "fail", "not_evaluable"].includes(check.status)) return undefined;
  return createViolation({
    code: check.code,
    field: check.metric,
    actual: check.actual,
    capacity: check.threshold,
    severity: check.status === "fail" ? "error" : "warning",
    recoverable: true,
    recommended_action: check.recommended_action,
    message: check.reason,
    details: check.evidence,
  });
}

function evaluateTextImageProtection(metric, definition, ruleId) {
  if (definition.enabled === false || !metric?.measurable) return evaluateRule(metric, definition, { rule_id: ruleId });
  const criteria = definition.criteria ?? {};
  const localContrastMin = Number(criteria.local_contrast_min);
  const overlayCoverageMin = Number(criteria.overlay_coverage_min);
  const overlayOpacityMin = Number(criteria.overlay_opacity_min);
  if (![localContrastMin, overlayCoverageMin, overlayOpacityMin].every(Number.isFinite)) {
    throw new TypeError(`${ruleId} requires finite text-image protection criteria`);
  }

  const failures = [];
  const unresolved = [];
  const protectedIntersections = [];
  for (const observation of metric.evidence?.intersections ?? []) {
    const localKnown = Number.isFinite(observation.local_contrast_ratio);
    const localSafe = localKnown && observation.local_contrast_ratio >= localContrastMin;
    // A text element's own fill is foreground paint, not an independent
    // surface. Ignore legacy/self-reported candidates defensively even if an
    // adapter or caller supplied one in the metric evidence.
    const surfaces = (Array.isArray(observation.overlays) ? observation.overlays : [])
      .filter((overlay) => overlay?.element_id !== observation.text_element_id);
    const surfaceSafe = surfaces.some((overlay) => Number.isFinite(overlay.opacity)
      && overlay.coverage_ratio >= overlayCoverageMin
      && overlay.opacity >= overlayOpacityMin);
    const surfaceCouldBeSafe = surfaces.some((overlay) => overlay.coverage_ratio >= overlayCoverageMin && !Number.isFinite(overlay.opacity));
    if (localSafe || surfaceSafe) protectedIntersections.push(observation);
    else if (!localKnown || surfaceCouldBeSafe) unresolved.push(observation);
    else failures.push(observation);
  }

  const evidence = {
    ...metric.evidence,
    criteria: {
      local_contrast_min: localContrastMin,
      overlay_coverage_min: overlayCoverageMin,
      overlay_opacity_min: overlayOpacityMin,
    },
    protected_count: protectedIntersections.length,
    unresolved_count: unresolved.length,
    failure_count: failures.length,
    unresolved,
    failures,
  };
  if (failures.length) {
    return evaluateRule(
      { measurable: true, value: failures.length, evidence },
      { ...definition, operator: "count", fail: 0 },
      { rule_id: ruleId },
    );
  }
  if (unresolved.length) {
    return evaluateRule(
      { measurable: false, value: null, unavailable_reason: "text_over_image_protection_unmeasured", evidence },
      definition,
      { rule_id: ruleId },
    );
  }
  return evaluateRule(
    { measurable: true, value: 0, evidence },
    { ...definition, operator: "count", fail: 0 },
    { rule_id: ruleId },
  );
}

export function evaluateQuality(metrics, profile) {
  if (!metrics || typeof metrics !== "object" || Array.isArray(metrics)) throw new TypeError("metrics must be an object");
  if (!profile || typeof profile !== "object" || Array.isArray(profile)) throw new TypeError("profile must be an object");
  const checks = {};
  const violations = [];
  for (const [ruleId, definition] of Object.entries(profile.rules ?? {})) {
    const check = definition.operator === "text_image_protection"
      ? evaluateTextImageProtection(metrics[definition.metric], definition, ruleId)
      : evaluateRule(metrics[definition.metric], definition, { rule_id: ruleId });
    checks[ruleId] = check;
    const violation = violationFromCheck(check);
    if (violation) violations.push(violation);
  }
  return { checks, violations };
}
