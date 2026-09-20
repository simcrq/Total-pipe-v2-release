const hasOwn = (value, key) => Object.prototype.hasOwnProperty.call(value, key);

function isRecord(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function invalidRectangle(message, value) {
  throw new TypeError(`Invalid rectangle: ${message}${value === undefined ? "" : ` (received ${String(value)})`}`);
}

function finiteNumber(value, field) {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    invalidRectangle(`${field} must be a finite number`, value);
  }
  return value;
}

function readField(rectangle, field, alias) {
  const hasField = hasOwn(rectangle, field);
  const hasAlias = alias !== undefined && hasOwn(rectangle, alias);
  if (hasField && hasAlias) {
    const fieldValue = finiteNumber(rectangle[field], field);
    const aliasValue = finiteNumber(rectangle[alias], alias);
    if (fieldValue !== aliasValue) {
      invalidRectangle(`${field} and ${alias} must agree`);
    }
    return fieldValue;
  }
  if (hasField) return finiteNumber(rectangle[field], field);
  if (hasAlias) return finiteNumber(rectangle[alias], alias);
  return undefined;
}

function readOrigin(rectangle, field, alias) {
  const value = readField(rectangle, field, alias);
  if (value === undefined) invalidRectangle(`${field} is required`);
  return value;
}

function readSize(rectangle, field, alias) {
  const value = readField(rectangle, field, alias);
  if (value === undefined) invalidRectangle(`${field} is required`);
  if (value < 0) invalidRectangle(`${field} must be non-negative`, value);
  return value;
}

/**
 * Convert supported axis-aligned rectangle representations to x/y/width/height.
 * The canonical telemetry representation uses width and height; w and h are
 * accepted for compatibility with the existing layout geometry representation.
 * Edge-coordinate rectangles using x1/y1/x2/y2 are also accepted.
 */
export function normalizeRectangle(rectangle, options = {}) {
  if (!isRecord(rectangle)) invalidRectangle("must be an object");
  if (!isRecord(options)) throw new TypeError("Rectangle options must be an object");

  const hasEdgeCoordinates = ["x1", "y1", "x2", "y2"].some((key) => hasOwn(rectangle, key));
  const hasSizeCoordinates = ["x", "y", "width", "height", "w", "h"].some((key) => hasOwn(rectangle, key));
  if (hasEdgeCoordinates && hasSizeCoordinates) {
    invalidRectangle("must use either x/y/width/height or x1/y1/x2/y2 coordinates");
  }

  if (hasEdgeCoordinates) {
    const x1 = readOrigin(rectangle, "x1");
    const y1 = readOrigin(rectangle, "y1");
    const x2 = readOrigin(rectangle, "x2");
    const y2 = readOrigin(rectangle, "y2");
    if (x2 < x1) invalidRectangle("x2 must not be less than x1", x2);
    if (y2 < y1) invalidRectangle("y2 must not be less than y1", y2);
    const width = x2 - x1;
    const height = y2 - y1;
    if (!Number.isFinite(width) || !Number.isFinite(height)) invalidRectangle("derived rectangle size must be finite");
    return { x: x1, y: y1, width, height };
  }

  const x = readOrigin(rectangle, "x");
  const y = readOrigin(rectangle, "y");
  const width = readSize(rectangle, "width", "w");
  const height = readSize(rectangle, "height", "h");
  if (!Number.isFinite(x + width) || !Number.isFinite(y + height)) {
    invalidRectangle("derived rectangle edge must be finite");
  }
  return { x, y, width, height };
}

function normalizeSlide(slide) {
  if (!isRecord(slide)) throw new TypeError("Invalid slide: must be an object");
  const hasOrigin = ["x", "y", "x1", "y1", "x2", "y2"].some((key) => hasOwn(slide, key));
  const normalized = hasOrigin
    ? normalizeRectangle(slide)
    : normalizeRectangle({ x: 0, y: 0, ...slide });
  if (normalized.width <= 0 || normalized.height <= 0) {
    throw new TypeError("Invalid slide: width and height must be positive");
  }
  if (!Number.isFinite(normalized.width * normalized.height)) {
    throw new TypeError("Invalid slide: area must be finite");
  }
  return normalized;
}

/**
 * Clip an axis-aligned rectangle to the slide. null means that the clipped
 * intersection has no positive area; zero-area input is still valid for the
 * normalization API and is ignored by area metrics.
 */
export function clipRectangle(rectangle, slide) {
  const normalized = normalizeRectangle(rectangle);
  const bounds = normalizeSlide(slide);
  const left = Math.max(normalized.x, bounds.x);
  const top = Math.max(normalized.y, bounds.y);
  const right = Math.min(normalized.x + normalized.width, bounds.x + bounds.width);
  const bottom = Math.min(normalized.y + normalized.height, bounds.y + bounds.height);
  if (right <= left || bottom <= top) return null;
  return { x: left, y: top, width: right - left, height: bottom - top };
}

export function normalizeSlideBounds(slide) {
  return normalizeSlide(slide);
}
