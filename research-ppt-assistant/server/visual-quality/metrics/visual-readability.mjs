const included = (element) => element?.quality_role === "content" && element.type === "image";
const finite = (value) => Number.isFinite(value) ? value : null;
const round = (value, digits = 6) => value === null ? null : Number(value.toFixed(digits));

function ratioBox(display, allocated) {
  if (!display || !allocated || allocated.width <= 0 || allocated.height <= 0) {
    return { fill_ratio: null, letterbox_ratio: null };
  }
  const fill = Math.max(0, Math.min(1, display.width * display.height / (allocated.width * allocated.height)));
  return { fill_ratio: round(fill), letterbox_ratio: round(1 - fill) };
}

export function computeVisualReadability(elements = [], slide = {}, { unavailable = [] } = {}) {
  const images = elements.filter(included);
  if (!images.length) {
    return { measurable: true, applicable: false, element_count: 0, observations: [], missing_fields: [], measurement_gaps: [] };
  }
  const usePixels = Number.isFinite(slide.render_width_px) && slide.render_width_px > 0
    && Number.isFinite(slide.render_height_px) && slide.render_height_px > 0;
  const observations = [];
  const missing = [];
  const measurementGaps = [];
  for (const element of images) {
    const image = element.image;
    const display = image?.display_bbox ?? element.bbox;
    const width = usePixels && element.render_bbox_px
      ? element.render_bbox_px.width / slide.render_width_px
      : display && slide.width > 0 ? display.width / slide.width : null;
    const height = usePixels && element.render_bbox_px
      ? element.render_bbox_px.height / slide.render_height_px
      : display && slide.height > 0 ? display.height / slide.height : null;
    const allocation = ratioBox(display, image?.allocated_bbox);
    const record = {
      element_id: element.element_id,
      visual_id: image?.visual_id ?? null,
      slot_id: image?.slot_id ?? null,
      visual_type: image?.visual_type ?? null,
      panel_count: finite(image?.panel_count),
      has_embedded_text: typeof image?.has_embedded_text === "boolean" ? image.has_embedded_text : null,
      min_display_width: finite(image?.min_display_width),
      display_width_norm: round(width),
      display_height_norm: round(height),
      fill_ratio: allocation.fill_ratio,
      letterbox_ratio: allocation.letterbox_ratio,
      rendered_embedded_text_px: finite(image?.rendered_embedded_text_px),
    };
    for (const field of ["visual_type", "panel_count", "has_embedded_text", "display_width_norm", "letterbox_ratio"]) {
      if (record[field] === null) missing.push(`elements.${element.element_id}.image.${field}`);
    }
    if (record.has_embedded_text === true && record.rendered_embedded_text_px === null) {
      const field = `elements.${element.element_id}.image.rendered_embedded_text_px`;
      missing.push(field);
      const elementIndex = elements.indexOf(element);
      const declared = unavailable.find((item) => item.field === `elements[${elementIndex}].image.rendered_embedded_text_px`);
      const state = /fail|error|unable|exception/u.test(String(declared?.reason ?? "").toLowerCase()) ? "measurement_failed" : "not_measured";
      measurementGaps.push({ field, state, reason: declared?.reason ?? "renderer did not provide a raster-text measurement" });
    }
    observations.push(record);
  }
  const missingFields = [...new Set(missing)];
  return {
    measurable: missingFields.length === 0,
    applicable: true,
    element_count: observations.length,
    observations,
    missing_fields: missingFields,
    measurement_gaps: measurementGaps,
    ...(missingFields.length ? { unavailable_reason: "scientific_visual_telemetry_incomplete" } : {}),
  };
}
