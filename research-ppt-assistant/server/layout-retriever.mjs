import { createViolation } from "./content-model.mjs";
import {
  analyzeVisualPlacements,
  defaultPlanningThresholds,
  layoutReadability,
  requiredVisualWidth,
  resolvePlanningThresholds,
} from "./visual-quality/legacy-planning.mjs";

export const DEFAULT_WEIGHTS = {
  text_fit: 0.14,
  image_fit: 0.14,
  table_fit: 0.11,
  visual_area_fit: 0.08,
  aspect_ratio_fit: 0.06,
  role_fit: 0.06,
  density_prior: 0.04,
  genericity_prior: 0.05,
  silhouette_fit: 0.08,
  process_fit: 0.10,
  visual_material_fit: 0.10,
  // RPA-1: 源图与图槽的几何契合度（contain 面积填充率）。默认权重足以压过
  // 类别先验等弱因子，避免"把 1:1 方图塞进 7:1 扁槽"这类几何错配胜出。
  visual_geometry_score: 0.10,
  readability_margin_fit: 0.08,
  support_space_fit: 0.05,
};

const layoutSlots = (layout) => layout.slot_specs ?? layout.slots ?? [];

const percent = (value) => `${Math.round(value * 100)}%`;

function slotId(slot) {
  return String(slot?.id ?? slot?.slot_id ?? "").trim();
}

function slotType(slot) {
  const raw = slot?.type ?? slot?.slot_type;
  if (raw === "image") return "figure";
  return raw;
}

function slotBox(slot) {
  const box = slot?.box ?? slot?.normalized_box ?? slot?.normalizedBox;
  if (!box) return null;
  const width = Number(box.width ?? box.w);
  const height = Number(box.height ?? box.h);
  return width > 0 && height > 0 ? { x: Number(box.x ?? 0), y: Number(box.y ?? 0), width, height } : null;
}

function visualSlots(layout) {
  return layoutSlots(layout).filter((slot) => ["figure", "chart"].includes(slotType(slot)) && slotBox(slot));
}

function visualSlotAspect(slot) {
  const box = slotBox(slot);
  return box ? (box.width * 16 / 9) / box.height : null;
}

function containAreaFit(sourceAspect, targetAspect) {
  if (!(sourceAspect > 0) || !(targetAspect > 0)) return 0.85;
  return Math.min(sourceAspect / targetAspect, targetAspect / sourceAspect);
}

/**
 * 落在「严重线 ≤ 实际宽度 < 要求宽度」区间的视觉槽：几何上偏窄、需要降权，
 * 但不足以像 VISUAL_SLOT_CAPACITY_EXCEEDED 那样把整个版面踢出候选池。
 */
function scoreVisualWidthShortfalls(layout, input, thresholds = defaultPlanningThresholds()) {
  return analyzeVisualPlacements(layout, input, thresholds).filter((placement) => (
    placement.slot_id
    && placement.required_width > 0
    && placement.display_width < placement.required_width
    && placement.display_width >= placement.severe_width_floor
  ));
}

function scoreVisualMaterials(layout, input, thresholds = defaultPlanningThresholds()) {
  const visuals = (input.visuals ?? []).filter((visual) => visual.aspectRatio > 0 || visual.panelCount > 1 || visual.hasEmbeddedText);
  const slots = visualSlots(layout);
  if (!visuals.length || !slots.length) return { fit: 0.85, margin: 0.85, assignments: [], geometry: null };
  const remaining = [...slots];
  const assignments = [];
  for (const visual of visuals) {
    let bestIndex = -1;
    let best = null;
    for (const [index, slot] of remaining.entries()) {
      const targetAspect = visualSlotAspect(slot);
      const areaFit = containAreaFit(visual.aspectRatio, targetAspect);
      const aspectFit = visual.aspectRatio ? gaussianAspectFit(visual.aspectRatio, targetAspect, 0.45) : 0.85;
      const box = slotBox(slot);
      const safety = input.visualSafetyMargin ?? 0.10;
      const requiredWidth = Math.min(1, requiredVisualWidth(visual, thresholds) * (1 + safety));
      const widthMargin = requiredWidth > 0 ? Math.min(1, box.width / requiredWidth) : 1;
      const embeddedFloor = thresholds.embedded_visual_evidence_width;
      const panelPenalty = visual.panelCount >= 6 && box.width < 0.5 ? 0.72 : visual.panelCount >= 4 && box.width < 0.42 ? 0.84 : 1;
      const textPenalty = visual.hasEmbeddedText && box.width < embeddedFloor
        ? Math.max(0.55, box.width / embeddedFloor)
        : visual.embeddedTextDensity > 0.55 && box.width < 0.5 ? 0.82 : 1;
      const score = (aspectFit * 0.45 + areaFit * 0.55) * widthMargin * panelPenalty * textPenalty;
      if (!best || score > best.score) best = { slot, score, aspectFit, areaFit, widthMargin, targetAspect };
      if (!best || best.slot === slot) bestIndex = index;
    }
    if (best) {
      assignments.push({
        visual_id: visual.visual_id ?? visual.sourceVisualId ?? null,
        slot_id: slotId(best.slot),
        source_aspect_ratio: visual.aspectRatio ?? null,
        slot_aspect_ratio: best.targetAspect,
        contain_area_fill: best.areaFit,
        safety_margin_fit: best.widthMargin,
        slot_x: slotBox(best.slot).x,
        score: best.score,
      });
      remaining.splice(bestIndex, 1);
    }
  }
  if (!assignments.length) return { fit: 0.85, margin: 0.85, assignments: [], geometry: null };
  const orderPreserved = assignments.every((item, index) => index === 0 || assignments[index - 1].slot_x <= item.slot_x);
  const fillValues = assignments.map((item) => item.contain_area_fill);
  return {
    fit: assignments.reduce((sum, item) => sum + item.score, 0) / assignments.length * (orderPreserved ? 1 : 0.94),
    margin: Math.min(...assignments.map((item) => item.safety_margin_fit)),
    // RPA-1: 纯几何量——每个 visual 在其分配槽位里的 contain 面积填充率。
    geometry: {
      mean_contain_fill: fillValues.reduce((sum, value) => sum + value, 0) / fillValues.length,
      worst_contain_fill: Math.min(...fillValues),
      source_aspect_ratio: assignments[0].source_aspect_ratio ?? null,
      slot_aspect_ratio: assignments[0].slot_aspect_ratio ?? null,
    },
    assignments,
  };
}

const GENERICITY = {
  single_figure: 1,
  figure_text: 0.98,
  dual_figure: 1,
  triple_figure: 0.94,
  four_panel: 0.90,
  table: 1,
  table_chart: 0.90,
  chart_takeaway: 0.92,
  chart_compare: 0.88,
  qualitative: 0.82,
  background: 0.72,
  case: 0.72,
  failure: 0.68,
  error: 0.70,
  dataset: 0.74,
  architecture: 0.68,
  method_overview: 0.68,
  experiment: 0.74,
  ablation: 0.78,
  baseline: 0.76,
  weekly: 0.66,
  qa: 0.58,
  references: 0.62,
  appendix: 0.62,
  cover: 0.50,
  section: 0.50,
};

function gaussianAspectFit(actual, target, sigma = 0.55) {
  if (actual <= 0 || target <= 0) return 0;
  const z = Math.log(actual / target) / sigma;
  return Math.exp(-0.5 * z * z);
}

function countFit(required, capacity) {
  if (required === 0) return capacity === 0 ? 1 : Math.max(0.35, 1 - 0.12 * capacity);
  if (capacity < required) return Math.max(0, 1 - 0.62 * (required - capacity));
  return Math.max(0.55, 1 - 0.10 * (capacity - required));
}

function textFit(chars, maximum) {
  if (chars <= 0) return 1;
  if (maximum <= 0) return 0;
  const ratio = chars / maximum;
  if (ratio <= 0.22) return 0.82;
  if (ratio <= 0.78) return 1;
  if (ratio <= 1) return 1 - 0.12 * ((ratio - 0.78) / 0.22);
  return Math.max(0, 0.88 - 1.35 * (ratio - 1));
}

function inferredDensity(input) {
  if (input.densityPreference && ["低", "中", "高"].includes(input.densityPreference)) return input.densityPreference;
  const visualCount = input.imageCount + input.tableCount + input.chartCount;
  if (input.textChars < 90 && visualCount <= 1) return "低";
  if (input.textChars > 260 || visualCount >= 4) return "高";
  return "中";
}

function silhouetteFit(layout, input) {
  if (input.tableCount > 0 && input.chartCount > 0) return ["table_chart", "ablation", "baseline", "experiment"].includes(layout.category) ? 1 : 0.58;
  if (input.tableCount > 0) return ["table", "experiment", "ablation", "baseline"].includes(layout.category) ? 1 : 0.62;
  if (input.chartCount >= 3) return layout.category === "chart_compare" ? 1 : 0.55;
  if (input.chartCount === 1) return ["chart_takeaway", "metrics", "single_figure"].includes(layout.category) ? 1 : 0.66;
  if (input.imageCount === 1) return ["single_figure", "figure_text", "case", "failure", "background"].includes(layout.category) ? 1 : 0.72;
  if (input.imageCount === 2) return layout.category === "dual_figure" ? 1 : ["method_overview", "architecture"].includes(layout.category) ? 0.82 : 0.54;
  if (input.imageCount === 3) return ["triple_figure", "error"].includes(layout.category) ? 1 : 0.55;
  if (input.imageCount >= 4) return ["four_panel", "qualitative", "dataset"].includes(layout.category) ? 1 : 0.52;
  return 0.85;
}

export function scoreLayout(layout, input) {
  const thresholds = defaultPlanningThresholds();
  const weights = { ...DEFAULT_WEIGHTS, ...(input.weights ?? {}) };
  const profile = layout.content_profile ?? {};
  const imageCapacity = profile.image_capacity ?? 0;
  const tableCapacity = profile.table_capacity ?? 0;
  const components = {};

  components.text_fit = textFit(input.textChars, layout.max_text_chars ?? 0);
  components.image_fit = countFit(input.imageCount, imageCapacity);
  components.table_fit = countFit(input.tableCount, tableCapacity);

  const requiredArea = Math.min(
    0.72,
    (input.imageCount ? 0.30 + 0.07 * Math.max(0, input.imageCount - 1) : 0)
      + (input.tableCount ? 0.32 : 0)
      + 0.05 * Math.max(0, input.tableCount - 1),
  );
  const availableArea = profile.media_area_capacity ?? profile.visual_area_capacity ?? 0;
  if (input.imageCount + input.tableCount === 0) {
    components.visual_area_fit = availableArea < 0.12 ? 1 : Math.max(0.4, 1 - availableArea * 0.65);
  } else if (availableArea <= 0) {
    components.visual_area_fit = 0;
  } else {
    components.visual_area_fit = Math.max(0, 1 - Math.max(0, requiredArea - availableArea) * 2.4);
  }

  components.aspect_ratio_fit = input.visualAspectRatio && layout.preferred_visual_aspect_ratio
    ? gaussianAspectFit(input.visualAspectRatio, layout.preferred_visual_aspect_ratio)
    : 0.85;

  if (input.contentRoles?.length) {
    const supported = new Set(layout.content_roles ?? []);
    components.role_fit = input.contentRoles.filter((role) => supported.has(role)).length / input.contentRoles.length;
    components.genericity_prior = 0.85;
  } else {
    components.role_fit = 0.85;
    components.genericity_prior = GENERICITY[layout.category] ?? 0.80;
  }

  const requestedDensity = inferredDensity(input);
  const extremeMismatch = (layout.density === "低" && requestedDensity === "高") || (layout.density === "高" && requestedDensity === "低");
  components.density_prior = layout.density === requestedDensity ? 1 : extremeMismatch ? 0.62 : 0.82;
  components.silhouette_fit = silhouetteFit(layout, input);
  const processCapacity = layoutSlots(layout).filter((slot) => slotType(slot) === "process").length;
  components.process_fit = countFit(input.processStepCount ?? 0, processCapacity);
  const materialFit = scoreVisualMaterials(layout, input, thresholds);
  components.visual_material_fit = materialFit.fit;
  // RPA-1: 独立暴露几何契合度，使"图槽宽高比 vs 源图宽高比"可被单独打分与审计。
  components.visual_geometry_score = materialFit.geometry ? materialFit.geometry.mean_contain_fill : 0.85;
  components.readability_margin_fit = materialFit.margin;
  const captionNeed = (input.visuals ?? []).reduce((sum, visual) => sum + Number(visual.captionChars ?? 0), 0);
  const captionSlots = layoutSlots(layout).filter((slot) => ["caption", "callout"].includes(String(slot?.type ?? "").toLowerCase())).length;
  components.support_space_fit = captionNeed > 0 ? Math.min(1, captionSlots / Math.max(1, input.imageCount)) : 0.9;

  const weightedKeys = Object.keys(components).filter((key) => Number.isFinite(weights[key]));
  const weightSum = weightedKeys.reduce((sum, key) => sum + weights[key], 0);
  let total = weightedKeys.reduce((sum, key) => sum + weights[key] * components[key], 0) / weightSum;
  let penalty = 1;
  if (imageCapacity < input.imageCount) penalty *= 0.52 ** (input.imageCount - imageCapacity);
  if (tableCapacity < input.tableCount) penalty *= 0.45 ** (input.tableCount - tableCapacity);
  if (input.textChars > (layout.max_text_chars ?? 0) && (layout.max_text_chars ?? 0) > 0) {
    penalty *= Math.max(0.22, layout.max_text_chars / input.textChars);
  }
  // 视觉槽「偏窄但不致命」的缺口改为扣分而非排除：低于要求宽度、但仍在严重线之上，
  // 按最差缺口比例温和降权（与 legacy-readability 的 VISUAL_READABILITY_RISK 警告档一致），
  // 使几何更匹配的版面仍能凭其它因子胜出，同时不会被完全从候选池里剔除。
  const widthShortfalls = scoreVisualWidthShortfalls(layout, input);
  if (widthShortfalls.length) {
    const worstRatio = Math.min(...widthShortfalls.map((placement) => placement.display_width / placement.required_width));
    penalty *= Math.max(0.55, 0.4 + 0.6 * worstRatio);
  }
  total *= penalty;

  const publicComponents = {};
  for (const [key, value] of Object.entries(components)) publicComponents[key] = Math.round(value * 1000) / 10;
  const readability = layoutReadability(layout, input);
  return {
    id: layout.id,
    category: layout.category,
    category_zh: layout.category_zh,
    variant_name_zh: layout.variant_name_zh,
    score: Math.round(total * 10000) / 100,
    components: publicComponents,
    capacity: {
      max_text_chars: layout.max_text_chars,
      body_chars_at_min_font: readability.body_capacity_chars,
      title_chars_at_min_font: readability.title_capacity_chars,
      image_capacity: imageCapacity,
      table_capacity: tableCapacity,
      chart_capacity: profile.chart_capacity ?? 0,
      process_capacity: processCapacity,
      visual_area_capacity: availableArea,
      preferred_visual_aspect_ratio: layout.preferred_visual_aspect_ratio,
    },
    content_roles: layout.content_roles ?? [],
    material_assignments: materialFit.assignments,
    // 视觉槽宽度的可审计摘要：把「要求宽度 / 严重线 / 实际宽度」同时暴露，
    // 便于区分「被硬排除」「偏窄降权」「完全满足」三种情形，而不是只看一个总分。
    visual_width: {
      severe_floor_ratio: defaultPlanningThresholds().severe_visual_width_ratio,
      shortfall_count: widthShortfalls.length,
      placements: analyzeVisualPlacements(layout, input, thresholds).map((placement) => ({
        slot_id: placement.slot_id,
        visual_type: placement.visual_type,
        display_width: placement.display_width,
        required_width: placement.required_width,
        severe_width_floor: placement.severe_width_floor,
        meets_requirement: placement.display_width >= placement.required_width,
        below_severe_floor: placement.display_width < placement.severe_width_floor,
      })),
    },
    // RPA-1: 供下游 gate 直接消费的填充率预估值（contain 面积填充率）。
    visual_fill: materialFit.geometry ? {
      estimated_contain_fill: Math.round(materialFit.geometry.mean_contain_fill * 1000) / 1000,
      worst_contain_fill: Math.round(materialFit.geometry.worst_contain_fill * 1000) / 1000,
      source_aspect_ratio: materialFit.geometry.source_aspect_ratio,
      slot_aspect_ratio: materialFit.geometry.slot_aspect_ratio,
      geometry_known: true,
    } : { geometry_known: false, reason: "no_visual_material_or_no_visual_slot" },
  };
}

function violation(code, field, actual, capacity, message, recommendedAction = "replan_or_split") {
  return createViolation({
    code,
    field,
    actual,
    capacity,
    severity: "error",
    recoverable: true,
    recommended_action: recommendedAction,
    message,
  });
}

/**
 * Evaluate structural compatibility before a layout participates in ranking.
 * Soft scores are intentionally kept separate from this result so an
 * over-capacity layout can never appear in normal Top-K results.
 */
export function evaluateLayoutCompatibility(layout, input = {}) {
  const profile = layout.content_profile ?? {};
  const slots = layoutSlots(layout);
  const textChars = input.textChars ?? input.text_chars ?? 0;
  const titleChars = input.titleChars ?? input.title_chars ?? 0;
  const imageCount = input.imageCount ?? input.image_count ?? 0;
  const tableCount = input.tableCount ?? input.table_count ?? 0;
  const chartCount = input.chartCount ?? input.chart_count ?? 0;
  const processStepCount = input.processStepCount ?? input.process_step_count ?? 0;
  const titleSlots = slots.filter((slot) => slotType(slot) === "title" || (slotId(slot) === "title" && slotType(slot) === "text"));
  const processCapacity = slots.filter((slot) => slotType(slot) === "process").length;
  const requiredImageSlots = slots.filter((slot) => slotType(slot) === "figure" && slot.optional !== true).length;
  const readability = layoutReadability(layout, input);
  const violations = [];

  if ((layout.max_text_chars ?? Infinity) < textChars) {
    violations.push(violation(
      "TEXT_CAPACITY_EXCEEDED",
      "text_chars",
      textChars,
      layout.max_text_chars,
      `正文需要 ${textChars} 字，但版式最多容纳 ${layout.max_text_chars} 字。`,
      "shorten_or_replan",
    ));
  }
  if (!titleSlots.length) {
    violations.push(violation(
      "MISSING_REQUIRED_TITLE",
      "title_slot",
      false,
      true,
      "版式没有必需的标题槽位。",
      "choose_layout_with_title",
    ));
  } else if (titleChars > readability.title_capacity_chars) {
    violations.push(violation(
      "TITLE_CAPACITY_EXCEEDED",
      "title_chars",
      titleChars,
      readability.title_capacity_chars,
      `标题需要 ${titleChars} 字，但标题槽位建议最多容纳 ${readability.title_capacity_chars} 字。`,
      "shorten_title_or_replan",
    ));
  }
  if (imageCount > (profile.image_capacity ?? 0)) {
    violations.push(violation(
      "FIGURE_CAPACITY_EXCEEDED",
      "image_count",
      imageCount,
      profile.image_capacity ?? 0,
      `需要 ${imageCount} 个图片槽，但版式只有 ${profile.image_capacity ?? 0} 个。`,
      "choose_layout_with_more_figures",
    ));
  }
  if (imageCount > 0 && requiredImageSlots > imageCount) {
    violations.push(violation(
      "UNUSED_REQUIRED_VISUAL_SLOT",
      "image_count",
      imageCount,
      requiredImageSlots,
      `版式要求填充 ${requiredImageSlots} 个图片槽，但当前只有 ${imageCount} 个视觉实例。`,
      "choose_layout_matching_visual_instances",
    ));
  }
  if (tableCount > (profile.table_capacity ?? 0)) {
    violations.push(violation(
      "TABLE_CAPACITY_EXCEEDED",
      "table_count",
      tableCount,
      profile.table_capacity ?? 0,
      `需要 ${tableCount} 个表格槽，但版式只有 ${profile.table_capacity ?? 0} 个。`,
      "choose_layout_with_table_capacity",
    ));
  }
  if (chartCount > (profile.chart_capacity ?? 0)) {
    violations.push(violation(
      "CHART_CAPACITY_EXCEEDED",
      "chart_count",
      chartCount,
      profile.chart_capacity ?? 0,
      `需要 ${chartCount} 个图表槽，但版式只有 ${profile.chart_capacity ?? 0} 个。`,
      "choose_layout_with_chart_capacity",
    ));
  }
  if (processStepCount > processCapacity) {
    violations.push(violation(
      "PROCESS_CAPACITY_EXCEEDED",
      "process_step_count",
      processStepCount,
      processCapacity,
      `需要 ${processStepCount} 个流程步骤，但版式只有 ${processCapacity} 个流程槽。`,
      "replan_or_split",
    ));
  }

  const visualPlacements = analyzeVisualPlacements(layout, input, resolvePlanningThresholds());
  const widthThresholds = resolvePlanningThresholds();
  for (const placement of visualPlacements) {
    // 只有跌破严重线（要求宽度 × severe_visual_width_ratio）才是结构性不合格。
    // 严重线以上、要求宽度以下的缺口由 scoreLayout 降权处理：那里是「偏窄但可复核」，
    // 硬排除会把宽高比更匹配的版面一起误删（例如 43.6% 的标准双栏槽 vs 44% 的带字图要求）。
    if (!placement.slot_id || placement.display_width >= placement.severe_width_floor) continue;
    violations.push(violation(
      "VISUAL_SLOT_CAPACITY_EXCEEDED",
      `visuals.${placement.slot_id}.display_width`,
      placement.display_width,
      placement.severe_width_floor,
      `${placement.visual_type} 在槽位 ${placement.slot_id} 只有 ${percent(placement.display_width)} 页宽，低于其最低要求 ${percent(placement.required_width)} 的严重线 ${percent(placement.severe_width_floor)}（严重线比例 ${percent(widthThresholds.severe_visual_width_ratio)}），应改用更大的图槽或拆页。`,
      placement.dense ? "replan_or_split" : "choose_larger_visual_slot",
    ));
  }

  return {
    compatible: violations.length === 0,
    hard_constraints: [
      "text_capacity",
      "required_title_capability",
      "image_capacity",
      "table_capacity",
      "chart_capacity",
      "process_step_count",
      "visual_slot_capacity",
    ],
    capacities: {
      max_text_chars: layout.max_text_chars,
      title_chars_at_min_font: readability.title_capacity_chars,
      image_capacity: profile.image_capacity ?? 0,
      table_capacity: profile.table_capacity ?? 0,
      chart_capacity: profile.chart_capacity ?? 0,
      process_capacity: processCapacity,
      visual_placements: visualPlacements,
      required_image_slots: requiredImageSlots,
      // 硬门槛实际比较的是严重线（required × severe_visual_width_ratio），
      // visual_safety_margin 仅作为上报用的建议余量，不再参与排除判定。
      severe_visual_width_ratio: widthThresholds.severe_visual_width_ratio,
      visual_safety_margin: input.visualSafetyMargin ?? 0.10,
    },
    violations,
  };
}

export function topKLayouts(layouts, input) {
  return layouts
    .filter((layout) => evaluateLayoutCompatibility(layout, input).compatible)
    .map((layout) => scoreLayout(layout, input))
    .sort((a, b) => b.score - a.score || a.id.localeCompare(b.id))
    .slice(0, input.k || 10);
}
