import assert from "node:assert/strict";
import test from "node:test";
import { clipRectangle, normalizeRectangle } from "../server/visual-quality/metrics/geometry.mjs";
import { computeElementUnion } from "../server/visual-quality/metrics/element-union.mjs";
import { computeWhitespace } from "../server/visual-quality/metrics/whitespace.mjs";

const slide = { width: 10, height: 10 };

function rectangle(x, y, width, height) {
  return { x, y, width, height };
}

function element(x, y, width, height, quality_role = "content") {
  return { quality_role, bbox: rectangle(x, y, width, height) };
}

test("geometry normalizes canonical, legacy, and edge-coordinate rectangles and clips to slide", () => {
  assert.deepEqual(normalizeRectangle(rectangle(1, 2, 3, 4)), { x: 1, y: 2, width: 3, height: 4 });
  assert.deepEqual(normalizeRectangle({ x: 1, y: 2, w: 3, h: 4 }), { x: 1, y: 2, width: 3, height: 4 });
  assert.deepEqual(normalizeRectangle({ x1: 1, y1: 2, x2: 4, y2: 6 }), { x: 1, y: 2, width: 3, height: 4 });
  assert.deepEqual(clipRectangle({ x: -2, y: 8, width: 5, height: 5 }, slide), { x: 0, y: 8, width: 3, height: 2 });
  assert.equal(clipRectangle({ x: 11, y: 0, width: 1, height: 1 }, slide), null);
});

test("element union handles empty, single, overlap, containment, adjacency, partial overlap, clipping, and zero area", () => {
  assert.deepEqual(computeElementUnion([], slide), {
    measurable: true,
    union_area: 0,
    slide_area: 100,
    element_area_ratio: 0,
    rectangle_count: 0,
  });
  assert.deepEqual(computeElementUnion([rectangle(1, 2, 3, 4)], slide), {
    measurable: true,
    union_area: 12,
    slide_area: 100,
    element_area_ratio: 0.12,
    rectangle_count: 1,
  });
  assert.equal(computeElementUnion([
    rectangle(0, 0, 4, 4),
    rectangle(2, 2, 4, 4),
  ], slide).union_area, 28);
  assert.equal(computeElementUnion([
    rectangle(0, 0, 8, 8),
    rectangle(2, 2, 2, 2),
  ], slide).union_area, 64);
  assert.equal(computeElementUnion([
    rectangle(0, 0, 4, 2),
    rectangle(4, 0, 4, 2),
  ], slide).union_area, 16);
  assert.equal(computeElementUnion([
    rectangle(0, 0, 4, 4),
    rectangle(3, 2, 4, 4),
  ], slide).union_area, 30);
  assert.equal(computeElementUnion([rectangle(-2, -1, 5, 4)], slide).union_area, 9);
  assert.deepEqual(computeElementUnion([
    rectangle(0, 0, 0, 5),
    rectangle(20, 20, 2, 2),
  ], slide), {
    measurable: true,
    union_area: 0,
    slide_area: 100,
    element_area_ratio: 0,
    rectangle_count: 0,
  });
});

test("geometry metrics reject malformed, non-finite, and negative-size rectangles", () => {
  for (const invalid of [
    null,
    {},
    { x: 0, y: 0, width: -1, height: 1 },
    { x: 0, y: 0, width: 1, height: -1 },
    { x: Number.NaN, y: 0, width: 1, height: 1 },
    { x: 0, y: Number.POSITIVE_INFINITY, width: 1, height: 1 },
    { x1: 2, y1: 0, x2: 1, y2: 1 },
  ]) {
    assert.throws(() => normalizeRectangle(invalid), TypeError);
    assert.throws(() => computeElementUnion([invalid], slide), TypeError);
  }
  assert.throws(() => computeElementUnion(rectangle(0, 0, 1, 1), slide), TypeError);
});

test("whitespace reports obvious horizontal and vertical gaps with margin/internal kinds", () => {
  const result = computeWhitespace([
    element(1, 1, 2, 2),
    element(5, 5, 2, 2),
  ], slide);
  assert.equal(result.measurable, true);
  assert.equal(result.element_count, 2);
  assert.equal(result.horizontal.largest_gap, 3);
  assert.equal(result.horizontal.largest_gap_ratio, 0.3);
  assert.deepEqual(result.horizontal.gaps.map((gap) => gap.kind), ["margin", "internal", "margin"]);
  assert.deepEqual(result.horizontal.gaps.map((gap) => gap.size), [1, 2, 3]);
  assert.equal(result.vertical.largest_gap, 3);
  assert.equal(result.vertical.largest_gap_ratio, 0.3);
  assert.deepEqual(result.vertical.gaps.map((gap) => gap.kind), ["margin", "internal", "margin"]);
});

test("whitespace merges overlapping and adjacent projections and distinguishes margins from internal gaps", () => {
  const result = computeWhitespace([
    element(1, 0, 2, 10),
    element(3, 0, 2, 10),
    element(7, 0, 2, 10),
  ], slide);
  assert.equal(result.horizontal.largest_gap, 2);
  assert.equal(result.horizontal.largest_gap_ratio, 0.2);
  assert.deepEqual(result.horizontal.gaps.map((gap) => ({ kind: gap.kind, size: gap.size })), [
    { kind: "margin", size: 1 },
    { kind: "internal", size: 2 },
    { kind: "margin", size: 1 },
  ]);
  assert.equal(result.vertical.largest_gap, 0);
  assert.equal(result.vertical.gaps.length, 0);
});

test("background and ignore never participate, while decoration follows include_decoration", () => {
  const elements = [
    element(0, 0, 10, 10, "background"),
    element(0, 0, 10, 10, "ignore"),
    element(1, 1, 2, 2, "decoration"),
  ];
  const excluded = computeWhitespace(elements, slide);
  assert.equal(excluded.element_count, 0);
  assert.equal(excluded.horizontal.largest_gap_ratio, 1);
  assert.equal(excluded.vertical.largest_gap_ratio, 1);

  const included = computeWhitespace(elements, slide, { include_decoration: true });
  assert.equal(included.element_count, 1);
  assert.equal(included.horizontal.largest_gap, 7);
  assert.equal(included.vertical.largest_gap, 7);
});

test("empty whitespace is measurable and deterministic across repeated calls", () => {
  const expected = computeWhitespace([], slide);
  assert.equal(expected.measurable, true);
  assert.equal(expected.element_count, 0);
  assert.equal(expected.horizontal.largest_gap, 10);
  assert.equal(expected.vertical.largest_gap, 10);
  assert.deepEqual(computeWhitespace([], slide), expected);
  assert.deepEqual(computeWhitespace([
    element(0, 0, 3, 3),
    element(4, 4, 2, 2),
  ], slide), computeWhitespace([
    element(4, 4, 2, 2),
    element(0, 0, 3, 3),
  ], slide));
});
