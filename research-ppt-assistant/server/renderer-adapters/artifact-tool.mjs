import { adaptTelemetryWithMapping, createRendererMapping, isRecord } from "./common.mjs";
import { assertRenderTelemetry } from "../visual-quality/telemetry.mjs";

export const ARTIFACT_TOOL_TELEMETRY_MAPPING = createRendererMapping("artifact-tool");

function firstRecord(input) {
  for (const value of [input, input?.layout, input?.renderer_output, input?.rendererOutput, input?.data]) {
    if (isRecord(value) && (String(value.schema ?? "").startsWith("openai.presentation.layout/") || Array.isArray(value.elements))) return value;
  }
  throw new TypeError("artifact-tool telemetry requires an openai.presentation.layout document");
}

function finite(value) {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function elementOpacity(element) {
  for (const value of [element.opacity, element.fillOpacity, element.fill_opacity, element.alpha]) {
    const number = finite(value);
    if (number !== null && number >= 0 && number <= 1) return number;
  }
  for (const value of [element.transparency, element.fillTransparency, element.fill_transparency]) {
    const number = finite(value);
    if (number !== null && number >= 0 && number <= 100) return 1 - number / 100;
  }
  if (element.fillColor || String(element.kind ?? "").toLowerCase() === "image") return 1;
  return null;
}

function inferredTextRole(element) {
  const name = String(element.name ?? "").toLowerCase();
  if (name.includes("subtitle")) return "subtitle";
  if (name.includes("meta") || name.includes("footer")) return "meta";
  if (name.includes("title")) return "title";
  return "body";
}

function inferredQualityRole(element, type) {
  const explicit = element.quality_role ?? element.qualityRole ?? element.semantic_role ?? element.semanticRole;
  if (typeof explicit === "string" && explicit.trim()) return explicit;
  if (type === "text" || type === "image" || type === "chart" || type === "table") return "content";
  return "decoration";
}

function textRecord(element) {
  const style = isRecord(element.resolvedTextStyle) ? element.resolvedTextStyle : {};
  // artifact-tool layout/v4 reports CSS pixels at 96 DPI. Canonical font_size
  // is points, also used by viewing profiles and the overflow estimator.
  const fontPx = finite(element.resolvedFontSize) ?? finite(style.fontSize);
  const lineCount = finite(element.textLayout?.lineCount);
  const overflow = typeof element.textLayout?.overflow === "boolean"
    ? element.textLayout.overflow
    : typeof element.overflow === "boolean" ? element.overflow : null;
  return {
    content: String(element.text ?? element.textPreview ?? ""),
    language: element.language ?? null,
    script: element.script ?? null,
    font_family: style.typeface ?? element.typeface ?? null,
    font_size: fontPx === null ? null : fontPx * 72 / 96,
    font_weight: style.bold === true ? "bold" : style.bold === false ? "normal" : null,
    line_count: lineCount,
    overflow,
    foreground_color: style.color ?? element.textColor ?? null,
    local_contrast_ratio: finite(element.localContrastRatio ?? element.local_contrast_ratio),
    intended_single_line: style.wrap === "none" ? true : null,
    role: element.textRole ?? element.text_role ?? inferredTextRole(element),
  };
}

function imageRecord(element) {
  const sourceWidth = finite(element.asset?.width ?? element.asset?.widthPx ?? element.sourceWidthPx);
  const sourceHeight = finite(element.asset?.height ?? element.asset?.heightPx ?? element.sourceHeightPx);
  return {
    display_bbox: element.effectiveDisplayBbox ?? element.effective_display_bbox ?? element.displayBbox ?? element.display_bbox ?? null,
    source_width_px: Number.isInteger(sourceWidth) && sourceWidth > 0 ? sourceWidth : null,
    source_height_px: Number.isInteger(sourceHeight) && sourceHeight > 0 ? sourceHeight : null,
    visual_id: element.visual_id ?? element.visualId ?? element.asset?.visual_id ?? element.aid ?? element.id ?? null,
    content_id: element.content_id ?? element.contentId ?? null,
    slot_id: element.slot_id ?? element.slotId ?? null,
    visual_type: element.visual_type ?? element.visualType ?? null,
    panel_count: finite(element.panel_count ?? element.panelCount),
    has_embedded_text: typeof (element.has_embedded_text ?? element.hasEmbeddedText) === "boolean" ? (element.has_embedded_text ?? element.hasEmbeddedText) : null,
    min_display_width: finite(element.min_display_width ?? element.minDisplayWidth),
    allocated_bbox: element.allocated_bbox ?? element.allocatedBbox ?? null,
    rendered_embedded_text_px: finite(element.rendered_embedded_text_px ?? element.renderedEmbeddedTextPx),
    source_region_bbox: element.source_region_bbox ?? element.sourceRegionBbox ?? null,
    visual_parent_id: element.visual_parent_id ?? element.visualParentId ?? null,
    relation: (element.relation?.type ?? element.relation_type) === "visual_child" ? { type: "visual_child" } : null,
    effective_source_region: element.effective_source_region ?? element.effectiveSourceRegion ?? null,
    effective_placement: element.effective_placement ?? element.effectivePlacement ?? null,
    source_region_coordinate_space: element.source_region_coordinate_space ?? element.sourceRegionCoordinateSpace ?? null,
    effective_fit_mode: element.effective_fit_mode ?? element.effectiveFitMode ?? null,
    actual_letterbox_ratio: finite(element.actual_letterbox_ratio ?? element.actualLetterboxRatio),
    visible_region_ids: element.visible_region_ids ?? element.visibleRegionIds ?? null,
    visible_label_ids: element.visible_label_ids ?? element.visibleLabelIds ?? null,
  };
}

function relationRecord(element) {
  const raw = isRecord(element.relation) ? element.relation : {};
  const type = raw.type ?? element.relation_type ?? element.relationType;
  const targetId = raw.target_id ?? raw.targetId ?? element.relation_target_id ?? element.relationTargetId;
  if (typeof type !== "string" || !type.trim() || typeof targetId !== "string" || !targetId.trim()) return null;
  return { type: type.trim(), target_id: targetId.trim(), source: "renderer" };
}

function canonicalElement(element, index) {
  const hasText = typeof element.text === "string" || typeof element.textPreview === "string";
  const rawKind = String(element.kind ?? element.type ?? "other").toLowerCase();
  const type = hasText ? "text" : rawKind === "image" ? "image" : rawKind;
  const bbox = element.bbox ?? null;
  return {
    element_id: String(element.aid ?? element.id ?? `artifact-element-${index + 1}`),
    type,
    quality_role: inferredQualityRole(element, type),
    z_index: finite(element.order ?? element.zIndex ?? element.z_index),
    opacity: elementOpacity(element),
    bbox,
    render_bbox_px: bbox,
    text: type === "text" ? textRecord(element) : null,
    image: type === "image" ? imageRecord(element) : null,
    fill_color: element.fillColor ?? element.fill_color ?? null,
    // Artifact fillColor is ambiguous for text (often glyph paint); only an
    // explicit background field may establish a text-box protection surface.
    background_color: type === "text"
      ? element.backgroundColor ?? element.background_color ?? element.textBackgroundColor ?? element.text_background_color ?? null
      : null,
    theme_token: element.themeToken ?? element.theme_token ?? null,
    theme_usage: element.themeUsage ?? element.theme_usage ?? null,
    geometry_kind: rawKind,
    relation: relationRecord(element),
    source_element_id: element.source_element_id ?? element.sourceElementId ?? null,
  };
}

function localBox(value) {
  if (Array.isArray(value) && value.length >= 4 && value.slice(0, 4).every(Number.isFinite)) {
    return { x: value[0], y: value[1], width: value[2], height: value[3] };
  }
  if (!isRecord(value)) return null;
  const box = { x: finite(value.x ?? value.left), y: finite(value.y ?? value.top), width: finite(value.width ?? value.w), height: finite(value.height ?? value.h) };
  return Object.values(box).every(Number.isFinite) && box.width >= 0 && box.height >= 0 ? box : null;
}

function contains(outer, inner, epsilon = 0.5) {
  return outer && inner
    && inner.x >= outer.x - epsilon && inner.y >= outer.y - epsilon
    && inner.x + inner.width <= outer.x + outer.width + epsilon
    && inner.y + inner.height <= outer.y + outer.height + epsilon;
}

function inferArtifactRelations(rawElements, elements) {
  const title = elements.find((element) => element.type === "text" && element.text?.role === "title");
  for (const [index, raw] of rawElements.entries()) {
    const element = elements[index];
    const name = String(raw.name ?? raw.aid ?? raw.id ?? "").toLowerCase();
    if (!element.relation && title && /(?:title|headline)[-_\s]*(?:rule|line|separator|divider)/u.test(name)) {
      element.relation = { type: "title_rule", target_id: title.element_id, source: "adapter_inferred" };
    }
  }

  const candidates = rawElements.map((raw, index) => ({ raw, element: elements[index], index }))
    .filter(({ raw, element }) => {
      const name = String(raw.name ?? raw.aid ?? raw.id ?? "").toLowerCase();
      const semantic = String(raw.semantic_role ?? raw.semanticRole ?? "").toLowerCase();
      return element.type !== "image" && (semantic === "visual_container" || /(?:rpa[-_\s]*)?(?:visual|figure)[-_\s]*(?:container|frame)/u.test(name));
    })
    .map(({ raw, element, index }) => {
      const outer = localBox(raw.bbox ?? element.bbox);
      const content = localBox(raw.content_bbox ?? raw.contentBbox) ?? outer;
      return { raw, element, index, outer, content };
    })
    .filter((candidate) => candidate.outer && candidate.content);
  const images = elements.filter((element) => element.type === "image" && element.bbox && element.image?.visual_id);
  const containers = [];
  for (const { raw, element, outer, content } of candidates) {
    const children = images.filter((image) => {
      const imageBox = localBox(image.bbox);
      return contains(content, imageBox) && candidates.filter((candidate) => contains(candidate.content, imageBox)).length === 1;
    });
    if (!children.length) continue;
    const containerId = String(raw.container_id ?? raw.containerId ?? raw.aid ?? raw.id ?? element.element_id);
    for (const child of children) {
      child.image.visual_parent_id = containerId;
      child.image.relation = { type: "visual_child" };
    }
    element.relation ??= { type: "container_border", target_id: containerId, source: "adapter_inferred" };
    containers.push({
      container_id: containerId,
      role: raw.container_role ?? raw.containerRole ?? "image_only",
      outer_bbox: outer,
      content_bbox: content,
      content_inset: raw.content_inset ?? raw.contentInset ?? { left: 0, right: 0, top: 0, bottom: 0 },
      child_visual_ids: children.map((child) => child.image.visual_id),
      fit_policy: raw.fit_policy ?? raw.fitPolicy ?? "contain",
      crop_policy: raw.crop_policy ?? raw.cropPolicy ?? "fixed_region",
      whitespace_policy: raw.whitespace_policy ?? raw.whitespacePolicy ?? "minimal",
      mismatch_policy: raw.mismatch_policy ?? raw.mismatchPolicy ?? "replan",
      inference_source: "semantic_name_and_unambiguous_containment",
    });
  }
  return containers;
}

function rpaLayoutId(document, slide) {
  for (const value of [document.rpa_layout_id, document.rpaLayoutId, slide.rpa_layout_id, slide.rpaLayoutId, document.layout_id, slide.layout_id, slide.layoutId]) {
    if (typeof value === "string" && /^RM-/u.test(value.trim())) return value.trim();
  }
  return null;
}

function inferredCategory(document, slide) {
  const explicit = document.category ?? document.slide_category ?? slide.category;
  if (typeof explicit === "string" && explicit.trim()) return explicit.trim();
  const type = String(slide.layoutType ?? slide.layout_type ?? "").trim().toLowerCase();
  if (type === "title") return "cover";
  return type || null;
}

function normalizedArtifactDocument(input) {
  const document = firstRecord(input);
  const slide = isRecord(document.slide) ? document.slide : {};
  const frame = isRecord(slide.frame) ? slide.frame : {};
  const width = finite(frame.width ?? slide.width);
  const height = finite(frame.height ?? slide.height);
  if (!(width > 0) || !(height > 0)) throw new TypeError("artifact-tool layout requires a positive slide frame");
  const colors = isRecord(document.theme?.colors) ? document.theme.colors : {};
  const tokens = Object.fromEntries(Object.entries(colors).map(([id, color]) => [id, { color }]));
  const rawElements = Array.isArray(document.elements) ? document.elements : [];
  const elements = rawElements.map(canonicalElement);
  const explicitContainers = document.visual_containers ?? document.visualContainers;
  const visualContainers = Array.isArray(explicitContainers)
    ? structuredClone(explicitContainers)
    : inferArtifactRelations(rawElements, elements);
  return {
    renderer: "artifact-tool",
    slide_id: String(slide.aid ?? slide.id ?? document.slide_id ?? "artifact-slide"),
    slide: {
      width,
      height,
      render_width_px: Math.round(width),
      render_height_px: Math.round(height),
      background: { kind: "solid", color: slide.backgroundColor ?? slide.background_color ?? null },
      layout_id: rpaLayoutId(document, slide),
      category: inferredCategory(document, slide),
      elements,
      visual_containers: visualContainers,
    },
    theme: Object.keys(tokens).length
      ? { id: document.theme?.colorSchemeName ?? "artifact-tool", tokens }
      : null,
  };
}

export function adaptArtifactToolTelemetry(input = {}) {
  return assertRenderTelemetry(adaptTelemetryWithMapping(normalizedArtifactDocument(input), ARTIFACT_TOOL_TELEMETRY_MAPPING));
}

export const adaptArtifactTelemetry = adaptArtifactToolTelemetry;
