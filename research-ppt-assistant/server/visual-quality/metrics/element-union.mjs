import { clipRectangle, normalizeSlideBounds } from "./geometry.mjs";

function mergeIntervals(intervals) {
  const sorted = intervals
    .filter(([start, end]) => end > start)
    .sort((left, right) => left[0] - right[0] || left[1] - right[1]);
  const merged = [];
  for (const interval of sorted) {
    const previous = merged.at(-1);
    if (!previous || interval[0] > previous[1]) merged.push([...interval]);
    else previous[1] = Math.max(previous[1], interval[1]);
  }
  return merged;
}

function unionLength(intervals) {
  return mergeIntervals(intervals).reduce((total, [start, end]) => total + end - start, 0);
}

/**
 * Compute exact area of the clipped rectangle union using a deterministic
 * sweep line. Rectangles are validated by clipRectangle; zero-area and
 * completely out-of-slide rectangles do not participate.
 */
export function computeElementUnion(rectangles, slide) {
  if (!Array.isArray(rectangles)) throw new TypeError("rectangles must be an array");
  const bounds = normalizeSlideBounds(slide);
  const clipped = rectangles
    .map((rectangle) => clipRectangle(rectangle, bounds))
    .filter((rectangle) => rectangle !== null);
  const slideArea = bounds.width * bounds.height;
  if (!clipped.length) {
    return {
      measurable: true,
      union_area: 0,
      slide_area: slideArea,
      element_area_ratio: 0,
      rectangle_count: 0,
    };
  }

  const events = new Map();
  const addEvent = (x, type, index) => {
    if (!events.has(x)) events.set(x, { starts: [], ends: [] });
    events.get(x)[type].push(index);
  };
  clipped.forEach((rectangle, index) => {
    addEvent(rectangle.x, "starts", index);
    addEvent(rectangle.x + rectangle.width, "ends", index);
  });

  const xCoordinates = [...events.keys()].sort((left, right) => left - right);
  const active = new Set();
  let unionArea = 0;
  let previousX = xCoordinates[0];
  for (const x of xCoordinates) {
    const width = x - previousX;
    if (width > 0 && active.size) {
      unionArea += width * unionLength([...active].map((index) => {
        const rectangle = clipped[index];
        return [rectangle.y, rectangle.y + rectangle.height];
      }));
    }
    const event = events.get(x);
    for (const index of event.ends) active.delete(index);
    for (const index of event.starts) active.add(index);
    previousX = x;
  }

  return {
    measurable: true,
    union_area: unionArea,
    slide_area: slideArea,
    element_area_ratio: unionArea / slideArea,
    rectangle_count: clipped.length,
  };
}
