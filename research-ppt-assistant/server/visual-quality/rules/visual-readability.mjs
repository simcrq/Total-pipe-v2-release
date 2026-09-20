import { createViolation } from "../../content-model.mjs";

function requiredWidth(observation, config) {
  if (Number.isFinite(observation.min_display_width)) return observation.min_display_width;
  const type = config.visual_types?.[observation.visual_type] ? observation.visual_type : "visual_evidence";
  let required = Number(config.visual_types?.[type]?.minimum_width ?? 0.34);
  if (type === "multi_panel_figure") {
    if (observation.panel_count >= 6) required += Number(config.multi_panel_width_add_6 ?? 0);
    else if (observation.panel_count >= 4) required += Number(config.multi_panel_width_add_4 ?? 0);
  }
  if (observation.has_embedded_text && type === "visual_evidence") {
    required = Math.max(required, Number(config.embedded_visual_evidence_width ?? required));
  }
  return required;
}

function violation(code, field, actual, capacity, severity, recommendedAction, message, details) {
  return createViolation({
    code,
    field,
    actual,
    capacity,
    severity,
    recoverable: true,
    recommended_action: recommendedAction,
    message,
    details,
  });
}

function statusOf(violations, measurable) {
  if (violations.some((item) => item.severity === "error")) return "fail";
  if (!measurable && violations.every((item) => item.code === "SCIENTIFIC_VISUAL_NOT_EVALUABLE")) return "not_evaluable";
  if (violations.some((item) => item.severity === "warning")) return "warning";
  return measurable ? "pass" : "not_evaluable";
}

export function evaluateScientificVisualReadability(facts, profile, context = {}) {
  const config = profile.scientific_visual_rules ?? profile.legacy_rules ?? {};
  const viewingMode = String(context.viewing_mode ?? "projector").toLowerCase();
  const viewing = config.viewing_modes?.[viewingMode] ?? config.viewing_modes?.projector ?? {};
  const violations = [];
  if (facts.applicable) {
    for (const observation of facts.observations) {
      if (observation.visual_type === null || observation.panel_count === null
          || observation.has_embedded_text === null || observation.display_width_norm === null) continue;
      const required = requiredWidth(observation, config);
      const severeWidthRatio = Number(config.severe_visual_width_ratio ?? 0.72);
      if (observation.display_width_norm < required * severeWidthRatio) {
        violations.push(violation(
          "DENSE_FIGURE_TOO_SMALL",
          `elements.${observation.element_id}.image.display_width_norm`,
          observation.display_width_norm,
          required,
          "error",
          "replan_or_split",
          `${observation.element_id} is substantially smaller than the scientific visual width requirement.`,
          observation,
        ));
      } else if (observation.display_width_norm < required) {
        violations.push(violation(
          "VISUAL_READABILITY_RISK",
          `elements.${observation.element_id}.image.display_width_norm`,
          observation.display_width_norm,
          required,
          "warning",
          "reflow_content",
          `${observation.element_id} is smaller than the scientific visual width requirement.`,
          observation,
        ));
      }
      const maxLetterbox = Number(config.max_letterbox_ratio ?? 0.35);
      if (Number.isFinite(observation.letterbox_ratio) && observation.letterbox_ratio > maxLetterbox) {
        violations.push(violation(
          "IMAGE_UNDERFILLED_SLOT",
          `elements.${observation.element_id}.image.letterbox_ratio`,
          observation.letterbox_ratio,
          maxLetterbox,
          "error",
          "reconsider_visual_placement",
          `${observation.element_id} leaves excessive unused area inside its allocated visual slot.`,
          observation,
        ));
      }
      const embeddedMin = Number(viewing.embedded_text_warning_px ?? viewing.embedded_text_min_px ?? 14);
      if (observation.has_embedded_text && Number.isFinite(observation.rendered_embedded_text_px)
          && observation.rendered_embedded_text_px < embeddedMin) {
        const severe = observation.rendered_embedded_text_px < embeddedMin * Number(config.severe_embedded_text_ratio ?? 0.75);
        violations.push(violation(
          "EMBEDDED_TEXT_TOO_SMALL",
          `elements.${observation.element_id}.image.rendered_embedded_text_px`,
          observation.rendered_embedded_text_px,
          embeddedMin,
          severe ? "error" : "warning",
          "replan_or_split",
          `${observation.element_id} contains embedded text below the ${viewingMode} readability threshold.`,
          observation,
        ));
      }
    }
  }
  if (facts.missing_fields.length) {
    const measurementOnly = facts.missing_fields.every((field) => field.endsWith(".rendered_embedded_text_px"));
    const measurementFailed = (facts.measurement_gaps ?? []).some((item) => item.state === "measurement_failed");
    violations.push(violation(
      "SCIENTIFIC_VISUAL_NOT_EVALUABLE",
      "metrics.visual_readability.missing_fields",
      facts.missing_fields,
      "complete_renderer_visual_facts",
      measurementOnly && !measurementFailed ? "info" : "warning",
      measurementOnly && !measurementFailed ? "review_raster_text_if_readability_risk" : "provide_required_input",
      measurementFailed ? "Raster-text measurement failed." : measurementOnly ? "Raster text was not measured; geometry checks remain valid." : "Scientific visual readability requires complete renderer facts.",
      { missing_fields: facts.missing_fields, measurement_gaps: facts.measurement_gaps ?? [] },
    ));
  }
  const status = facts.applicable ? statusOf(violations, facts.measurable) : "pass";
  const blocking = violations.find((item) => item.severity === "error") ?? violations[0];
  const nonBlockingUnmeasuredRasterText = violations.length > 0
    && violations.every((item) => item.code === "SCIENTIFIC_VISUAL_NOT_EVALUABLE" && item.severity === "info");
  return {
    checks: {
      scientific_visual_readability: {
        rule_id: "scientific_visual_readability",
        metric: "visual_readability",
        status,
        actual: violations.length,
        threshold: { warning: null, fail: null, triggered: null },
        code: blocking?.code ?? null,
        reason: violations.length ? "scientific_visual_readability_violations" : "within_profile_thresholds",
        recommended_action: blocking?.recommended_action ?? "none",
        evidence: facts,
        disabled: false,
        blocking: !nonBlockingUnmeasuredRasterText,
        review_required: nonBlockingUnmeasuredRasterText,
      },
    },
    violations,
  };
}
