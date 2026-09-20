import assert from "node:assert/strict";
import test from "node:test";
import { assertJsonSchema } from "../server/schema-validator.mjs";
import { RENDER_TELEMETRY_SCHEMA } from "../server/visual-quality/contracts.mjs";
import { adaptRendererTelemetry } from "../server/renderer-adapters/index.mjs";
import { adaptSlidepTelemetry } from "../server/renderer-adapters/slidep.mjs";
import { adaptTencentPptxTelemetry } from "../server/renderer-adapters/tencent-pptx.mjs";
import { evaluateVisualQuality } from "../server/visual-quality/index.mjs";

function assertContract(value) {
  assertJsonSchema(RENDER_TELEMETRY_SCHEMA, value, { toolName: "renderer_telemetry" });
  assert.equal(value.telemetry_version, "1.3.0");
  return value;
}

const slidepInput = {
  renderer: "slidep",
  slideId: "slide-1",
  slide: {
    size: { w: 13.333, h: 7.5 },
    renderSize: { width: 1920, height: 1080 },
    background: { type: "solid", color: "#ffffff" },
    elements: [
      {
        elementId: "title",
        elementType: "text",
        qualityRole: "content",
        pptx_in: { x: 0.8, y: 0.4, w: 11.7, h: 0.7 },
        rendered: { bbox: { x: 115, y: 58, width: 1685, height: 101 } },
        textData: {
          content: "研究结论",
          language: "zh-CN",
          script: "CJK",
          fontFamily: "Microsoft YaHei",
          fontSize: 28,
          fontWeight: 600,
          lineCount: 1,
          isOverflow: false,
          foregroundColor: "#111111",
          intendedSingleLine: true,
          role: "title",
        },
      },
      {
        id: "figure",
        kind: "picture",
        quality_role: "content",
        bbox: { x: 1, y: 1.4, width: 5.5, height: 4.8 },
        image: {
          displayBox: { x: 1, y: 1.4, width: 5.5, height: 4.8 },
          sourceWidthPx: 2200,
          sourceHeightPx: 1800,
          visualId: "VIS-RESULT",
          contentId: "CONTENT-RESULT",
          slotId: "figure",
          visualType: "dense_plot",
          panelCount: 2,
          hasEmbeddedText: true,
          minDisplayWidth: 0.5,
          allocatedBox: { x: 1, y: 1.4, width: 5.5, height: 4.8 },
          renderedEmbeddedTextPx: 16,
        },
      },
      { id: "background", type: "rect", qualityRole: "background", bbox: { x: 0, y: 0, w: 13.333, h: 7.5 }, fillColor: "#ffffff" },
      { id: "rule", type: "line", role: "decorative", bbox: { x: 0.8, y: 1.1, w: 11.7, h: 0 } },
    ],
  },
  theme: {
    id: "paper-blue",
    tokens: {
      accent: { color: "#2463eb", allowed_usage: ["fill"], forbidden_usage: ["body_text"] },
    },
  },
};

function artifactCoverInput() {
  return {
    schema: "openai.presentation.layout/v4",
    slide: {
      aid: "sl/cover",
      layoutId: "RM-COVER-03",
      layoutType: "title",
      backgroundColor: "#061826",
      frame: { width: 1280, height: 720 },
    },
    elements: [
      { order: 1, kind: "image", aid: "im/figure", bbox: [51.17, 28.8, 1177.54, 662.4] },
      { order: 2, kind: "shape", aid: "sh/title-surface", name: "cover-title-surface", bbox: [84.43, 358.4, 829.54, 155.6], fillColor: "#061826" },
      {
        order: 3,
        kind: "shape",
        aid: "sh/title",
        name: "cover-title",
        bbox: [102.43, 374.4, 793.54, 129.6],
        text: "可打印元组装实现协同着色",
        resolvedFontSize: 62,
        resolvedTextStyle: { typeface: "Microsoft YaHei", color: "#F8FAFC", bold: true, wrap: "none" },
        textLayout: { lineCount: 1, overflow: false },
      },
      {
        order: 4,
        kind: "shape",
        aid: "sh/subtitle",
        name: "cover-subtitle",
        bbox: [102, 518, 640, 50],
        text: "从多尺度耦合到米级印品",
        resolvedFontSize: 28,
        resolvedTextStyle: { typeface: "Microsoft YaHei", color: "#22D3EE", wrap: "none" },
        textLayout: { lineCount: 1, overflow: false },
      },
      {
        order: 5,
        kind: "shape",
        aid: "sh/meta",
        name: "cover-meta",
        bbox: [102, 598, 538, 36],
        text: "Research update · 2026",
        resolvedFontSize: 18,
        resolvedTextStyle: { typeface: "Arial", color: "#E2E8F0", wrap: "none" },
        textLayout: { lineCount: 1, overflow: false },
      },
    ],
  };
}

function canonicalCoverTelemetry({ textBackgroundColor = null, independentOverlay = false } = {}) {
  const textZ = independentOverlay ? 3 : 2;
  const elements = [
    {
      element_id: "cover-image",
      type: "image",
      quality_role: "content",
      z_index: 1,
      opacity: 1,
      bbox: { x: 0, y: 0, width: 10, height: 5 },
      render_bbox_px: { x: 0, y: 0, width: 1000, height: 500 },
      text: null,
      image: {
        display_bbox: { x: 0, y: 0, width: 10, height: 5 },
        source_width_px: 1000,
        source_height_px: 500,
        visual_id: "cover-image",
        content_id: "cover-image-content",
        slot_id: "cover",
        visual_type: "photo",
        panel_count: 1,
        has_embedded_text: false,
        min_display_width: null,
        allocated_bbox: { x: 0, y: 0, width: 10, height: 5 },
        rendered_embedded_text_px: null,
      },
      fill_color: null,
      background_color: null,
      theme_token: null,
      theme_usage: null,
    },
  ];
  if (independentOverlay) {
    elements.push({
      element_id: "cover-surface",
      type: "shape",
      quality_role: "decoration",
      z_index: 2,
      opacity: 1,
      bbox: { x: 1, y: 1, width: 8, height: 2 },
      render_bbox_px: { x: 100, y: 100, width: 800, height: 200 },
      text: null,
      image: null,
      fill_color: "#000000",
      background_color: null,
      theme_token: null,
      theme_usage: null,
    });
  }
  elements.push({
    element_id: "cover-title",
    type: "text",
    quality_role: "content",
    z_index: textZ,
    opacity: 1,
    bbox: { x: 1, y: 1, width: 8, height: 2 },
    render_bbox_px: { x: 100, y: 100, width: 800, height: 200 },
    text: {
      content: "Title",
      language: "en",
      script: "Latin",
      font_family: "Arial",
      font_size: 40,
      font_weight: 700,
      line_count: 1,
      overflow: false,
      foreground_color: "#FFFFFF",
      local_contrast_ratio: null,
      intended_single_line: true,
      role: "title",
    },
    image: null,
    // This is the glyph paint exposed by several renderers, not a surface.
    fill_color: "#000000",
    background_color: textBackgroundColor,
    theme_token: null,
    theme_usage: null,
  });
  return {
    telemetry_version: "1.3.0",
    slide_id: "cover-text-surface",
    renderer: "slidep",
    slide: {
      width: 10,
      height: 5,
      render_width_px: 1000,
      render_height_px: 500,
      background: { kind: "solid", color: "#FFFFFF" },
      layout_id: "RM-COVER-03",
      category: "cover",
    },
    elements,
    theme: null,
    unavailable: [{ field: `elements[${elements.length - 1}].text.local_contrast_ratio`, reason: "renderer did not measure local contrast" }],
    provided_metrics: {},
  };
}

function artifactCoverWithText({ textBackgroundColor = null, independentOverlay = false } = {}) {
  const elements = [
    { aid: "cover-image", kind: "image", order: 1, bbox: [0, 0, 1000, 500], asset: { width: 1000, height: 500 } },
  ];
  if (independentOverlay) {
    elements.push({ aid: "cover-surface", kind: "shape", order: 2, bbox: [100, 100, 800, 200], fillColor: "#000000", opacity: 1 });
  }
  elements.push({
    aid: "cover-title",
    kind: "shape",
    order: independentOverlay ? 3 : 2,
    bbox: [100, 100, 800, 200],
    text: "Title",
    fillColor: "#000000",
    ...(textBackgroundColor ? { backgroundColor: textBackgroundColor } : {}),
    resolvedTextStyle: { typeface: "Arial", color: "#FFFFFF", fontSize: 40, bold: true, wrap: "none" },
    textLayout: { lineCount: 1, overflow: false },
  });
  return {
    schema: "openai.presentation.layout/v4",
    slide: { aid: "sl/cover-text-surface", layoutId: "RM-COVER-03", layoutType: "title", frame: { width: 1000, height: 500 }, backgroundColor: "#FFFFFF" },
    elements,
  };
}

test("slidep adapter maps text, image, background, decoration, and overflow facts", () => {
  const output = assertContract(adaptRendererTelemetry(slidepInput));
  assert.equal(output.renderer, "slidep");
  assert.deepEqual(output.slide, {
    width: 13.333,
    height: 7.5,
    render_width_px: 1920,
    render_height_px: 1080,
    background: { kind: "solid", color: "#ffffff" },
    layout_id: null,
    category: null,
  });
  assert.deepEqual(output.elements[0].text, {
    content: "研究结论",
    language: "zh-CN",
    script: "CJK",
    font_family: "Microsoft YaHei",
    font_size: 28,
    font_weight: 600,
    line_count: 1,
    overflow: false,
    foreground_color: "#111111",
    local_contrast_ratio: null,
    intended_single_line: true,
    role: "title",
  });
  assert.deepEqual(output.elements[1].image, {
    display_bbox: { x: 1, y: 1.4, width: 5.5, height: 4.8 },
    source_width_px: 2200,
    source_height_px: 1800,
    visual_id: "VIS-RESULT",
    content_id: "CONTENT-RESULT",
    slot_id: "figure",
    visual_type: "dense_plot",
    panel_count: 2,
    has_embedded_text: true,
    min_display_width: 0.5,
    allocated_bbox: { x: 1, y: 1.4, width: 5.5, height: 4.8 },
    rendered_embedded_text_px: 16,
  });
  assert.equal(output.elements[2].quality_role, "background");
  assert.equal(output.elements[3].quality_role, "decoration");
  assert.equal(output.elements[0].text.overflow, false);
  assert.deepEqual(output.theme.tokens.accent, { color: "#2463eb", allowed_usage: ["fill"], forbidden_usage: ["body_text"] });
});

test("tencent-pptx adapter accepts underscore renderer alias and preserves pixel units", () => {
  const input = {
    renderer: "tencent_pptx",
    page: {
      pageId: "page-2",
      pageSize: { width: 10, height: 5.625 },
      renderedSize: { width: 1600, height: 900 },
      backgroundColor: "#000000",
      shapes: [{
        shapeId: "text-1",
        shapeType: "textbox",
        shapeRole: "content",
        transform: { left: 0.5, top: 0.4, width: 5, height: 0.6 },
        rendered_bbox: { left: 80, top: 64, width: 800, height: 72 },
        textBody: { text: "Mixed language", font: { face: "Arial", pt: 24 }, renderedLines: 1, textOverflow: true },
      }],
    },
  };
  const output = assertContract(adaptRendererTelemetry(input));
  assert.deepEqual(adaptTencentPptxTelemetry(input), output);
  assert.equal(output.renderer, "tencent-pptx");
  assert.equal(output.slide.render_width_px, 1600);
  assert.equal(output.slide.render_height_px, 900);
  assert.deepEqual(output.elements[0].bbox, { x: 0.5, y: 0.4, width: 5, height: 0.6 });
  assert.deepEqual(output.elements[0].render_bbox_px, { x: 80, y: 64, width: 800, height: 72 });
  assert.equal(output.elements[0].text.font_family, "Arial");
  assert.equal(output.elements[0].text.font_size, 24);
  assert.equal(output.elements[0].text.overflow, true);
});

test("tencent-pptx does not misreport paragraph count as rendered line count", () => {
  const output = assertContract(adaptTencentPptxTelemetry({
    renderer: "tencent-pptx",
    page: {
      pageId: "paragraph-only",
      pageSize: { width: 10, height: 5.625 },
      shapes: [{
        shapeId: "text-1",
        shapeType: "textbox",
        transform: { left: 1, top: 1, width: 4, height: 1 },
        textBody: { text: "Two paragraphs", paragraphCount: 2 },
      }],
    },
  }));
  assert.equal(output.elements[0].text.line_count, null);
  assert.ok(output.unavailable.some((item) => item.field === "elements[0].text.line_count"));
});

test("missing render and text metrics stay nullable and are listed as unavailable", () => {
  const output = assertContract(adaptSlidepTelemetry({
    renderer: "slidep",
    slide_id: "missing-metrics",
    width: 13.333,
    height: 7.5,
    elements: [{ id: "body", type: "text", bbox: { x: 1, y: 1, width: 4, height: 2 }, text: { content: "正文" } }],
  }));
  assert.equal(output.slide.render_width_px, null);
  assert.equal(output.slide.render_height_px, null);
  assert.equal(output.elements[0].render_bbox_px, null);
  assert.equal(output.elements[0].text.font_size, null);
  assert.equal(output.elements[0].text.overflow, null);
  assert.ok(output.unavailable.some((item) => item.field === "slide.render_width_px"));
  assert.ok(output.unavailable.some((item) => item.field === "elements[0].text.font_size"));
  assert.ok(output.unavailable.some((item) => item.field === "elements[0].render_bbox_px"));
  assert.ok(output.unavailable.every((item) => !/too small|too empty|bad contrast/i.test(item.reason)));
});

test("unknown ordinary roles default to content while explicit special roles survive", () => {
  const output = assertContract(adaptRendererTelemetry({
    renderer: "slidep",
    slide_id: "roles",
    width: 10,
    height: 5,
    elements: [
      { id: "image", type: "image", bbox: { x: 1, y: 1, width: 2, height: 2 } },
      { id: "unknown", type: "future-widget", bbox: { x: 4, y: 1, width: 2, height: 2 } },
      { id: "background", type: "background", bbox: { x: 0, y: 0, width: 10, height: 5 } },
      { id: "ignored", type: "shape", qualityRole: "ignore", bbox: { x: 0, y: 0, width: 1, height: 1 } },
    ],
  }));
  assert.equal(output.elements[0].image.display_bbox, null);
  assert.equal(output.elements[1].type, "other");
  assert.equal(output.elements[1].quality_role, "content");
  assert.equal(output.elements[2].quality_role, "background");
  assert.equal(output.elements[3].quality_role, "ignore");
  assert.ok(output.unavailable.some((item) => item.field === "elements[0].image.display_bbox"));
});

test("unsupported renderers are rejected and output is deterministic", () => {
  assert.throws(() => adaptRendererTelemetry({ renderer: "unknown", slide_id: "x", width: 1, height: 1 }), /Unsupported renderer/);
  const first = adaptRendererTelemetry(slidepInput);
  const second = adaptRendererTelemetry(JSON.parse(JSON.stringify(slidepInput)));
  assert.deepEqual(second, first);
  assert.equal(JSON.stringify(second), JSON.stringify(first));
});

test("artifact-tool layout v4 is auto-adapted with image, z-order, and cover context", () => {
  const output = assertContract(adaptRendererTelemetry(artifactCoverInput()));
  assert.equal(output.renderer, "artifact-tool");
  assert.equal(output.slide.layout_id, "RM-COVER-03");
  assert.equal(output.slide.category, "cover");
  assert.equal(output.elements[0].type, "image");
  assert.equal(output.elements[0].z_index, 1);
  assert.deepEqual(output.elements[0].bbox, { x: 51.17, y: 28.8, width: 1177.54, height: 662.4 });
  assert.equal(output.elements[1].opacity, 1);
});

test("text glyph fill is not cover protection, while explicit text background and independent surface are", async () => {
  const fillOnly = assertContract(canonicalCoverTelemetry());
  const fillOnlyReport = await evaluateVisualQuality({ telemetry: fillOnly });
  assert.equal(fillOnlyReport.checks.cover_text_over_image.status, "not_evaluable");
  assert.deepEqual(fillOnlyReport.metrics.text_image_occlusion.intersections[0].overlays, []);

  const textBackground = assertContract(canonicalCoverTelemetry({ textBackgroundColor: "#000000" }));
  const textBackgroundReport = await evaluateVisualQuality({ telemetry: textBackground });
  assert.equal(textBackgroundReport.checks.cover_text_over_image.status, "pass");
  assert.deepEqual(textBackgroundReport.metrics.text_image_occlusion.intersections[0].overlays.map((item) => item.element_id), ["cover-title::background"]);

  const independentOverlay = assertContract(canonicalCoverTelemetry({ independentOverlay: true }));
  const independentOverlayReport = await evaluateVisualQuality({ telemetry: independentOverlay });
  assert.equal(independentOverlayReport.checks.cover_text_over_image.status, "pass");
  assert.deepEqual(independentOverlayReport.metrics.text_image_occlusion.intersections[0].overlays.map((item) => item.element_id), ["cover-surface"]);
});

test("artifact adapter keeps fill-only text unprotected and accepts explicit text background or overlay", async () => {
  const fillOnly = assertContract(adaptRendererTelemetry(artifactCoverWithText()));
  assert.equal(fillOnly.elements.find((element) => element.element_id === "cover-title").background_color, null);
  const fillOnlyReport = await evaluateVisualQuality({ telemetry: fillOnly });
  assert.equal(fillOnlyReport.checks.cover_text_over_image.status, "not_evaluable");

  const textBackground = assertContract(adaptRendererTelemetry(artifactCoverWithText({ textBackgroundColor: "#000000" })));
  assert.equal(textBackground.elements.find((element) => element.element_id === "cover-title").background_color, "#000000");
  const textBackgroundReport = await evaluateVisualQuality({ telemetry: textBackground });
  assert.equal(textBackgroundReport.checks.cover_text_over_image.status, "pass");

  const independentOverlay = assertContract(adaptRendererTelemetry(artifactCoverWithText({ independentOverlay: true })));
  const independentOverlayReport = await evaluateVisualQuality({ telemetry: independentOverlay });
  assert.equal(independentOverlayReport.checks.cover_text_over_image.status, "pass");
});

test("artifact adapter infers high-confidence visual parents and Visual QA detects orphan or duplicate rules", async () => {
  const input = {
    schema: "openai.presentation.layout/v4",
    slide: { aid: "sl/relations", frame: { width: 100, height: 100 }, backgroundColor: "#FFFFFF" },
    elements: [
      { aid: "title", kind: "shape", name: "title", bbox: [5, 5, 90, 10], text: "Relations", resolvedFontSize: 30, resolvedTextStyle: { color: "#111111" }, textLayout: { lineCount: 1, overflow: false } },
      { aid: "frame", kind: "shape", name: "rpa-visual-container-main", bbox: [5, 20, 90, 60] },
      { aid: "visual-a", kind: "image", bbox: [10, 25, 80, 50], visual_id: "VIS-A" },
      { aid: "title-rule", kind: "line", name: "title-rule", bbox: [5, 17, 90, 0] },
      { aid: "custom-line-a", kind: "line", name: "custom-line-a", bbox: [5, 60, 90, 0] },
      { aid: "custom-line-b", kind: "line", name: "custom-line-b", bbox: [5, 60.2, 90, 0] },
    ],
  };
  const telemetry = assertContract(adaptRendererTelemetry(input));
  assert.equal(telemetry.visual_containers.length, 1);
  assert.equal(telemetry.visual_containers[0].inference_source, "semantic_name_and_unambiguous_containment");
  assert.equal(telemetry.elements.find((element) => element.element_id === "visual-a").image.visual_parent_id, "frame");
  assert.equal(telemetry.elements.find((element) => element.element_id === "title-rule").relation.type, "title_rule");
  const report = await evaluateVisualQuality({ telemetry });
  assert.ok(report.violations.some((item) => item.code === "ORPHAN_DECORATIVE_ELEMENT"));
  assert.ok(report.violations.some((item) => item.code === "DUPLICATE_SEPARATOR"));
});

test("existing-deck baseline keeps four visual siblings and detects parent or geometry drift", async () => {
  const document = (moved = false) => ({
    schema: "openai.presentation.layout/v4",
    slide: { aid: moved ? "sl/current" : "sl/baseline", frame: { width: 100, height: 100 }, backgroundColor: "#FFFFFF" },
    elements: [
      { aid: "frame", kind: "shape", name: "rpa-visual-container-results", bbox: [5, 20, 90, 70] },
      ...[0, 1, 2, 3].map((index) => ({
        aid: `visual-${index + 1}`,
        visual_id: `VIS-${index + 1}`,
        kind: "image",
        bbox: index === 3 && moved ? [75, 92, 18, 18] : [8 + index * 22, 30, 18, 40],
      })),
    ],
  });
  const baseline = assertContract(adaptRendererTelemetry(document(false)));
  const current = assertContract(adaptRendererTelemetry(document(true)));
  const report = await evaluateVisualQuality({ telemetry: current, context: { baseline_telemetry: baseline } });
  assert.equal(report.checks.layout_relation_regression.status, "fail");
  assert.ok(report.violations.some((item) => item.code === "LAYOUT_RELATION_REGRESSION"));
  assert.ok(report.metrics.layout_regression.issues.some((item) => item.code === "SIBLING_GROUP_BROKEN"));

  const reordered = structuredClone(baseline);
  reordered.elements = [reordered.elements[0], ...reordered.elements.slice(1).reverse()];
  reordered.visual_containers[0].fit_policy = "cover";
  const relationReport = await evaluateVisualQuality({ telemetry: reordered, context: { baseline_telemetry: baseline } });
  assert.ok(relationReport.metrics.layout_regression.issues.some((item) => item.code === "READING_ORDER_CHANGED"));
  assert.ok(relationReport.metrics.layout_regression.issues.some((item) => item.code === "SHARED_CONTAINER_STYLE_CHANGED"));
});

test("RM-COVER-03 does not pass when subtitle and meta protection are unmeasured", async () => {
  const report = await evaluateVisualQuality({ telemetry: adaptRendererTelemetry(artifactCoverInput()) });
  assert.equal(report.checks.cover_text_over_image.status, "not_evaluable");
  assert.ok(report.violations.some((violation) => violation.code === "TEXT_IMAGE_PROTECTION_NOT_EVALUABLE"));
  assert.deepEqual(
    report.checks.cover_text_over_image.evidence.unresolved.map((item) => item.text_element_id),
    ["sh/subtitle", "sh/meta"],
  );
  assert.equal(report.checks.cover_text_over_image.evidence.protected_count, 1);
  assert.ok(report.metrics.text_image_occlusion.intersections.every((item) => item.overlap_ratio <= 1
    && item.overlays.every((overlay) => overlay.coverage_ratio <= 1)));
});

test("RM-COVER-03 fails known low local contrast and passes measured safe contrast", async () => {
  const unsafe = artifactCoverInput();
  unsafe.elements[3].localContrastRatio = 2;
  unsafe.elements[4].localContrastRatio = 2.5;
  const unsafeReport = await evaluateVisualQuality({ telemetry: adaptRendererTelemetry(unsafe) });
  assert.equal(unsafeReport.checks.cover_text_over_image.status, "fail");
  assert.ok(unsafeReport.violations.some((violation) => violation.code === "UNPROTECTED_TEXT_OVER_IMAGE"));

  const safe = artifactCoverInput();
  safe.elements[3].localContrastRatio = 7;
  safe.elements[4].localContrastRatio = 6;
  const safeReport = await evaluateVisualQuality({ telemetry: adaptRendererTelemetry(safe) });
  assert.equal(safeReport.checks.cover_text_over_image.status, "pass");
});
