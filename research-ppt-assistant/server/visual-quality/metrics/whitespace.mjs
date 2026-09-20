import { clipRectangle, normalizeSlideBounds } from "./geometry.mjs";

const QUALITY_ROLES = new Set(["content", "decoration", "background", "ignore"]);

function isRecord(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function gapRecord(start, end, slideSize, kind) {
  const size = end - start;
  return {
    start,
    end,
    size,
    ratio: size / slideSize,
    kind,
  };
}

function projectedGaps(intervals, start, end) {
  const sorted = intervals
    .sort((left, right) => left[0] - right[0] || left[1] - right[1]);
  const merged = [];
  for (const interval of sorted) {
    const previous = merged.at(-1);
    if (!previous || interval[0] > previous[1]) merged.push([...interval]);
    else previous[1] = Math.max(previous[1], interval[1]);
  }

  const gaps = [];
  if (!merged.length) {
    gaps.push(gapRecord(start, end, end - start, "margin"));
  } else {
    if (merged[0][0] > start) gaps.push(gapRecord(start, merged[0][0], end - start, "margin"));
    for (let index = 1; index < merged.length; index += 1) {
      const previous = merged[index - 1];
      const current = merged[index];
      if (current[0] > previous[1]) gaps.push(gapRecord(previous[1], current[0], end - start, "internal"));
    }
    const last = merged.at(-1);
    if (last[1] < end) gaps.push(gapRecord(last[1], end, end - start, "margin"));
  }
  return gaps;
}

function axisMetric(axis, intervals, start, end) {
  const gaps = projectedGaps(intervals, start, end);
  const largestGap = gaps.reduce((largest, gap) => Math.max(largest, gap.size), 0);
  return {
    axis,
    largest_gap: largestGap,
    largest_gap_ratio: largestGap / (end - start),
    gaps,
  };
}

function elementRole(element) {
  if (!isRecord(element)) return undefined;
  const role = element.quality_role ?? element.qualityRole ?? element.role ?? "content";
  return typeof role === "string" && QUALITY_ROLES.has(role) ? role : undefined;
}

function elementRectangle(element) {
  if (element.bbox !== null && element.bbox !== undefined) return element.bbox;
  if (element.box !== null && element.box !== undefined) return element.box;
  if (["x", "y", "width", "height", "w", "h", "x1", "y1", "x2", "y2"].some((key) => Object.prototype.hasOwnProperty.call(element, key))) return element;
  return undefined;
}

function selectedElements(elements, includeDecoration, slide) {
  const clipped = [];
  let elementCount = 0;
  let unavailableReason;
  for (const element of elements) {
    const role = elementRole(element);
    if (!role) {
      unavailableReason ??= "invalid_element_role";
      continue;
    }
    if (role === "background" || role === "ignore") continue;
    if (role === "decoration" && !includeDecoration) continue;
    const rawRectangle = elementRectangle(element);
    if (rawRectangle === null || rawRectangle === undefined) {
      unavailableReason ??= "element_bbox_telemetry_missing";
      continue;
    }
    const rectangle = clipRectangle(rawRectangle, slide);
    if (rectangle) {
      clipped.push(rectangle);
      elementCount += 1;
    }
  }
  return { clipped, element_count: elementCount, unavailable_reason: unavailableReason };
}

function unavailable(reason, elementCount) {
  const axis = (name) => ({
    axis: name,
    largest_gap: null,
    largest_gap_ratio: null,
    gaps: [],
  });
  return {
    measurable: false,
    horizontal: axis("x"),
    vertical: axis("y"),
    element_count: elementCount,
    unavailable_reason: reason,
  };
}

/**
 * Project selected element rectangles onto each slide axis and report all
 * positive gaps. Gaps touching a slide edge are margins; gaps between merged
 * occupied intervals are internal gaps. This metric intentionally has no
 * warning/fail thresholds and does not detect two-dimensional internal voids.
 */
export function computeWhitespace(elements, slide, options = {}) {
  if (!Array.isArray(elements)) throw new TypeError("elements must be an array");
  if (!isRecord(options)) throw new TypeError("Whitespace options must be an object");
  const includeDecoration = options.include_decoration ?? options.includeDecoration ?? false;
  if (typeof includeDecoration !== "boolean") throw new TypeError("include_decoration must be boolean");
  const bounds = normalizeSlideBounds(slide);
  const selection = selectedElements(elements, includeDecoration, bounds);
  if (selection.unavailable_reason) return unavailable(selection.unavailable_reason, selection.element_count);
  const { clipped } = selection;
  const horizontal = axisMetric(
    "x",
    clipped.map((rectangle) => [rectangle.x, rectangle.x + rectangle.width]),
    bounds.x,
    bounds.x + bounds.width,
  );
  const vertical = axisMetric(
    "y",
    clipped.map((rectangle) => [rectangle.y, rectangle.y + rectangle.height]),
    bounds.y,
    bounds.y + bounds.height,
  );
  return {
    measurable: true,
    horizontal,
    vertical,
    element_count: clipped.length,
  };
}
