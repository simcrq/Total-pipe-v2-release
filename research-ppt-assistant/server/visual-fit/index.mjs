import { createViolation } from "../content-model.mjs";
import { computeVisualFitMetrics } from "./metrics.mjs";
import { resolveVisualFitProfile } from "./profile.mjs";
import { ASPECT_FAIL_POLICY, evaluateVisualFit } from "./rules.mjs";

export const VISUAL_FIT_VERSION = "1.0.0";

function normalizeIntent(input) {
  const intent = input.visual_intent ?? input.intent ?? {};
  const container = input.visual_container ?? {};
  const legacySelection = intent.selection?.strategy;
  const cropPolicy = intent.crop_policy
    ?? (legacySelection === "full_figure" ? "full_figure" : legacySelection ? "fixed_region" : "full_figure");
  return {
    visual_type: String(intent.visual_type ?? input.visual_type ?? "scientific_figure"),
    crop_policy: String(cropPolicy),
    fit_policy: String(intent.fit_policy ?? intent.placement?.preferred_fit ?? container.fit_policy ?? "contain"),
    semantic_crop_allowed: intent.semantic_crop_allowed === true || cropPolicy === "semantic_crop_allowed",
    whitespace_policy: String(intent.whitespace_policy ?? container.whitespace_policy ?? "minimal"),
    priority: String(intent.priority ?? "primary_visual"),
    container_role: String(container.role ?? input.container_role ?? "image_only"),
    mismatch_policy: String(container.mismatch_policy ?? input.mismatch_policy ?? "replan"),
    visual_container: {
      container_id: container.container_id ?? null,
      outer_bbox: container.outer_bbox ?? null,
      content_bbox: container.content_bbox ?? null,
      content_inset: container.content_inset ?? null,
      child_visual_ids: container.child_visual_ids ?? [],
    },
  };
}

function boxesMatch(left, right, epsilon = 1e-6) {
  return ["x", "y", "width", "height"].every((key) => Math.abs(Number(left[key]) - Number(right[key])) <= epsilon);
}

export function runVisualFitPreflight(input = {}) {
  const visualId = String(input.visual_id ?? input.id ?? "").trim();
  if (!visualId) throw new TypeError("visual_id is required");
  const contract = normalizeIntent(input);
  const metrics = computeVisualFitMetrics({
    source: input.source,
    source_region: input.source_region,
    allocated_visual_bbox: input.allocated_visual_bbox,
    fit_policy: contract.fit_policy,
  });
  if (contract.visual_container.content_bbox
      && !boxesMatch(contract.visual_container.content_bbox, metrics.allocated_bbox)) {
    throw new RangeError("visual_container.content_bbox must equal the inner allocated_visual_bbox used for preflight");
  }
  const profile = resolveVisualFitProfile(input.quality_profile);
  const evaluated = evaluateVisualFit(metrics, contract, profile, input.aspect_fail_policy ?? ASPECT_FAIL_POLICY.ASPECT_ONLY);
  const issue = evaluated.status === "pass" ? null : createViolation({
    code: "VISUAL_SLOT_FIT_INCOMPATIBLE",
    field: "visual_fit",
    actual: {
      source_aspect_ratio: metrics.source_aspect_ratio,
      slot_aspect_ratio: metrics.allocated_aspect_ratio,
      aspect_mismatch_factor: metrics.aspect_mismatch_factor,
      predicted_width_fill_ratio: metrics.visual_fill.width_ratio,
      predicted_height_fill_ratio: metrics.visual_fill.height_ratio,
      predicted_area_fill_ratio: metrics.visual_fill.area_ratio,
    },
    capacity: profile.scientific_figure,
    severity: evaluated.status === "fail" ? "error" : "warning",
    recoverable: true,
    recommended_action: evaluated.recommended_action,
    message: evaluated.reason,
    details: {
      visual_id: visualId,
      decision: evaluated.decision,
      governance: evaluated.governance,
      geometry_checked: evaluated.geometry_checked,
      contract,
    },
  });
  return {
    pipeline_status: "visual_fit_preflight_complete",
    status: evaluated.status,
    decision: evaluated.decision,
    // RPA-2: governed=已按 scientific_figure 校验；not_governed=不在管辖清单、只跑宽松下限
    // （pass 仅代表"未发现问题"，不代表质量已校验合格）；skipped=命中白名单豁免。
    governance: evaluated.governance,
    geometry_checked: evaluated.geometry_checked,
    verified: evaluated.governance === "governed" || evaluated.geometry_checked === true,
    visual_id: visualId,
    contract,
    metrics,
    issue,
    issues: issue ? [issue] : [],
    recommended_action: evaluated.recommended_action,
    reason: evaluated.reason,
  };
}

export { boxContainsWithin, computeContainerChildMetrics, computeVisualFitMetrics, CONTAINER_GEOMETRY_EPSILON } from "./metrics.mjs";
export { resolveVisualFitProfile } from "./profile.mjs";
export { ASPECT_FAIL_POLICY, evaluateContainerChildFit, evaluateVisualFit } from "./rules.mjs";
