import assert from "node:assert/strict";
import test from "node:test";
import { assertJsonSchema } from "../server/schema-validator.mjs";
import {
  QA_REPORT_SCHEMA,
  RENDER_TELEMETRY_SCHEMA,
  evaluateRule,
  evaluateVisualQuality,
  loadQualityProfile,
  resolveQualityProfile,
} from "../server/visual-quality/index.mjs";
import { assertRenderTelemetry } from "../server/visual-quality/telemetry.mjs";

function telemetryFixture(overrides = {}) {
  const fixture = {
    telemetry_version: "1.0.0",
    slide_id: "slide-1",
    renderer: "slidep",
    slide: {
      width: 10,
      height: 10,
      render_width_px: 1000,
      render_height_px: 1000,
      background: { kind: "solid", color: "#FFFFFF" },
    },
    elements: [
      {
        element_id: "background",
        type: "shape",
        quality_role: "background",
        bbox: { x: 0, y: 0, width: 10, height: 10 },
        render_bbox_px: { x: 0, y: 0, width: 1000, height: 1000 },
        text: null,
        image: null,
        fill_color: "#FFFFFF",
        background_color: null,
        theme_token: "bg",
        theme_usage: "background",
      },
      {
        element_id: "body",
        type: "text",
        quality_role: "content",
        bbox: { x: 1, y: 1, width: 8, height: 8 },
        render_bbox_px: { x: 100, y: 100, width: 800, height: 800 },
        text: {
          content: "Readable",
          language: "en",
          script: "Latin",
          font_family: "Arial",
          font_size: 20,
          font_weight: 400,
          line_count: 1,
          overflow: false,
          foreground_color: "#111111",
          intended_single_line: false,
          role: "body",
        },
        image: null,
        fill_color: null,
        background_color: "#FFFFFF",
        theme_token: "text",
        theme_usage: "body_text",
      },
    ],
    theme: {
      id: "fixture",
      tokens: {
        bg: { color: "#FFFFFF", allowed_usage: ["background"], forbidden_usage: ["body_text"] },
        text: { color: "#111111", allowed_usage: ["body_text", "title_text"], forbidden_usage: ["background"] },
      },
    },
    unavailable: [],
    provided_metrics: {},
  };
  return { ...fixture, ...overrides };
}

function scientificVisualTelemetry({
  slideId,
  elementId,
  bbox,
  allocatedBbox,
  visualType,
  panelCount = 1,
  hasEmbeddedText = true,
  renderedEmbeddedTextPx = 14,
} = {}) {
  const slide = { width: 13.333, height: 7.5, render_width_px: 1920, render_height_px: 1080 };
  const renderBox = {
    x: Math.round(bbox.x / slide.width * slide.render_width_px),
    y: Math.round(bbox.y / slide.height * slide.render_height_px),
    width: Math.round(bbox.width / slide.width * slide.render_width_px),
    height: Math.round(bbox.height / slide.height * slide.render_height_px),
  };
  return {
    telemetry_version: "1.2.0",
    slide_id: slideId,
    renderer: "slidep",
    slide: {
      ...slide,
      background: { kind: "solid", color: "#FFFFFF" },
      layout_id: "fixture-layout",
      category: "evidence",
    },
    elements: [
      {
        element_id: "background", type: "shape", quality_role: "background", z_index: 0, opacity: 1,
        bbox: { x: 0, y: 0, width: slide.width, height: slide.height },
        render_bbox_px: { x: 0, y: 0, width: slide.render_width_px, height: slide.render_height_px },
        text: null, image: null, fill_color: "#FFFFFF", background_color: null, theme_token: "bg", theme_usage: "background",
      },
      {
        element_id: "title", type: "text", quality_role: "content", z_index: 1, opacity: 1,
        bbox: { x: 0.7, y: 0.3, width: 11.9, height: 0.8 },
        render_bbox_px: { x: 101, y: 43, width: 1714, height: 115 },
        text: {
          content: "Scientific visual", language: "en", script: "Latin", font_family: "Arial", font_size: 40,
          font_weight: 700, line_count: 1, overflow: false, foreground_color: "#111111", local_contrast_ratio: 18,
          intended_single_line: true, role: "title",
        },
        image: null, fill_color: null, background_color: "#FFFFFF", theme_token: "text", theme_usage: "title_text",
      },
      {
        element_id: elementId, type: "image", quality_role: "content", z_index: 2, opacity: 1,
        bbox, render_bbox_px: renderBox, text: null,
        image: {
          display_bbox: bbox,
          source_width_px: 1200,
          source_height_px: 900,
          visual_id: `VIS-${elementId}`,
          content_id: `CONTENT-${elementId}`,
          slot_id: "figure",
          visual_type: visualType,
          panel_count: panelCount,
          has_embedded_text: hasEmbeddedText,
          min_display_width: null,
          allocated_bbox: allocatedBbox,
          rendered_embedded_text_px: hasEmbeddedText ? renderedEmbeddedTextPx : null,
        },
        fill_color: null, background_color: null, theme_token: null, theme_usage: null,
      },
    ],
    theme: {
      id: "fixture",
      tokens: {
        bg: { color: "#FFFFFF", allowed_usage: ["background"], forbidden_usage: ["body_text"] },
        text: { color: "#111111", allowed_usage: ["body_text", "title_text"], forbidden_usage: ["background"] },
      },
    },
    unavailable: [],
    provided_metrics: {},
  };
}

test("visual quality contract, profile, and report schemas validate", async () => {
  const telemetry = telemetryFixture();
  assertJsonSchema(RENDER_TELEMETRY_SCHEMA, telemetry);
  const profile = await loadQualityProfile("slidep");
  assert.equal(profile.profile_id, "slidep");
  assert.ok(profile.rules.text_overflow);
  const report = await evaluateVisualQuality({ telemetry });
  assertJsonSchema(QA_REPORT_SCHEMA, report);
  assert.equal(report.status, "pass");
  assert.equal(report.violations.length, 0);
});

test("renderer-measured local contrast takes precedence over the slide background", async () => {
  const protectedText = telemetryFixture();
  protectedText.elements[1].text.foreground_color = "#FFFFFF";
  protectedText.elements[1].text.local_contrast_ratio = 16;
  protectedText.elements[1].background_color = null;
  protectedText.elements[1].fill_color = "#0B1F33";
  const passing = await evaluateVisualQuality({ telemetry: protectedText });
  assert.equal(passing.checks.solid_text_contrast.status, "pass");
  assert.equal(passing.metrics.contrast.find((item) => item.element_id === "body").contrast_ratio, 16);

  protectedText.elements[1].text.local_contrast_ratio = 1.1;
  const failing = await evaluateVisualQuality({ telemetry: protectedText });
  assert.equal(failing.checks.solid_text_contrast.status, "fail");
  assert.ok(failing.violations.some((item) => item.code === "TEXT_CONTRAST_LOW"));
});

test("profile-driven rules separate metric facts from warning/fail interpretation", () => {
  const definition = {
    enabled: true,
    metric: "ratio",
    operator: "maximum",
    warning: 0.2,
    fail: 0.4,
    warning_code: "WARN",
    fail_code: "FAIL",
    reason: "fixture",
    recommended_action: "review",
  };
  assert.equal(evaluateRule({ measurable: true, value: 0.1 }, definition).status, "pass");
  assert.equal(evaluateRule({ measurable: true, value: 0.3 }, definition).status, "warning");
  assert.equal(evaluateRule({ measurable: true, value: 0.5 }, definition).status, "fail");
  assert.equal(evaluateRule({ measurable: false, unavailable_reason: "missing" }, definition).status, "not_evaluable");
  assert.equal(evaluateRule(0.5, { ...definition, enabled: false }).disabled, true);
});

test("overflow, out-of-bounds, and forbidden theme usage cannot false pass", async () => {
  const telemetry = telemetryFixture();
  telemetry.elements[1].bbox.x = 9;
  telemetry.elements[1].render_bbox_px.x = 900;
  telemetry.elements[1].render_bbox_px.width = 800;
  telemetry.elements[1].text.overflow = true;
  telemetry.elements[1].theme_usage = "background";
  const first = await evaluateVisualQuality({ telemetry });
  const second = await evaluateVisualQuality({ telemetry: structuredClone(telemetry) });
  assert.equal(first.status, "fail");
  for (const code of ["TEXT_VISUAL_OVERFLOW", "ELEMENT_OUT_OF_BOUNDS", "THEME_USAGE_VIOLATION"]) {
    assert.ok(first.violations.some((violation) => violation.code === code), code);
  }
  assert.deepEqual(first, second);
});

test("canonical scientific visual QA catches the P5 and P11 undersized-placement regressions", async () => {
  const p5 = scientificVisualTelemetry({
    slideId: "P5",
    elementId: "mech-input-img",
    bbox: { x: 4.128, y: 1.5, width: 0.678, height: 0.737 },
    allocatedBbox: { x: 3.467, y: 1.5, width: 2, height: 0.737 },
    visualType: "multi_panel_figure",
    panelCount: 2,
  });
  const p11 = scientificVisualTelemetry({
    slideId: "P11",
    elementId: "summary-img",
    bbox: { x: 8.013, y: 4.18, width: 2.16, height: 1.539 },
    allocatedBbox: { x: 8.013, y: 3.525, width: 2.16, height: 2.85 },
    visualType: "visual_evidence",
  });
  for (const telemetry of [p5, p11]) {
    const report = await evaluateVisualQuality({ telemetry, context: { viewing_mode: "projector" } });
    assert.equal(report.checks.scientific_visual_readability.status, "fail");
    assert.ok(report.violations.some((item) => item.code === "DENSE_FIGURE_TOO_SMALL"));
    assert.ok(report.violations.some((item) => item.code === "IMAGE_UNDERFILLED_SLOT"));
  }
});

test("telemetry 1.2 requires renderer-declared scientific visual facts instead of inferred passes", async () => {
  const telemetry = scientificVisualTelemetry({
    slideId: "missing-allocation",
    elementId: "figure",
    bbox: { x: 2, y: 1.5, width: 7, height: 4 },
    allocatedBbox: { x: 2, y: 1.5, width: 7, height: 4 },
    visualType: "dense_plot",
    hasEmbeddedText: false,
  });
  telemetry.elements[2].image.allocated_bbox = null;
  assert.throws(() => assertRenderTelemetry(telemetry), /allocated_bbox must be present or listed as unavailable/);
  telemetry.unavailable.push({ field: "elements[2].image.allocated_bbox", reason: "renderer_did_not_expose_allocated_visual_geometry" });
  const report = await evaluateVisualQuality({ telemetry });
  assert.equal(report.checks.scientific_visual_readability.status, "not_evaluable");
  assert.ok(report.violations.some((item) => item.code === "SCIENTIFIC_VISUAL_NOT_EVALUABLE"));
});

test("scientific visual QA distinguishes profile warning, embedded-text warning, and pass", async () => {
  const narrow = scientificVisualTelemetry({
    slideId: "narrow-dense-plot",
    elementId: "plot",
    bbox: { x: 2, y: 1.5, width: 5.333, height: 4 },
    allocatedBbox: { x: 2, y: 1.5, width: 5.333, height: 4 },
    visualType: "dense_plot",
    hasEmbeddedText: false,
  });
  const narrowReport = await evaluateVisualQuality({ telemetry: narrow, context: { viewing_mode: "projector" } });
  assert.equal(narrowReport.checks.scientific_visual_readability.status, "warning");
  assert.ok(narrowReport.violations.some((item) => item.code === "VISUAL_READABILITY_RISK"));

  const smallText = scientificVisualTelemetry({
    slideId: "small-embedded-text",
    elementId: "plot",
    bbox: { x: 2, y: 1.5, width: 7, height: 4 },
    allocatedBbox: { x: 2, y: 1.5, width: 7, height: 4 },
    visualType: "dense_plot",
    renderedEmbeddedTextPx: 12,
  });
  const smallTextReport = await evaluateVisualQuality({ telemetry: smallText, context: { viewing_mode: "projector" } });
  assert.equal(smallTextReport.checks.scientific_visual_readability.status, "warning");
  assert.ok(smallTextReport.violations.some((item) => item.code === "EMBEDDED_TEXT_TOO_SMALL"));

  smallText.elements[2].image.rendered_embedded_text_px = 15;
  const passingReport = await evaluateVisualQuality({ telemetry: smallText, context: { viewing_mode: "projector" } });
  assert.equal(passingReport.checks.scientific_visual_readability.status, "pass");
});

test("unmeasured raster text is a non-blocking manual-review item, while measurement failure remains a warning", async () => {
  const telemetry = scientificVisualTelemetry({
    slideId: "raster-unmeasured",
    elementId: "figure",
    bbox: { x: 1, y: 1.4, width: 9, height: 5.4 },
    allocatedBbox: { x: 1, y: 1.4, width: 9, height: 5.4 },
    visualType: "dense_plot",
    renderedEmbeddedTextPx: null,
  });
  telemetry.unavailable.push({ field: "elements[2].image.rendered_embedded_text_px", reason: "renderer did not measure raster text" });
  const unmeasured = await evaluateVisualQuality({ telemetry });
  assert.equal(unmeasured.status, "pass");
  assert.equal(unmeasured.checks.scientific_visual_readability.status, "not_evaluable");
  assert.equal(unmeasured.checks.scientific_visual_readability.blocking, false);
  assert.equal(unmeasured.manual_review.length, 1);
  assert.equal(unmeasured.violations.find((item) => item.code === "SCIENTIFIC_VISUAL_NOT_EVALUABLE").severity, "info");

  telemetry.unavailable[0].reason = "OCR measurement failed with an error";
  const failed = await evaluateVisualQuality({ telemetry });
  assert.equal(failed.status, "warning");
  assert.equal(failed.checks.scientific_visual_readability.blocking, true);
});

test("complex backgrounds remain not_evaluable for contrast", async () => {
  const telemetry = telemetryFixture();
  telemetry.elements[1].background_color = null;
  telemetry.slide.background = { kind: "image", color: null };
  const report = await evaluateVisualQuality({ telemetry });
  assert.equal(report.checks.solid_text_contrast.status, "not_evaluable");
  assert.notEqual(report.status, "pass");
});

test("a renderer-declared missing element collection produces not_evaluable instead of pass", async () => {
  const telemetry = telemetryFixture({ elements: [], theme: null });
  telemetry.unavailable = [{ field: "elements", reason: "renderer_did_not_expose_elements" }];
  const report = await evaluateVisualQuality({ telemetry });
  assert.equal(report.status, "not_evaluable");
  assert.ok(Object.values(report.checks).every((check) => check.status === "not_evaluable"));
});

test("mixed missing geometry and overflow data cannot pass by observing only a subset", async () => {
  const telemetry = telemetryFixture();
  const second = structuredClone(telemetry.elements[1]);
  second.element_id = "body-missing";
  second.bbox = null;
  second.text.overflow = null;
  telemetry.elements.push(second);
  telemetry.unavailable.push(
    { field: "elements[2].bbox", reason: "renderer_did_not_expose_logical_box" },
    { field: "elements[2].text.overflow", reason: "renderer_did_not_expose_overflow" },
  );
  const report = await evaluateVisualQuality({ telemetry });
  assert.equal(report.checks.element_area_ratio.status, "not_evaluable");
  assert.equal(report.checks.largest_horizontal_gap.status, "not_evaluable");
  assert.equal(report.checks.visual_center.status, "not_evaluable");
  assert.equal(report.checks.text_overflow.status, "not_evaluable");
  assert.notEqual(report.status, "pass");
});

test("missing theme usage constraints are not treated as an explicit empty constraint", async () => {
  const telemetry = telemetryFixture();
  telemetry.theme.tokens.text.allowed_usage = [];
  telemetry.theme.tokens.text.forbidden_usage = [];
  telemetry.unavailable.push({ field: "theme.tokens.text.allowed_usage", reason: "renderer_did_not_expose_allowed_usage" });
  const report = await evaluateVisualQuality({ telemetry });
  assert.equal(report.checks.theme_usage.status, "not_evaluable");
  assert.equal(report.metrics.theme_usage.unavailable_reason, "theme_usage_constraints_incomplete");
});

test("inline profiles resolve extends exactly like file profiles and reject cycles", async () => {
  const profile = await resolveQualityProfile({
    profile: { profile_id: "custom", profile_version: "1.0.0", extends: "default", rules: {} },
  });
  assert.ok(profile.rules.text_overflow);
  assert.equal(profile.profile_id, "custom");
  await assert.rejects(
    resolveQualityProfile({ profile: { profile_id: "default", profile_version: "1.0.0", extends: "default", rules: {} } }),
    /inheritance cycle/,
  );
});

test("QA report schema rejects undeclared nested check, metric, and violation fields", async () => {
  const report = await evaluateVisualQuality({ telemetry: telemetryFixture() });
  const badCheck = structuredClone(report);
  badCheck.checks.text_overflow.extra = true;
  assert.throws(() => assertJsonSchema(QA_REPORT_SCHEMA, badCheck), /not allowed/);
  const badMetric = structuredClone(report);
  badMetric.metrics.extra = {};
  assert.throws(() => assertJsonSchema(QA_REPORT_SCHEMA, badMetric), /not allowed/);

  const failingTelemetry = telemetryFixture();
  failingTelemetry.elements[1].text.overflow = true;
  const failing = await evaluateVisualQuality({ telemetry: failingTelemetry });
  const badViolation = structuredClone(failing);
  badViolation.violations[0].extra = true;
  assert.throws(() => assertJsonSchema(QA_REPORT_SCHEMA, badViolation), /not allowed/);
});

test("telemetry semantic validation rejects duplicate element ids and unexplained missing typed payloads", () => {
  const duplicate = telemetryFixture();
  duplicate.elements.push(structuredClone(duplicate.elements[1]));
  assert.throws(() => assertRenderTelemetry(duplicate), /Duplicate/);
  const missingText = telemetryFixture();
  missingText.elements[1].text = null;
  assert.throws(() => assertRenderTelemetry(missingText), /must be present or listed as unavailable/);
  missingText.unavailable.push({ field: "elements[1].text", reason: "renderer_did_not_expose_text_metrics" });
  assert.doesNotThrow(() => assertRenderTelemetry(missingText));
});
