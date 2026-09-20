const LEGACY_TELEMETRY_VERSION = "1.3.0";

const asArray = (value) => (Array.isArray(value) ? value : []);

function positiveNumber(value, fallback) {
  if (value === undefined || value === null || value === "") return fallback;
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed <= 0) throw new TypeError(`Expected a positive number, received ${value}`);
  return parsed;
}

function nonNegativeInteger(value, fallback) {
  if (value === undefined || value === null || value === "") return fallback;
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed < 0) throw new TypeError(`Expected a non-negative number, received ${value}`);
  return Math.round(parsed);
}

function finiteRatio(value) {
  if (value === undefined || value === null || value === "") return undefined;
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) throw new TypeError(`Expected a number, received ${value}`);
  return Math.min(1, Math.max(0, parsed));
}

function textElement(item, index) {
  if (!item || typeof item !== "object" || Array.isArray(item)) throw new TypeError(`text_elements[${index}] must be an object`);
  const role = String(item.role ?? "body").toLowerCase();
  return {
    element_id: String(item.id ?? item.slot_id ?? item.slotId ?? `text-${index + 1}`),
    type: "text",
    quality_role: "content",
    z_index: Number.isFinite(item.z_index ?? item.zIndex) ? Number(item.z_index ?? item.zIndex) : null,
    opacity: Number.isFinite(item.opacity) ? Number(item.opacity) : null,
    bbox: item.bbox ?? null,
    render_bbox_px: item.render_bbox_px ?? item.renderBBoxPx ?? null,
    text: {
      content: item.content ?? item.text ?? null,
      language: item.language ?? null,
      script: item.script ?? null,
      font_family: item.font_family ?? item.fontFamily ?? null,
      font_size: positiveNumber(item.font_pt ?? item.fontPt ?? item.font_size, null),
      font_weight: item.font_weight ?? item.fontWeight ?? null,
      line_count: nonNegativeInteger(item.line_count ?? item.lineCount, null),
      overflow: typeof item.overflow === "boolean" ? item.overflow : null,
      foreground_color: item.foreground_color ?? item.foregroundColor ?? null,
      local_contrast_ratio: Number.isFinite(item.local_contrast_ratio ?? item.localContrastRatio)
        ? Number(item.local_contrast_ratio ?? item.localContrastRatio)
        : null,
      intended_single_line: item.intended_single_line === undefined && item.intendedSingleLine === undefined
        ? false
        : Boolean(item.intended_single_line ?? item.intendedSingleLine),
      role,
    },
    image: null,
    fill_color: item.fill_color ?? item.fillColor ?? null,
    background_color: item.background_color ?? item.backgroundColor ?? null,
    theme_token: item.theme_token ?? item.themeToken ?? null,
    theme_usage: item.theme_usage ?? item.themeUsage ?? (item.theme_token || item.themeToken ? "body_text" : null),
  };
}

function legacyTextElements(input) {
  const elements = asArray(input.text_elements ?? input.textElements).map(textElement);
  if (input.title_font_pt !== undefined || input.titleFontPt !== undefined) {
    elements.push(textElement({
      id: "title",
      role: "title",
      font_pt: input.title_font_pt ?? input.titleFontPt,
      line_count: input.title_line_count ?? input.titleLineCount,
      intended_single_line: input.title_wrap_allowed === undefined ? true : !input.title_wrap_allowed,
    }, elements.length));
  }
  for (const [index, fontSize] of asArray(input.body_font_pts ?? input.bodyFontPts).entries()) {
    elements.push(textElement({ id: `body-${index + 1}`, role: "body", font_pt: fontSize }, elements.length));
  }
  return elements;
}

function unavailableFor(elements, slide) {
  const unavailable = [];
  if (!elements.length) unavailable.push({ field: "elements", reason: "legacy_input_did_not_provide_elements" });
  if (slide.render_width_px === null) unavailable.push({ field: "slide.render_width_px", reason: "legacy_input_did_not_provide_render_width" });
  if (slide.render_height_px === null) unavailable.push({ field: "slide.render_height_px", reason: "legacy_input_did_not_provide_render_height" });
  if (slide.layout_id === null) unavailable.push({ field: "slide.layout_id", reason: "legacy_input_did_not_provide_layout_id" });
  if (slide.category === null) unavailable.push({ field: "slide.category", reason: "legacy_input_did_not_provide_category" });
  for (const [index, element] of elements.entries()) {
    if (element.z_index === null) unavailable.push({ field: `elements[${index}].z_index`, reason: "legacy_input_did_not_provide_z_order" });
    if (element.opacity === null) unavailable.push({ field: `elements[${index}].opacity`, reason: "legacy_input_did_not_provide_opacity" });
    if (element.bbox === null) unavailable.push({ field: `elements[${index}].bbox`, reason: "legacy_input_did_not_provide_bbox" });
    if (element.render_bbox_px === null) unavailable.push({ field: `elements[${index}].render_bbox_px`, reason: "legacy_input_did_not_provide_render_bbox" });
    if (element.text?.overflow === null) unavailable.push({ field: `elements[${index}].text.overflow`, reason: "legacy_input_did_not_provide_overflow" });
    if (element.text?.foreground_color === null) unavailable.push({ field: `elements[${index}].text.foreground_color`, reason: "legacy_input_did_not_provide_foreground_color" });
    if (element.text?.local_contrast_ratio === null) unavailable.push({ field: `elements[${index}].text.local_contrast_ratio`, reason: "legacy_input_did_not_measure_local_contrast" });
  }
  return unavailable;
}

export function adaptLegacyRenderedSlide(input = {}) {
  const elements = legacyTextElements(input);
  const renderWidth = nonNegativeInteger(input.render_width_px ?? input.renderWidthPx, null);
  const renderHeight = nonNegativeInteger(input.render_height_px ?? input.renderHeightPx, null);
  const backgroundColor = input.background_color ?? input.backgroundColor ?? null;
  const slide = {
    width: positiveNumber(input.slide_width ?? input.slideWidth, 13.333),
    height: positiveNumber(input.slide_height ?? input.slideHeight, 7.5),
    render_width_px: renderWidth && renderWidth > 0 ? renderWidth : null,
    render_height_px: renderHeight && renderHeight > 0 ? renderHeight : null,
    background: { kind: backgroundColor ? "solid" : "unknown", color: backgroundColor },
    layout_id: input.layout_id ?? input.layoutId ?? null,
    category: input.category ?? null,
  };
  return {
    telemetry_version: LEGACY_TELEMETRY_VERSION,
    slide_id: String(input.slide_id ?? input.slideId ?? input.slide_number ?? input.slideNumber ?? "rendered-slide"),
    renderer: String(input.renderer ?? "legacy").toLowerCase().replaceAll("_", "-"),
    slide,
    elements,
    theme: input.theme ?? null,
    unavailable: unavailableFor(elements, slide),
    provided_metrics: {
      content_footprint: finiteRatio(input.content_occupancy ?? input.content_footprint ?? input.contentFootprint) ?? null,
      largest_empty_band: finiteRatio(input.largest_empty_band ?? input.largestEmptyBand) ?? null,
      content_center_x: finiteRatio(input.content_center_x ?? input.contentCenterX) ?? null,
      content_center_y: finiteRatio(input.content_center_y ?? input.contentCenterY) ?? null,
      intentional_whitespace: Boolean(input.intentional_whitespace ?? input.intentionalWhitespace),
      visuals: asArray(input.visuals).map((visual) => ({
        visual_type: String(visual.visual_type ?? visual.visualType ?? "visual_evidence"),
        panel_count: nonNegativeInteger(visual.panel_count ?? visual.panelCount, 1),
        has_embedded_text: Boolean(visual.has_embedded_text ?? visual.hasEmbeddedText),
        min_display_width: finiteRatio(visual.min_display_width ?? visual.minDisplayWidth) ?? null,
        display_width_norm: finiteRatio(visual.display_width ?? visual.display_width_norm ?? visual.displayWidth) ?? null,
        display_height_norm: finiteRatio(visual.display_height ?? visual.display_height_norm ?? visual.displayHeight) ?? null,
        rendered_embedded_text_px: positiveNumber(visual.embedded_text_px ?? visual.rendered_embedded_text_px ?? visual.embeddedTextPx, null),
      })),
    },
  };
}
