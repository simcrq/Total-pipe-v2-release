import { runVisualFitPreflight } from "./visual-fit/index.mjs";

const FULL_REGION = Object.freeze({ x: 0, y: 0, width: 1, height: 1 });
const DEFAULT_POLICY = Object.freeze({
  epsilon: 0.01,
  padding: 0,
  allow_crop: false,
  max_letterbox_ratio: 0.35,
  minimum_effective_resolution: { width_px: 240, height_px: 160 },
});

const isRecord = (value) => Boolean(value) && typeof value === "object" && !Array.isArray(value);
const finite = (value) => Number.isFinite(Number(value)) ? Number(value) : null;
const round = (value, digits = 6) => Number(Number(value).toFixed(digits));
const asArray = (value) => Array.isArray(value) ? value : [];

function normalizeKey(value) {
  return String(value ?? "").trim().toLowerCase().replace(/^panel[\s_-]*/, "").replace(/[\s_-]+/g, "");
}

function normalizeBox(value, field) {
  if (!isRecord(value)) throw new TypeError(`${field} must be an object`);
  const box = {
    x: finite(value.x),
    y: finite(value.y),
    width: finite(value.width ?? value.w),
    height: finite(value.height ?? value.h),
  };
  if (Object.values(box).some((item) => item === null) || box.width <= 0 || box.height <= 0) {
    throw new RangeError(`${field} requires finite x/y and positive width/height`);
  }
  return Object.fromEntries(Object.entries(box).map(([key, number]) => [key, round(number)]));
}

function normalizeRegion(value, field = "source_region", source = null) {
  const region = normalizeBox(value, field);
  const coordinateSpace = String(value?.coordinate_space ?? value?.coordinateSpace ?? "normalized").trim().toLowerCase();
  if (["pixel", "pixels", "source_pixels", "source-pixels"].includes(coordinateSpace)) {
    const sourceWidth = finite(source?.width ?? source?.source_width_px);
    const sourceHeight = finite(source?.height ?? source?.source_height_px);
    if (!sourceWidth || !sourceHeight) throw new RangeError(`${field} in source-pixel coordinates requires source dimensions`);
    return normalizeRegion({
      x: region.x / sourceWidth,
      y: region.y / sourceHeight,
      width: region.width / sourceWidth,
      height: region.height / sourceHeight,
      coordinate_space: "normalized",
    }, field);
  }
  if (!["normalized", "normalized_0_1", "source_normalized"].includes(coordinateSpace)) {
    throw new RangeError(`${field}.coordinate_space must be normalized or source_pixels`);
  }
  if (region.x < 0 || region.y < 0 || region.x + region.width > 1.000001 || region.y + region.height > 1.000001) {
    throw new RangeError(`${field} must stay inside normalized source coordinates`);
  }
  return region;
}

function within(inner, outer, epsilon = 0) {
  return inner.x >= outer.x - epsilon
    && inner.y >= outer.y - epsilon
    && inner.x + inner.width <= outer.x + outer.width + epsilon
    && inner.y + inner.height <= outer.y + outer.height + epsilon;
}

function overlapArea(left, right) {
  const width = Math.max(0, Math.min(left.x + left.width, right.x + right.width) - Math.max(left.x, right.x));
  const height = Math.max(0, Math.min(left.y + left.height, right.y + right.height) - Math.max(left.y, right.y));
  return width * height;
}

function maximumDeviation(left, right) {
  if (!left || !right) return null;
  return Math.max(...["x", "y", "width", "height"].map((key) => Math.abs(left[key] - right[key])));
}

function check(status, code, reason, recommendedAction, evidence = {}) {
  return { status, code: code ?? null, reason, recommended_action: recommendedAction, evidence };
}

function violationFromCheck(id, item) {
  if (!item.code || item.status === "pass") return undefined;
  return {
    code: item.code,
    field: `checks.${id}`,
    actual: item.evidence,
    capacity: null,
    severity: item.status === "fail" ? "error" : "warning",
    recoverable: true,
    recommended_action: item.recommended_action,
  };
}

export function resolveFigureRegion({ trace_id, visual = {} } = {}) {
  const intent = visual.visual_intent;
  const selection = intent?.selection;
  if (!isRecord(intent) || !isRecord(selection)) {
    return {
      trace_id,
      stage: "region_resolution",
      status: "not_evaluable",
      source_region_candidates: [],
      selected_region: null,
      code: "REGION_RESOLUTION_NOT_EVALUABLE",
      reason: "visual_intent.selection is absent",
    };
  }
  const strategy = String(selection.strategy ?? "auto").toLowerCase();
  if (strategy === "full_figure") {
    return {
      trace_id,
      stage: "region_resolution",
      status: "resolved",
      source_region_candidates: [{ region_id: "full_figure", roi: FULL_REGION, confidence: 1 }],
      selected_region: { region_id: "full_figure", roi: FULL_REGION, confidence: 1 },
      code: null,
      reason: "full figure explicitly requested",
    };
  }
  const rawCandidates = [...asArray(visual.region_candidates)];
  if (isRecord(visual.crop_candidate)) rawCandidates.push({
    region_id: visual.crop_candidate.region_id ?? selection.target ?? "crop_candidate",
    roi: visual.crop_candidate,
    confidence: visual.crop_candidate.confidence,
  });
  if (isRecord(visual.recommended_crop?.roi)) rawCandidates.push({
    region_id: visual.recommended_crop.region_id ?? selection.target ?? visual.recommended_crop.focus ?? "recommended_crop",
    roi: visual.recommended_crop.roi,
    confidence: visual.recommended_crop.confidence,
  });
  const candidates = rawCandidates.map((candidate, index) => ({
    region_id: String(candidate.region_id ?? `candidate_${index + 1}`),
    roi: normalizeRegion(candidate.roi, `visual.region_candidates[${index}].roi`, { width: visual.source_width_px, height: visual.source_height_px }),
    confidence: finite(candidate.confidence),
    aliases: asArray(candidate.aliases).map(String),
  }));
  if (!["panel", "semantic_focus", "multi_panel"].includes(strategy) || !selection.target || !candidates.length) {
    return {
      trace_id,
      stage: "region_resolution",
      status: "not_evaluable",
      source_region_candidates: candidates,
      selected_region: null,
      code: "REGION_RESOLUTION_NOT_EVALUABLE",
      reason: "semantic selection requires a target and region candidates",
    };
  }
  const target = normalizeKey(selection.target);
  const matches = candidates.filter((candidate) => [candidate.region_id, ...candidate.aliases].some((value) => normalizeKey(value) === target));
  if (matches.length > 1) {
    return {
      trace_id,
      stage: "region_resolution",
      status: "ambiguous",
      source_region_candidates: candidates,
      selected_region: null,
      code: "REGION_RESOLUTION_AMBIGUOUS",
      reason: `multiple candidates match ${selection.target}`,
    };
  }
  if (!matches.length) {
    return {
      trace_id,
      stage: "region_resolution",
      status: "failed",
      source_region_candidates: candidates,
      selected_region: null,
      code: "SEMANTIC_REGION_NOT_RESOLVED",
      reason: `no candidate matches ${selection.target}`,
    };
  }
  return {
    trace_id,
    stage: "region_resolution",
    status: "resolved",
    source_region_candidates: candidates,
    selected_region: matches[0],
    code: null,
    reason: `selected ${matches[0].region_id}`,
  };
}

function coverRegion(region, sourceAspect, targetAspect) {
  if (Math.abs(sourceAspect - targetAspect) <= 1e-9) return region;
  if (sourceAspect > targetAspect) {
    const width = region.width * targetAspect / sourceAspect;
    return { ...region, x: region.x + (region.width - width) / 2, width };
  }
  const height = region.height * sourceAspect / targetAspect;
  return { ...region, y: region.y + (region.height - height) / 2, height };
}

export function computeFigurePlacement({ trace_id, visual = {}, source_region, allocated_visual_bbox, policy = {}, exclusion_bboxes = [] } = {}) {
  const sourceWidth = finite(visual.source_width_px);
  const sourceHeight = finite(visual.source_height_px);
  if (!sourceWidth || !sourceHeight) throw new RangeError("visual source_width_px/source_height_px must be positive");
  const region = normalizeRegion(source_region);
  const allocated = normalizeBox(allocated_visual_bbox, "allocated_visual_bbox");
  const mergedPolicy = { ...DEFAULT_POLICY, ...policy };
  const padding = finite(mergedPolicy.padding) ?? 0;
  if (padding < 0 || padding * 2 >= allocated.width || padding * 2 >= allocated.height) throw new RangeError("policy.padding leaves no usable visual area");
  const inner = {
    x: allocated.x + padding,
    y: allocated.y + padding,
    width: allocated.width - padding * 2,
    height: allocated.height - padding * 2,
  };
  const preferred = String(visual.visual_intent?.placement?.preferred_fit ?? "contain").toLowerCase();
  if (!["contain", "cover", "maximize", "auto"].includes(preferred)) throw new RangeError(`unsupported preferred_fit: ${preferred}`);
  const allowCover = mergedPolicy.allow_crop === true && visual.visual_intent?.placement?.allow_cover === true;
  const fitMode = preferred === "cover" || preferred === "maximize" && allowCover ? "cover" : "contain";
  const sourceAspect = sourceWidth * region.width / (sourceHeight * region.height);
  const targetAspect = inner.width / inner.height;
  let finalPlacement;
  let finalRegion = region;
  if (fitMode === "cover") {
    finalPlacement = inner;
    finalRegion = coverRegion(region, sourceAspect, targetAspect);
  } else if (sourceAspect >= targetAspect) {
    const height = inner.width / sourceAspect;
    finalPlacement = { x: inner.x, y: inner.y + (inner.height - height) / 2, width: inner.width, height };
  } else {
    const width = inner.height * sourceAspect;
    finalPlacement = { x: inner.x + (inner.width - width) / 2, y: inner.y, width, height: inner.height };
  }
  finalPlacement = Object.fromEntries(Object.entries(finalPlacement).map(([key, value]) => [key, round(value)]));
  finalRegion = Object.fromEntries(Object.entries(finalRegion).map(([key, value]) => [key, round(value)]));
  const collisions = asArray(exclusion_bboxes)
    .map((box, index) => ({ index, box: normalizeBox(box, `exclusion_bboxes[${index}]`) }))
    .filter(({ box }) => overlapArea(finalPlacement, box) > 1e-9)
    .map(({ index }) => index);
  if (!within(finalPlacement, allocated, mergedPolicy.epsilon)) throw new RangeError("computed placement escapes allocated_visual_bbox");
  return {
    trace_id,
    stage: "placement",
    status: collisions.length ? "failed" : "resolved",
    source_region: finalRegion,
    allocated_visual_bbox: allocated,
    final_placement: finalPlacement,
    fit_mode: fitMode,
    geometry_source: "placement_engine",
    preserve_aspect_ratio: true,
    collisions,
    code: collisions.length ? "PLACEMENT_GEOMETRY_INVALID" : null,
    adaptation_log: [{
      action: fitMode === "cover" ? "apply_deterministic_cover_crop" : "preserve_source_region_and_contain",
      visual_id: visual.id ?? visual.figure_id ?? null,
      reason: preferred,
    }],
  };
}

function rendererAudit(rendererInput, rendererResult, epsilon, source) {
  const effectivePlacement = rendererResult?.effective_placement ? normalizeBox(rendererResult.effective_placement, "renderer_result.effective_placement") : null;
  const effectiveRegion = rendererResult?.effective_source_region
    ? normalizeRegion({
        ...rendererResult.effective_source_region,
        coordinate_space: rendererResult.effective_source_region.coordinate_space
          ?? rendererResult.source_region_coordinate_space
          ?? "normalized",
      }, "renderer_result.effective_source_region", source)
    : null;
  if (!effectivePlacement || !effectiveRegion) {
    return {
      status: "not_evaluable",
      placement_modified: null,
      modification_reason: "renderer effective placement/source region telemetry is incomplete",
      placement_deviation: maximumDeviation(rendererInput.requested_placement, effectivePlacement),
      source_region_deviation: maximumDeviation(rendererInput.requested_source_region, effectiveRegion),
      effective_placement: effectivePlacement,
      effective_source_region: effectiveRegion,
    };
  }
  const placementDeviation = maximumDeviation(rendererInput.requested_placement, effectivePlacement);
  const regionDeviation = maximumDeviation(rendererInput.requested_source_region, effectiveRegion);
  const placementModified = placementDeviation > epsilon || regionDeviation > epsilon;
  return {
    status: placementModified ? "modified" : "preserved",
    placement_modified: placementModified,
    modification_reason: placementModified
      ? placementDeviation > epsilon && regionDeviation > epsilon ? "placement_and_source_region_changed" : placementDeviation > epsilon ? "placement_changed" : "source_region_changed"
      : null,
    placement_deviation: round(placementDeviation),
    source_region_deviation: round(regionDeviation),
    effective_placement: effectivePlacement,
    effective_source_region: effectiveRegion,
  };
}

function deriveDisplayPixels(input, effectivePlacement) {
  const explicit = input.renderer_result?.render_bbox_px;
  if (explicit) return normalizeBox(explicit, "renderer_result.render_bbox_px");
  const slide = input.slide;
  if (!effectivePlacement || !isRecord(slide)) return null;
  const width = finite(slide.width);
  const height = finite(slide.height);
  const renderWidth = finite(slide.render_width_px);
  const renderHeight = finite(slide.render_height_px);
  if (!width || !height || !renderWidth || !renderHeight) return null;
  return {
    x: round(effectivePlacement.x / width * renderWidth),
    y: round(effectivePlacement.y / height * renderHeight),
    width: round(effectivePlacement.width / width * renderWidth),
    height: round(effectivePlacement.height / height * renderHeight),
  };
}

function semanticCheck(input, regionStage, rendererAuditResult) {
  if (regionStage.status !== "resolved") {
    const status = regionStage.status === "not_evaluable" ? "not_evaluable" : "fail";
    return check(status, regionStage.code, regionStage.reason, "resolve_semantic_region", { region_status: regionStage.status });
  }
  const selection = input.visual?.visual_intent?.selection ?? {};
  if (selection.strategy === "full_figure") return check("pass", null, "full figure intent is traceable", "none", { selected_region: "full_figure" });
  if (!rendererAuditResult.effective_source_region) {
    return check("not_evaluable", "IMAGE_PANEL_VISIBILITY_NOT_EVALUABLE", "effective source region telemetry is missing", "provide_required_input");
  }
  const visible = asArray(input.renderer_result?.visible_region_ids).map(normalizeKey);
  const labels = asArray(input.renderer_result?.visible_label_ids).map(normalizeKey);
  const target = normalizeKey(selection.target);
  const expectedExcluded = asArray(input.expectations?.excluded_region_ids).map(normalizeKey);
  const expectedLabels = asArray(input.expectations?.expected_label_ids).map(normalizeKey);
  if (!visible.length || input.visual?.visual_intent?.crop?.preserve_labels === true && !labels.length) {
    return check("not_evaluable", "IMAGE_PANEL_VISIBILITY_NOT_EVALUABLE", "panel or label visibility facts are incomplete", "provide_required_input", { visible_region_ids: visible, visible_label_ids: labels });
  }
  const targetVisible = visible.includes(target);
  const irrelevantVisible = expectedExcluded.filter((item) => visible.includes(item));
  const missingLabels = expectedLabels.filter((item) => !labels.includes(item));
  if (!targetVisible || irrelevantVisible.length || missingLabels.length) {
    const code = missingLabels.length ? "IMAGE_LABEL_CLIPPED" : "IMAGE_FOCUS_LOST";
    return check("fail", code, "rendered semantic focus does not satisfy visual intent", "retry_region_resolution", { target_visible: targetVisible, irrelevant_visible: irrelevantVisible, missing_labels: missingLabels });
  }
  return check("pass", null, "target region and labels remain visible", "none", { target_visible: true, visible_region_ids: visible, visible_label_ids: labels });
}

function aggregateStatus(checks) {
  const statuses = Object.values(checks).map((item) => item.status);
  if (statuses.includes("fail")) return "fail";
  if (statuses.includes("warning")) return "warning";
  if (statuses.every((status) => status === "not_evaluable")) return "not_evaluable";
  if (statuses.includes("not_evaluable")) return "warning";
  return "pass";
}

export function runFigurePlacement(input = {}) {
  const traceId = String(input.trace_id ?? "").trim();
  if (!traceId) throw new TypeError("trace_id is required");
  if (!isRecord(input.visual)) throw new TypeError("visual is required");
  const policy = { ...DEFAULT_POLICY, ...input.policy, minimum_effective_resolution: { ...DEFAULT_POLICY.minimum_effective_resolution, ...input.policy?.minimum_effective_resolution } };
  const modelIntent = {
    trace_id: traceId,
    stage: "model_intent",
    visual_intent: input.visual.visual_intent ?? null,
    recommended_crop: input.visual.recommended_crop ?? null,
    crop_candidate: input.visual.crop_candidate ?? null,
    intent_status: isRecord(input.visual.visual_intent) ? "present" : "absent",
  };
  const regionResolution = resolveFigureRegion({ trace_id: traceId, visual: input.visual });
  let visualFitPreflight = null;
  let visualFitError = null;
  if (regionResolution.status === "resolved" && isRecord(input.visual_container)) {
    try {
      const region = regionResolution.selected_region.roi;
      visualFitPreflight = runVisualFitPreflight({
        visual_id: input.visual.id ?? input.visual.figure_id ?? traceId,
        source: { width: input.visual.source_width_px, height: input.visual.source_height_px },
        source_region: {
          x: input.visual.source_width_px * region.x,
          y: input.visual.source_height_px * region.y,
          width: input.visual.source_width_px * region.width,
          height: input.visual.source_height_px * region.height,
        },
        visual_intent: input.visual.visual_intent,
        visual_container: input.visual_container,
        allocated_visual_bbox: input.allocated_visual_bbox,
        quality_profile: input.quality_profile,
      });
    } catch (error) {
      visualFitError = error;
    }
  }
  const visualFitBlocksPlacement = visualFitError || visualFitPreflight?.status === "fail";
  let placement = null;
  let placementError = null;
  if (regionResolution.status === "resolved" && !visualFitBlocksPlacement) {
    try {
      placement = computeFigurePlacement({
        trace_id: traceId,
        visual: input.visual,
        source_region: regionResolution.selected_region.roi,
        allocated_visual_bbox: input.allocated_visual_bbox,
        policy,
        exclusion_bboxes: input.exclusion_bboxes,
      });
    } catch (error) {
      placementError = error;
    }
  }
  const rendererInput = placement ? {
    trace_id: traceId,
    stage: "renderer_input",
    requested_placement: placement.final_placement,
    requested_source_region: placement.source_region,
    source_region_coordinate_space: "source_normalized_0_1",
    crop_semantics: "source-relative rectangle before contain/cover placement",
    renderer_must_not_override_placement: true,
  } : null;
  const audit = rendererInput ? rendererAudit(
    rendererInput,
    input.renderer_result,
    finite(policy.epsilon) ?? DEFAULT_POLICY.epsilon,
    { width: input.visual.source_width_px, height: input.visual.source_height_px },
  ) : null;
  const rendererEffective = audit ? { trace_id: traceId, stage: "renderer_effective", ...audit } : null;
  const displayPixels = audit ? deriveDisplayPixels(input, audit.effective_placement) : null;
  const allocation = placement?.allocated_visual_bbox;
  const fillRatio = allocation && audit?.effective_placement ? audit.effective_placement.width * audit.effective_placement.height / (allocation.width * allocation.height) : null;
  const letterboxRatio = fillRatio === null ? null : Math.max(0, 1 - Math.min(1, fillRatio));
  const sourceRegion = audit?.effective_source_region;
  const sourceRegionPixels = sourceRegion ? {
    width_px: input.visual.source_width_px * sourceRegion.width,
    height_px: input.visual.source_height_px * sourceRegion.height,
  } : null;
  const effectiveScale = displayPixels && sourceRegionPixels
    ? Math.min(displayPixels.width / sourceRegionPixels.width_px, displayPixels.height / sourceRegionPixels.height_px)
    : null;
  const telemetry = {
    trace_id: traceId,
    telemetry_version: "figure-placement/1.0",
    requested_placement: rendererInput?.requested_placement ?? null,
    effective_placement: audit?.effective_placement ?? null,
    requested_source_region: rendererInput?.requested_source_region ?? null,
    effective_source_region: audit?.effective_source_region ?? null,
    source_region_coordinate_space: "source_normalized_0_1",
    allocated_visual_bbox: allocation ?? null,
    display_bbox_px: displayPixels,
    metrics: {
      visual_fill_ratio: fillRatio === null ? null : round(fillRatio),
      letterbox_ratio: letterboxRatio === null ? null : round(letterboxRatio),
      source_crop_area_ratio: sourceRegion ? round(sourceRegion.width * sourceRegion.height) : null,
      effective_display_scale: effectiveScale === null ? null : round(effectiveScale),
      effective_image_resolution: displayPixels ? { width_px: round(displayPixels.width), height_px: round(displayPixels.height) } : null,
      panel_visibility: input.renderer_result?.visible_region_ids ?? null,
      label_visibility: input.renderer_result?.visible_label_ids ?? null,
      visual_fit: visualFitPreflight?.metrics ?? null,
    },
    unavailable: [],
  };
  for (const [field, value] of Object.entries({
    "effective_placement": telemetry.effective_placement,
    "effective_source_region": telemetry.effective_source_region,
    "metrics.visual_fill_ratio": telemetry.metrics.visual_fill_ratio,
    "metrics.letterbox_ratio": telemetry.metrics.letterbox_ratio,
    "metrics.effective_display_scale": telemetry.metrics.effective_display_scale,
    "metrics.effective_image_resolution": telemetry.metrics.effective_image_resolution,
  })) if (value === null) telemetry.unavailable.push({ field, reason: "required renderer fact is unavailable" });
  const semanticSelection = input.visual?.visual_intent?.selection?.strategy !== "full_figure";
  if (semanticSelection && !Array.isArray(telemetry.metrics.panel_visibility)) {
    telemetry.unavailable.push({ field: "metrics.panel_visibility", reason: "renderer did not report actually visible semantic regions" });
  }
  if (semanticSelection && input.visual?.visual_intent?.crop?.preserve_labels === true && !Array.isArray(telemetry.metrics.label_visibility)) {
    telemetry.unavailable.push({ field: "metrics.label_visibility", reason: "renderer did not report actually visible labels" });
  }

  const checks = {};
  if (visualFitError) {
    checks.visual_fit_preflight = check("fail", "VISUAL_FIT_PREFLIGHT_INVALID", visualFitError.message, "correct_visual_fit_input");
  } else if (visualFitPreflight) {
    checks.visual_fit_preflight = check(
      visualFitPreflight.status,
      visualFitPreflight.issue?.code ?? null,
      visualFitPreflight.reason,
      visualFitPreflight.recommended_action,
      visualFitPreflight.metrics,
    );
  }
  if (visualFitBlocksPlacement) {
    checks.placement_geometry = check("not_evaluable", "VISUAL_SLOT_FIT_INCOMPATIBLE", "placement skipped because Visual Fit Preflight blocked the layout candidate", visualFitPreflight?.recommended_action ?? "correct_visual_fit_input");
  } else if (placementError || placement?.status === "failed" || !placement) {
    checks.placement_geometry = check("fail", placement?.code ?? "PLACEMENT_INPUT_INVALID", placementError?.message ?? regionResolution.reason, "correct_placement_input");
  } else {
    checks.placement_geometry = check("pass", null, "placement is bounded, aspect-preserving, and collision-free", "none", { geometry_source: placement.geometry_source });
  }
  if (!audit || !audit.effective_placement) {
    checks.renderer_placement = check("not_evaluable", "IMAGE_PLACEMENT_NOT_EVALUABLE", "requested/effective renderer facts are incomplete", "provide_required_input", audit ?? {});
  } else if (audit.placement_deviation > policy.epsilon) {
    checks.renderer_placement = check("fail", "RENDERER_PLACEMENT_OVERRIDE", "renderer changed final placement", "fix_renderer_adapter", audit);
  } else {
    checks.renderer_placement = check("pass", null, "renderer preserved requested placement", "none", audit);
  }
  if (!audit || !audit.effective_source_region) {
    checks.renderer_source_region = check("not_evaluable", "IMAGE_PANEL_VISIBILITY_NOT_EVALUABLE", "requested/effective source-region facts are incomplete", "provide_required_input", audit ?? {});
  } else if (audit.source_region_deviation > policy.epsilon) {
    checks.renderer_source_region = check("fail", "RENDERER_SOURCE_REGION_OVERRIDE", "renderer changed selected source region", "fix_renderer_adapter", audit);
  } else {
    checks.renderer_source_region = check("pass", null, "renderer preserved requested source region", "none", audit);
  }
  checks.semantic_region = semanticCheck(input, regionResolution, audit ?? {});
  if (letterboxRatio === null) {
    checks.letterbox = check("not_evaluable", "IMAGE_PLACEMENT_NOT_EVALUABLE", "letterbox ratio requires effective and allocated geometry", "provide_required_input");
  } else if (letterboxRatio > policy.max_letterbox_ratio) {
    checks.letterbox = check("fail", "IMAGE_UNDERFILLED_SLOT", "contain placement leaves excessive unused visual area", "reconsider_visual_placement", { actual: round(letterboxRatio), maximum: policy.max_letterbox_ratio });
  } else {
    checks.letterbox = check("pass", null, "letterbox ratio is within policy", "none", { actual: round(letterboxRatio), maximum: policy.max_letterbox_ratio });
  }
  const minimum = policy.minimum_effective_resolution;
  if (!displayPixels) {
    checks.effective_resolution = check("not_evaluable", "IMAGE_EFFECTIVE_RESOLUTION_LOW", "effective resolution requires rendered pixel geometry", "provide_required_input");
  } else if (displayPixels.width < minimum.width_px || displayPixels.height < minimum.height_px) {
    checks.effective_resolution = check("fail", "IMAGE_EFFECTIVE_RESOLUTION_LOW", "rendered figure resolution is below policy", "reconsider_visual_placement", { actual: { width_px: round(displayPixels.width), height_px: round(displayPixels.height) }, minimum });
  } else {
    checks.effective_resolution = check("pass", null, "effective resolution is within policy", "none", { actual: { width_px: round(displayPixels.width), height_px: round(displayPixels.height) }, minimum });
  }
  if (telemetry.unavailable.length) {
    checks.telemetry_completeness = check("not_evaluable", "TELEMETRY_INCOMPLETE", "required figure-placement telemetry is incomplete", "provide_required_input", { unavailable: telemetry.unavailable });
  } else {
    checks.telemetry_completeness = check("pass", null, "required figure-placement telemetry is complete", "none");
  }
  const status = aggregateStatus(checks);
  const violations = Object.entries(checks).map(([id, item]) => violationFromCheck(id, item)).filter(Boolean);
  const blocking = Object.values(checks).find((item) => item.status === "fail")
    ?? Object.values(checks).find((item) => item.status === "warning")
    ?? Object.values(checks).find((item) => item.status === "not_evaluable");
  const qaReport = {
    trace_id: traceId,
    stage: "visual_qa",
    status,
    checks,
    violations,
    recommended_action: blocking?.recommended_action ?? "none",
  };
  return {
    pipeline_status: "figure_placement_complete",
    status,
    trace_id: traceId,
    stages: { model_intent: modelIntent, region_resolution: regionResolution, visual_fit_preflight: visualFitPreflight, placement, renderer_input: rendererInput, renderer_effective: rendererEffective, visual_qa: qaReport },
    metrics: telemetry.metrics,
    artifacts: {
      "model_intent.json": modelIntent,
      "planner_output.json": { trace_id: traceId, allocated_visual_bbox: input.allocated_visual_bbox ?? null, exclusion_bboxes: input.exclusion_bboxes ?? [] },
      "placement_output.json": placement,
      "renderer_input.json": rendererInput,
      "pptx_geometry.json": input.renderer_result ?? null,
      "canonical_telemetry.json": telemetry,
      "qa_report.json": qaReport,
      ...(visualFitPreflight ? { "visual_fit_preflight.json": visualFitPreflight } : {}),
    },
  };
}
