const isRecord = (value) => Boolean(value) && typeof value === "object" && !Array.isArray(value);
const finite = (value) => typeof value === "number" && Number.isFinite(value) ? value : null;
const round = (value, digits = 6) => Number(value.toFixed(digits));

export const CONTAINER_GEOMETRY_EPSILON = 1e-6;

export function boxContainsWithin(outer, inner, epsilon = CONTAINER_GEOMETRY_EPSILON) {
  return Boolean(outer && inner)
    && outer.x <= inner.x + epsilon
    && outer.y <= inner.y + epsilon
    && outer.x + outer.width >= inner.x + inner.width - epsilon
    && outer.y + outer.height >= inner.y + inner.height - epsilon;
}

export function normalizeFitBox(value, field) {
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
  return Object.fromEntries(Object.entries(box).map(([key, item]) => [key, round(item)]));
}

function centeredContain(sourceAspect, allocated) {
  if (sourceAspect >= allocated.width / allocated.height) {
    const height = allocated.width / sourceAspect;
    return {
      x: allocated.x,
      y: allocated.y + (allocated.height - height) / 2,
      width: allocated.width,
      height,
    };
  }
  const width = allocated.height * sourceAspect;
  return {
    x: allocated.x + (allocated.width - width) / 2,
    y: allocated.y,
    width,
    height: allocated.height,
  };
}
function gaps(display, allocated) {
  const left = Math.max(0, display.x - allocated.x);
  const right = Math.max(0, allocated.x + allocated.width - display.x - display.width);
  const top = Math.max(0, display.y - allocated.y);
  const bottom = Math.max(0, allocated.y + allocated.height - display.y - display.height);
  return {
    left: round(left),
    right: round(right),
    top: round(top),
    bottom: round(bottom),
    left_ratio: round(left / allocated.width),
    right_ratio: round(right / allocated.width),
    top_ratio: round(top / allocated.height),
    bottom_ratio: round(bottom / allocated.height),
    gap_symmetry: {
      horizontal_delta_ratio: round(Math.abs(left - right) / allocated.width),
      vertical_delta_ratio: round(Math.abs(top - bottom) / allocated.height),
    },
  };
}

function metricsForDisplay({ sourceAspect, allocated, display, fitPolicy, effectiveSourceScale = null }) {
  const widthFill = display.width / allocated.width;
  const heightFill = display.height / allocated.height;
  const areaFill = widthFill * heightFill;
  const allocatedAspect = allocated.width / allocated.height;
  return {
    fit_policy: fitPolicy,
    source_aspect_ratio: round(sourceAspect),
    allocated_aspect_ratio: round(allocatedAspect),
    aspect_mismatch_factor: round(Math.max(sourceAspect / allocatedAspect, allocatedAspect / sourceAspect)),
    predicted_display_bbox: Object.fromEntries(Object.entries(display).map(([key, item]) => [key, round(item)])),
    visual_fill: {
      width_ratio: round(widthFill),
      height_ratio: round(heightFill),
      area_ratio: round(areaFill),
    },
    unused_space: {
      horizontal_ratio: round(1 - widthFill),
      vertical_ratio: round(1 - heightFill),
    },
    gaps: gaps(display, allocated),
    effective_source_scale: effectiveSourceScale === null ? null : round(effectiveSourceScale),
  };
}

export function computeVisualFitMetrics({ source, source_region: sourceRegion, allocated_visual_bbox: allocatedBox, fit_policy: fitPolicy = "contain" } = {}) {
  const sourceBox = normalizeFitBox({ x: 0, y: 0, width: source?.width, height: source?.height }, "source");
  const region = sourceRegion
    ? normalizeFitBox(sourceRegion, "source_region")
    : sourceBox;
  if (region.x < 0 || region.y < 0
      || region.x + region.width > sourceBox.width
      || region.y + region.height > sourceBox.height) {
    throw new RangeError("source_region must stay inside source bounds");
  }
  const allocated = normalizeFitBox(allocatedBox, "allocated_visual_bbox");
  const normalizedFit = String(fitPolicy).trim().toLowerCase();
  if (!["contain", "cover"].includes(normalizedFit)) throw new RangeError(`unsupported fit_policy: ${fitPolicy}`);
  const sourceAspect = region.width / region.height;
  const display = normalizedFit === "contain" ? centeredContain(sourceAspect, allocated) : allocated;
  const scale = normalizedFit === "contain"
    ? Math.min(allocated.width / region.width, allocated.height / region.height)
    : Math.max(allocated.width / region.width, allocated.height / region.height);
  return {
    source_bbox: sourceBox,
    source_region_bbox: region,
    allocated_bbox: allocated,
    ...metricsForDisplay({ sourceAspect, allocated, display, fitPolicy: normalizedFit, effectiveSourceScale: scale }),
  };
}

export function computeContainerChildMetrics({ content_bbox: contentBox, child_display_bbox: childBox } = {}) {
  const content = normalizeFitBox(contentBox, "content_bbox");
  const child = normalizeFitBox(childBox, "child_display_bbox");
  const sourceAspect = child.width / child.height;
  return {
    content_bbox: content,
    child_display_bbox: child,
    ...metricsForDisplay({ sourceAspect, allocated: content, display: child, fitPolicy: "effective" }),
  };
}
