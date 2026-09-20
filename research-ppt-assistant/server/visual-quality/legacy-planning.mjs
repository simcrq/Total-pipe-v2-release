/**
 * Isolated 0.3.x pre-render compatibility helpers.
 *
 * The v0.4 Visual QA pipeline does not use these helpers for rendered quality
 * decisions. Planner and Layout Retrieval consume capacity facts only; all
 * rendered pass/warning/fail decisions enter through evaluateVisualQuality.
 */

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const clamp = (value, min, max) => Math.min(max, Math.max(min, value));

export const VIEWING_PROFILES = Object.freeze({
  projector: Object.freeze({
    id: "projector",
    label_zh: "会议室投影",
    deck_title_target_pt: 54,
    deck_title_min_pt: 50,
    slide_title_target_pt: 40,
    slide_title_min_pt: 35,
    subheading_target_pt: 26,
    subheading_min_pt: 24,
    body_target_pt: 20,
    body_min_pt: 18,
    body_absolute_min_pt: 16,
    caption_target_pt: 16,
    caption_min_pt: 16,
    content_footprint_min: 0.68,
    content_footprint_max: 0.90,
    max_empty_band: 0.12,
    embedded_text_min_px: 14,
  }),
  desktop: Object.freeze({
    id: "desktop",
    label_zh: "桌面屏幕",
    deck_title_target_pt: 50,
    deck_title_min_pt: 50,
    slide_title_target_pt: 38,
    slide_title_min_pt: 35,
    subheading_target_pt: 24,
    subheading_min_pt: 24,
    body_target_pt: 18,
    body_min_pt: 16,
    body_absolute_min_pt: 16,
    caption_target_pt: 16,
    caption_min_pt: 16,
    content_footprint_min: 0.62,
    content_footprint_max: 0.90,
    max_empty_band: 0.15,
    embedded_text_min_px: 12,
  }),
  handout: Object.freeze({
    id: "handout",
    label_zh: "打印讲义",
    deck_title_target_pt: 50,
    deck_title_min_pt: 50,
    slide_title_target_pt: 35,
    slide_title_min_pt: 35,
    subheading_target_pt: 24,
    subheading_min_pt: 24,
    body_target_pt: 16,
    body_min_pt: 16,
    body_absolute_min_pt: 16,
    caption_target_pt: 16,
    caption_min_pt: 16,
    content_footprint_min: 0.60,
    content_footprint_max: 0.92,
    max_empty_band: 0.16,
    embedded_text_min_px: 11,
  }),
});

export const VISUAL_TYPE_RULES = Object.freeze({
  photo: Object.freeze({ min_display_width: 0.25, dense: false }),
  schematic: Object.freeze({ min_display_width: 0.36, dense: false }),
  simple_plot: Object.freeze({ min_display_width: 0.36, dense: false }),
  dense_plot: Object.freeze({ min_display_width: 0.50, dense: true }),
  multi_panel_figure: Object.freeze({ min_display_width: 0.55, dense: true }),
  composite_figure_region: Object.freeze({ min_display_width: 0.42, dense: true }),
  table_screenshot: Object.freeze({ min_display_width: 0.55, dense: true }),
  microscopy: Object.freeze({ min_display_width: 0.36, dense: false }),
  visual_evidence: Object.freeze({ min_display_width: 0.34, dense: false }),
});

const TEXT_TYPES = new Set(["subtitle", "meta", "text", "callout", "caption", "process", "timeline", "question"]);
const VISUAL_TYPES = new Set(["figure", "chart", "table"]);
const LOW_DENSITY_CATEGORIES = new Set(["cover", "section", "qa"]);

/**
 * 宽度门槛的单一来源：server/visual-quality/profiles/default.json 的 legacy_rules。
 * 与 group-fit / visual-fit 的 profile 模块使用同一种路径解析（fileURLToPath + path.resolve），
 * 因此 Windows / macOS 都成立，且不再需要在多个文件里各写一份 0.44 这类魔法数。
 * 读取失败时回退到下面的默认值，保证无 IO 环境下仍可调用。
 */
const LEGACY_RULES_PATH = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "profiles", "default.json");

const FALLBACK_PLANNING_THRESHOLDS = Object.freeze({
  embedded_visual_evidence_width: 0.44,
  multi_panel_width_add_4: 0.03,
  multi_panel_width_add_6: 0.07,
  dense_panel_count: 4,
  dense_visual_split_count: 2,
  dense_visual_split_width: 0.44,
  severe_visual_width_ratio: 0.72,
});

let cachedLegacyRules;

function readLegacyRules() {
  if (cachedLegacyRules !== undefined) return cachedLegacyRules;
  try {
    cachedLegacyRules = JSON.parse(fs.readFileSync(LEGACY_RULES_PATH, "utf8"))?.legacy_rules ?? {};
  } catch {
    cachedLegacyRules = {};
  }
  return cachedLegacyRules;
}

function positiveNumberOr(value, fallback) {
  const numeric = Number(value);
  return Number.isFinite(numeric) && numeric > 0 ? numeric : fallback;
}

/**
 * 解析规划/检索侧使用的宽度门槛。类型下限优先取 profile 的 legacy_rules.visual_types[*].minimum_width，
 * 缺失时回退到 VISUAL_TYPE_RULES，使两处声明不会静默分叉。
 */
export function resolvePlanningThresholds(overrides = {}) {
  const legacy = readLegacyRules();
  const configuredTypes = legacy.visual_types ?? {};
  const typeMinWidth = {};
  for (const [type, rules] of Object.entries(VISUAL_TYPE_RULES)) {
    typeMinWidth[type] = positiveNumberOr(configuredTypes[type]?.minimum_width, rules.min_display_width);
  }
  const thresholds = { ...FALLBACK_PLANNING_THRESHOLDS };
  for (const key of Object.keys(FALLBACK_PLANNING_THRESHOLDS)) {
    thresholds[key] = positiveNumberOr(legacy[key], FALLBACK_PLANNING_THRESHOLDS[key]);
  }
  thresholds.dense_panel_count = Math.max(1, Math.round(thresholds.dense_panel_count));
  thresholds.dense_visual_split_count = Math.max(1, Math.round(thresholds.dense_visual_split_count));
  thresholds.type_min_width = typeMinWidth;
  return { ...thresholds, ...overrides };
}

/**
 * 默认门槛做一次记忆化：requiredVisualWidth 在检索打分里是热路径（320 版面 × 每页图片数），
 * 不应每次都重建对象。返回冻结副本，避免调用方误改污染全局默认值。
 */
let cachedDefaultThresholds;
export function defaultPlanningThresholds() {
  cachedDefaultThresholds ??= Object.freeze(resolvePlanningThresholds());
  return cachedDefaultThresholds;
}

export function getViewingProfile(mode = "projector") {
  const normalized = String(mode || "projector").toLowerCase();
  return VIEWING_PROFILES[normalized] ?? VIEWING_PROFILES.projector;
}

function slotBox(slot) {
  if (slot?.box) return slot.box;
  const pptx = slot?.pptx_in;
  if (!pptx) return undefined;
  return {
    x: pptx.x / 13.333,
    y: pptx.y / 7.5,
    w: pptx.w / 13.333,
    h: pptx.h / 7.5,
  };
}

function slotSizeIn(slot) {
  if (slot?.pptx_in) return { w: slot.pptx_in.w, h: slot.pptx_in.h };
  const box = slotBox(slot);
  if (!box) return undefined;
  return { w: box.w * 13.333, h: box.h * 7.5 };
}

function slotTypography(slot, category, profile) {
  if (slot.type === "title") {
    const cover = category === "cover";
    return {
      target: cover ? profile.deck_title_target_pt : profile.slide_title_target_pt,
      minimum: cover ? profile.deck_title_min_pt : profile.slide_title_min_pt,
      absoluteMinimum: cover ? profile.deck_title_min_pt : profile.slide_title_min_pt,
      maxLines: 1,
    };
  }
  if (["subtitle", "callout", "question"].includes(slot.type)) {
    return {
      target: profile.subheading_target_pt,
      minimum: profile.subheading_min_pt,
      absoluteMinimum: profile.subheading_min_pt,
      maxLines: slot.type === "subtitle" ? 2 : 3,
    };
  }
  if (["caption", "meta"].includes(slot.type)) {
    return {
      target: profile.caption_target_pt,
      minimum: profile.caption_min_pt,
      absoluteMinimum: profile.caption_min_pt,
      maxLines: slot.type === "meta" ? 1 : 2,
    };
  }
  return {
    target: profile.body_target_pt,
    minimum: profile.body_min_pt,
    absoluteMinimum: profile.body_absolute_min_pt,
    maxLines: slot.type === "process" ? 3 : slot.type === "timeline" ? 3 : 8,
  };
}

export function estimateSlotTextCapacity(slot, fontPt, requestedMaxLines) {
  const size = slotSizeIn(slot);
  if (!size || !Number.isFinite(fontPt) || fontPt <= 0) return 0;
  const widthPt = Math.max(0, size.w * 72 - 16);
  const heightPt = Math.max(0, size.h * 72 - 8);
  const charWidthFactor = slot.type === "title" ? 0.92 : slot.type === "caption" || slot.type === "meta" ? 0.78 : 0.84;
  const charsPerLine = Math.max(1, Math.floor(widthPt / (fontPt * charWidthFactor)));
  const geometricLines = Math.max(1, Math.floor(heightPt / (fontPt * 1.20)));
  const maxLines = Math.max(1, Math.min(geometricLines, requestedMaxLines ?? geometricLines));
  return charsPerLine * maxLines;
}

export function enrichSlotReadability(slot, category, viewingMode = "projector") {
  if (!slot || !["title", ...TEXT_TYPES].includes(slot.type)) return { ...slot };
  const profile = getViewingProfile(viewingMode);
  const typography = slotTypography(slot, category, profile);
  const maxLines = typography.maxLines;
  const target = Math.max(Number(slot.font_pt_hint) || 0, typography.target);
  return {
    ...slot,
    font_pt_hint: target,
    min_font_pt: typography.minimum,
    absolute_min_font_pt: typography.absoluteMinimum,
    max_lines: maxLines,
    max_chars_at_min_font: estimateSlotTextCapacity(slot, typography.minimum, maxLines),
    max_chars_at_absolute_min: estimateSlotTextCapacity(slot, typography.absoluteMinimum, maxLines),
    collapse_when_empty: Boolean(slot.optional),
  };
}

function mergeIntervals(intervals) {
  const sorted = intervals
    .filter(([start, end]) => Number.isFinite(start) && Number.isFinite(end) && end > start)
    .map(([start, end]) => [clamp(start, 0, 1), clamp(end, 0, 1)])
    .sort((a, b) => a[0] - b[0]);
  const merged = [];
  for (const interval of sorted) {
    const previous = merged.at(-1);
    if (!previous || interval[0] > previous[1]) merged.push([...interval]);
    else previous[1] = Math.max(previous[1], interval[1]);
  }
  return merged;
}

export function computeSlotGeometry(slots = [], safeMargin = 0.045) {
  const boxes = slots.map(slotBox).filter(Boolean);
  if (!boxes.length) {
    return { footprint: 0, element_area_ratio: 0, largest_horizontal_empty_band: 1, content_center_x: 0.5, content_center_y: 0.5 };
  }
  const minX = Math.min(...boxes.map((box) => box.x));
  const minY = Math.min(...boxes.map((box) => box.y));
  const maxX = Math.max(...boxes.map((box) => box.x + box.w));
  const maxY = Math.max(...boxes.map((box) => box.y + box.h));
  const footprint = clamp((maxX - minX) * (maxY - minY), 0, 1);

  const xs = [...new Set(boxes.flatMap((box) => [clamp(box.x, 0, 1), clamp(box.x + box.w, 0, 1)]))].sort((a, b) => a - b);
  let unionArea = 0;
  for (let index = 0; index < xs.length - 1; index += 1) {
    const startX = xs[index];
    const endX = xs[index + 1];
    if (endX <= startX) continue;
    const ys = mergeIntervals(
      boxes
        .filter((box) => box.x < endX && box.x + box.w > startX)
        .map((box) => [box.y, box.y + box.h]),
    );
    unionArea += (endX - startX) * ys.reduce((sum, [start, end]) => sum + end - start, 0);
  }

  const occupiedY = mergeIntervals(boxes.map((box) => [box.y, box.y + box.h]));
  const contentStart = clamp(safeMargin, 0, 0.25);
  const contentEnd = 1 - contentStart;
  let cursor = contentStart;
  let largestGap = 0;
  for (const [start, end] of occupiedY) {
    if (end <= contentStart || start >= contentEnd) continue;
    largestGap = Math.max(largestGap, clamp(start, contentStart, contentEnd) - cursor);
    cursor = Math.max(cursor, clamp(end, contentStart, contentEnd));
  }
  largestGap = Math.max(largestGap, contentEnd - cursor);

  return {
    footprint: Math.round(footprint * 1000) / 1000,
    element_area_ratio: Math.round(clamp(unionArea, 0, 1) * 1000) / 1000,
    largest_horizontal_empty_band: Math.round(clamp(largestGap, 0, 1) * 1000) / 1000,
    content_center_x: Math.round(((minX + maxX) / 2) * 1000) / 1000,
    content_center_y: Math.round(((minY + maxY) / 2) * 1000) / 1000,
  };
}

function takeSlots(slots, count) {
  return [...slots]
    .sort((a, b) => (b.priority ?? 0) - (a.priority ?? 0) || (slotBox(b)?.w ?? 0) * (slotBox(b)?.h ?? 0) - (slotBox(a)?.w ?? 0) * (slotBox(a)?.h ?? 0))
    .slice(0, Math.max(0, count));
}

export function activeSlotsForMetrics(layout, metrics = {}) {
  const slots = layout.slots ?? [];
  const active = [];
  const add = (items) => {
    for (const slot of items) if (!active.includes(slot)) active.push(slot);
  };
  add(slots.filter((slot) => slot.type === "title"));
  if ((metrics.textChars ?? 0) > 0 || layout.category === "cover") {
    add(slots.filter((slot) => TEXT_TYPES.has(slot.type) && !slot.optional));
    const optionalText = slots.filter((slot) => TEXT_TYPES.has(slot.type) && slot.optional);
    if (optionalText.length && (metrics.textChars ?? 0) > 120) add(optionalText);
  }
  add(takeSlots(slots.filter((slot) => slot.type === "figure"), metrics.imageCount ?? 0));
  add(takeSlots(slots.filter((slot) => slot.type === "chart"), metrics.chartCount ?? 0));
  add(takeSlots(slots.filter((slot) => slot.type === "table"), metrics.tableCount ?? 0));
  return active;
}

function effectiveOccupancyThresholds(category, profile) {
  if (LOW_DENSITY_CATEGORIES.has(category)) {
    return {
      minimum: Math.min(profile.content_footprint_min, 0.40),
      maximum: profile.content_footprint_max,
      maxEmptyBand: Math.max(profile.max_empty_band, 0.22),
    };
  }
  return {
    minimum: profile.content_footprint_min,
    maximum: profile.content_footprint_max,
    maxEmptyBand: profile.max_empty_band,
  };
}

export function layoutReadability(layout, metrics = {}) {
  const profile = getViewingProfile(metrics.viewingMode ?? metrics.viewing_mode);
  const slots = (layout.slots ?? []).map((slot) => enrichSlotReadability(slot, layout.category, profile.id));
  const activeSlots = activeSlotsForMetrics({ ...layout, slots }, metrics);
  const safeMargin = layout.constraints?.safe_margin_norm ?? 0.045;
  const geometry = computeSlotGeometry(activeSlots, safeMargin);
  const thresholds = effectiveOccupancyThresholds(layout.category, profile);
  const titleSlot = slots.find((slot) => slot.type === "title");
  const bodySlots = slots.filter((slot) => TEXT_TYPES.has(slot.type));
  const bodyCapacity = bodySlots.reduce((sum, slot) => sum + (slot.max_chars_at_min_font ?? 0), 0);
  return {
    profile,
    thresholds,
    slots,
    active_slots: activeSlots.map((slot) => slot.id),
    title_capacity_chars: titleSlot?.max_chars_at_min_font ?? 0,
    body_capacity_chars: bodyCapacity,
    geometry,
  };
}

export function enrichLayoutReadability(layout, viewingMode = "projector") {
  const readability = layoutReadability(layout, { viewingMode, textChars: layout.max_text_chars ?? 0, imageCount: layout.content_profile?.image_capacity ?? 0, tableCount: layout.content_profile?.table_capacity ?? 0, chartCount: layout.content_profile?.chart_capacity ?? 0 });
  const profile = readability.profile;
  const cover = layout.category === "cover";
  return {
    ...layout,
    slots: readability.slots,
    constraints: {
      ...(layout.constraints ?? {}),
      default_title_font_pt: cover ? profile.deck_title_target_pt : profile.slide_title_target_pt,
      minimum_title_font_pt: cover ? profile.deck_title_min_pt : profile.slide_title_min_pt,
      default_body_font_pt: Math.max(layout.constraints?.default_body_font_pt ?? 0, profile.body_target_pt),
      minimum_body_font_pt: Math.max(layout.constraints?.minimum_body_font_pt ?? 0, profile.body_min_pt),
      absolute_minimum_body_font_pt: profile.body_absolute_min_pt,
      minimum_subheading_font_pt: profile.subheading_min_pt,
      minimum_caption_font_pt: profile.caption_min_pt,
      target_content_footprint: [readability.thresholds.minimum, readability.thresholds.maximum],
      maximum_empty_band: readability.thresholds.maxEmptyBand,
      optional_slots_collapse: true,
    },
    content_profile: {
      ...(layout.content_profile ?? {}),
      content_footprint_capacity: readability.geometry.footprint,
      element_area_ratio: readability.geometry.element_area_ratio,
      largest_horizontal_empty_band: readability.geometry.largest_horizontal_empty_band,
    },
    readability_contract: {
      viewing_mode: profile.id,
      title_capacity_chars: readability.title_capacity_chars,
      body_capacity_chars_at_min_font: readability.body_capacity_chars,
      content_footprint: readability.geometry.footprint,
      largest_horizontal_empty_band: readability.geometry.largest_horizontal_empty_band,
      reflow_policy: "Collapse unused optional slots, then expand adjacent high-priority content before reducing font size.",
    },
  };
}

function ratioFit(used, capacity) {
  if (!used) return 1;
  if (!capacity) return 0;
  const ratio = used / capacity;
  if (ratio <= 0.78) return 1;
  if (ratio <= 1) return 1 - 0.20 * ((ratio - 0.78) / 0.22);
  return Math.max(0, 0.80 - 1.6 * (ratio - 1));
}

export function typographyFit(layout, metrics = {}) {
  const readability = layoutReadability(layout, metrics);
  const titleFit = ratioFit(metrics.titleChars ?? 0, readability.title_capacity_chars);
  const bodyFit = ratioFit(metrics.textChars ?? 0, readability.body_capacity_chars);
  let slotFit = 1;
  for (const item of metrics.slotMetrics ?? []) {
    const slot = readability.slots.find((candidate) => candidate.id === item.slotId);
    if (!slot || !["title", ...TEXT_TYPES].includes(slot.type)) continue;
    slotFit = Math.min(slotFit, ratioFit(item.textChars ?? 0, slot.max_chars_at_min_font ?? 0));
  }
  return clamp(titleFit * 0.35 + bodyFit * 0.45 + slotFit * 0.20, 0, 1);
}

function normalizeVisualType(type) {
  return VISUAL_TYPE_RULES[type] ? type : "visual_evidence";
}

export function requiredVisualWidth(visual = {}, thresholds = defaultPlanningThresholds()) {
  if (Number.isFinite(visual.minDisplayWidth) && visual.minDisplayWidth > 0) return clamp(visual.minDisplayWidth, 0.1, 1);
  const type = normalizeVisualType(visual.visualType);
  let required = positiveNumberOr(thresholds.type_min_width?.[type], VISUAL_TYPE_RULES[type].min_display_width);
  const panels = Math.max(1, visual.panelCount ?? 1);
  if (type === "multi_panel_figure" && panels >= 6) required += thresholds.multi_panel_width_add_6;
  else if (type === "multi_panel_figure" && panels >= 4) required += thresholds.multi_panel_width_add_4;
  if (visual.hasEmbeddedText && type === "visual_evidence") {
    required = Math.max(required, thresholds.embedded_visual_evidence_width);
  }
  return clamp(required, 0.1, 0.72);
}

/**
 * 严重线：低于「要求宽度 × severe_visual_width_ratio」才视为结构性不合格（可硬排除），
 * 与 legacy-readability.mjs 的 DENSE_FIGURE_TOO_SMALL / VISUAL_READABILITY_RISK 两档语义一致。
 * 介于严重线与要求宽度之间的缺口是「可复核的偏小」，只应扣分，不应把版面从候选池里删掉。
 */
export function severeVisualWidthFloor(visual = {}, thresholds = defaultPlanningThresholds()) {
  return clamp(requiredVisualWidth(visual, thresholds) * thresholds.severe_visual_width_ratio, 0.1, 1);
}

export function analyzeVisualPlacements(layout, metrics = {}, thresholds = defaultPlanningThresholds()) {
  const allVisualSlots = (layout.slots ?? [])
    .filter((slot) => VISUAL_TYPES.has(slot.type))
    .sort((a, b) => (b.priority ?? 0) - (a.priority ?? 0) || (slotBox(b)?.w ?? 0) - (slotBox(a)?.w ?? 0));
  const used = new Set();
  const placements = [];
  for (const visual of metrics.visuals ?? []) {
    let slot = visual.slotId ? allVisualSlots.find((candidate) => candidate.id === visual.slotId) : undefined;
    if (!visual.slotId) slot = allVisualSlots.find((candidate) => !used.has(candidate.id));
    if (slot) used.add(slot.id);
    const width = slotBox(slot)?.w ?? 0;
    const required = requiredVisualWidth(visual, thresholds);
    const floor = severeVisualWidthFloor(visual, thresholds);
    const type = normalizeVisualType(visual.visualType);
    placements.push({
      slot_id: slot?.id,
      visual_type: type,
      dense: VISUAL_TYPE_RULES[type].dense || (visual.panelCount ?? 1) >= thresholds.dense_panel_count,
      panel_count: visual.panelCount ?? 1,
      has_embedded_text: Boolean(visual.hasEmbeddedText),
      display_width: Math.round(width * 1000) / 1000,
      required_width: Math.round(required * 1000) / 1000,
      severe_width_floor: Math.round(floor * 1000) / 1000,
      width_fit: required > 0 ? clamp(width / required, 0, 1) : 1,
    });
  }
  return placements;
}

export function visualComplexityFit(layout, metrics = {}, thresholds = defaultPlanningThresholds()) {
  if (!(metrics.visuals ?? []).length) return 0.85;
  const placements = analyzeVisualPlacements(layout, metrics, thresholds);
  if (!placements.length) return 0;
  let fit = placements.reduce((sum, placement) => sum + placement.width_fit, 0) / placements.length;
  const denseCount = placements.filter((placement) => placement.dense).length;
  if (denseCount >= thresholds.dense_visual_split_count
      && placements.some((placement) => placement.display_width < thresholds.dense_visual_split_width)) fit *= 0.72;
  return clamp(fit, 0, 1);
}

export function occupancyFit(layout, metrics = {}) {
  const readability = layoutReadability(layout, metrics);
  const { footprint, largest_horizontal_empty_band: emptyBand } = readability.geometry;
  const { minimum, maximum, maxEmptyBand } = readability.thresholds;
  let fit = 1;
  if (footprint < minimum) fit *= clamp(footprint / minimum, 0, 1);
  else if (footprint > maximum) fit *= clamp(1 - (footprint - maximum) * 1.5, 0.55, 1);
  if (emptyBand > maxEmptyBand) fit *= clamp(1 - (emptyBand - maxEmptyBand) * 2.5, 0.45, 1);
  return clamp(fit, 0, 1);
}
