import assert from "node:assert/strict";
import test from "node:test";
import { computeOverflow, measureTextOverflow } from "../server/visual-quality/metrics/overflow.mjs";
import { collectThemeUsage } from "../server/visual-quality/metrics/theme-usage.mjs";

const slide = { width: 10, height: 10 };

function element(overrides = {}) {
  return {
    element_id: "content",
    type: "text",
    quality_role: "content",
    bbox: { x: 1, y: 1, width: 4, height: 2 },
    text: { overflow: false },
    theme_token: "text",
    theme_usage: "body_text",
    ...overrides,
  };
}

test("overflow metrics report explicit renderer overflow and clipped-edge evidence", () => {
  const result = computeOverflow([
    element({ element_id: "overflow", text: { overflow: true } }),
    element({ element_id: "outside", bbox: { x: -1, y: 9, width: 12, height: 3 } }),
  ], slide);
  assert.equal(result.text_overflow.measurable, true);
  assert.equal(result.text_overflow.count, 1);
  assert.equal(result.element_out_of_bounds.count, 1);
  assert.deepEqual(result.element_out_of_bounds.elements[0].overflow, { left: 1, top: 0, right: 1, bottom: 2 });
});

test("overflow metrics never pass a partially observed participating set", () => {
  const result = computeOverflow([
    element({ element_id: "known" }),
    element({ element_id: "unknown", bbox: null, text: { overflow: null } }),
  ], slide);
  assert.equal(result.text_overflow.measurable, false);
  assert.equal(result.element_out_of_bounds.measurable, false);
  assert.equal(result.text_overflow.observed_count, 1);
  assert.equal(result.text_overflow.expected_count, 2);
});

test("pixel geometry is authoritative when render dimensions are present", () => {
  const result = computeOverflow([
    element({
      bbox: { x: 1, y: 1, width: 4, height: 2 },
      render_bbox_px: { x: 900, y: 100, width: 200, height: 100 },
    }),
  ], { width: 10, height: 10, render_width_px: 1000, render_height_px: 1000 });
  assert.equal(result.element_out_of_bounds.measurable, true);
  assert.equal(result.element_out_of_bounds.count, 1);
  assert.equal(result.element_out_of_bounds.coordinate_space, "render_bbox_px");
});

test("overflow excludes background, ignore, and decoration by default", () => {
  const elements = [
    element({ quality_role: "background", bbox: { x: -2, y: -2, width: 14, height: 14 }, text: { overflow: true } }),
    element({ quality_role: "ignore", bbox: { x: -2, y: -2, width: 14, height: 14 }, text: { overflow: true } }),
    element({ quality_role: "decoration", bbox: { x: -2, y: -2, width: 14, height: 14 }, text: { overflow: true } }),
  ];
  const excluded = computeOverflow(elements, slide);
  assert.equal(excluded.text_overflow.measurable, false);
  assert.equal(excluded.element_out_of_bounds.measurable, false);
  const included = computeOverflow(elements, slide, { include_decoration: true });
  assert.equal(included.text_overflow.count, 1);
  assert.equal(included.element_out_of_bounds.count, 1);
  assert.throws(() => computeOverflow([], { width: 0, height: 10 }), TypeError);
  assert.throws(() => computeOverflow({}, slide), TypeError);
});

test("theme usage distinguishes allowed, forbidden, not-allowed, unknown, and ignored facts", () => {
  const theme = {
    tokens: {
      text: { allowed_usage: ["body_text"], forbidden_usage: ["background"] },
      accent: { allowed_usage: ["fill"], forbidden_usage: [] },
    },
  };
  const result = collectThemeUsage([
    element({ element_id: "allowed" }),
    element({ element_id: "forbidden", theme_usage: "background" }),
    element({ element_id: "not-allowed", theme_token: "accent", theme_usage: "body_text" }),
    element({ element_id: "unknown", theme_token: "future", theme_usage: "fill" }),
    element({ element_id: "ignored", quality_role: "ignore", theme_usage: "background" }),
    element({ element_id: "unreported", theme_token: null, theme_usage: null }),
  ], theme);
  assert.equal(result.measurable, true);
  assert.equal(result.usage_count, 4);
  assert.equal(result.violation_count, 3);
  assert.deepEqual(result.usages.map((usage) => usage.result), ["allowed", "forbidden", "not_allowed", "unknown_token"]);
});

test("missing theme or usage telemetry is explicitly unavailable", () => {
  assert.equal(collectThemeUsage([], null).unavailable_reason, "theme_token_contract_missing");
  const noUsage = collectThemeUsage([element({ theme_token: null, theme_usage: null })], { tokens: {} });
  assert.equal(noUsage.measurable, false);
  assert.equal(noUsage.unavailable_reason, "theme_usage_telemetry_missing");
  assert.throws(() => collectThemeUsage({}, { tokens: {} }), TypeError);
});

// A 16:9 deck rendered at 1280x720, matching the geometry a slidep renderer reports.
const deckSlide = { width: 13.333, height: 7.5, render_width_px: 1280, render_height_px: 720 };
// 66 full-width characters: the real body copy that was silently clipped in production.
const CJK_BODY = "化学染料虽统治千年，但有毒污染与褪色问题不可持续；人工结构色却难以预测多尺度协同、难以统一生色机制，因而无法指导层级结构的理性设计。";

function measuredElement(overrides = {}) {
  return {
    element_id: "body",
    type: "text",
    quality_role: "content",
    bbox: { x: 0.729, y: 1.427, width: 3.729, height: 2.604 },
    render_bbox_px: { x: 70, y: 137, width: 358, height: 250 },
    text: {
      content: CJK_BODY,
      language: "zh-CN",
      script: "CJK",
      font_family: "Microsoft YaHei",
      font_size: 26.25, // 35px expressed in points, as the contract requires
      font_weight: 500,
      line_count: 1,
      overflow: false,
      foreground_color: "#0F172A",
      intended_single_line: false,
      role: "body",
    },
    theme_token: "text",
    theme_usage: "body_text",
    ...overrides,
  };
}

test("text overflow is detected from font metrics even when the renderer reports no overflow", () => {
  // The renderer neither shrank the text nor flagged it; it simply clipped. The gate
  // must still catch this from geometry, font size and content alone.
  const result = computeOverflow([measuredElement()], deckSlide);
  assert.equal(result.text_overflow.measurable, true);
  assert.equal(result.text_overflow.count, 1);
  assert.deepEqual(result.text_overflow.elements, [{ element_id: "body", overflow: true }]);
});

test("the same copy at a size fitted to the box does not trip the overflow gate", () => {
  const fitted = measuredElement({ text: { ...measuredElement().text, font_size: 18.75 } });
  const result = computeOverflow([fitted], deckSlide);
  assert.equal(result.text_overflow.measurable, true);
  assert.equal(result.text_overflow.count, 0);
});

test("a declared overflow is never replaced by a coarser measurement", () => {
  const declared = measuredElement({ text: { ...measuredElement().text, overflow: true } });
  const result = computeOverflow([declared], deckSlide);
  assert.equal(result.text_overflow.count, 1);
  assert.equal(result.text_overflow.observed_count, 1);
});

test("full-width copy is measured as wider than the same amount of latin text", () => {
  const latin = "Colorants dominate, yet pollution and fading make them unsustainable across decades of everyday use.";
  const measure = (content) => measureTextOverflow(
    measuredElement({ text: { ...measuredElement().text, content } }),
    measuredElement().render_bbox_px,
    deckSlide,
    { unitsPerInch: 1280 / 13.333 },
  );
  assert.equal(measure(CJK_BODY).overflow, true);
  assert.equal(measure(latin).overflow, false);
  assert.ok(measure(CJK_BODY).lines > measure(latin).lines);
});

test("measurement does not claim coverage when neither overflow nor geometry is available", () => {
  // Honouring `unavailable` is what keeps a partially observed deck from passing: with
  // no declared overflow and no usable box there is nothing to measure, so the gate
  // must stay unenforceable rather than silently reporting zero overflows.
  const blind = measuredElement({ text: { ...measuredElement().text, overflow: null } });
  const result = computeOverflow([blind], deckSlide, {
    unavailable: [{ field: "elements[0].bbox", reason: "renderer_did_not_expose_logical_box" }],
  });
  assert.equal(result.text_overflow.measurable, false);
  assert.equal(result.text_overflow.unavailable_reason, "text_overflow_telemetry_incomplete");
});

test("a declared overflow flag still covers an element whose geometry is unavailable", () => {
  const blind = measuredElement();
  const result = computeOverflow([blind], deckSlide, {
    unavailable: [{ field: "elements[0].bbox", reason: "renderer_did_not_expose_logical_box" }],
  });
  assert.equal(result.text_overflow.measurable, true);
  assert.equal(result.text_overflow.count, 0);
});

test("text without content or font telemetry cannot be measured", () => {
  const box = measuredElement().render_bbox_px;
  assert.equal(measureTextOverflow(measuredElement({ text: { overflow: false } }), box, deckSlide), null);
  const noFont = measuredElement({ text: { ...measuredElement().text, font_size: null } });
  assert.equal(measureTextOverflow(noFont, noFont.render_bbox_px, deckSlide), null);
  assert.equal(measureTextOverflow(measuredElement(), null, deckSlide), null);
});
