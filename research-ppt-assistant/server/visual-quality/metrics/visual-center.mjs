const QUALITY_ROLES = new Set(["content", "decoration", "background", "ignore"]);

function unavailable(unavailableReason, elementCount = 0) {
  return {
    measurable: false,
    center: null,
    normalized_center: null,
    offset: null,
    element_count: elementCount,
    unavailable_reason: unavailableReason,
  };
}

function dimension(value, longName, shortName) {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    return value[longName] ?? value[shortName];
  }
  return undefined;
}

function slideGeometry(slide) {
  if (!slide || typeof slide !== "object" || Array.isArray(slide)) return null;
  const x = slide.x ?? 0;
  const y = slide.y ?? 0;
  const width = dimension(slide, "width", "w");
  const height = dimension(slide, "height", "h");
  if (![x, y, width, height].every(Number.isFinite) || width <= 0 || height <= 0) return null;
  if (!Number.isFinite(x + width) || !Number.isFinite(y + height)) return null;
  if (!Number.isFinite(width * height)) return null;
  return { x, y, width, height };
}

function elementRole(element) {
  if (!element || typeof element !== "object" || Array.isArray(element)) return undefined;
  return element.quality_role ?? element.qualityRole ?? element.role;
}

function elementBox(element) {
  if (!element || typeof element !== "object" || Array.isArray(element)) return null;
  return element.bbox ?? element.box ?? element;
}

function clippedBox(element, slide) {
  const box = elementBox(element);
  if (!box || typeof box !== "object" || Array.isArray(box)) return null;
  const x = box.x;
  const y = box.y;
  const width = dimension(box, "width", "w");
  const height = dimension(box, "height", "h");
  if (![x, y, width, height].every(Number.isFinite) || width < 0 || height < 0) return null;
  if (!Number.isFinite(x + width) || !Number.isFinite(y + height)) return null;

  const left = Math.max(slide.x, x);
  const top = Math.max(slide.y, y);
  const right = Math.min(slide.x + slide.width, x + width);
  const bottom = Math.min(slide.y + slide.height, y + height);
  if (right <= left || bottom <= top) return { area: 0 };
  return {
    left,
    top,
    right,
    bottom,
    area: (right - left) * (bottom - top),
  };
}

function roleWeights(options) {
  const weights = options.role_weights;
  if (weights === undefined || weights === null) return {};
  if (!weights || typeof weights !== "object" || Array.isArray(weights)) return null;
  for (const value of Object.values(weights)) {
    if (!Number.isFinite(value) || value < 0) return null;
  }
  return weights;
}

/**
 * Compute the area-weighted center of visible slide elements.
 *
 * The function deliberately reports unavailable input instead of treating an
 * invalid participating element as absent. It has no quality thresholds.
 */
export function computeVisualCenter(elements = [], slide, options = {}) {
  const geometry = slideGeometry(slide);
  if (!geometry) return unavailable("invalid_slide_geometry");
  if (!Array.isArray(elements)) return unavailable("invalid_elements");
  if (!options || typeof options !== "object" || Array.isArray(options)) return unavailable("invalid_options");

  const includeDecoration = options.include_decoration ?? options.includeDecoration ?? false;
  if (typeof includeDecoration !== "boolean") return unavailable("invalid_include_decoration_option");
  const weights = roleWeights(options);
  if (weights === null) return unavailable("invalid_role_weights");

  let weightedX = 0;
  let weightedY = 0;
  let totalWeight = 0;
  let elementCount = 0;

  for (const element of elements) {
    const role = elementRole(element);
    if (!QUALITY_ROLES.has(role)) return unavailable("invalid_element_role", elementCount);
    if (role === "background" || role === "ignore" || (role === "decoration" && !includeDecoration)) continue;

    const visible = clippedBox(element, geometry);
    if (!visible) return unavailable("invalid_element_geometry", elementCount);
    if (visible.area <= 0) continue;

    const roleWeight = weights[role] ?? 1;
    if (!Number.isFinite(roleWeight) || roleWeight < 0) return unavailable("invalid_role_weights", elementCount);
    elementCount += 1;
    if (roleWeight === 0) continue;

    const weight = visible.area * roleWeight;
    totalWeight += weight;
    weightedX += ((visible.left + visible.right) / 2) * weight;
    weightedY += ((visible.top + visible.bottom) / 2) * weight;
  }

  if (elementCount === 0) return unavailable("no_visible_elements");
  if (!(totalWeight > 0) || ![weightedX, weightedY, totalWeight].every(Number.isFinite)) {
    return unavailable("zero_or_non_finite_total_weight", elementCount);
  }

  const center = {
    x: weightedX / totalWeight,
    y: weightedY / totalWeight,
  };
  const normalizedCenter = {
    x: (center.x - geometry.x) / geometry.width,
    y: (center.y - geometry.y) / geometry.height,
  };
  const slideCenter = {
    x: geometry.x + (geometry.width / 2),
    y: geometry.y + (geometry.height / 2),
  };
  const slideDiagonal = Math.hypot(geometry.width, geometry.height);
  const offset = Math.hypot(center.x - slideCenter.x, center.y - slideCenter.y) / slideDiagonal;
  if (![center.x, center.y, normalizedCenter.x, normalizedCenter.y, offset].every(Number.isFinite)) {
    return unavailable("non_finite_center", elementCount);
  }

  return {
    measurable: true,
    center,
    normalized_center: normalizedCenter,
    offset,
    element_count: elementCount,
  };
}
