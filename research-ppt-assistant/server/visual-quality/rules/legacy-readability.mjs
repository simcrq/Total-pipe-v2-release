import { createViolation } from "../../content-model.mjs";

const STATUS_WEIGHT = Object.freeze({ pass: 0, not_evaluable: 1, warning: 2, fail: 3 });

function createLegacyViolation(code, field, actual, capacity, severity, recommendedAction, message, details) {
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

function roleThreshold(role, settings) {
  if (role === "title") return { warning: settings.title_minimum, fail: settings.title_minimum };
  if (["subheading", "callout", "question"].includes(role)) return { warning: settings.subheading_minimum, fail: settings.subheading_minimum };
  if (["caption", "meta", "footer"].includes(role)) return { warning: settings.caption_minimum, fail: settings.caption_minimum };
  return { warning: settings.body_warning, fail: settings.body_fail };
}

function worstStatus(violations) {
  if (violations.some((violation) => violation.severity === "error")) return "fail";
  if (violations.some((violation) => violation.severity === "warning")) return "warning";
  return "pass";
}

export function evaluateLegacyReadability(telemetry, profile, context = {}) {
  const config = profile.legacy_rules ?? {};
  const viewingMode = String(context.viewing_mode ?? "projector").toLowerCase();
  const settings = config.viewing_modes?.[viewingMode] ?? config.viewing_modes?.projector;
  if (!settings) return { checks: {}, violations: [] };
  const violations = [];
  const textElements = telemetry.elements.filter((element) => element.type === "text" && element.quality_role === "content");
  const measuredText = textElements.filter((element) => Number.isFinite(element.text?.font_size));
  if (!measuredText.length) {
    violations.push(createLegacyViolation(
      "MISSING_TYPOGRAPHY_TELEMETRY",
      "elements[].text.font_size",
      null,
      "renderer_font_metrics",
      "warning",
      "provide_required_input",
      "Rendered text font-size telemetry is unavailable.",
    ));
  }
  for (const element of measuredText) {
    const role = element.text.role ?? "body";
    const threshold = roleThreshold(role, settings);
    if (element.text.font_size < threshold.fail) {
      violations.push(createLegacyViolation(
        "FONT_FLOOR_VIOLATION",
        `elements.${element.element_id}.text.font_size`,
        element.text.font_size,
        threshold.fail,
        "error",
        "replan_or_split",
        `${element.element_id} is below the configured ${role} absolute font floor.`,
      ));
    } else if (element.text.font_size < threshold.warning) {
      violations.push(createLegacyViolation(
        "FONT_BELOW_VIEWING_TARGET",
        `elements.${element.element_id}.text.font_size`,
        element.text.font_size,
        threshold.warning,
        "warning",
        "reflow_content",
        `${element.element_id} is below the configured ${viewingMode} viewing target.`,
      ));
    }
    if (role === "title" && element.text.line_count > 1 && element.text.intended_single_line !== false) {
      violations.push(createLegacyViolation(
        "TITLE_WRAPPED",
        `elements.${element.element_id}.text.line_count`,
        element.text.line_count,
        1,
        "error",
        "replan_or_split",
        `${element.element_id} rendered on more than one line.`,
      ));
    }
  }

  const provided = telemetry.provided_metrics ?? {};
  const intentionalWhitespace = provided.intentional_whitespace === true;
  const lowDensity = (config.low_density_categories ?? []).includes(context.category);
  const footprintMin = lowDensity ? config.low_density_content_footprint_warning_min : settings.content_footprint_warning_min;
  const emptyBandMax = lowDensity ? config.low_density_largest_empty_band_warning : settings.largest_empty_band_warning;
  if (!Number.isFinite(provided.content_footprint)) {
    violations.push(createLegacyViolation(
      "MISSING_OCCUPANCY_TELEMETRY",
      "provided_metrics.content_footprint",
      null,
      "content_footprint",
      "warning",
      "provide_required_input",
      "Rendered content-footprint telemetry is unavailable.",
    ));
  } else if (provided.content_footprint < footprintMin && !intentionalWhitespace) {
    violations.push(createLegacyViolation("LOW_CONTENT_OCCUPANCY", "provided_metrics.content_footprint", provided.content_footprint, footprintMin, "warning", "review_content_distribution", "Rendered content footprint is below the configured minimum."));
  } else if (provided.content_footprint > settings.content_footprint_warning_max) {
    violations.push(createLegacyViolation("CONTENT_TOO_DENSE", "provided_metrics.content_footprint", provided.content_footprint, settings.content_footprint_warning_max, "warning", "reflow_content", "Rendered content footprint is above the configured maximum."));
  }
  if (Number.isFinite(provided.largest_empty_band) && provided.largest_empty_band > emptyBandMax && !intentionalWhitespace) {
    violations.push(createLegacyViolation("UNINTENTIONAL_EMPTY_BAND", "provided_metrics.largest_empty_band", provided.largest_empty_band, emptyBandMax, "warning", "review_content_distribution", "Rendered slide contains an excessive empty band."));
  }
  if (Number.isFinite(provided.content_center_x) && Number.isFinite(provided.content_center_y)
      && (Math.abs(provided.content_center_x - 0.5) > config.center_axis_warning_x || Math.abs(provided.content_center_y - 0.5) > config.center_axis_warning_y)) {
    violations.push(createLegacyViolation(
      "UNBALANCED_CONTENT_CENTER",
      "provided_metrics.content_center",
      { x: provided.content_center_x, y: provided.content_center_y },
      { x: config.center_axis_warning_x, y: config.center_axis_warning_y },
      "warning",
      "rebalance_content",
      "Rendered content center is displaced beyond the configured axes.",
    ));
  }

  const visuals = Array.isArray(provided.visuals) ? provided.visuals : [];
  let denseCount = 0;
  for (const [index, visual] of visuals.entries()) {
    const type = config.visual_types?.[visual.visual_type] ? visual.visual_type : "visual_evidence";
    const typeConfig = config.visual_types?.[type] ?? {};
    const panels = Math.max(1, Number(visual.panel_count) || 1);
    const dense = typeConfig.dense === true || panels >= config.dense_panel_count;
    if (dense) denseCount += 1;
    let requiredWidth = Number.isFinite(visual.min_display_width) ? visual.min_display_width : typeConfig.minimum_width;
    if (type === "multi_panel_figure") {
      if (panels >= 6) requiredWidth += config.multi_panel_width_add_6;
      else if (panels >= 4) requiredWidth += config.multi_panel_width_add_4;
    }
    if (visual.has_embedded_text && type === "visual_evidence") requiredWidth = Math.max(requiredWidth, config.embedded_visual_evidence_width);
    if (!Number.isFinite(visual.display_width_norm)) {
      violations.push(createLegacyViolation("MISSING_VISUAL_SIZE_TELEMETRY", `provided_metrics.visuals[${index}].display_width_norm`, null, requiredWidth, "warning", "provide_required_input", "Rendered visual display width is unavailable."));
    } else if (visual.display_width_norm < requiredWidth * config.severe_visual_width_ratio) {
      violations.push(createLegacyViolation("DENSE_FIGURE_TOO_SMALL", `provided_metrics.visuals[${index}].display_width_norm`, visual.display_width_norm, requiredWidth, "error", "replan_or_split", "Rendered visual is substantially smaller than its profile requirement."));
    } else if (visual.display_width_norm < requiredWidth) {
      violations.push(createLegacyViolation("VISUAL_READABILITY_RISK", `provided_metrics.visuals[${index}].display_width_norm`, visual.display_width_norm, requiredWidth, "warning", "reflow_content", "Rendered visual is smaller than its profile requirement."));
    }
    if (visual.has_embedded_text && Number.isFinite(visual.rendered_embedded_text_px) && visual.rendered_embedded_text_px < settings.embedded_text_warning_px) {
      const severe = visual.rendered_embedded_text_px < settings.embedded_text_warning_px * config.severe_embedded_text_ratio;
      violations.push(createLegacyViolation("EMBEDDED_TEXT_TOO_SMALL", `provided_metrics.visuals[${index}].rendered_embedded_text_px`, visual.rendered_embedded_text_px, settings.embedded_text_warning_px, severe ? "error" : "warning", "replan_or_split", "Rendered embedded figure text is below the configured pixel height."));
    }
  }
  if (denseCount >= config.dense_visual_split_count && visuals.some((visual) => (visual.display_width_norm ?? 0) < config.dense_visual_split_width)) {
    violations.push(createLegacyViolation("SPLIT_SLIDE_RECOMMENDED", "provided_metrics.visuals", denseCount, config.dense_visual_split_count, "warning", "replan_or_split", "Multiple dense visuals compete for insufficient display width."));
  }

  const status = worstStatus(violations);
  return {
    checks: {
      legacy_readability: {
        rule_id: "legacy_readability",
        metric: "legacy_violation_count",
        status,
        actual: violations.length,
        threshold: { warning: null, fail: null, triggered: null },
        code: null,
        reason: violations.length ? "legacy_readability_violations" : "within_profile_thresholds",
        recommended_action: violations[0]?.recommended_action ?? "none",
        evidence: {
          viewing_mode: viewingMode,
          violation_count: violations.length,
          metric_source: "renderer_telemetry",
        },
        disabled: false,
      },
    },
    violations,
    status_weight: STATUS_WEIGHT[status],
  };
}
