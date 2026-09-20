import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { CONTENT_MODEL_VERSION, createViolation, normalizeContentModel, normalizePaperWorkflowV4 } from "./content-model.mjs";
import { evaluateLayoutCompatibility, scoreLayout } from "./layout-retriever.mjs";
import { PLANNING_LOOP_VERSION, planSlideClosedLoop, splitSlideBrief, inferSemanticCategory } from "./planning-loop.mjs";
import { validateRendererInputs, verifyRendererInputsOnDisk } from "./renderer-guard.mjs";
import {
  SLOT_BINDING_VERSION,
  assignmentHasContent,
  bindSlideToLayout,
  canonicalAssignmentType,
  truncateTextDeterministically,
  validateSlotBindingContract,
} from "./slot-binding.mjs";
import {
  VISUAL_TYPE_RULES,
  VIEWING_PROFILES,
  analyzeVisualPlacements,
  enrichLayoutReadability,
  getViewingProfile,
  layoutReadability,
} from "./visual-quality/legacy-planning.mjs";
import { adaptLegacyRenderedSlide, evaluateVisualQuality } from "./visual-quality/index.mjs";
import {
  QA_REPORT_VERSION,
  QUALITY_PROFILE_VERSION,
  RENDER_TELEMETRY_VERSION,
  VISUAL_QUALITY_VERSION,
} from "./visual-quality/contracts.mjs";
import { adaptRendererTelemetry } from "./renderer-adapters/index.mjs";
import { RENDER_EVIDENCE_CONTRACT_VERSION } from "./render-telemetry-assembly.mjs";
import { GROUP_FIT_VERSION, runGroupFitPreflight } from "./group-fit/index.mjs";
import { compileSlideDesignIR, DESIGN_COMPILER_VERSION, SLIDE_DESIGN_IR_VERSION } from "./design-intelligence/design-compiler.mjs";
import { createDesignCandidates, CANDIDATE_FACTORY_VERSION, materializeRankedLayouts } from "./design-intelligence/candidate-factory.mjs";
import { AESTHETIC_SCORER_VERSION } from "./design-intelligence/aesthetic-scorer.mjs";
import {
  createDeckDesignState,
  DECK_DESIGN_STATE_VERSION,
  estimateContainerDensity,
  publicDeckDesignState,
  updateDeckDesignState,
} from "./design-intelligence/deck-state.mjs";
import { DESIGN_QA_VERSION, evaluateDeckDesign } from "./design-intelligence/design-qa.mjs";
import { DESIGN_REGISTRY_VERSION, loadDesignRegistry } from "./design-intelligence/registry.mjs";
import {
  BOUNDED_REPAIR_LOOP_VERSION,
  REPAIR_CONTROLLER_VERSION,
  VISUAL_OBSERVER_VERSION,
} from "./perceptual-loop/contracts.mjs";
export { runVisualFitPreflight } from "./visual-fit/index.mjs";
export { runGroupFitPreflight };

export { validateRendererInputs, verifyRendererInputsOnDisk };
export { normalizeContentModel, normalizePaperWorkflowV4 };
export { bindSlideToLayout, planSlideClosedLoop, splitSlideBrief, truncateTextDeterministically, validateSlotBindingContract };

export const PIPELINE_CONTRACT_VERSION = "1.3.0";
export const PIPELINE_STATUS = Object.freeze({
  plan: "plan_complete",
  preflight: "preflight_complete",
  renderQa: "render_qa_complete",
});

const SERVER_DIR = path.dirname(fileURLToPath(import.meta.url));
export const PLUGIN_ROOT = path.resolve(SERVER_DIR, "..");
const DATA_DIR = path.join(PLUGIN_ROOT, "assets", "layout-library");

let catalogPromise;

const clamp = (value, min, max) => Math.min(max, Math.max(min, value));
const asArray = (value) => (Array.isArray(value) ? value : []);
const unique = (values) => [...new Set(values)];

async function readJson(fileName) {
  return JSON.parse(await fs.readFile(path.join(DATA_DIR, fileName), "utf8"));
}

export async function loadCatalog() {
  if (!catalogPromise) {
    catalogPromise = Promise.all([readJson("layouts.json"), readJson("themes.json")]).then(
      ([layoutPayload, themePayload]) => {
        const layouts = layoutPayload.layouts ?? [];
        const themes = themePayload.themes ?? [];
        const byId = new Map(layouts.map((layout) => [layout.id, layout]));
        const themesById = new Map(themes.map((theme) => [theme.id, theme]));
        return {
          meta: layoutPayload.meta ?? {},
          themeMeta: themePayload.meta ?? {},
          layouts,
          byId,
          themes,
          themesById,
        };
      },
    );
  }
  return catalogPromise;
}

function enrichThemeContract(theme, themeMeta) {
  if (!theme) return theme;
  const constraints = themeMeta?.token_usage_constraints ?? {};
  const tokens = {};
  for (const key of ["bg", "panel", "text", "muted", "accent1", "accent2", "accent3", "border"]) {
    tokens[key] = {
      color: theme[key] ?? null,
      allowed_usage: constraints[key]?.allowed_usage ?? [],
      forbidden_usage: constraints[key]?.forbidden_usage ?? [],
    };
  }
  return { ...theme, token_contract_version: themeMeta?.token_contract_version ?? "1.0.0", tokens };
}

function integer(value, fallback, min = 0, max = 100000) {
  if (value === undefined || value === null || value === "") return fallback;
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) throw new TypeError(`Expected a number, received ${value}`);
  return clamp(Math.round(parsed), min, max);
}

function positiveNumber(value, fallback) {
  if (value === undefined || value === null || value === "") return fallback;
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed <= 0) {
    throw new TypeError(`Expected a positive number, received ${value}`);
  }
  return parsed;
}

function finiteNumber(value, fallback, min = -Infinity, max = Infinity) {
  if (value === undefined || value === null || value === "") return fallback;
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) throw new TypeError(`Expected a number, received ${value}`);
  return clamp(parsed, min, max);
}

function normalizeViewingMode(value) {
  const mode = String(value ?? "projector").toLowerCase();
  if (!VIEWING_PROFILES[mode]) throw new RangeError(`Unsupported viewing_mode: ${value}`);
  return mode;
}

function normalizeDensityPreference(value) {
  if (value === undefined || value === null || value === "") return undefined;
  const aliases = { spacious: "低", balanced: "中", dense: "高", "低": "低", "中": "中", "高": "高" };
  const normalized = aliases[String(value).toLowerCase()] ?? aliases[String(value)];
  if (!normalized) throw new RangeError(`Unsupported density_preference: ${value}`);
  return normalized;
}

function normalizeSlotMetrics(value) {
  return asArray(value).map((item, index) => {
    if (!item || typeof item !== "object" || Array.isArray(item)) throw new TypeError(`slot_metrics[${index}] must be an object`);
    return {
      slotId: String(item.slot_id ?? item.slotId ?? "").trim(),
      role: String(item.role ?? "body").trim() || "body",
      textChars: integer(item.text_chars ?? item.textChars, 0),
      fontPt: positiveNumber(item.font_pt ?? item.fontPt, undefined),
      lineCount: integer(item.line_count ?? item.lineCount, undefined, 0, 100),
      intendedSingleLine: Boolean(item.intended_single_line ?? item.intendedSingleLine),
    };
  });
}

/** RPA-1: 从源像素尺寸推导宽高比；无法推导时返回 undefined。 */
function derivedAspectFromPixels(item) {
  const width = Number(item?.source_width_px ?? item?.sourceWidthPx);
  const height = Number(item?.source_height_px ?? item?.sourceHeightPx);
  if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0) return undefined;
  return width / height;
}

function normalizeVisuals(value) {
  return asArray(value).map((item, index) => {
    if (!item || typeof item !== "object" || Array.isArray(item)) throw new TypeError(`visuals[${index}] must be an object`);
    const visualType = String(item.visual_type ?? item.visualType ?? "visual_evidence").trim();
    if (!VISUAL_TYPE_RULES[visualType]) throw new RangeError(`Unsupported visual_type: ${visualType}`);
    return {
      ...item,
      slotId: item.slot_id ?? item.slotId ? String(item.slot_id ?? item.slotId).trim() : undefined,
      visualType,
      panelCount: integer(item.panel_count ?? item.panelCount, 1, 1, 100),
      hasEmbeddedText: Boolean(item.has_embedded_text ?? item.hasEmbeddedText),
      minDisplayWidth: finiteNumber(item.min_display_width ?? item.minDisplayWidth, undefined, 0.1, 1),
      displayWidth: finiteNumber(item.display_width ?? item.display_width_norm ?? item.displayWidth, undefined, 0, 1),
      displayHeight: finiteNumber(item.display_height ?? item.display_height_norm ?? item.displayHeight, undefined, 0, 1),
      embeddedTextPx: finiteNumber(item.embedded_text_px ?? item.rendered_embedded_text_px ?? item.embeddedTextPx, undefined, 0, 1000),
      source_width_px: integer(item.source_width_px ?? item.sourceWidthPx, undefined, 1, Number.MAX_SAFE_INTEGER),
      source_height_px: integer(item.source_height_px ?? item.sourceHeightPx, undefined, 1, Number.MAX_SAFE_INTEGER),
      // RPA-1: 缺失显式宽高比时，回退到源像素尺寸推导。
      aspectRatio: positiveNumber(
        item.visual_aspect_ratio ?? item.aspect_ratio ?? item.visualAspectRatio ?? item.aspectRatio
          ?? derivedAspectFromPixels(item),
        undefined,
      ),
      embeddedTextDensity: finiteNumber(item.embedded_text_density ?? item.embeddedTextDensity, undefined, 0, 1),
      captionChars: integer(item.caption_chars ?? item.captionChars, 0, 0, 2000),
      sourceVisualId: item.source_visual_id ?? item.sourceVisualId ? String(item.source_visual_id ?? item.sourceVisualId).trim() : undefined,
      regionId: item.region_id ?? item.regionId ? String(item.region_id ?? item.regionId).trim() : undefined,
      semanticRelation: item.semantic_relation ?? item.semanticRelation ? String(item.semantic_relation ?? item.semanticRelation).trim() : undefined,
    };
  });
}

function publicSlotMetric(metric) {
  return {
    slot_id: metric.slotId,
    role: metric.role,
    text_chars: metric.textChars,
    font_pt: metric.fontPt,
    line_count: metric.lineCount,
    intended_single_line: metric.intendedSingleLine,
  };
}

function publicVisualMetric(visual) {
  return {
    slot_id: visual.slotId,
    visual_type: visual.visualType,
    panel_count: visual.panelCount,
    has_embedded_text: visual.hasEmbeddedText,
    min_display_width: visual.minDisplayWidth,
    display_width_norm: visual.displayWidth,
    display_height_norm: visual.displayHeight,
    rendered_embedded_text_px: visual.embeddedTextPx,
    source_width_px: visual.source_width_px,
    source_height_px: visual.source_height_px,
    visual_aspect_ratio: visual.aspectRatio,
    embedded_text_density: visual.embeddedTextDensity,
    caption_chars: visual.captionChars,
    source_visual_id: visual.sourceVisualId,
    region_id: visual.regionId,
    semantic_relation: visual.semanticRelation,
  };
}

function normalizeTextCharsByRole(value) {
  if (value === undefined || value === null) return {};
  if (typeof value !== "object" || Array.isArray(value)) throw new TypeError("text_chars_by_role must be an object");
  const result = {};
  for (const [role, chars] of Object.entries(value)) {
    const normalizedRole = String(role).trim();
    if (normalizedRole) result[normalizedRole] = integer(chars, 0);
  }
  return result;
}

export function normalizeMetrics(input = {}) {
  const textCharsByRole = normalizeTextCharsByRole(input.text_chars_by_role ?? input.textCharsByRole);
  const roleCharTotal = Object.values(textCharsByRole).reduce((sum, chars) => sum + chars, 0);
  const normalizedVisuals = normalizeVisuals(input.visuals);
  // RPA-1: 未显式给出 visual_aspect_ratio 时，用 visuals 里约束最强（最偏离 1）的那个推导。
  // 种子必须是首元素：若传 undefined，第一轮 `Math.abs(Math.log(undefined))` 是 NaN，
  // `x > NaN` 恒为 false，reduce 会把初始值 undefined 原样返回，整个推导恒失效。
  // 这里与 planning-loop.mjs 的 dominantVisualAspectRatio 保持同一实现，避免两处行为分叉。
  const derivedAspectRatios = normalizedVisuals
    .map((visual) => visual.aspectRatio)
    .filter((ratio) => Number.isFinite(ratio) && ratio > 0);
  const derivedAspect = derivedAspectRatios.length
    ? derivedAspectRatios.reduce((worst, current) => (
      Math.abs(Math.log(current)) > Math.abs(Math.log(worst)) ? current : worst
    ), derivedAspectRatios[0])
    : undefined;
  return {
    textChars: integer(input.text_chars ?? input.textChars, roleCharTotal),
    textCharsByRole,
    titleChars: integer(input.title_chars ?? input.titleChars, 0),
    imageCount: integer(input.image_count ?? input.imageCount, 0, 0, 20),
    tableCount: integer(input.table_count ?? input.tableCount, 0, 0, 10),
    chartCount: integer(input.chart_count ?? input.chartCount, 0, 0, 20),
    processStepCount: integer(input.process_step_count ?? input.processStepCount, 0, 0, 20),
    visualAspectRatio: positiveNumber(
      input.visual_aspect_ratio ?? input.visualAspectRatio ?? derivedAspect,
      undefined,
    ),
    contentRoles: unique(
      asArray(input.content_roles ?? input.contentRoles)
        .map((role) => String(role).trim())
        .filter(Boolean),
    ),
    viewingMode: normalizeViewingMode(input.viewing_mode ?? input.viewingMode),
    densityPreference: normalizeDensityPreference(input.density_preference ?? input.densityPreference),
    allowAutoSplit: input.allow_auto_split ?? input.allowAutoSplit ?? true,
    visualSafetyMargin: finiteNumber(input.visual_safety_margin ?? input.visualSafetyMargin, 0.10, 0, 0.5),
    slotMetrics: normalizeSlotMetrics(input.slot_metrics ?? input.slotMetrics),
    visuals: normalizedVisuals,
  };
}

function canonicalSlotType(slot) {
  const type = String(slot?.type ?? slot?.slot_type ?? "").toLowerCase();
  if (["title", "subtitle", "meta", "text", "callout", "caption", "question", "reference", "metadata"].includes(type)) return "text";
  if (type === "figure" || type === "image" || type === "visual") return "image";
  return type;
}

function publicSlotSpec(slot) {
  const maxChars = Number.isFinite(slot.max_chars_at_min_font) ? slot.max_chars_at_min_font : null;
  const maxCharsAtAbsoluteMin = Number.isFinite(slot.max_chars_at_absolute_min) ? slot.max_chars_at_absolute_min : null;
  return {
    slot_id: slot.id,
    slot_type: canonicalSlotType(slot),
    required: !slot.optional,
    capacity: {
      max_chars: maxChars,
      max_chars_at_absolute_min: maxCharsAtAbsoluteMin,
      max_lines: Number.isFinite(slot.max_lines) ? slot.max_lines : null,
      font_pt_hint: Number.isFinite(slot.font_pt_hint) ? slot.font_pt_hint : null,
      min_font_pt: Number.isFinite(slot.min_font_pt) ? slot.min_font_pt : null,
      absolute_min_font_pt: Number.isFinite(slot.absolute_min_font_pt) ? slot.absolute_min_font_pt : null,
    },
    label_zh: slot.label_zh,
    priority: slot.priority,
    collapse_when_empty: Boolean(slot.collapse_when_empty),
    box: slot.box,
    pptx_in: slot.pptx_in,
  };
}

function enrichResult(layout, scored, adjustedScore, chartFit, includeSlots, metrics) {
  const effectiveLayout = enrichLayoutReadability(layout, metrics.viewingMode);
  const result = {
    ...scored,
    score: Math.round(adjustedScore * 100) / 100,
    family: layout.family,
    density: layout.density,
    recommended_for: layout.recommended_for,
    reading_order: layout.reading_order,
    preview_path: `assets/layout-library/svg/${layout.id}.svg`,
    preview_uri: `research-ppt://preview/${layout.id}`,
    readability_contract: effectiveLayout.readability_contract,
  };
  if (chartFit !== undefined) result.components.chart_fit = Math.round(chartFit * 1000) / 10;
  if (includeSlots) result.slot_specs = effectiveLayout.slots.map(publicSlotSpec);
  return result;
}

export async function searchLayouts(input = {}) {
  const catalog = await loadCatalog();
  const metrics = normalizeMetrics(input);
  const k = integer(input.k, 5, 1, 20);
  const categories = unique(
    asArray(input.categories ?? (input.category ? [input.category] : []))
      .map((category) => String(category).trim())
      .filter(Boolean),
  );
  const densities = unique(
    asArray(input.densities ?? (input.density ? [input.density] : []))
      .map((density) => String(density).trim())
      .filter(Boolean),
  );
  const excludedIds = new Set(asArray(input.exclude_ids ?? input.excludeIds));
  const includeSlots = Boolean(input.include_slots ?? input.includeSlots);
  const diversity = input.diversity ?? "none";

  let candidates = catalog.layouts.filter((layout) => !excludedIds.has(layout.id));
  if (categories.length) candidates = candidates.filter((layout) => categories.includes(layout.category));
  if (densities.length) candidates = candidates.filter((layout) => densities.includes(layout.density));

  const compatibilityChecks = candidates.map((layout) => ({
    layout,
    compatibility: evaluateLayoutCompatibility(layout, metrics),
  }));
  const compatibleCandidates = compatibilityChecks
    .filter(({ compatibility }) => compatibility.compatible)
    .map(({ layout }) => layout);
  const excludedLayouts = compatibilityChecks
    .filter(({ compatibility }) => !compatibility.compatible)
    .map(({ layout, compatibility }) => ({
      layout_id: layout.id,
      violations: compatibility.violations,
      capacities: compatibility.capacities,
    }));

  const ranked = compatibleCandidates
    .map((layout) => {
      const scored = scoreLayout(layout, metrics);
      const chartCapacity = layout.content_profile?.chart_capacity ?? 0;
      let chartFit;
      let adjustedScore = scored.score;
      if (metrics.chartCount > 0) {
        chartFit = chartCapacity >= metrics.chartCount ? 1 : Math.max(0, chartCapacity / metrics.chartCount);
        if (chartCapacity < metrics.chartCount) {
          adjustedScore *= 0.55 ** (metrics.chartCount - chartCapacity);
        } else {
          adjustedScore = Math.min(100, adjustedScore * 1.025);
        }
      }
      return enrichResult(layout, scored, adjustedScore, chartFit, includeSlots, metrics);
    })
    .sort((a, b) => b.score - a.score || a.id.localeCompare(b.id));

  let results = ranked;
  if (diversity === "category" || diversity === "family") {
    const seen = new Set();
    const diverse = [];
    const remainder = [];
    for (const result of ranked) {
      const key = diversity === "category" ? result.category : result.family;
      if (!seen.has(key)) {
        seen.add(key);
        diverse.push(result);
      } else {
        remainder.push(result);
      }
    }
    results = [...diverse, ...remainder];
  }

  return {
    query: {
      text_chars: metrics.textChars,
      text_chars_by_role: metrics.textCharsByRole,
      title_chars: metrics.titleChars,
      image_count: metrics.imageCount,
      table_count: metrics.tableCount,
      chart_count: metrics.chartCount,
      process_step_count: metrics.processStepCount,
      visual_aspect_ratio: metrics.visualAspectRatio,
      content_roles: metrics.contentRoles,
      viewing_mode: metrics.viewingMode,
      density_preference: metrics.densityPreference,
      allow_auto_split: metrics.allowAutoSplit,
      visual_safety_margin: metrics.visualSafetyMargin,
      slot_metrics: metrics.slotMetrics,
      visuals: metrics.visuals,
      categories,
      densities,
      diversity,
    },
    candidate_count: candidates.length,
    compatible_candidate_count: compatibleCandidates.length,
    compatibility: {
      mode: "hard_constraints_before_ranking",
      hard_constraints: [
        "text_capacity",
        "required_title_capability",
        "image_capacity",
        "table_capacity",
        "chart_capacity",
        "process_step_count",
      ],
      excluded_candidate_count: excludedLayouts.length,
      excluded_layouts: excludedLayouts,
    },
    results: results.slice(0, k),
  };
}

export async function getLayout(layoutId, themeId, viewingMode = "projector") {
  const catalog = await loadCatalog();
  const layout = catalog.byId.get(layoutId);
  if (!layout) throw new RangeError(`Unknown layout_id: ${layoutId}`);
  const normalizedViewingMode = normalizeViewingMode(viewingMode);
  let theme;
  if (themeId) {
    theme = catalog.themesById.get(themeId);
    if (!theme) throw new RangeError(`Unknown theme_id: ${themeId}`);
  }
  const enrichedLayout = enrichLayoutReadability(layout, normalizedViewingMode);
  const { slots: _internalSlots, ...publicLayout } = enrichedLayout;
  const profile = layout.content_profile ?? {};
  return {
    layout: {
      ...publicLayout,
      slot_specs: enrichedLayout.slots.map(publicSlotSpec),
      // RPA-3: 与 assets/layout-library/layouts.json 原生 schema 对齐的镜像字段，
      // 使集成层不必在 slot_specs/slots 两套命名之间维护映射。
      slots: asArray(enrichedLayout.slots).map((slot) => ({
        id: slot.id,
        type: slot.type,
        label_zh: slot.label_zh,
        box: slot.box,
        pptx_in: slot.pptx_in,
        optional: slot.optional === true,
        priority: slot.priority,
      })),
      capacity: {
        max_text_chars: layout.max_text_chars ?? null,
        image_capacity: profile.image_capacity ?? 0,
        table_capacity: profile.table_capacity ?? 0,
        chart_capacity: profile.chart_capacity ?? 0,
        visual_area_capacity: profile.media_area_capacity ?? profile.visual_area_capacity ?? 0,
      },
      field_aliases: {
        "slots[]": "layouts.json 原生命名；slot_specs[] 是同一批槽位的规范化视图",
        "slots[].id": "对应 slot_specs[].slot_id",
        "slots[].type": "对应 slot_specs[].slot_type（注意 slot_type 会把 figure/image/visual 统一规范为 image）",
        "content_profile.image_capacity": "对应 capacity.image_capacity",
        max_text_chars: "版式正文容量上限，与 layouts.json 同名同义",
      },
    },
    theme: enrichThemeContract(theme, catalog.themeMeta),
    viewing_profile: getViewingProfile(normalizedViewingMode),
    preview_path: `assets/layout-library/svg/${layout.id}.svg`,
    preview_uri: `research-ppt://preview/${layout.id}`,
    coordinate_contract: {
      normalized: "slot_specs[].box uses 0..1 coordinates from the top-left",
      powerpoint_inches: "slot_specs[].pptx_in targets a 13.333 x 7.5 inch 16:9 slide",
    },
  };
}

export async function bindSlideContent(input = {}) {
  const layoutId = input.layout_id ?? input.layoutId ?? input.layout_spec?.layout_id ?? input.layout_spec?.id;
  if (!layoutId) throw new TypeError("layout_id is required for slot binding");
  const resolved = input.layout_spec
    ? { layout: input.layout_spec }
    : await getLayout(layoutId, input.theme_id, input.viewing_mode);
  return bindSlideToLayout({
    ...input,
    layout_spec: resolved.layout,
    slot_specs: input.slot_specs ?? resolved.layout.slot_specs,
  });
}

export async function planSlideContent(input = {}) {
  if (!input.slide_brief || typeof input.slide_brief !== "object" || Array.isArray(input.slide_brief)) {
    throw new TypeError("slide_brief is required for closed-loop planning");
  }
  return planSlideClosedLoop(input, {
    searchLayouts,
    getLayout,
    bindSlide: bindSlideToLayout,
  });
}

export async function catalogSummary() {
  const catalog = await loadCatalog();
  const categories = new Map();
  for (const layout of catalog.layouts) {
    const current = categories.get(layout.category) ?? {
      id: layout.category,
      name_zh: layout.category_zh,
      name_en: layout.category_en,
      family: layout.family,
      count: 0,
      roles: new Set(),
    };
    current.count += 1;
    for (const role of layout.content_roles ?? []) current.roles.add(role);
    categories.set(layout.category, current);
  }
  return {
    library: {
      ...catalog.meta,
      runtime_contract_version: "2.2.0",
      content_model_contract_version: CONTENT_MODEL_VERSION,
      slot_binding_contract_version: SLOT_BINDING_VERSION,
      planning_loop_contract_version: PLANNING_LOOP_VERSION,
      pipeline_contract_version: PIPELINE_CONTRACT_VERSION,
      slide_design_ir_contract_version: SLIDE_DESIGN_IR_VERSION,
      design_compiler_contract_version: DESIGN_COMPILER_VERSION,
      design_registry_contract_version: DESIGN_REGISTRY_VERSION,
      candidate_factory_contract_version: CANDIDATE_FACTORY_VERSION,
      aesthetic_scorer_contract_version: AESTHETIC_SCORER_VERSION,
      deck_design_state_contract_version: DECK_DESIGN_STATE_VERSION,
      design_qa_contract_version: DESIGN_QA_VERSION,
      visual_observer_contract_version: VISUAL_OBSERVER_VERSION,
      repair_controller_contract_version: REPAIR_CONTROLLER_VERSION,
      bounded_repair_loop_contract_version: BOUNDED_REPAIR_LOOP_VERSION,
      stability_contract_version: "1.1.0",
      retrieval: "Hard structural compatibility filtering for text, title, image, table, chart, and process capacities before Top-K structural scoring; v0.5 expands only legal layouts into treatment and decoration candidates, applies explainable aesthetic ranking and deck-rhythm penalties, then preserves the existing slot-binding and Evidence gates",
    },
    categories: [...categories.values()].map((category) => ({
      ...category,
      roles: [...category.roles],
    })),
    themes: catalog.themes.map((theme) => enrichThemeContract(theme, catalog.themeMeta)),
    supported_presentation_types: Object.keys(DECK_BLUEPRINTS),
    viewing_profiles: Object.values(VIEWING_PROFILES),
    supported_visual_types: Object.entries(VISUAL_TYPE_RULES).map(([id, rules]) => ({ id, ...rules })),
    readability_contract_version: "1.1.0",
    renderer_guard_contract_version: "1.0.0",
    content_model_contract_version: CONTENT_MODEL_VERSION,
    slot_binding_contract_version: SLOT_BINDING_VERSION,
    planning_loop_contract_version: PLANNING_LOOP_VERSION,
    pipeline_contract_version: PIPELINE_CONTRACT_VERSION,
    slide_design_ir_contract_version: SLIDE_DESIGN_IR_VERSION,
    design_compiler_contract_version: DESIGN_COMPILER_VERSION,
    design_registry_contract_version: DESIGN_REGISTRY_VERSION,
    candidate_factory_contract_version: CANDIDATE_FACTORY_VERSION,
    aesthetic_scorer_contract_version: AESTHETIC_SCORER_VERSION,
    deck_design_state_contract_version: DECK_DESIGN_STATE_VERSION,
    design_qa_contract_version: DESIGN_QA_VERSION,
    visual_observer_contract_version: VISUAL_OBSERVER_VERSION,
    repair_controller_contract_version: REPAIR_CONTROLLER_VERSION,
    bounded_repair_loop_contract_version: BOUNDED_REPAIR_LOOP_VERSION,
    stability_contract_version: "1.1.0",
    render_telemetry_contract_version: RENDER_TELEMETRY_VERSION,
    render_evidence_contract_version: RENDER_EVIDENCE_CONTRACT_VERSION,
    visual_quality_contract_version: VISUAL_QUALITY_VERSION,
    quality_profile_contract_version: QUALITY_PROFILE_VERSION,
    qa_report_contract_version: QA_REPORT_VERSION,
    relation_fit_contract_version: GROUP_FIT_VERSION,
    theme_token_contract_version: catalog.themeMeta?.token_contract_version ?? "1.0.0",
    violation_contract_version: "1.0.0",
    adaptation_log_contract_version: "1.0.0",
    supported_renderers: ["slidep", "tencent-pptx"],
    supported_visual_qa_renderers: ["slidep", "tencent-pptx", "artifact-tool"],
    tool_boundary: "Plans slide specifications, validates pre-render capacity, and audits renderer telemetry after export; a separate renderer creates PPTX files.",
  };
}

const CATEGORY_GUIDANCE = {
  cover: ["研究主题与汇报身份", "建立汇报语境", 60, 1, 0, 0, ["headline", "subtitle", "metadata", "primary_visual"]],
  section: ["章节过渡", "提示叙事阶段变化", 25, 1, 0, 0, ["headline", "primary_visual"]],
  agenda: ["本次汇报如何展开", "建立听众预期", 100, 0, 0, 0, ["headline", "process", "timeline"]],
  weekly: ["本周进展聚焦一个可验证变化", "概括进展与阻塞", 150, 1, 0, 0, ["headline", "takeaway", "primary_visual", "metric"]],
  question: ["我们要回答的核心问题", "定义研究问题", 70, 0, 0, 0, ["headline", "question", "takeaway"]],
  background: ["现有背景说明问题为何重要", "给出必要背景", 150, 1, 0, 0, ["headline", "body_text", "primary_visual"]],
  literature: ["已有工作留下一个明确缺口", "定位相关工作", 210, 0, 0, 0, ["headline", "body_text", "reference", "takeaway"]],
  gap: ["现有方案在关键条件下仍不足", "收束研究缺口", 120, 0, 0, 0, ["headline", "body_text", "takeaway"]],
  theory: ["理论假设给出可检验预测", "建立理论依据", 170, 1, 0, 0, ["headline", "body_text", "primary_visual"]],
  method_overview: ["方法把输入转化为可检验输出", "总览方法逻辑", 130, 2, 0, 0, ["headline", "primary_visual", "process", "takeaway"]],
  workflow: ["实验流程围绕关键控制变量展开", "说明执行流程", 140, 1, 0, 0, ["headline", "process", "primary_visual"]],
  architecture: ["系统结构明确模块边界与信息流", "解释架构", 140, 2, 0, 0, ["headline", "primary_visual", "process"]],
  algorithm: ["算法步骤对应可复现实现", "解释算法", 180, 1, 0, 0, ["headline", "process", "body_text"]],
  dataset: ["数据覆盖决定结论的适用范围", "交代数据与划分", 68, 4, 0, 1, ["headline", "primary_visual", "secondary_visual", "data_visual"]],
  experiment: ["实验设计隔离了核心变量", "说明实验设置", 180, 1, 1, 0, ["headline", "body_text", "table", "primary_visual"]],
  metrics: ["指标组合覆盖性能与可靠性", "定义评价口径", 148, 0, 0, 1, ["headline", "metric", "data_visual"]],
  single_figure: ["主结果支持核心结论", "呈现关键证据", 80, 1, 0, 0, ["headline", "primary_visual", "takeaway", "caption"]],
  dual_figure: ["两组证据共同支持结论", "对照两幅关键图", 85, 2, 0, 0, ["headline", "primary_visual", "secondary_visual", "takeaway"]],
  triple_figure: ["三组证据形成一致趋势", "并列多组证据", 42, 3, 0, 0, ["headline", "primary_visual", "secondary_visual"]],
  four_panel: ["四个条件揭示结果边界", "展示多条件结果", 42, 4, 0, 0, ["headline", "primary_visual", "secondary_visual"]],
  chart_takeaway: ["趋势变化指向一个清晰结论", "解释主图趋势", 90, 0, 0, 1, ["headline", "data_visual", "takeaway"]],
  chart_compare: ["对照结果显示方案差异", "比较多组数据", 90, 0, 0, 3, ["headline", "data_visual", "takeaway"]],
  table: ["表格给出完整数值证据", "呈现结构化结果", 170, 0, 1, 0, ["headline", "table", "takeaway"]],
  table_chart: ["表格与图形在不同粒度上印证结论", "结合数据表和趋势图", 150, 0, 1, 1, ["headline", "table", "data_visual", "takeaway"]],
  qualitative: ["典型案例展示模型行为差异", "呈现定性证据", 68, 4, 0, 0, ["headline", "primary_visual", "secondary_visual", "takeaway"]],
  ablation: ["消融结果定位模块贡献", "验证组成部分", 200, 0, 1, 1, ["headline", "table", "data_visual", "takeaway"]],
  baseline: ["基线比较说明增益来自哪里", "对比基线", 160, 0, 1, 1, ["headline", "table", "data_visual", "takeaway"]],
  error: ["错误分布暴露主要失效模式", "分析误差结构", 68, 3, 0, 1, ["headline", "primary_visual", "secondary_visual", "data_visual", "takeaway"]],
  case: ["单个案例连接机制与结果", "深入解释案例", 112, 1, 0, 0, ["headline", "primary_visual", "body_text", "takeaway"]],
  failure: ["失败案例界定方法边界", "呈现失败模式", 110, 1, 0, 0, ["headline", "primary_visual", "takeaway"]],
  discussion: ["证据支持的解释与替代解释需分开", "讨论结果含义", 175, 0, 0, 0, ["headline", "body_text", "takeaway"]],
  limitations: ["当前证据仍受三类边界约束", "明确局限", 170, 0, 0, 0, ["headline", "body_text", "takeaway"]],
  next_steps: ["下一步优先验证最高风险假设", "安排后续工作", 140, 0, 0, 0, ["headline", "process", "takeaway", "body_text"]],
  timeline: ["关键里程碑与依赖关系明确", "展示计划", 120, 0, 0, 0, ["headline", "timeline", "process"]],
  decision: ["本次讨论需要形成明确决策", "推动讨论或选择", 130, 0, 0, 0, ["headline", "question", "takeaway"]],
  summary: ["核心结论可压缩为三点", "综合结论", 160, 1, 0, 0, ["headline", "takeaway", "primary_visual"]],
  qa: ["讨论聚焦证据、边界与下一步", "开启问答", 40, 1, 0, 0, ["headline", "question", "primary_visual"]],
  references: ["关键来源可追溯", "列出引用", 260, 1, 0, 0, ["headline", "reference", "body_text", "primary_visual"]],
  appendix: ["补充材料支持追问", "承载备查证据", 180, 0, 0, 0, ["headline", "body_text", "reference", "metadata"]],
};

export const DECK_BLUEPRINTS = {
  group_meeting: ["cover", "agenda", "weekly", "question", "background", "gap", "method_overview", "experiment", "chart_takeaway", "ablation", "error", "discussion", "next_steps", "summary", "qa"],
  journal_club: ["cover", "agenda", "background", "question", "literature", "method_overview", "dataset", "experiment", "single_figure", "dual_figure", "ablation", "limitations", "discussion", "summary", "qa", "references"],
  proposal: ["cover", "agenda", "background", "literature", "gap", "question", "theory", "method_overview", "experiment", "dataset", "metrics", "timeline", "limitations", "decision", "summary", "qa", "references"],
  progress_report: ["cover", "agenda", "weekly", "gap", "method_overview", "experiment", "chart_takeaway", "table_chart", "error", "next_steps", "timeline", "decision", "summary", "qa"],
  defense: ["cover", "agenda", "background", "gap", "question", "method_overview", "architecture", "experiment", "chart_takeaway", "chart_compare", "qualitative", "ablation", "limitations", "discussion", "summary", "qa", "references", "appendix"],
  paper_presentation: ["cover", "agenda", "background", "literature", "gap", "method_overview", "architecture", "dataset", "experiment", "metrics", "single_figure", "chart_compare", "ablation", "qualitative", "limitations", "summary", "qa", "references"],
  custom: ["cover", "question", "method_overview", "single_figure", "summary", "qa"],
};

const NARRATIVE_ARCS = {
  group_meeting: "进展与问题 → 方法或实验 → 证据 → 风险与下一步",
  journal_club: "研究问题 → 论文方法 → 核心证据 → 局限 → 可迁移启示",
  proposal: "重要问题 → 文献缺口 → 可检验方案 → 评价设计 → 决策与计划",
  progress_report: "目标与当前状态 → 新证据 → 偏差与风险 → 后续里程碑",
  defense: "研究问题 → 原创方法 → 多层证据 → 边界 → 贡献总结",
  paper_presentation: "问题与缺口 → 方法 → 实验 → 主结果 → 局限与结论",
  custom: "问题 → 分析 → 证据 → 结论",
};

function briefFromCategory(category) {
  const guide = CATEGORY_GUIDANCE[category] ?? ["本页结论", "推进叙事", 100, 0, 0, 0, ["headline", "body_text"]];
  return {
    category_hint: category,
    title: guide[0],
    narrative_job: guide[1],
    text_chars: guide[2],
    image_count: guide[3],
    table_count: guide[4],
    chart_count: guide[5],
    content_roles: guide[6],
  };
}

function fitBlueprint(type, slideCount) {
  const base = [...(DECK_BLUEPRINTS[type] ?? DECK_BLUEPRINTS.custom)];
  if (slideCount === base.length) return base;
  if (slideCount < base.length) {
    const priority = {
      cover: 100,
      qa: 98,
      summary: 96,
      agenda: 88,
      question: 82,
      gap: 80,
      method_overview: 78,
      chart_takeaway: 76,
      single_figure: 76,
      next_steps: 74,
      limitations: 68,
      discussion: 66,
      references: 40,
      appendix: 20,
    };
    return base
      .map((category, index) => ({ category, index, priority: priority[category] ?? 60 }))
      .sort((a, b) => b.priority - a.priority || a.index - b.index)
      .slice(0, slideCount)
      .sort((a, b) => a.index - b.index)
      .map((item) => item.category);
  }
  const extension = ["single_figure", "chart_takeaway", "dual_figure", "table_chart", "case", "error", "discussion", "appendix"];
  const insertionPoint = Math.max(1, base.findIndex((category) => category === "summary"));
  let cursor = 0;
  while (base.length < slideCount) {
    base.splice(insertionPoint + cursor, 0, extension[cursor % extension.length]);
    cursor += 1;
  }
  return base;
}

function normalizeBrief(raw, index) {
  const categoryHint = raw.category_hint ?? raw.category;
  const base = categoryHint ? briefFromCategory(categoryHint) : briefFromCategory("__generic__");
  const title = String(raw.title ?? base.title ?? `第 ${index + 1} 页`).trim();
  const metrics = normalizeMetrics({
    ...base,
    ...raw,
    title_chars: raw.title_chars ?? [...title].length,
    content_roles: raw.content_roles ?? base.content_roles,
  });
  return {
    ...base,
    ...raw,
    title,
    category_hint: categoryHint,
    text_chars: metrics.textChars,
    text_chars_by_role: metrics.textCharsByRole,
    title_chars: metrics.titleChars,
    image_count: metrics.imageCount,
    table_count: metrics.tableCount,
    chart_count: metrics.chartCount,
    process_step_count: metrics.processStepCount,
    visual_aspect_ratio: metrics.visualAspectRatio,
    content_roles: metrics.contentRoles,
    viewing_mode: metrics.viewingMode,
    density_preference: metrics.densityPreference,
    allow_auto_split: metrics.allowAutoSplit,
    slot_metrics: metrics.slotMetrics,
    visuals: metrics.visuals,
  };
}

export async function createDeckPlan(input = {}) {
  const [catalog, designRegistry] = await Promise.all([loadCatalog(), loadDesignRegistry()]);
  const type = input.presentation_type ?? "group_meeting";
  if (!DECK_BLUEPRINTS[type]) throw new RangeError(`Unsupported presentation_type: ${type}`);
  const viewingMode = normalizeViewingMode(input.viewing_mode ?? "projector");
  const densityPreference = normalizeDensityPreference(input.density_preference);
  const allowAutoSplit = input.allow_auto_split ?? true;

  const suppliedBriefs = asArray(input.slide_briefs);
  let rawBriefs;
  if (suppliedBriefs.length) {
    if (suppliedBriefs.length > 40) throw new RangeError("slide_briefs supports at most 40 slides");
    rawBriefs = suppliedBriefs.map((brief) => ({
      viewing_mode: viewingMode,
      density_preference: densityPreference,
      allow_auto_split: allowAutoSplit,
      ...brief,
    }));
  } else {
    const slideCount = integer(input.slide_count, Math.min(12, DECK_BLUEPRINTS[type].length), 3, 40);
    rawBriefs = fitBlueprint(type, slideCount).map((category) => ({
      ...briefFromCategory(category),
      viewing_mode: viewingMode,
      density_preference: densityPreference,
      allow_auto_split: allowAutoSplit,
    }));
  }

  const contentModel = normalizeContentModel({
    sources: input.sources,
    citations: input.citations,
    evidence: input.evidence,
    slide_briefs: rawBriefs,
    paperworkflow_v4: input.paperworkflow_v4,
  });
  if (contentModel.status === "invalid") {
    const error = new TypeError(`Invalid content model: ${contentModel.violations.map((issue) => `${issue.field}: ${issue.message ?? issue.code}`).join("; ")}`);
    error.violations = contentModel.violations;
    throw error;
  }
  const briefs = contentModel.slide_briefs.map((brief, index) => {
    const metrics = normalizeBrief(brief, index);
    return {
      canonical: {
        ...brief,
        text_chars: metrics.text_chars,
        text_chars_by_role: metrics.text_chars_by_role,
        title_chars: metrics.title_chars,
        image_count: metrics.image_count,
        table_count: metrics.table_count,
        chart_count: metrics.chart_count,
        process_step_count: metrics.process_step_count,
        visual_aspect_ratio: metrics.visual_aspect_ratio,
        content_roles: metrics.content_roles,
        viewing_mode: metrics.viewing_mode,
        density_preference: metrics.density_preference,
        allow_auto_split: metrics.allow_auto_split,
        metadata: {
          ...(brief.metadata ?? {}),
          planning_mode: "guidance",
        },
      },
      metrics,
    };
  });

  const themeId = input.theme_id ?? "paper_blue";
  const theme = catalog.themesById.get(themeId);
  if (!theme) throw new RangeError(`Unknown theme_id: ${themeId}`);

  const usedLayoutIds = [];
  const slides = [];
  const warnings = [];
  const unplannedSlideBriefs = [];
  const planningContexts = [];
  const designTelemetry = [];
  let deckDesignState = createDeckDesignState({
    tone: input.deck_style?.tone,
    accent_strength: input.deck_style?.accent_strength,
    preferred_density: densityPreference === "低" ? "low" : densityPreference === "高" ? "high" : "medium",
  });
  let planStatus = "success";
  for (let index = 0; index < briefs.length; index += 1) {
    const { canonical, metrics } = briefs[index];
    const designIR = compileSlideDesignIR(canonical);
    const candidateRuns = [];
    let categoryRelaxed = false;
    const planning = await planSlideClosedLoop({
      slide_brief: canonical,
      ...metrics,
      categories: metrics.category_hint ? [metrics.category_hint] : undefined,
      exclude_ids: usedLayoutIds,
      allow_auto_split: metrics.allow_auto_split,
      max_replan_attempts: integer(input.max_replan_attempts, 3, 0, 20),
      k: 8,
    }, {
      searchLayouts: async (query) => {
        let result = await searchLayouts(query);
        if (!result.results.length && asArray(query.categories).length) {
          result = await searchLayouts({ ...query, categories: undefined, category: undefined });
          categoryRelaxed = true;
        }
        const candidateResult = createDesignCandidates({
          design_ir: designIR,
          layouts: result.results,
          deck_state: deckDesignState,
          registry: designRegistry,
          max_candidates: 24,
          treatments_per_layout: 2,
          decorations_per_treatment: 2,
        });
        candidateRuns.push({
          factory_version: candidateResult.factory_version,
          hard_constraint_mode: candidateResult.hard_constraint_mode,
          structural_candidate_count: result.results.length,
          raw_candidate_count: candidateResult.raw_candidate_count,
          candidate_count: candidateResult.candidate_count,
          candidate_set: candidateResult.candidate_set,
          rejected_combinations: candidateResult.rejected_combinations,
        });
        return {
          ...result,
          results: materializeRankedLayouts(candidateResult),
          design_candidate_count: candidateResult.candidate_count,
        };
      },
      getLayout,
      bindSlide: bindSlideToLayout,
    });
    planningContexts.push({
      slide_id: canonical.slide_id,
      planning_decision: planning.planning_decision,
      status: planning.status,
      replan_context: planning.replan_context,
      design_ir: designIR,
      candidate_runs: candidateRuns,
    });
    if (categoryRelaxed) warnings.push(`第 ${index + 1} 页的类别提示无法满足，已放宽到全库检索。`);
    // RPA-5: 正文语义与 category hint 冲突时给出显式提示，避免静默选到语义错位的版面。
    const semanticSignals = inferSemanticCategory(canonical, metrics.category_hint ? [metrics.category_hint] : []);
    if (semanticSignals.conflict) {
      warnings.push(
        `第 ${index + 1} 页正文含「${semanticSignals.label_zh}」信号，与类别提示「${semanticSignals.hinted_category}」冲突；`
        + `已按语义优先检索 ${semanticSignals.category} 类版面。如确需原类别，请用 --layout-override 指定。`,
      );
    }
    if (["failed", "needs_replan"].includes(planning.status)) {
      planStatus = planning.status === "failed" ? "failed" : planStatus === "failed" ? planStatus : "needs_replan";
      unplannedSlideBriefs.push(...asArray(planning.unplanned_slide_briefs ?? planning.slide_briefs));
      warnings.push(`第 ${index + 1} 个 Slide Brief 未形成合法页面（${planning.status}），请检查 replan_context。`);
      continue;
    }
    if (planning.status === "adapted" || planning.planning_decision === "split") planStatus = planStatus === "success" ? "adapted" : planStatus;
    for (const binding of planning.slides) {
      const choice = binding.layout_spec ?? {};
      const layoutId = binding.layout_id ?? choice.id ?? choice.layout_id;
      const brief = normalizeBrief(binding.slide_brief ?? canonical, slides.length);
      if (layoutId && !usedLayoutIds.includes(layoutId)) usedLayoutIds.push(layoutId);
      if ((choice.score ?? 100) < 65) warnings.push(`第 ${slides.length + 1} 页版式匹配分较低（${choice.score}），建议拆页或减少内容。`);
      const splitReasons = planning.planning_decision === "split" ? ["structural_capacity_exceeded"] : [];
      const selectedDesign = choice.design_candidate;
      const selectedRun = [...candidateRuns].reverse().find((run) => run.candidate_set.some((candidate) => candidate.candidate_id === selectedDesign?.candidate_id));
      const selectedRunCandidates = selectedRun?.candidate_set ?? [];
      const selectedCandidate = selectedRunCandidates.find((candidate) => candidate.candidate_id === selectedDesign?.candidate_id);
      const decorationProfile = selectedDesign?.decoration;
      const deckStateBefore = publicDeckDesignState(deckDesignState);
      const designContext = {
        design_ir: designIR,
        visual_treatment: selectedDesign?.treatment?.id,
        decoration_profile: decorationProfile,
        container_density: estimateContainerDensity(decorationProfile),
        deck_state_before: deckStateBefore,
      };

      slides.push({
        index: slides.length + 1,
        slide_id: brief.slide_id,
        title: brief.title,
        goal: brief.goal,
        narrative_job: brief.narrative_job,
        evidence_ids: brief.evidence_ids,
        citation_ids: brief.citation_ids,
        category: choice.category,
        layout_family: choice.family ?? choice.category,
        layout_id: layoutId,
        layout_score: choice.score,
        variant: choice.variant_name_zh,
        density: choice.density,
        content_metrics: {
          text_chars: brief.text_chars,
          text_chars_by_role: brief.text_chars_by_role,
          title_chars: brief.title_chars,
          image_count: brief.image_count,
          table_count: brief.table_count,
          chart_count: brief.chart_count,
          process_step_count: brief.process_step_count,
          visual_aspect_ratio: brief.visual_aspect_ratio,
          content_roles: brief.content_roles,
          viewing_mode: brief.viewing_mode,
          density_preference: brief.density_preference,
          allow_auto_split: brief.allow_auto_split,
          slot_metrics: brief.slot_metrics.map(publicSlotMetric),
          visuals: brief.visuals.map(publicVisualMetric),
        },
        slot_specs: binding.slot_specs,
        slot_assignments: binding.slot_assignments,
        binding_status: binding.status,
        contract_valid: binding.contract_valid,
        contract_violations: binding.contract_violations ?? [],
        violations: binding.violations ?? [],
        adaptation_log: binding.adaptation_log ?? [],
        planning_decision: planning.planning_decision,
        replan_context: planning.replan_context,
        reading_order: choice.reading_order,
        design_ir: designIR,
        visual_treatment: selectedDesign?.treatment?.id,
        decoration_profile: decorationProfile,
        container_density: estimateContainerDensity(decorationProfile),
        design_context: designContext,
        aesthetic_score: selectedDesign ? {
          score: selectedDesign.aesthetic_score,
          components: selectedDesign.aesthetic_components,
          explanation: selectedDesign.aesthetic_explanation,
        } : undefined,
        alternatives: selectedRunCandidates
          .filter((candidate) => candidate.candidate_id !== selectedDesign?.candidate_id)
          .slice(0, 4),
        readability: {
          viewing_mode: brief.viewing_mode,
          compatibility_mode: "legacy_capacity_only",
          capacity: choice.capacity,
        },
        split_recommendation: {
          recommended: Boolean(brief.allow_auto_split && splitReasons.length && planning.planning_decision !== "split"),
          applied: planning.planning_decision === "split",
          reasons: splitReasons,
        },
        preview_path: choice.preview_path,
      });
      if (selectedDesign) {
        deckDesignState = updateDeckDesignState(deckDesignState, {
          layout: choice,
          treatment: selectedDesign.treatment,
          decoration: selectedDesign.decoration,
          design_ir: designIR,
        });
      }
      const deckStateAfter = publicDeckDesignState(deckDesignState);
      designTelemetry.push({
        slide_id: brief.slide_id,
        design_ir: designIR,
        candidate_set: selectedRunCandidates,
        selected_candidate: selectedCandidate ?? null,
        hard_filter: {
          mode: "existing_structural_gate_before_design_ranking",
          structural_candidates: selectedRun?.structural_candidate_count ?? 0,
          design_candidates: selectedRunCandidates.length,
        },
        deck_state_before: deckStateBefore,
        deck_state_after: deckStateAfter,
        human_override: null,
      });
    }
  }

  const designQa = evaluateDeckDesign(slides);

  return {
    pipeline_status: PIPELINE_STATUS.plan,
    deck_title: input.topic ? `${input.topic}｜科研汇报规划` : "科研汇报规划",
    presentation_type: type,
    audience: input.audience ?? "课题组成员与科研合作者",
    purpose: input.purpose ?? "同步研究进展、审视证据并明确下一步",
    narrative_arc: NARRATIVE_ARCS[type],
    viewing_profile: getViewingProfile(viewingMode),
    density_preference: densityPreference ?? "中",
    allow_auto_split: Boolean(allowAutoSplit),
    status: planStatus,
    production_status: planStatus,
    design_status: designQa.status,
    design_score: designQa.score,
    design_qa: designQa,
    content_model: contentModel,
    theme,
    requested_slide_count: briefs.length,
    slide_count: slides.length,
    slides,
    unplanned_slide_briefs: unplannedSlideBriefs,
    planning_contexts: planningContexts,
    deck_design_state: publicDeckDesignState(deckDesignState),
    design_telemetry: designTelemetry,
    warnings,
    renderer_contract: {
      slide_size_in: catalog.meta.slide_size_in,
      coordinate_source: "Use each slot_specs[].pptx_in value without changing the layout hierarchy; bind content through slot_assignments[slot_id].",
      reflow_policy: "Collapse unused optional slots and expand neighboring priority content before reducing font size.",
      final_check: "Call validate_slide before rendering, then validate_rendered_deck with actual font, footprint, empty-band, and visual telemetry after export.",
    },
  };
}

function addIssue(issues, severity, code, message, suggestion, details = {}) {
  const normalizedDetails = details && typeof details === "object" && !Array.isArray(details) ? details : {};
  const recommendedAction = /CAPACITY|OVERFLOW|FONT|DENSE|SPLIT/.test(code)
    ? "replan_or_split"
    : /MISSING/.test(code)
      ? "provide_required_input"
      : /INVALID|UNKNOWN|MISMATCH|DUPLICATE/.test(code)
        ? "correct_input"
        : "review";
  issues.push(createViolation({
    code,
    field: normalizedDetails.field ?? "input",
    actual: normalizedDetails.actual ?? null,
    capacity: normalizedDetails.capacity ?? null,
    severity,
    recoverable: code !== "INTERNAL_ERROR",
    recommended_action: recommendedAction,
    message,
    suggestion,
    details: Object.keys(normalizedDetails).length ? normalizedDetails : undefined,
  }));
}

function rawSlotType(slot) {
  const type = String(slot?.type ?? slot?.slot_type ?? "").trim().toLowerCase();
  if (type === "image") return "figure";
  return type;
}

function publicSlotType(slot) {
  return canonicalSlotType(slot);
}

function assignmentTypeMatches(slot, assignmentType) {
  if (assignmentType === "guidance") return true;
  const slotType = publicSlotType(slot);
  const accepted = {
    text: new Set(["text"]),
    image: new Set(["image"]),
    chart: new Set(["chart", "image"]),
    table: new Set(["table"]),
    process: new Set(["process", "text"]),
    timeline: new Set(["timeline", "text"]),
  }[slotType] ?? new Set([slotType]);
  return accepted.has(assignmentType);
}

function validateAssignmentCapacity(issues, slot, assignment, assignmentType) {
  if (assignmentType === "guidance" || typeof assignment.text !== "string") return;
  const actual = [...assignment.text].length;
  const recommendedCapacity = slot.max_chars_at_min_font;
  const absoluteCapacity = slot.max_chars_at_absolute_min;
  if (Number.isFinite(absoluteCapacity) && actual > absoluteCapacity) {
    addIssue(
      issues,
      "error",
      "SLOT_CAPACITY_EXCEEDED",
      `slot_assignments[${slot.id}] 的 ${actual} 字超过绝对容量 ${absoluteCapacity} 字。`,
      "缩短内容、换版式或拆页；不要通过缩小到绝对字号下限以下来容纳。",
      { field: "slot_assignments", slot_id: slot.id, actual, capacity: absoluteCapacity },
    );
  } else if (Number.isFinite(recommendedCapacity) && actual > recommendedCapacity) {
    addIssue(
      issues,
      "warning",
      "SLOT_CAPACITY_NEAR_LIMIT",
      `slot_assignments[${slot.id}] 的 ${actual} 字超过推荐容量 ${recommendedCapacity} 字。`,
      "优先精简文本或选择容量更大的槽位，并在渲染后检查实际换行。",
      { field: "slot_assignments", slot_id: slot.id, actual, capacity: recommendedCapacity },
    );
  }
}

function validateSlotContract(issues, layout, slotSpecs, assignments) {
  const slots = layout.slots ?? [];
  const byId = new Map(slots.map((slot) => [slot.id, slot]));

  if (slotSpecs !== undefined) {
    if (!Array.isArray(slotSpecs)) {
      addIssue(issues, "error", "INVALID_LAYOUT_SPEC", "slot_specs 必须是数组。", "传入 Planner 输出的 slot_specs 数组。");
    } else {
      const seen = new Set();
      for (const [index, spec] of slotSpecs.entries()) {
        if (!spec || typeof spec !== "object" || Array.isArray(spec)) {
          addIssue(issues, "error", "INVALID_LAYOUT_SPEC", `slot_specs[${index}] 必须是对象。`, "每个 slot spec 至少包含 slot_id、slot_type、required 和 capacity。");
          continue;
        }
        const slotId = String(spec.slot_id ?? "").trim();
        const slotType = String(spec.slot_type ?? "").trim().toLowerCase();
        if (!slotId || !slotType || typeof spec.required !== "boolean" || !spec.capacity || typeof spec.capacity !== "object" || Array.isArray(spec.capacity) || !("max_chars" in spec.capacity)) {
          addIssue(issues, "error", "INVALID_LAYOUT_SPEC", `slot_specs[${index}] 结构不完整。`, "每个 slot spec 至少包含 slot_id、slot_type、required 和 capacity。");
          continue;
        }
        if (seen.has(slotId)) {
          addIssue(issues, "error", "INVALID_LAYOUT_SPEC", `slot_specs 重复定义了 ${slotId}。`, "每个 slot_id 只能定义一次。");
          continue;
        }
        seen.add(slotId);
        const actual = byId.get(slotId);
        if (!actual) {
          addIssue(issues, "error", "INVALID_EXPLICIT_SLOT", `slot_specs 包含未知槽位 ${slotId}。`, "使用 get_layout 返回的精确 slot_id。", { field: "slot_specs", slot_id: slotId });
          continue;
        }
        if (publicSlotType(actual) !== canonicalAssignmentType(slotType) || spec.required !== !actual.optional) {
          addIssue(issues, "error", "INVALID_LAYOUT_SPEC", `slot_specs 中 ${slotId} 的类型或 required 标记与 layout 不一致。`, "不要修改 Layout 的 slot spec；重新使用 get_layout 或 Planner 输出。", { field: "slot_specs", slot_id: slotId });
        }
        const expectedCapacity = publicSlotSpec(actual).capacity;
        for (const key of Object.keys(expectedCapacity)) {
          if (key in spec.capacity && spec.capacity[key] !== expectedCapacity[key]) {
            addIssue(issues, "error", "INVALID_LAYOUT_SPEC", `slot_specs 中 ${slotId} 的 capacity.${key} 与 layout 不一致。`, "不要修改 Layout 的容量定义；重新使用 get_layout 或 Planner 输出。", { field: "slot_specs", slot_id: slotId });
          }
        }
      }
      for (const slot of slots) {
        if (!seen.has(slot.id)) {
          addIssue(issues, "error", "INVALID_LAYOUT_SPEC", `slot_specs 缺少 Layout 槽位 ${slot.id}。`, "完整传入 get_layout 或 Planner 返回的 slot_specs；不要省略 Layout 定义。", { field: "slot_specs", slot_id: slot.id });
        }
      }
    }
  }

  if (assignments !== undefined && (!assignments || typeof assignments !== "object" || Array.isArray(assignments))) {
    addIssue(issues, "error", "INVALID_SLOT_ASSIGNMENTS", "slot_assignments 必须是以 slot_id 为键的对象。", "使用 { \"title\": { \"type\": \"text\", \"text\": \"...\" } } 的结构。");
    return;
  }
  const assignmentMap = assignments ?? {};
  for (const slot of slots.filter((item) => !item.optional)) {
    const value = assignmentMap[slot.id];
    if (value === undefined || value === null || !assignmentHasContent(value)) {
      addIssue(issues, "error", "MISSING_REQUIRED_SLOT", `必需槽位 ${slot.id}（${slot.label_zh}）尚未填充。`, "为该 slot_id 提供非空结构化 assignment。", { field: "slot_assignments", slot_id: slot.id });
    }
  }
  for (const [slotId, assignment] of Object.entries(assignmentMap)) {
    const slot = byId.get(slotId);
    if (!slot) {
      addIssue(issues, "error", "INVALID_EXPLICIT_SLOT", `slot_assignments 包含未知槽位 ${slotId}。`, "使用 get_layout 返回的精确 slot_id；不会自动回退到其他槽位。", { field: "slot_assignments", slot_id: slotId });
      continue;
    }
    if (!assignment || typeof assignment !== "object" || Array.isArray(assignment) || typeof assignment.type !== "string" || !assignment.type.trim() || !assignmentHasContent(assignment)) {
      addIssue(issues, "error", "INVALID_SLOT_ASSIGNMENT", `slot_assignments[${slotId}] 必须是包含 type 和非空内容的结构化对象。`, "例如 { type: \"text\", text: \"...\" }；规划器指导使用 type: \"guidance\"。", { field: "slot_assignments", slot_id: slotId });
      continue;
    }
    const assignmentType = canonicalAssignmentType(assignment.type);
    if (!assignmentTypeMatches(slot, assignmentType)) {
      addIssue(issues, "error", "SLOT_TYPE_MISMATCH", `slot_assignments[${slotId}] 的 type=${assignment.type} 与 slot_type=${publicSlotType(slot)} 不兼容。`, "使用匹配的 text、image、chart、table、process 或 guidance assignment。", { field: "slot_assignments", slot_id: slotId });
      continue;
    }
    validateAssignmentCapacity(issues, slot, assignment, assignmentType);
  }
}

function validateSlotReadability(issues, effectiveLayout, slotMetrics) {
  const byId = new Map((effectiveLayout.slots ?? []).map((slot) => [slot.id, slot]));
  for (const item of slotMetrics) {
    const slot = byId.get(item.slotId);
    if (!slot) {
      addIssue(issues, "error", "INVALID_EXPLICIT_SLOT", `slot_metrics 包含未知槽位 ${item.slotId || "（空）"}。`, "使用 get_layout 返回的精确 slot_id；不会自动回退。", { field: "slot_metrics", slot_id: item.slotId });
      continue;
    }
    if (item.textChars > (slot.max_chars_at_absolute_min ?? Infinity)) {
      addIssue(issues, "error", "SLOT_TEXT_OVERFLOW", `${slot.id} 的 ${item.textChars} 字超过绝对字号下限容量 ${slot.max_chars_at_absolute_min} 字。`, "缩短文本、扩大槽位、换版式或拆页；不要继续缩小字号。");
    } else if (item.textChars > (slot.max_chars_at_min_font ?? Infinity)) {
      addIssue(issues, "warning", "SLOT_TEXT_NEAR_FONT_FLOOR", `${slot.id} 在推荐字号下最多约容纳 ${slot.max_chars_at_min_font} 字，当前为 ${item.textChars} 字。`, "优先精简文本或让相邻空槽折叠扩展该槽位。");
    }
  }
}

export async function validateSlide(input = {}) {
  const catalog = await loadCatalog();
  const layoutId = input.layout_id;
  const layout = catalog.byId.get(layoutId);
  if (!layout) throw new RangeError(`Unknown layout_id: ${layoutId}`);
  const metrics = normalizeMetrics({ ...input, ...(input.content_metrics ?? {}) });
  const effectiveLayout = enrichLayoutReadability(layout, metrics.viewingMode);
  const readability = layoutReadability(layout, metrics);
  const profile = layout.content_profile ?? {};
  const issues = [];

  const compatibility = evaluateLayoutCompatibility(layout, metrics);
  for (const violation of compatibility.violations) {
    addIssue(
      issues,
      "error",
      violation.code,
      violation.message,
      violation.recommended_action,
      {
        field: violation.field,
        actual: violation.actual,
        capacity: violation.capacity,
      },
    );
  }

  if (metrics.textChars <= layout.max_text_chars && metrics.textChars > layout.max_text_chars * 0.85) {
    addIssue(issues, "warning", "TEXT_NEAR_LIMIT", `正文已使用约 ${Math.round((metrics.textChars / layout.max_text_chars) * 100)}% 的建议容量。`, "装填真实文本后检查换行与最小字号。");
  }
  const supportedRoles = new Set(layout.content_roles ?? []);
  const unsupportedRoles = metrics.contentRoles.filter((role) => !supportedRoles.has(role));
  if (unsupportedRoles.length) {
    addIssue(issues, "warning", "ROLE_MISMATCH", `版式未显式支持角色：${unsupportedRoles.join(", ")}。`, "检查候选版式的 content_roles 或重新检索。");
  }

  validateSlotReadability(issues, effectiveLayout, metrics.slotMetrics);

  const knownSlotIds = new Set(layout.slots.map((slot) => slot.id));
  const visualSlotIds = new Set(
    layout.slots.filter((slot) => ["figure", "chart", "table"].includes(slot.type)).map((slot) => slot.id),
  );
  for (const visual of metrics.visuals) {
    if (visual.slotId && !knownSlotIds.has(visual.slotId)) {
      addIssue(issues, "error", "INVALID_EXPLICIT_SLOT", `visuals 指定了未知槽位 ${visual.slotId}。`, "使用 get_layout 返回的精确 slot_id；不会自动回退到其他视觉槽。", { field: "visuals", slot_id: visual.slotId });
    } else if (visual.slotId && !visualSlotIds.has(visual.slotId)) {
      addIssue(issues, "error", "SLOT_TYPE_MISMATCH", `visuals 指定的 ${visual.slotId} 不是视觉槽位。`, "为视觉内容使用 figure、chart 或 table 槽位；不会自动回退。", { field: "visuals", slot_id: visual.slotId });
    }
  }

  const placements = analyzeVisualPlacements(layout, metrics);
  for (const placement of placements) {
    if (!placement.slot_id) {
      addIssue(issues, "error", "VISUAL_SLOT_SHORTAGE", `${placement.visual_type} 没有可用的视觉槽位。`, "选择具有足够视觉证据槽的版式。");
    }
  }

  validateSlotContract(issues, effectiveLayout, input.slot_specs, input.slot_assignments);

  const recommendation = await searchLayouts({ ...input, categories: [layout.category], k: 8 });
  const current = recommendation.results.find((result) => result.id === layoutId);
  const hasError = issues.some((issue) => issue.severity === "error");
  const hasWarning = issues.some((issue) => issue.severity === "warning");
  return {
    layout_id: layoutId,
    status: hasError ? "invalid" : hasWarning ? "warning" : "valid",
    score: current?.score,
    metrics: {
      text_chars: metrics.textChars,
      text_chars_by_role: metrics.textCharsByRole,
      title_chars: metrics.titleChars,
      image_count: metrics.imageCount,
      table_count: metrics.tableCount,
      chart_count: metrics.chartCount,
      visual_aspect_ratio: metrics.visualAspectRatio,
      content_roles: metrics.contentRoles,
      viewing_mode: metrics.viewingMode,
      process_step_count: metrics.processStepCount,
      slot_metrics: metrics.slotMetrics,
      visuals: metrics.visuals,
    },
    capacity: {
      max_text_chars: layout.max_text_chars,
      image_capacity: profile.image_capacity ?? 0,
      table_capacity: profile.table_capacity ?? 0,
      chart_capacity: profile.chart_capacity ?? 0,
      process_capacity: compatibility.capacities.process_capacity,
      title_chars_at_min_font: readability.title_capacity_chars,
      body_chars_at_min_font: readability.body_capacity_chars,
      minimum_title_font_pt: effectiveLayout.constraints?.minimum_title_font_pt,
      minimum_body_font_pt: effectiveLayout.constraints?.minimum_body_font_pt,
      absolute_minimum_body_font_pt: effectiveLayout.constraints?.absolute_minimum_body_font_pt,
      content_footprint_target: effectiveLayout.constraints?.target_content_footprint,
      maximum_empty_band: effectiveLayout.constraints?.maximum_empty_band,
    },
    layout_geometry: readability.geometry,
    visual_placements: placements,
    reflow_actions: [
      "collapse_unused_optional_slots",
      "expand_adjacent_priority_content",
      "switch_layout",
      "split_slide",
      "reduce_font_only_above_absolute_floor",
    ],
    issues,
  };
}

function renderedSlideTextBlocks(telemetry) {
  const elements = asArray(telemetry?.elements);
  return elements
    .map((element) => {
      const text = element?.text;
      if (typeof text === "string") return text;
      if (text && typeof text === "object") return text.content ?? text.preview ?? text.raw ?? "";
      return element?.content ?? element?.textPreview ?? "";
    })
    .filter((value) => typeof value === "string" && value.trim())
    .map((value) => value.trim());
}

function renderedSlideText(telemetry) {
  return renderedSlideTextBlocks(telemetry).join("\n");
}

function bigramSet(text) {
  const normalized = String(text).replace(/\s+/g, "");
  const grams = new Set();
  for (let index = 0; index < normalized.length - 1; index += 1) {
    grams.add(normalized.slice(index, index + 2));
  }
  return grams;
}

function coverageRatio(declaredText, renderedText) {
  const declared = bigramSet(declaredText);
  if (declared.size === 0) return null;
  const rendered = bigramSet(renderedText);
  let hit = 0;
  for (const gram of declared) if (rendered.has(gram)) hit += 1;
  return hit / declared.size;
}

const TEXT_SPARSITY_CONFIG = {
  // 期望承载完整科学论证（成段正文）的分类：这些页必须有实质段落，不能只有标签。
  content_heavy_categories: new Set([
    "theory", "case", "discussion", "limitations", "method_overview", "question", "background",
  ]),
  min_paragraph_chars: 16,      // 最长文本块低于此 → 页面只有标题/标签碎片，无正文（error）
  min_body_depth_chars: 40,     // 低于此（但 ≥16）→ 有句子无段落，深度不足（warning）
  summary_min_chars: 30,        // 结论页正文总长低于此 → warning
};

function textSparsityIssues({ blocks = [], category } = {}) {
  const issues = [];
  const normalizedCategory = String(category ?? "").toLowerCase();
  if (!normalizedCategory) return issues;
  const normalized = blocks.map((block) => String(block).replace(/\s+/g, ""));
  const totalChars = normalized.reduce((sum, block) => sum + block.length, 0);
  const longestBlock = normalized.reduce((max, block) => Math.max(max, block.length), 0);
  const details = {
    field: "rendered_text",
    actual: { longest_block_chars: longestBlock, total_chars: totalChars, block_count: normalized.length },
  };

  if (TEXT_SPARSITY_CONFIG.content_heavy_categories.has(normalizedCategory)) {
    if (longestBlock < TEXT_SPARSITY_CONFIG.min_paragraph_chars) {
      addIssue(issues, "error", "TEXT_SPARSITY",
        `正文内容过于单薄：最长文本块仅 ${longestBlock} 字，页面只有短标签碎片，缺少成句的科学论证。`,
        "把 brief 的 body 完整段落渲染进正文槽，而非只放 ≤16 字的标签式 claim；正文应至少有一句完整的机理/结论表述。",
        details);
    } else if (longestBlock < TEXT_SPARSITY_CONFIG.min_body_depth_chars) {
      addIssue(issues, "warning", "TEXT_SPARSITY",
        `正文深度不足：最长文本块 ${longestBlock} 字，有句子但缺少完整段落论证。`,
        "扩充正文为完整段落（≥40 字），把证据结论展开，而非一句话带过。",
        details);
    }
  } else if (normalizedCategory === "summary" && totalChars < TEXT_SPARSITY_CONFIG.summary_min_chars) {
    addIssue(issues, "warning", "TEXT_SPARSITY",
      `结论页正文过于单薄：总文本仅 ${totalChars} 字，未承载结论、局限与展望。`,
      "结论页应至少包含核心结论、局限与下一步，而非一句短句带过。",
      details);
  }
  return issues;
}

function evidenceCoverageIssues({ renderedText, declaredEvidence = [], declaredBody = "" }) {
  const issues = [];
  const leaked = [...String(renderedText).matchAll(/\bEV\d{4}\b/g)].map((match) => match[0]);
  const uniqueLeaked = [...new Set(leaked)];
  if (uniqueLeaked.length) {
    addIssue(
      issues,
      "warning",
      "EVIDENCE_ID_LEAKED_TO_SLIDE",
      `页面文本中出现了溯源证据编号：${uniqueLeaked.join(", ")}。汇报页不应暴露内部溯源元数据。`,
      "把正文/图注中的 EV 编号替换为语义标签或直接删除；证据溯源只保留在链路侧数据中，不进入听众可见页面。",
      { field: "rendered_text", actual: uniqueLeaked },
    );
  }
  const normalizedRendered = String(renderedText).replace(/\s+/g, "");

  if (declaredBody) {
    const needle = String(declaredBody).replace(/\s+/g, "");
    const ratio = coverageRatio(needle, normalizedRendered);
    if (!normalizedRendered.includes(needle) && (ratio === null || ratio < 0.5)) {
      addIssue(issues, "warning", "EVIDENCE_COVERAGE_GAP",
        `声明的正文 body 未充分落到渲染页（覆盖度 ${ratio === null ? 0 : Math.round(ratio * 100)}%）。`,
        "确认 brief 的 body 正文已渲染到 text 槽；若已改写请保证语义等价并同步 body。",
        { field: "declared_body", actual: { coverage: ratio } });
    }
  }

  for (const evidence of asArray(declaredEvidence)) {
    const id = evidence?.evidence_id ?? evidence?.evidenceId;
    const text = evidence?.text ?? evidence?.content ?? evidence?.claim ?? "";
    if (!id) continue;
    const needle = String(text).replace(/\s+/g, "");
    if (!needle) continue;
    const exact = normalizedRendered.includes(needle);
    const ratio = needle.length <= 8 ? (exact ? 1 : 0) : coverageRatio(needle, normalizedRendered);
    if (ratio === null || ratio < 0.5) {
      addIssue(issues, "warning", "EVIDENCE_COVERAGE_GAP",
        `声明引用的证据 ${id} 的内容未在渲染页文本中找到${ratio !== null ? `（覆盖度 ${Math.round(ratio * 100)}%）` : ""}。`,
        "确认该证据的结论已落到页面正文；若已改写请同步更新 brief 的 evidence_ids，或提供改写后的等价文本。",
        { field: "declared_evidence", actual: id });
    }
  }
  return issues;
}

export async function validateRenderedSlide(input = {}) {
  const catalog = await loadCatalog();
  const layoutId = input.layout_id ?? input.layoutId;
  const layout = layoutId ? catalog.byId.get(layoutId) : undefined;
  if (layoutId && !layout) throw new RangeError(`Unknown layout_id: ${layoutId}`);
  const viewingMode = normalizeViewingMode(input.viewing_mode ?? input.viewingMode);
  const category = input.category ?? input.slide?.category ?? layout?.category;
  const legacyInput = input.telemetry === undefined && input.renderer_output === undefined;
  const telemetry = input.telemetry
    ?? (input.renderer_output ? adaptRendererTelemetry(input.renderer_output) : adaptLegacyRenderedSlide(input));
  const baselineTelemetry = input.preserve_layout_relations === false
    ? null
    : input.baseline_telemetry
      ?? (input.baseline_renderer_output ? adaptRendererTelemetry(input.baseline_renderer_output) : null);
  const report = await evaluateVisualQuality({
    telemetry,
    profile: input.quality_profile,
    profile_id: input.quality_profile_id,
    presentation_intent: input.presentation_intent ?? input.design_ir?.presentation_intent,
    design_context: input.design_context,
    repair_context: input.repair_context,
    render_artifact: input.render_artifact,
    context: {
      viewing_mode: viewingMode,
      category,
      layout_id: layoutId,
      legacy_compatibility: legacyInput,
      enforce_typography: input.enforce_typography === true,
      baseline_telemetry: baselineTelemetry,
      layout_drift_tolerance: finiteNumber(input.layout_drift_tolerance ?? input.layoutDriftTolerance, 0.08, 0, 1),
    },
  });
  const renderedTextBlocks = renderedSlideTextBlocks(telemetry);
  const renderedText = renderedTextBlocks.join("\n");
  const coverageIssues = evidenceCoverageIssues({
    renderedText,
    declaredEvidence: input.declared_evidence ?? input.declaredEvidence,
    declaredBody: input.declared_body ?? input.declaredBody,
  });
  const sparsityIssues = textSparsityIssues({ blocks: renderedTextBlocks, category });
  const contentIssues = [...coverageIssues, ...sparsityIssues];
  const allViolations = [...(report.violations ?? []), ...contentIssues];
  const hasContentError = contentIssues.some((issue) => issue.severity === "error");
  const hasContentWarning = contentIssues.length > 0;
  const legacyStatus = report.checks.legacy_readability?.status;
  const readabilityStatus = legacyStatus === "fail"
    ? "invalid"
    : legacyStatus === "pass"
      ? "valid"
      : "warning";
  const overallStatus = report.status === "fail" || hasContentError
    ? "invalid"
    : report.status === "pass" && !hasContentWarning
      ? "valid"
      : "warning";
  return {
    pipeline_status: PIPELINE_STATUS.renderQa,
    slide_number: input.slide_number ?? input.slideNumber,
    layout_id: layoutId,
    category,
    viewing_mode: viewingMode,
    status: overallStatus,
    overall_status: overallStatus,
    readability_status: readabilityStatus,
    visual_quality_status: report.status,
    production_status: report.production_status,
    design_status: report.design_status,
    repair_status: report.repair_status,
    design_observation: report.design_observation,
    repair_plan: report.repair_plan,
    profile_id: report.profile_id,
    profile_version: report.profile_version,
    checks: report.checks,
    metrics: report.metrics,
    violations: allViolations,
    issues: allViolations,
    evidence_coverage_issues: coverageIssues,
    text_sparsity_issues: sparsityIssues,
    recommended_action: report.recommended_action,
    reasons: report.reasons,
    manual_review: report.manual_review,
  };
}

export async function validateRenderedDeck(input = {}) {
  const slides = asArray(input.slides);
  if (!slides.length) throw new RangeError("slides must contain at least one rendered slide telemetry object");
  if (slides.length > 200) throw new RangeError("validate_rendered_deck supports at most 200 slides");
  const viewingMode = normalizeViewingMode(input.viewing_mode ?? input.viewingMode);
  const results = [];
  for (let index = 0; index < slides.length; index += 1) {
    results.push(await validateRenderedSlide({
      viewing_mode: viewingMode,
      slide_number: index + 1,
      ...slides[index],
    }));
  }
  const issueCounts = {};
  for (const result of results) {
    for (const issue of result.issues) issueCounts[issue.code] = (issueCounts[issue.code] ?? 0) + 1;
  }
  const textSparsityInvalidSlides = results
    .filter((result) => (result.text_sparsity_issues ?? []).some((issue) => issue.severity === "error"))
    .map((result) => result.slide_number);
  const textSparsityWarningSlides = results
    .filter((result) => (result.text_sparsity_issues ?? []).length > 0)
    .map((result) => result.slide_number);
  const invalidSlides = results.filter((result) => result.status === "invalid").map((result) => result.slide_number);
  const warningSlides = results.filter((result) => result.status === "warning").map((result) => result.slide_number);
  const manualReviewSlides = results.filter((result) => result.manual_review?.length).map((result) => result.slide_number);
  const readabilityInvalidSlides = results.filter((result) => result.readability_status === "invalid").map((result) => result.slide_number);
  const readabilityWarningSlides = results.filter((result) => result.readability_status === "warning").map((result) => result.slide_number);
  const readabilityStatus = readabilityInvalidSlides.length ? "invalid" : readabilityWarningSlides.length ? "warning" : "valid";
  const visualStatuses = results.map((result) => result.visual_quality_status);
  const visualQualityStatus = visualStatuses.includes("fail")
    ? "fail"
    : visualStatuses.includes("warning")
      ? "warning"
      : visualStatuses.length && visualStatuses.every((status) => status === "not_evaluable")
        ? "not_evaluable"
        : visualStatuses.includes("not_evaluable")
          ? "warning"
          : "pass";
  const overallStatus = invalidSlides.length ? "invalid" : warningSlides.length ? "warning" : "valid";
  const productionStatuses = results.map((result) => result.production_status);
  const productionStatus = productionStatuses.includes("fail")
    ? "fail"
    : productionStatuses.includes("warning")
      ? "warning"
      : productionStatuses.length && productionStatuses.every((status) => status === "not_evaluable")
        ? "not_evaluable"
        : productionStatuses.includes("not_evaluable") ? "warning" : "pass";
  const designStatuses = results.map((result) => result.design_status);
  const designStatus = designStatuses.includes("blocked")
    ? "blocked"
    : designStatuses.includes("manual_review_required")
      ? "manual_review_required"
      : designStatuses.includes("repairable") ? "repairable" : "pass";
  const repairStatuses = results.map((result) => result.repair_status);
  const repairStatus = repairStatuses.includes("blocked")
    ? "blocked"
    : repairStatuses.includes("manual_review_required")
      ? "manual_review_required"
      : repairStatuses.includes("repair_required") ? "repair_required" : "keep";
  const repairSlides = results.filter((result) => result.repair_plan?.action !== "KEEP").map((result) => result.slide_number);
  const repairActions = Object.fromEntries(results.map((result) => [result.slide_number, result.repair_plan?.action ?? "KEEP"]));
  const needsTelemetry = results.some((result) => result.issues.some((issue) => issue.recommended_action === "provide_required_input"));
  return {
    pipeline_status: PIPELINE_STATUS.renderQa,
    status: overallStatus,
    overall_status: overallStatus,
    readability_status: readabilityStatus,
    visual_quality_status: visualQualityStatus,
    production_status: productionStatus,
    design_status: designStatus,
    repair_status: repairStatus,
    viewing_mode: viewingMode,
    slide_count: slides.length,
    invalid_slides: invalidSlides,
    warning_slides: warningSlides,
    manual_review_slides: manualReviewSlides,
    repair_slides: repairSlides,
    repair_actions: repairActions,
    readability_invalid_slides: readabilityInvalidSlides,
    readability_warning_slides: readabilityWarningSlides,
    text_sparsity_invalid_slides: textSparsityInvalidSlides,
    text_sparsity_warning_slides: textSparsityWarningSlides,
    issue_counts: issueCounts,
    slides: results,
    next_action: repairStatus === "blocked" || repairStatus === "manual_review_required"
      ? needsTelemetry
        ? "Provide the missing renderer telemetry, preserve the render/evidence lineage, and escalate if the evidence remains incomplete."
        : "Preserve the render and evidence lineage and escalate the listed slides for human review."
      : repairStatus === "repair_required"
        ? "Apply each slide's deterministic repair_plan once, re-render, and repeat validation within the two-iteration budget."
        : invalidSlides.length
      ? "Reflow or split invalid slides, render again, and repeat validate_rendered_deck."
      : warningSlides.length
        ? needsTelemetry
          ? "Provide the missing renderer telemetry for warning slides, then repeat validate_rendered_deck before accepting the result."
          : "Inspect warning slides at full size and either reflow them or explicitly accept intentional whitespace."
        : manualReviewSlides.length
          ? "Review the listed raster-text visuals at full size; unmeasured raster text did not change the deck release status."
        : "Rendered deck satisfies the configured readability contract.",
  };
}

function codePointLength(value) {
  return [...String(value ?? "")].length;
}

/**
 * 把 slide brief 的"声明指标"与"源内容真实规模"独立交叉比对。
 * 这是打破 validate-deck 同源背书的一层：用 visuals 数组长度、title 码点长度
 * 这类"不来自任何声明字段"的事实，去核对 brief 与 plan 里写死的 image_count/title_chars。
 */
function crossCheckContentModel(slides, briefs) {
  const divergences = [];
  const length = Math.min(slides.length, briefs.length);
  for (let index = 0; index < length; index += 1) {
    const slide = slides[index];
    const brief = briefs[index] ?? {};
    const metrics = slide.content_metrics ?? {};
    const visuals = asArray(brief.visuals);
    const declaredImage = Number.isFinite(brief.image_count) ? brief.image_count : undefined;
    const declaredTitle = Number.isFinite(brief.title_chars) ? brief.title_chars : undefined;
    const declaredText = Number.isFinite(brief.text_chars) ? brief.text_chars : undefined;
    const recomputedImage = visuals.length;
    const recomputedTitle = codePointLength(brief.title);
    const findings = [];
    if (declaredImage !== undefined && declaredImage !== recomputedImage) {
      findings.push(`brief.image_count=${declaredImage} 但 visuals 数组实际长度=${recomputedImage}`);
    }
    if (declaredTitle !== undefined && declaredTitle !== recomputedTitle) {
      findings.push(`brief.title_chars=${declaredTitle} 但 title 实际码点长度=${recomputedTitle}`);
    }
    if (metrics.image_count !== undefined && declaredImage !== undefined && Number(metrics.image_count) !== declaredImage) {
      findings.push(`plan.content_metrics.image_count=${metrics.image_count} 但 brief.image_count=${declaredImage}`);
    }
    if (metrics.title_chars !== undefined && declaredTitle !== undefined && Number(metrics.title_chars) !== declaredTitle) {
      findings.push(`plan.content_metrics.title_chars=${metrics.title_chars} 但 brief.title_chars=${declaredTitle}`);
    }
    if (metrics.text_chars !== undefined && declaredText !== undefined && Number(metrics.text_chars) !== declaredText) {
      findings.push(`plan.content_metrics.text_chars=${metrics.text_chars} 但 brief.text_chars=${declaredText}`);
    }
    if (findings.length) {
      divergences.push({ index: index + 1, slide_id: slide.slide_id, findings });
    }
  }
  return divergences;
}

export async function validateDeckPlan(input = {}) {
  const catalog = await loadCatalog();
  const slides = asArray(input.slides ?? input.deck?.slides);
  if (!slides.length) throw new RangeError("slides must contain at least one slide specification");
  if (slides.length > 80) throw new RangeError("validate_deck_plan supports at most 80 slides");
  const themeId = input.theme_id ?? input.deck?.theme?.id;
  const deckIssues = [];
  if (themeId && !catalog.themesById.has(themeId)) {
    addIssue(deckIssues, "error", "UNKNOWN_THEME", `未知主题 ${themeId}。`, "调用 catalog_summary 选择有效 theme_id。");
  }

  const briefs = asArray(input.content_model?.slide_briefs ?? input.content_model?.slideBriefs);
  const crossChecked = briefs.length > 0;
  const divergences = crossChecked ? crossCheckContentModel(slides, briefs) : [];
  for (const divergence of divergences) {
    addIssue(
      deckIssues,
      "warning",
      "DECLARED_METRICS_MISMATCH",
      `第 ${divergence.index} 页声明的指标与源内容不一致：${divergence.findings.join("；")}。`,
      "以源 brief 的实际内容为准重新声明 content_metrics；不要手填与素材规模不符的指标。",
      { field: "content_model", actual: divergence.findings },
    );
  }

  const results = [];
  const seen = new Map();
  for (let index = 0; index < slides.length; index += 1) {
    const slide = slides[index];
    const layoutId = slide.layout_id;
    const validation = await validateSlide({
      ...slide,
      ...(slide.content_metrics ?? {}),
      layout_id: layoutId,
    });
    results.push({
      index: index + 1,
      ...validation,
      metric_provenance: crossChecked ? "cross_checked_against_content_model" : "declared_not_verified",
    });
    if (index > 0 && slides[index - 1].layout_id === layoutId) {
      addIssue(deckIssues, "warning", "ADJACENT_LAYOUT_REPEAT", `第 ${index} 与 ${index + 1} 页连续使用 ${layoutId}。`, "从 alternatives 中选择不同变体。");
    }
    seen.set(layoutId, (seen.get(layoutId) ?? 0) + 1);
  }
  for (const [layoutId, count] of seen.entries()) {
    if (count >= 3) addIssue(deckIssues, "warning", "LAYOUT_OVERUSE", `${layoutId} 在整套中使用了 ${count} 次。`, "增加版式轮廓多样性，但保持同一视觉主题。");
  }

  const categories = slides.map((slide) => catalog.byId.get(slide.layout_id)?.category).filter(Boolean);
  if (!categories.includes("summary")) addIssue(deckIssues, "warning", "MISSING_SUMMARY", "整套中没有 summary 页面。", "在结尾综合核心结论和下一步。");
  if (!categories.includes("cover")) addIssue(deckIssues, "warning", "MISSING_COVER", "整套中没有 cover 页面。", "添加简洁封面或确认这是截取的部分页面。");

  const hasError = deckIssues.some((issue) => issue.severity === "error") || results.some((result) => result.status === "invalid");
  const hasWarning = deckIssues.length > 0 || results.some((result) => result.status === "warning");
  const invalidIndexes = results.filter((result) => result.status === "invalid").map((result) => result.index);
  const warningIndexes = results.filter((result) => result.status === "warning").map((result) => result.index);
  const deckErrorCount = deckIssues.filter((issue) => issue.severity === "error").length;
  const deckWarningCount = deckIssues.filter((issue) => issue.severity !== "error").length;
  const slideIssueCounts = results.reduce((counts, result) => {
    for (const issue of asArray(result.issues)) {
      const severity = issue?.severity === "error" ? "error" : "warning";
      counts[severity] += 1;
      const code = String(issue?.code ?? "UNKNOWN");
      counts.by_code[code] = (counts.by_code[code] ?? 0) + 1;
    }
    return counts;
  }, { error: 0, warning: 0, by_code: {} });
  return {
    status: hasError ? "invalid" : hasWarning ? "warning" : "valid",
    slide_count: slides.length,
    invalid_slides: invalidIndexes,
    warning_slides: warningIndexes,
    // RPA-4: 顶层 summary，避免下游按 results[]/slides[] 猜字段而误判"全部通过"。
    // 约定：逐页结果固定为顶层 slides[]（每项含 index/status/issues），不存在 results[]。
    summary: {
      total_slides: results.length,
      valid_slides: results.filter((result) => result.status === "valid").length,
      invalid_slides: invalidIndexes.length,
      warning_slides: warningIndexes.length,
      slide_errors: slideIssueCounts.error,
      slide_warnings: slideIssueCounts.warning,
      deck_errors: deckErrorCount,
      deck_warnings: deckWarningCount,
      issue_counts_by_code: slideIssueCounts.by_code,
      passed: !hasError && !hasWarning,
    },
    result_contract: {
      per_slide_field: "slides",
      per_slide_index_field: "index",
      per_slide_status_field: "status",
      per_slide_issues_field: "issues",
      invalid_index_field: "invalid_slides",
      warning_index_field: "warning_slides",
      status_enum: ["valid", "warning", "invalid"],
    },
    deck_issues: deckIssues,
    metric_provenance: crossChecked ? "cross_checked_against_content_model" : "declared_not_verified",
    cross_check_divergences: divergences,
    slides: results,
  };
}

export async function runPreflight(input = {}) {
  const rendererInputs = input.renderer_inputs ?? input.rendererInputs;
  const verifyFilesystem = input.verify_filesystem ?? true;
  const rendererGuard = validateRendererInputs(rendererInputs);
  let filesystemVerification;
  if (verifyFilesystem) {
    filesystemVerification = await verifyRendererInputsOnDisk(rendererInputs ?? {});
    for (const issue of filesystemVerification.issues) rendererGuard.issues.push(issue);
    if (filesystemVerification.status === "verified_missing") rendererGuard.status = "invalid";
    else if (rendererGuard.status !== "invalid" && filesystemVerification.status === "not_verifiable") rendererGuard.status = "warning";
  } else {
    filesystemVerification = { verifyable: false, status: "skipped", reason: "disabled_by_caller", project_dir_exists: null, issues: [] };
  }
  rendererGuard.filesystem_verification = filesystemVerification;
  const deckValidation = await validateDeckPlan({
    ...(input.deck_plan ?? input.deckPlan ?? {}),
    ...(input.content_model ? { content_model: input.content_model } : {}),
  });
  const hasError = rendererGuard.status === "invalid" || deckValidation.status === "invalid";
  const hasWarning = rendererGuard.status === "warning" || deckValidation.status === "warning";
  return {
    pipeline_status: PIPELINE_STATUS.preflight,
    status: hasError ? "invalid" : hasWarning ? "warning" : "valid",
    invalid_slides: deckValidation.invalid_slides,
    warning_slides: deckValidation.warning_slides,
    renderer_guard: rendererGuard,
    deck_validation: deckValidation,
    next_action: hasError
      ? "Resolve renderer-input and deck-contract errors, then run preflight again before rendering."
      : hasWarning
        ? "Review preflight warnings before rendering and explicitly accept only intentional conditions."
        : "Preflight is complete; the deck specification and renderer inputs are ready for rendering.",
  };
}

export async function readPreview(layoutId) {
  const catalog = await loadCatalog();
  if (!catalog.byId.has(layoutId)) throw new RangeError(`Unknown layout_id: ${layoutId}`);
  return fs.readFile(path.join(DATA_DIR, "svg", `${layoutId}.svg`), "utf8");
}
