import assert from "node:assert/strict";
import test from "node:test";
import { computeSolidContrast } from "../server/visual-quality/metrics/contrast.mjs";
import { computeVisualCenter } from "../server/visual-quality/metrics/visual-center.mjs";

const slide = { width: 100, height: 100 };
const box = (x, y, width = 10, height = 10, quality_role = "content") => ({
  quality_role,
  bbox: { x, y, width, height },
});

function closeTo(actual, expected, tolerance = 1e-12) {
  assert.ok(Math.abs(actual - expected) <= tolerance, `${actual} is not close to ${expected}`);
}

test("visual center is centered for symmetric content and reports every directional shift", () => {
  const centered = computeVisualCenter([box(45, 45, 10, 10)], slide);
  assert.equal(centered.measurable, true);
  assert.deepEqual(centered.normalized_center, { x: 0.5, y: 0.5 });
  assert.equal(centered.offset, 0);

  const cases = [
    ["left", [box(0, 45)], { x: 0.05, y: 0.5 }],
    ["right", [box(90, 45)], { x: 0.95, y: 0.5 }],
    ["up", [box(45, 0)], { x: 0.5, y: 0.05 }],
    ["down", [box(45, 90)], { x: 0.5, y: 0.95 }],
  ];
  for (const [name, elements, expected] of cases) {
    const result = computeVisualCenter(elements, slide);
    assert.equal(result.measurable, true, name);
    assert.deepEqual(result.normalized_center, expected, name);
    closeTo(result.offset, 45 / Math.hypot(100, 100), 1e-12);
  }

  const symmetric = computeVisualCenter([box(0, 0), box(90, 90)], slide);
  assert.deepEqual(symmetric.normalized_center, { x: 0.5, y: 0.5 });
  assert.equal(symmetric.element_count, 2);
});

test("visual center uses clipped effective area and different area weights", () => {
  const clipped = computeVisualCenter([box(-10, 40, 30, 20)], slide);
  assert.equal(clipped.measurable, true);
  closeTo(clipped.center.x, 10);
  closeTo(clipped.center.y, 50);

  const weighted = computeVisualCenter([box(0, 45, 10, 10), box(80, 45, 20, 10)], slide);
  assert.equal(weighted.measurable, true);
  closeTo(weighted.center.x, 61.666666666666664);
  closeTo(weighted.normalized_center.x, 0.6166666666666667);
  assert.equal(weighted.element_count, 2);
});

test("visual center normalizes physical displacement by a non-square slide diagonal", () => {
  const result = computeVisualCenter([box(0, 40, 20, 20)], { width: 200, height: 100 });
  closeTo(result.center.x, 10);
  closeTo(result.center.y, 50);
  closeTo(result.offset, 90 / Math.hypot(200, 100));
});

test("visual center applies quality roles and optional role weights", () => {
  const elements = [
    box(0, 45),
    box(90, 45, 10, 10, "decoration"),
    box(45, 45, 10, 10, "background"),
    box(45, 0, 10, 10, "ignore"),
  ];
  const contentOnly = computeVisualCenter(elements, slide);
  assert.deepEqual(contentOnly.normalized_center, { x: 0.05, y: 0.5 });
  assert.equal(contentOnly.element_count, 1);

  const withDecoration = computeVisualCenter(elements, slide, { include_decoration: true });
  closeTo(withDecoration.normalized_center.x, 0.5);
  assert.equal(withDecoration.element_count, 2);

  const weighted = computeVisualCenter([box(0, 45), box(90, 45, 10, 10, "decoration")], slide, { include_decoration: true, role_weights: { content: 1, decoration: 3 } });
  closeTo(weighted.normalized_center.x, 0.725);
  assert.equal(weighted.measurable, true);
});

test("visual center makes empty, invalid, and unmeasurable input explicit", () => {
  const empty = computeVisualCenter([], slide);
  assert.equal(empty.measurable, false);
  assert.equal(empty.center, null);
  assert.equal(empty.normalized_center, null);
  assert.equal(empty.offset, null);
  assert.equal(empty.element_count, 0);
  assert.ok(empty.unavailable_reason);

  const invalid = computeVisualCenter([box(0, 0, -1, 10)], slide);
  assert.equal(invalid.measurable, false);
  assert.match(invalid.unavailable_reason, /geometry/);

  const missingRole = computeVisualCenter([{ bbox: { x: 0, y: 0, width: 10, height: 10 } }], slide);
  assert.equal(missingRole.measurable, false);
  assert.equal(missingRole.unavailable_reason, "invalid_element_role");

  const outside = computeVisualCenter([box(200, 200)], slide);
  assert.equal(outside.measurable, false);
  assert.equal(outside.unavailable_reason, "no_visible_elements");
});

test("solid contrast uses WCAG luminance and normalized colors", () => {
  const blackWhite = computeSolidContrast("#000000", "#FFFFFF");
  assert.equal(blackWhite.measurable, true);
  assert.equal(blackWhite.contrast_ratio, 21);
  assert.equal(blackWhite.foreground_color, "#000000");
  assert.equal(blackWhite.background_color, "#ffffff");

  const same = computeSolidContrast("#777", { kind: "solid", color: "#777777" });
  assert.equal(same.measurable, true);
  assert.equal(same.contrast_ratio, 1);
  assert.equal(same.foreground_color, "#777777");
  assert.equal(same.background_color, "#777777");

  const alpha = computeSolidContrast("#ff000080", "#000");
  assert.equal(alpha.measurable, true);
  assert.equal(alpha.foreground_color, "#ff000080");
  assert.equal(alpha.background_color, "#000000");
  assert.ok(alpha.contrast_ratio > 1);
});

test("solid contrast rejects invalid and complex or transparent backgrounds", () => {
  for (const result of [
    computeSolidContrast("#000", "not-a-color"),
    computeSolidContrast("not-a-color", "#fff"),
    computeSolidContrast("#000", { kind: "image", color: "#fff" }),
    computeSolidContrast("#000", { kind: "gradient", color: "#fff" }),
    computeSolidContrast("#000", { kind: "unknown", color: "#fff" }),
    computeSolidContrast("#000", { kind: "transparent", color: null }),
    computeSolidContrast("#000", null),
    computeSolidContrast("#000", "#ffffff00"),
  ]) {
    assert.equal(result.measurable, false);
    assert.equal(result.contrast_ratio, null);
    assert.ok(result.unavailable_reason);
  }
});

test("both metrics are deterministic for repeated input", () => {
  const elements = [box(10, 20, 30, 40), box(60, 70, 20, 10, "decoration")];
  const centerA = computeVisualCenter(elements, slide, { include_decoration: true, role_weights: { content: 2, decoration: 0.5 } });
  const centerB = computeVisualCenter(elements, slide, { include_decoration: true, role_weights: { content: 2, decoration: 0.5 } });
  assert.deepEqual(centerA, centerB);
  assert.deepEqual(computeSolidContrast("#1234", { kind: "solid", color: "#abcdef" }), computeSolidContrast("#1234", { kind: "solid", color: "#abcdef" }));
});
