function isBox(value) {
  return Boolean(value)
    && typeof value === "object"
    && ["x", "y", "width", "height"].every((key) => Number.isFinite(value[key]))
    && value.width >= 0
    && value.height >= 0;
}

function area(box) {
  return isBox(box) ? box.width * box.height : 0;
}

function coverageRatio(overlap, totalArea) {
  if (!(totalArea > 0)) return 0;
  return Math.min(1, Math.max(0, area(overlap) / totalArea));
}

function intersection(left, right) {
  if (!isBox(left) || !isBox(right)) return null;
  const x = Math.max(left.x, right.x);
  const y = Math.max(left.y, right.y);
  const rightEdge = Math.min(left.x + left.width, right.x + right.width);
  const bottomEdge = Math.min(left.y + left.height, right.y + right.height);
  if (rightEdge <= x || bottomEdge <= y) return null;
  return { x, y, width: rightEdge - x, height: bottomEdge - y };
}

function normalizeCategory(value) {
  return String(value ?? "").trim().toLowerCase().replace(/[\s_]+/gu, "-");
}

function isCoverContext(context) {
  const category = normalizeCategory(context.category);
  const layoutId = String(context.layout_id ?? context.layoutId ?? "").trim().toUpperCase();
  return layoutId === "RM-COVER-03" || ["cover", "title", "title-slide"].includes(category);
}

function participating(element) {
  return element && element.quality_role !== "ignore" && element.quality_role !== "background";
}

function hasColor(value) {
  return typeof value === "string" && value.trim().length > 0;
}

function coordinateSpace(elements, slide) {
  if (Number.isFinite(slide.render_width_px) && Number.isFinite(slide.render_height_px)
      && elements.every((element) => isBox(element.render_bbox_px))) return "render_bbox_px";
  return "bbox";
}

function fieldFor(element, index, field) {
  return `elements[${index}].${field}`;
}

export function computeTextImageOcclusion(telemetry, context = {}) {
  const category = context.category ?? telemetry.slide.category;
  const layoutId = context.layout_id ?? context.layoutId ?? telemetry.slide.layout_id;
  const cover = isCoverContext({ category, layout_id: layoutId });
  const indexed = telemetry.elements.map((element, index) => ({ element, index })).filter(({ element }) => participating(element));
  const texts = indexed.filter(({ element }) => element.type === "text" && element.quality_role === "content");
  const images = indexed.filter(({ element }) => element.type === "image");
  const overlays = indexed.filter(({ element }) => element.type === "shape" && hasColor(element.fill_color));
  const slideImage = telemetry.slide.background?.kind === "image";
  const applicable = cover && (slideImage || images.length > 0);
  const exactCoverLayout = String(layoutId ?? "").trim().toUpperCase() === "RM-COVER-03";

  if (telemetry.unavailable?.some((item) => item?.field === "elements")) {
    return {
      measurable: false,
      applicable: cover,
      coordinate_space: "bbox",
      text_count: 0,
      image_count: 0,
      intersection_count: 0,
      intersections: [],
      missing_fields: ["elements"],
      unavailable_reason: "element_collection_missing",
    };
  }

  if (!cover) {
    return {
      measurable: true,
      applicable: false,
      coordinate_space: "bbox",
      text_count: texts.length,
      image_count: images.length,
      intersection_count: 0,
      intersections: [],
      missing_fields: [],
    };
  }
  if (!applicable) {
    return {
      measurable: !exactCoverLayout,
      applicable: exactCoverLayout,
      coordinate_space: "bbox",
      text_count: texts.length,
      image_count: 0,
      intersection_count: 0,
      intersections: [],
      missing_fields: exactCoverLayout ? ["elements[type=image]"] : [],
      ...(exactCoverLayout ? { unavailable_reason: "expected_cover_image_element_missing" } : {}),
    };
  }

  const relevant = [...texts, ...images, ...overlays].map(({ element }) => element);
  const space = coordinateSpace(relevant, telemetry.slide);
  const missingFields = [];
  for (const { element, index } of [...texts, ...images]) {
    if (!isBox(element[space])) missingFields.push(fieldFor(element, index, space));
    if (!Number.isFinite(element.z_index)) missingFields.push(fieldFor(element, index, "z_index"));
  }
  for (const { element, index } of overlays) {
    if (!isBox(element[space])) missingFields.push(fieldFor(element, index, space));
    if (!Number.isFinite(element.z_index)) missingFields.push(fieldFor(element, index, "z_index"));
  }
  if (missingFields.length) {
    return {
      measurable: false,
      applicable: true,
      coordinate_space: space,
      text_count: texts.length,
      image_count: images.length + (slideImage ? 1 : 0),
      intersection_count: 0,
      intersections: [],
      missing_fields: [...new Set(missingFields)],
      unavailable_reason: "text_image_z_order_or_geometry_missing",
    };
  }

  const imageLayers = images.map(({ element }) => ({
    element_id: element.element_id,
    bbox: element[space],
    z_index: element.z_index,
  }));
  if (slideImage) {
    imageLayers.push({
      element_id: "__slide_background__",
      bbox: space === "render_bbox_px"
        ? { x: 0, y: 0, width: telemetry.slide.render_width_px, height: telemetry.slide.render_height_px }
        : { x: 0, y: 0, width: telemetry.slide.width, height: telemetry.slide.height },
      z_index: null,
    });
  }

  const intersections = [];
  for (const { element: text } of texts) {
    const textBox = text[space];
    const textArea = area(textBox);
    if (!textArea) continue;
    for (const image of imageLayers) {
      const imageUnderText = image.element_id === "__slide_background__" || image.z_index < text.z_index;
      if (!imageUnderText) continue;
      const overlap = intersection(textBox, image.bbox);
      if (!overlap) continue;
      const surfaceCandidates = overlays
        .filter(({ element: overlay }) => {
          const aboveImage = image.element_id === "__slide_background__" || overlay.z_index > image.z_index;
          return aboveImage && overlay.z_index < text.z_index && intersection(textBox, overlay[space]);
        })
        .map(({ element: overlay }) => {
          const covered = intersection(textBox, overlay[space]);
          return {
            element_id: overlay.element_id,
            z_index: overlay.z_index,
            coverage_ratio: coverageRatio(covered, textArea),
            opacity: Number.isFinite(overlay.opacity) ? overlay.opacity : null,
            fill_color: overlay.fill_color,
          };
        });
      // A text element's fill_color is normally its glyph/foreground paint. It
      // cannot prove that the image behind the glyphs has a readable surface.
      // Keep a separately declared text-box background eligible, since that is
      // an actual surface behind the text.
      if (hasColor(text.background_color)) {
        surfaceCandidates.push({
          element_id: `${text.element_id}::background`,
          z_index: text.z_index,
          coverage_ratio: 1,
          opacity: Number.isFinite(text.opacity) ? text.opacity : null,
          fill_color: text.background_color,
        });
      }
      intersections.push({
        text_element_id: text.element_id,
        image_element_id: image.element_id,
        text_bbox: { ...textBox },
        image_bbox: { ...image.bbox },
        overlap_ratio: coverageRatio(overlap, textArea),
        text_z_index: text.z_index,
        image_z_index: image.z_index,
        local_contrast_ratio: Number.isFinite(text.text?.local_contrast_ratio) ? text.text.local_contrast_ratio : null,
        overlays: surfaceCandidates.sort((left, right) => right.coverage_ratio - left.coverage_ratio || right.z_index - left.z_index),
      });
    }
  }

  return {
    measurable: true,
    applicable: true,
    coordinate_space: space,
    text_count: texts.length,
    image_count: imageLayers.length,
    intersection_count: intersections.length,
    intersections,
    missing_fields: [],
  };
}
