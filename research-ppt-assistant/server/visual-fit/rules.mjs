import { boxContainsWithin, CONTAINER_GEOMETRY_EPSILON } from "./metrics.mjs";

const COMPOSITE_ROLES = new Set(["image_caption", "image_annotation", "workflow_region", "comparison_region", "decorative_exhibit"]);

/** 未受管辖（非 scientific_figure）visual 的宽松几何下限默认值。 */
const DEFAULT_UNGOVERNED_RULES = {
  minimum_area_fill_warning: 0.4,
  aspect_mismatch_warning: 2.2,
};

function ungovernedRules(profile) {
  return { ...DEFAULT_UNGOVERNED_RULES, ...(profile?.ungoverned_visual_types ?? {}) };
}

/**
 * status 只表达"结论"，governance 表达"这个结论是不是真的被几何校验过"。
 * - governed:     受 scientific_figure profile 管辖，且几何已被正式校验
 * - not_governed: 不在管辖清单内，只跑宽松几何下限；status=pass 表示"未发现问题"而非"质量合格"
 * - skipped:      命中白名单豁免（intentional whitespace / reserved / composite role / 规则不适用）
 */
function statusResult(status, reason, recommendedAction, decision, governance = "governed") {
  return {
    status,
    reason,
    recommended_action: recommendedAction,
    decision,
    governance,
    geometry_checked: governance === "governed",
  };
}

/**
 * RPA-2: 对不受 scientific_figure profile 管辖的 visual（如 schematic / 流程示意图）
 * 仍然跑一道宽松的几何下限校验，避免"15% 填充率也判 pass"的虚假安全感。
 * 未触发下限时，status 仍为 pass，但 governance=not_governed + geometry_checked=false，
 * 下游不应把它读成"质量已校验合格"。
 */
function evaluateUngovernedVisual(metrics, contract, profile) {
  const rules = ungovernedRules(profile);
  const notGoverned = (reason, recommendedAction) => statusResult(
    "pass",
    reason,
    recommendedAction,
    "proceed",
    "not_governed",
  );
  const fill = metrics?.visual_fill;
  if (!fill || !Number.isFinite(fill.area_ratio)) {
    return notGoverned("visual_type_not_governed_by_scientific_figure_profile", "none");
  }
  if (contract.whitespace_policy === "intentional") {
    return notGoverned("visual_type_not_governed_and_whitespace_declared_intentional", "allow_whitespace");
  }
  if (fill.area_ratio < rules.minimum_area_fill_warning) {
    return {
      ...statusResult("warning", "ungoverned_visual_type_underfills_slot", "resize_container_or_choose_matching_layout", "review", "not_governed"),
      geometry_checked: true,
    };
  }
  if (Number.isFinite(metrics.aspect_mismatch_factor) && metrics.aspect_mismatch_factor >= rules.aspect_mismatch_warning) {
    return {
      ...statusResult("warning", "ungoverned_visual_type_aspect_ratio_mismatch", "resize_container_or_choose_matching_layout", "review", "not_governed"),
      geometry_checked: true,
    };
  }
  return notGoverned("visual_type_not_governed_by_scientific_figure_profile", "none");
}

/**
 * 失配严重性的两种判定策略。
 *
 * - ASPECT_ONLY（默认，单图预检）：以配置的 `aspect_mismatch_fail` 为主判据。
 * - ASPECT_AND_FILL（组内子图仲裁）：要求宽高比失配超阈「且」单轴填充跌破
 *   `minimum_axis_fill_fail` 才判 fail。
 *
 * 为什么需要区分：contain 拟合下 min(width_ratio, height_ratio) 恒等于
 * 1 / aspect_mismatch_factor，两者本是同一个量，旧实现用 AND 把失配阈值
 * 悄悄改写成 1/0.35≈2.857，使 `aspect_mismatch_fail` 完全失效（P05 实测失配 2.753
 * 只判 warning，被"每张图不得 fail"的流水线放行）。
 * 但组内子图是**可仲裁**的：失配应当由 group-fit 用非对称候选化解（它另有自己的
 * `minimum_child_fill_fail` 判据），只有在失去配又近乎填满不了槽位时才算无法恢复。
 * 因此单图预检收紧到 `aspect_mismatch_fail`，而组内子图保留联合条件。
 */
export const ASPECT_FAIL_POLICY = Object.freeze({
  ASPECT_ONLY: "aspect_only",
  ASPECT_AND_FILL: "aspect_and_fill",
});

export function evaluateVisualFit(metrics, contract, profile, policy = ASPECT_FAIL_POLICY.ASPECT_ONLY) {
  const rule = profile?.scientific_figure;
  if (!rule) throw new TypeError("visual fit profile requires scientific_figure thresholds");
  const visualTypes = new Set(rule.visual_types ?? ["scientific_figure"]);
  if (!visualTypes.has(contract.visual_type)) {
    return evaluateUngovernedVisual(metrics, contract, profile);
  }
  if (contract.whitespace_policy === "intentional") {
    return statusResult("pass", "intentional_whitespace_allows_underfill", "allow_whitespace", "proceed", "skipped");
  }
  if (contract.whitespace_policy === "reserved" || COMPOSITE_ROLES.has(contract.container_role)) {
    return statusResult("pass", "container_reserves_space_for_non_image_content", "none", "proceed", "skipped");
  }
  if (contract.fit_policy === "cover" && contract.crop_policy === "full_figure") {
    return statusResult("fail", "full_figure_contract_forbids_cover_crop", "change_fit_policy", "needs_replan", "governed");
  }
  if (contract.fit_policy !== "contain" || contract.container_role !== "image_only" || contract.whitespace_policy !== "minimal") {
    return statusResult("pass", "scientific_figure_minimal_image_only_rule_not_applicable", "none", "proceed", "skipped");
  }
  const minimumFill = Math.min(metrics.visual_fill.width_ratio, metrics.visual_fill.height_ratio);
  const aspectBeyondFail = metrics.aspect_mismatch_factor > rule.aspect_mismatch_fail;
  const severe = policy === ASPECT_FAIL_POLICY.ASPECT_AND_FILL
    ? aspectBeyondFail && minimumFill < rule.minimum_axis_fill_fail
    : aspectBeyondFail || minimumFill < rule.minimum_axis_fill_fail;
  if (severe) {
    if (contract.crop_policy === "semantic_crop_allowed" || contract.semantic_crop_allowed === true) {
      return statusResult("fail", "aspect_ratio_mismatch", "resolve_region", "needs_region_resolution", "governed");
    }
    return statusResult("fail", "aspect_ratio_mismatch", contract.mismatch_policy ?? "replan", "needs_replan", "governed");
  }
  const warning = metrics.aspect_mismatch_factor >= rule.aspect_mismatch_warning
    || minimumFill < rule.minimum_axis_fill_warning;
  if (warning) return statusResult("warning", "visual_slot_fit_requires_inspection", "resize_container", "review");
  return statusResult("pass", "visual_slot_fit_within_profile", "none", "proceed");
}

export function evaluateContainerChildFit(metrics, contract, profile) {
  if (!boxContainsWithin(metrics.content_bbox, metrics.child_display_bbox, CONTAINER_GEOMETRY_EPSILON)) {
    return statusResult("fail", "effective_child_outside_content_bbox", "fix_renderer_adapter", "review");
  }
  // 组内子图走联合条件：失配应由 group-fit 的非对称候选化解，不当成结构性不合格。
  const result = evaluateVisualFit(metrics, contract, profile, ASPECT_FAIL_POLICY.ASPECT_AND_FILL);
  if (result.status === "fail") {
    return { ...result, reason: "effective_child_does_not_satisfy_visual_container_contract", recommended_action: contract.mismatch_policy ?? result.recommended_action };
  }
  const tolerance = profile.scientific_figure.gap_symmetry_tolerance;
  if (result.status === "pass" && contract.fit_policy === "contain"
      && contract.container_role === "image_only" && contract.whitespace_policy === "minimal"
      && (metrics.gaps.gap_symmetry.horizontal_delta_ratio > tolerance
        || metrics.gaps.gap_symmetry.vertical_delta_ratio > tolerance)) {
    return statusResult("warning", "effective_contain_placement_is_asymmetric", "fix_renderer_adapter", "review");
  }
  return result;
}
