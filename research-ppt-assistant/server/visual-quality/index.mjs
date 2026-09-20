import { assertJsonSchema } from "../schema-validator.mjs";
import { createViolation } from "../content-model.mjs";
import { QA_REPORT_SCHEMA } from "./contracts.mjs";
import { computeElementUnion } from "./metrics/element-union.mjs";
import { computeWhitespace } from "./metrics/whitespace.mjs";
import { computeVisualCenter } from "./metrics/visual-center.mjs";
import { computeSolidContrast } from "./metrics/contrast.mjs";
import { computeOverflow } from "./metrics/overflow.mjs";
import { collectThemeUsage } from "./metrics/theme-usage.mjs";
import { computeTextImageOcclusion } from "./metrics/text-image-occlusion.mjs";
import { computeVisualReadability } from "./metrics/visual-readability.mjs";
import { computeVisualContainerFit } from "./metrics/visual-container-fit.mjs";
import { computeElementRelations } from "./metrics/element-relations.mjs";
import { computeLayoutRegression } from "./metrics/layout-regression.mjs";
import { resolveQualityProfile } from "./profile.mjs";
import { createQaReport } from "./report.mjs";
import { evaluateLegacyReadability } from "./rules/legacy-readability.mjs";
import { evaluateProjectorTypography } from "./rules/projector-typography.mjs";
import { evaluatePresentationIntent } from "./rules/presentation-intent.mjs";
import { evaluateQuality } from "./rules/quality-rules.mjs";
import { evaluateScientificVisualReadability } from "./rules/visual-readability.mjs";
import { evaluateVisualContainerFit } from "./rules/visual-container-fit.mjs";
import { evaluateElementRelations } from "./rules/element-relations.mjs";
import { evaluateLayoutRegression } from "./rules/layout-regression.mjs";
import { normalizeRenderTelemetry } from "./telemetry.mjs";
import { observeRenderedSlide } from "../perceptual-loop/visual-observer.mjs";
import { createRepairPlan } from "../perceptual-loop/repair-controller.mjs";

function metric(measurable, value, evidence, unavailableReason) {
  return {
    measurable,
    value: measurable ? value : null,
    evidence,
    ...(measurable ? {} : { unavailable_reason: unavailableReason ?? "metric_unavailable" }),
  };
}

function geometryUnavailable(telemetry) {
  return telemetry.unavailable.some((item) => {
    if (item.field === "elements") return true;
    const match = item.field.match(/^elements\[(\d+)\]\.bbox$/u);
    return match ? telemetry.elements[Number(match[1])]?.quality_role === "content" : false;
  });
}

function contrastMetric(telemetry) {
  const observations = [];
  for (const element of telemetry.elements) {
    if (element.type !== "text" || element.quality_role !== "content") continue;
    if (Number.isFinite(element.text?.local_contrast_ratio)) {
      observations.push({
        element_id: element.element_id,
        measurable: true,
        contrast_ratio: element.text.local_contrast_ratio,
        foreground_color: element.text.foreground_color,
        background_color: element.background_color ?? element.fill_color ?? null,
      });
      continue;
    }
    if (!element.text?.foreground_color) {
      observations.push({
        element_id: element.element_id,
        measurable: false,
        contrast_ratio: null,
        foreground_color: null,
        background_color: null,
        unavailable_reason: "text_foreground_color_missing",
      });
      continue;
    }
    const background = element.background_color
      ? { kind: "solid", color: element.background_color }
      : telemetry.slide.background;
    observations.push({ element_id: element.element_id, ...computeSolidContrast(element.text.foreground_color, background) });
  }
  const incomplete = observations.find((item) => !item.measurable);
  if (incomplete) return metric(false, null, observations, incomplete.unavailable_reason);
  const measurable = observations.filter((item) => item.measurable);
  if (!measurable.length) {
    const reason = observations.find((item) => item.unavailable_reason)?.unavailable_reason
      ?? "text_or_solid_background_color_missing";
    return metric(false, null, observations, reason);
  }
  return metric(true, Math.min(...measurable.map((item) => item.contrast_ratio)), observations);
}

function centerMetric(center, provided, slide, allowProvided) {
  if (center.measurable) return metric(true, center.offset, center);
  if (allowProvided && Number.isFinite(provided.content_center_x) && Number.isFinite(provided.content_center_y)) {
    const offset = Math.hypot(
      (provided.content_center_x - 0.5) * slide.width,
      (provided.content_center_y - 0.5) * slide.height,
    ) / Math.hypot(slide.width, slide.height);
    return metric(true, offset, {
      source: "provided_renderer_metric",
      normalized_center: { x: provided.content_center_x, y: provided.content_center_y },
    });
  }
  return metric(false, null, center, center.unavailable_reason ?? "visual_center_unavailable");
}

function evaluateRenderEvidenceClosure(telemetry) {
  const evidence = telemetry.render_evidence;
  if (!evidence) return { checks: {}, violations: [] };
  const failures = (evidence.issues ?? []).filter((item) => item.status === "fail");
  const blocked = (evidence.issues ?? []).filter((item) => item.status === "blocked");
  const manual = evidence.manual_review ?? [];
  const status = evidence.status === "fail" ? "fail"
    : evidence.status === "blocked" || evidence.status === "manual_review_required" ? "not_evaluable"
      : "pass";
  const primary = blocked[0] ?? failures[0] ?? manual[0] ?? null;
  const violations = failures.map((item) => createViolation({
    code: item.code,
    field: item.field,
    actual: item.details ?? item.message,
    capacity: "verified builder intent equals renderer fact",
    severity: "error",
    recoverable: true,
    recommended_action: "repair_render_evidence_mismatch",
    message: item.message,
    details: item,
  }));
  return {
    checks: {
      render_evidence_closure: {
        rule_id: "render_evidence_closure",
        metric: "render_evidence_status",
        status,
        actual: evidence.issues?.length ?? 0,
        threshold: { warning: null, fail: 0, triggered: evidence.status === "fail" ? 0 : null },
        code: primary?.code ?? null,
        reason: primary?.message ?? "render_identity_crop_geometry_and_relations_verified",
        recommended_action: evidence.status === "blocked" ? "provide_required_render_evidence"
          : evidence.status === "manual_review_required" ? "complete_manual_visual_review"
            : evidence.status === "fail" ? "repair_render_evidence_mismatch" : "none",
        evidence,
        disabled: false,
        blocking: evidence.status !== "manual_review_required",
        review_required: evidence.status === "manual_review_required",
      },
    },
    violations,
  };
}

export async function evaluateVisualQuality(input = {}) {
  const telemetry = normalizeRenderTelemetry(input.telemetry ?? input);
  const profile = await resolveQualityProfile({
    profile: input.profile,
    profile_id: input.profile_id ?? input.profileId,
    renderer: telemetry.renderer,
  });
  const inputContext = input.context && typeof input.context === "object" ? input.context : {};
  const context = {
    ...inputContext,
    category: inputContext.category ?? input.category ?? telemetry.slide.category,
    layout_id: inputContext.layout_id ?? inputContext.layoutId ?? input.layout_id ?? input.layoutId ?? telemetry.slide.layout_id,
  };
  const contentRectangles = telemetry.elements
    .filter((element) => element.quality_role === "content" && element.bbox)
    .map((element) => element.bbox);
  const missingGeometry = geometryUnavailable(telemetry);
  const union = computeElementUnion(contentRectangles, telemetry.slide);
  const reportedUnion = missingGeometry
    ? {
        measurable: false,
        union_area: null,
        slide_area: union.slide_area,
        element_area_ratio: null,
        rectangle_count: union.rectangle_count,
        unavailable_reason: "element_bbox_telemetry_incomplete",
      }
    : union;
  const whitespace = computeWhitespace(telemetry.elements, telemetry.slide, { include_decoration: false });
  const center = computeVisualCenter(telemetry.elements, telemetry.slide, { include_decoration: false });
  const overflow = computeOverflow(telemetry.elements, telemetry.slide, { include_decoration: false, unavailable: telemetry.unavailable });
  const themeUsage = collectThemeUsage(telemetry.elements, telemetry.theme, { unavailable: telemetry.unavailable });
  const textImageOcclusion = computeTextImageOcclusion(telemetry, context);
  const elementCollectionMissing = telemetry.unavailable.some((item) => item.field === "elements");
  const visualReadability = elementCollectionMissing
    ? { measurable: false, applicable: true, element_count: 0, observations: [], missing_fields: ["elements"], measurement_gaps: [], unavailable_reason: "element_collection_unavailable" }
    : ["1.2.0", "1.3.0", "1.4.0"].includes(telemetry.telemetry_version)
      ? computeVisualReadability(telemetry.elements, telemetry.slide, { unavailable: telemetry.unavailable })
      : { measurable: true, applicable: false, element_count: 0, observations: [], missing_fields: [], measurement_gaps: [] };
  const visualContainerFit = computeVisualContainerFit(telemetry);
  const elementRelations = computeElementRelations(telemetry, { baseline_telemetry: context.baseline_telemetry });
  const layoutRegression = computeLayoutRegression(telemetry, context.baseline_telemetry, { tolerance: context.layout_drift_tolerance ?? 0.08 });
  const provided = telemetry.provided_metrics ?? {};

  const metrics = {
    text_overflow_count: metric(overflow.text_overflow.measurable, overflow.text_overflow.count, overflow.text_overflow, overflow.text_overflow.unavailable_reason),
    out_of_bounds_count: metric(overflow.element_out_of_bounds.measurable, overflow.element_out_of_bounds.count, overflow.element_out_of_bounds, overflow.element_out_of_bounds.unavailable_reason),
    element_area_ratio: metric(reportedUnion.measurable, reportedUnion.element_area_ratio, reportedUnion, reportedUnion.unavailable_reason),
    largest_horizontal_gap_ratio: metric(!missingGeometry && whitespace.measurable, whitespace.horizontal.largest_gap_ratio, whitespace.horizontal, "element_bbox_telemetry_missing"),
    largest_vertical_gap_ratio: metric(!missingGeometry && whitespace.measurable, whitespace.vertical.largest_gap_ratio, whitespace.vertical, "element_bbox_telemetry_missing"),
    visual_center_offset: centerMetric(center, provided, telemetry.slide, context.legacy_compatibility === true),
    theme_usage_violation_count: metric(themeUsage.measurable, themeUsage.violation_count, themeUsage, themeUsage.unavailable_reason),
    minimum_text_contrast_ratio: contrastMetric(telemetry),
    text_image_occlusion: {
      measurable: textImageOcclusion.measurable,
      value: textImageOcclusion.intersection_count,
      evidence: textImageOcclusion,
      ...(textImageOcclusion.measurable ? {} : { unavailable_reason: textImageOcclusion.unavailable_reason }),
    },
  };

  const evaluated = evaluateQuality(metrics, profile);
  const scientificVisual = evaluateScientificVisualReadability(visualReadability, profile, context);
  const visualContainer = visualContainerFit.applicable
    ? evaluateVisualContainerFit(visualContainerFit, profile)
    : { checks: {}, violations: [] };
  const elementRelationResult = evaluateElementRelations(elementRelations);
  const layoutRegressionResult = evaluateLayoutRegression(layoutRegression);
  const renderEvidenceResult = evaluateRenderEvidenceClosure(telemetry);
  const intent = evaluatePresentationIntent(telemetry, input.presentation_intent ?? input.design_ir?.presentation_intent ?? context.presentation_intent);
  Object.assign(renderEvidenceResult.checks, intent.checks);
  renderEvidenceResult.violations.push(...intent.violations);
  const legacy = context.legacy_compatibility === true
    ? evaluateLegacyReadability(telemetry, profile, context)
    : { checks: {}, violations: [] };
  if (context.enforce_typography === true) {
    const typography = evaluateProjectorTypography(telemetry, profile, context);
    Object.assign(legacy.checks, typography.checks);
    for (const violation of typography.violations) {
      if (!legacy.violations.some(v => v.code === violation.code && v.field === violation.field)) {
        legacy.violations.push(violation);
      }
    }
  }
  const reportMetrics = {
    element_union: reportedUnion,
    whitespace,
    visual_center: center,
    overflow,
    theme_usage: themeUsage,
    contrast: metrics.minimum_text_contrast_ratio.evidence,
    text_image_occlusion: textImageOcclusion,
    visual_readability: visualReadability,
    visual_container_fit: visualContainerFit,
    element_relations: elementRelations,
    layout_regression: layoutRegression,
  };
  const baseReport = createQaReport({
    telemetry,
    profile,
    checks: { ...evaluated.checks, ...scientificVisual.checks, ...visualContainer.checks, ...elementRelationResult.checks, ...layoutRegressionResult.checks, ...renderEvidenceResult.checks, ...legacy.checks },
    metrics: reportMetrics,
    violations: [...evaluated.violations, ...scientificVisual.violations, ...visualContainer.violations, ...elementRelationResult.violations, ...layoutRegressionResult.violations, ...renderEvidenceResult.violations, ...legacy.violations],
  });
  const designObservation = observeRenderedSlide({
    qa_report: baseReport,
    telemetry,
    design_context: input.design_context ?? context.design_context,
    render_artifact: input.render_artifact ?? context.render_artifact,
  });
  const repairPlan = createRepairPlan(designObservation, input.repair_context ?? context.repair_context);
  const report = {
    ...baseReport,
    production_status: designObservation.production_status,
    design_status: designObservation.design_status,
    repair_status: repairPlan.status,
    design_observation: designObservation,
    repair_plan: repairPlan,
  };
  assertJsonSchema(QA_REPORT_SCHEMA, report, { toolName: "visual_quality_report" });
  return report;
}

export { RENDER_TELEMETRY_SCHEMA, QUALITY_PROFILE_SCHEMA, QA_REPORT_SCHEMA } from "./contracts.mjs";
export { adaptLegacyRenderedSlide } from "./legacy-adapter.mjs";
export { loadQualityProfile, resolveQualityProfile } from "./profile.mjs";
export { evaluateRule } from "./rules/evaluate-rule.mjs";
export { evaluateQuality } from "./rules/quality-rules.mjs";
