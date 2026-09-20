import { VISUAL_OBSERVER_VERSION } from "./contracts.mjs";

const asArray = (value) => (Array.isArray(value) ? value : []);
const clamp = (value, min = 0, max = 1) => Math.min(max, Math.max(min, value));
const round = (value) => Number(value.toFixed(3));

const DESIGN_ONLY_CHECKS = new Set([
  "element_area_ratio",
  "largest_horizontal_gap",
  "largest_vertical_gap",
  "visual_center",
]);

const PRODUCTION_CODE_GROUPS = Object.freeze({
  TEXT_DENSITY_HIGH: ["TEXT_VISUAL_OVERFLOW", "FONT_FLOOR_VIOLATION", "TITLE_WRAPPED", "LOW_CONTENT_OCCUPANCY"],
  VISUAL_TOO_SMALL: ["DENSE_FIGURE_TOO_SMALL", "VISUAL_READABILITY_RISK", "IMAGE_UNDERFILLED_SLOT", "EMBEDDED_TEXT_TOO_SMALL", "VISUAL_CONTAINER_CHILD_MISMATCH"],
  GEOMETRY_INVALID: ["ELEMENT_OUT_OF_BOUNDS", "LAYOUT_RELATION_REGRESSION", "RENDERER_PLACEMENT_OVERRIDE", "RENDERER_SOURCE_REGION_OVERRIDE"],
  RENDER_OR_EVIDENCE_MISMATCH: ["SEMANTIC_CROP_ASSET_MISMATCH", "ASSET_IDENTITY_MISMATCH", "RENDER_EVIDENCE_MISMATCH", "THEME_USAGE_VIOLATION", "UNPROTECTED_TEXT_OVER_IMAGE"],
});

const ACTION_BY_ISSUE = Object.freeze({
  LOW_VISUAL_HIERARCHY: "CHANGE_TREATMENT",
  LOW_VISUAL_FOCUS: "CHANGE_TREATMENT",
  LOW_WHITESPACE: "REDECORATE",
  UNBALANCED_VISUAL_WEIGHT: "CHANGE_TREATMENT",
  EXCESSIVE_CARDIFICATION: "CHANGE_TREATMENT",
  REPEATED_CONTAINER_LANGUAGE: "REDECORATE",
  REPEATED_TREATMENT: "CHANGE_TREATMENT",
  LOW_DECK_RHYTHM: "CHANGE_TREATMENT",
  TEXT_DENSITY_HIGH: "REBIND",
  VISUAL_TOO_SMALL: "RESELECT_LAYOUT",
  GEOMETRY_INVALID: "REBIND",
  RENDER_OR_EVIDENCE_MISMATCH: "ESCALATE",
  OBSERVATION_INCOMPLETE: "ESCALATE",
});

function metric(measurable, value, evidence, unavailableReason) {
  return {
    measurable,
    value: measurable ? round(clamp(value)) : null,
    evidence,
    ...(measurable ? {} : { unavailable_reason: unavailableReason ?? "metric_unavailable" }),
  };
}

function boxArea(box) {
  return Math.max(0, Number(box?.width ?? 0)) * Math.max(0, Number(box?.height ?? 0));
}

function hierarchyMetric(telemetry, designContext) {
  const content = asArray(telemetry?.elements).filter((element) => element?.quality_role === "content" && element?.bbox);
  if (!content.length) return metric(false, null, { content_element_count: 0 }, "content_geometry_unavailable");
  const visualPrimary = ["primary_visual", "data_visual"].includes(designContext?.design_ir?.hierarchy?.primary)
    || designContext?.design_ir?.visual_priority === "dominant";
  if (visualPrimary) {
    const visualAreas = content.filter((element) => ["image", "chart", "table"].includes(element.type)).map((element) => boxArea(element.bbox));
    if (!visualAreas.length) return metric(false, null, { visual_primary: true, visual_count: 0 }, "primary_visual_not_observed");
    const total = content.reduce((sum, element) => sum + boxArea(element.bbox), 0);
    const dominance = Math.max(...visualAreas) / Math.max(total, 0.001);
    return metric(true, clamp((dominance - 0.2) / 0.55), { visual_primary: true, dominance_ratio: dominance });
  }
  const fontSizes = content.filter((element) => element.type === "text" && Number.isFinite(element.text?.font_size)).map((element) => element.text.font_size);
  if (fontSizes.length >= 2) {
    const ratio = Math.max(...fontSizes) / Math.max(1, Math.min(...fontSizes));
    return metric(true, clamp((ratio - 1) / 0.8), { font_size_ratio: ratio, font_sizes: fontSizes });
  }
  const areas = content.map((element) => boxArea(element.bbox));
  const dominance = Math.max(...areas) / Math.max(areas.reduce((sum, value) => sum + value, 0), 0.001);
  return metric(true, content.length === 1 ? 1 : clamp((dominance - 0.25) / 0.55), { dominance_ratio: dominance, content_element_count: content.length });
}

function balanceMetric(report) {
  const center = report?.metrics?.visual_center;
  if (!center?.measurable || !Number.isFinite(center.offset)) return metric(false, null, center ?? null, center?.unavailable_reason ?? "visual_center_unavailable");
  return metric(true, 1 - center.offset / 0.25, center);
}

function whitespaceMetric(report, designContext) {
  const union = report?.metrics?.element_union;
  if (!union?.measurable || !Number.isFinite(union.element_area_ratio)) return metric(false, null, union ?? null, union?.unavailable_reason ?? "content_area_unavailable");
  const actualWhitespace = clamp(1 - union.element_area_ratio);
  const target = { low: 0.2, medium: 0.3, medium_high: 0.4, high: 0.5 }[designContext?.design_ir?.whitespace] ?? 0.32;
  return metric(true, 1 - Math.abs(actualWhitespace - target) / 0.5, { actual_whitespace_ratio: actualWhitespace, target_whitespace_ratio: target });
}

function visualFocusMetric(telemetry, hierarchy, designContext) {
  const expectsVisual = ["dominant", "coequal", "supporting"].includes(designContext?.design_ir?.visual_priority);
  const content = asArray(telemetry?.elements).filter((element) => element?.quality_role === "content" && element?.bbox);
  const visualAreas = content.filter((element) => ["image", "chart", "table"].includes(element.type)).map((element) => boxArea(element.bbox));
  if (!expectsVisual && !visualAreas.length) return metric(hierarchy.measurable, hierarchy.value, { fallback: "hierarchy", hierarchy: hierarchy.evidence }, hierarchy.unavailable_reason);
  if (!visualAreas.length) return metric(false, null, { expected_visual_priority: designContext?.design_ir?.visual_priority }, "expected_visual_not_observed");
  const total = content.reduce((sum, element) => sum + boxArea(element.bbox), 0);
  const visualShare = visualAreas.reduce((sum, value) => sum + value, 0) / Math.max(total, 0.001);
  const target = designContext?.design_ir?.visual_priority === "dominant" ? 0.55 : designContext?.design_ir?.visual_priority === "coequal" ? 0.4 : 0.22;
  return metric(true, 1 - Math.abs(visualShare - target) / 0.55, { visual_area_share: visualShare, target_visual_share: target, visual_count: visualAreas.length });
}

function repetitionRatio(history, current, key) {
  const values = asArray(history?.[key]);
  if (!current || !values.length) return null;
  return values.filter((value) => value === current).length / values.length;
}

function decorationVarietyMetric(designContext) {
  const history = designContext?.deck_state_before?.recent_history ?? designContext?.deck_design_state?.recent_history;
  const treatment = designContext?.visual_treatment;
  const decoration = designContext?.decoration_profile;
  if (!history || (!treatment && !decoration?.id)) return metric(false, null, null, "deck_design_history_unavailable");
  const treatmentRepeat = repetitionRatio(history, treatment, "treatments") ?? 0;
  const decorationRepeat = repetitionRatio(history, decoration?.id, "decoration_patterns") ?? 0;
  const containerRepeat = repetitionRatio(history, decoration?.container, "container_families") ?? 0;
  const repetition = treatmentRepeat * 0.4 + decorationRepeat * 0.35 + containerRepeat * 0.25;
  return metric(true, 1 - repetition, { treatment_repeat: treatmentRepeat, decoration_repeat: decorationRepeat, container_repeat: containerRepeat });
}

function diagnosis(code, source, severity, sourceCodes, message) {
  return { code, source, severity, source_codes: [...new Set(sourceCodes)], message };
}

function productionDiagnoses(report, productionStatus) {
  const activeChecks = Object.entries(report?.checks ?? {})
    .filter(([id, check]) => !DESIGN_ONLY_CHECKS.has(id) && check?.disabled !== true && check?.blocking !== false)
    .map(([, check]) => check);
  const codes = [...new Set(activeChecks.filter((check) => check.status !== "pass").map((check) => check?.code).filter(Boolean))];
  const diagnoses = [];
  for (const [group, members] of Object.entries(PRODUCTION_CODE_GROUPS)) {
    const matches = codes.filter((code) => members.includes(code));
    if (matches.length) diagnoses.push(diagnosis(group, "production_qa", group === "RENDER_OR_EVIDENCE_MISMATCH" ? "error" : "warning", matches, `Rendered production QA reported ${matches.join(", ")}.`));
  }
  const known = new Set(Object.values(PRODUCTION_CODE_GROUPS).flat());
  const missing = codes.filter((code) => /NOT_EVALUABLE|TELEMETRY|MISSING|INCOMPLETE/u.test(code));
  if (missing.length || productionStatus === "not_evaluable") {
    diagnoses.push(diagnosis("OBSERVATION_INCOMPLETE", "observer", "warning", missing, "Required rendered facts are incomplete, so automatic repair cannot be selected safely."));
  }
  const otherErrors = activeChecks.filter((check) => check?.status === "fail" && check?.code && !known.has(check.code) && !missing.includes(check.code)).map((check) => check.code);
  if (otherErrors.length) diagnoses.push(diagnosis("GEOMETRY_INVALID", "production_qa", "error", otherErrors, `Production blockers require rebinding or reselection: ${otherErrors.join(", ")}.`));
  return diagnoses;
}

function designDiagnoses(report, metrics, designContext) {
  const diagnoses = [];
  const addLow = (key, code, message, threshold) => {
    const current = metrics[key];
    if (current.measurable && current.value < threshold) diagnoses.push(diagnosis(code, "design_qa", "warning", [], message));
  };
  addLow("hierarchy", "LOW_VISUAL_HIERARCHY", "Rendered hierarchy does not establish a clear primary message.", 0.42);
  addLow("balance", "UNBALANCED_VISUAL_WEIGHT", "Rendered content weight is substantially displaced.", 0.42);
  addLow("whitespace", "LOW_WHITESPACE", "Rendered whitespace does not match the Design IR intent.", 0.38);
  addLow("visual_focus", "LOW_VISUAL_FOCUS", "Rendered visual focus does not match the requested priority.", 0.4);
  addLow("decoration_variety", "LOW_DECK_RHYTHM", "Recent design history repeats the same treatment, decoration, or container language.", 0.34);
  const decoration = designContext?.decoration_profile;
  if (decoration?.container === "card" || Number(designContext?.container_density) > 0.4) {
    diagnoses.push(diagnosis("EXCESSIVE_CARDIFICATION", "design_qa", "warning", [], "The rendered design context exceeds the anti-cardification policy."));
  }
  const history = designContext?.deck_state_before?.recent_history ?? {};
  if (asArray(history.container_families).slice(-2).every((value) => value && value === decoration?.container) && asArray(history.container_families).length >= 2) {
    diagnoses.push(diagnosis("REPEATED_CONTAINER_LANGUAGE", "design_qa", "warning", [], "Three consecutive pages use the same container language."));
  }
  if (asArray(history.treatments).slice(-2).every((value) => value && value === designContext?.visual_treatment) && asArray(history.treatments).length >= 2) {
    diagnoses.push(diagnosis("REPEATED_TREATMENT", "design_qa", "warning", [], "Three consecutive pages use the same visual treatment."));
  }
  const whitespaceChecks = [report?.checks?.element_area_ratio, report?.checks?.largest_horizontal_gap, report?.checks?.largest_vertical_gap].filter((check) => ["warning", "fail"].includes(check?.status));
  if (whitespaceChecks.length && !diagnoses.some((item) => item.code === "LOW_WHITESPACE")) {
    diagnoses.push(diagnosis("LOW_WHITESPACE", "design_qa", "warning", whitespaceChecks.map((check) => check.code).filter(Boolean), "Rendered occupancy or empty bands require a whitespace repair."));
  }
  if (["warning", "fail"].includes(report?.checks?.visual_center?.status) && !diagnoses.some((item) => item.code === "UNBALANCED_VISUAL_WEIGHT")) {
    diagnoses.push(diagnosis("UNBALANCED_VISUAL_WEIGHT", "design_qa", "warning", [report.checks.visual_center.code].filter(Boolean), "Rendered visual center requires rebalancing."));
  }
  return diagnoses;
}

export function productionStatusFromReport(report) {
  const active = Object.entries(report?.checks ?? {})
    .filter(([id, check]) => !DESIGN_ONLY_CHECKS.has(id) && check?.disabled !== true && check?.blocking !== false)
    .map(([, check]) => check);
  if (active.some((check) => check.status === "fail")) return "fail";
  if (active.some((check) => check.status === "warning")) return "warning";
  if (active.length && active.every((check) => check.status === "not_evaluable")) return "not_evaluable";
  if (active.some((check) => check.status === "not_evaluable")) return "warning";
  return "pass";
}

export function observeRenderedSlide(input = {}) {
  const report = input.qa_report;
  const telemetry = input.telemetry;
  if (!report || !telemetry) throw new TypeError("qa_report and telemetry are required");
  const designContext = input.design_context && typeof input.design_context === "object" ? input.design_context : {};
  const hierarchy = hierarchyMetric(telemetry, designContext);
  const metrics = {
    hierarchy,
    balance: balanceMetric(report),
    whitespace: whitespaceMetric(report, designContext),
    visual_focus: visualFocusMetric(telemetry, hierarchy, designContext),
    decoration_variety: decorationVarietyMetric(designContext),
  };
  const productionStatus = productionStatusFromReport(report);
  const diagnoses = [...productionDiagnoses(report, productionStatus), ...designDiagnoses(report, metrics, designContext)];
  const uniqueDiagnoses = [...new Map(diagnoses.map((item) => [item.code, item])).values()];
  const incomplete = uniqueDiagnoses.some((item) => item.code === "OBSERVATION_INCOMPLETE");
  const measurableCount = Object.values(metrics).filter((item) => item.measurable).length;
  const designIssueCount = uniqueDiagnoses.filter((item) => item.source === "design_qa").length;
  const designStatus = incomplete && measurableCount < 3 ? "blocked" : designIssueCount ? "repairable" : "pass";
  return {
    observer_version: VISUAL_OBSERVER_VERSION,
    slide_id: String(telemetry.slide_id ?? report.slide_id ?? "unknown"),
    production_status: productionStatus,
    design_status: designStatus,
    observation_status: incomplete && measurableCount < 3 ? "blocked" : measurableCount < Object.keys(metrics).length ? "partial" : "complete",
    design_metrics: metrics,
    issues: uniqueDiagnoses.map((item) => item.code),
    diagnoses: uniqueDiagnoses,
    recommended_actions: [...new Set(uniqueDiagnoses.map((item) => ACTION_BY_ISSUE[item.code]).filter(Boolean))],
    design_context_used: Object.keys(designContext).length > 0,
    render_artifact: input.render_artifact && typeof input.render_artifact === "object" ? structuredClone(input.render_artifact) : null,
  };
}
