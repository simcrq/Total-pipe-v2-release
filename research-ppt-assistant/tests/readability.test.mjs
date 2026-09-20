import assert from "node:assert/strict";
import test from "node:test";
import {
  activeSlotsForMetrics,
  analyzeVisualPlacements,
  computeSlotGeometry,
  enrichLayoutReadability,
  enrichSlotReadability,
  estimateSlotTextCapacity,
  getViewingProfile,
  layoutReadability,
  occupancyFit,
  requiredVisualWidth,
  typographyFit,
  visualComplexityFit,
} from "../server/readability.mjs";
import { evaluateLayoutCompatibility, scoreLayout, topKLayouts } from "../server/layout-retriever.mjs";

const slots = [
  { id: "title", type: "title", priority: 100, pptx_in: { x: 0.6, y: 0.3, w: 12, h: 0.7 } },
  { id: "body", type: "text", priority: 80, box: { x: 0.05, y: 0.2, w: 0.35, h: 0.55 } },
  { id: "optional", type: "caption", optional: true, priority: 20, box: { x: 0.05, y: 0.78, w: 0.35, h: 0.08 } },
  { id: "figure1", type: "figure", priority: 90, box: { x: 0.44, y: 0.2, w: 0.5, h: 0.5 } },
  { id: "figure2", type: "figure", priority: 50, box: { x: 0.70, y: 0.72, w: 0.24, h: 0.2 } },
  { id: "chart", type: "chart", priority: 70, box: { x: 0.44, y: 0.72, w: 0.24, h: 0.2 } },
  { id: "table", type: "table", priority: 60, box: { x: 0.44, y: 0.72, w: 0.5, h: 0.2 } },
  { id: "step", type: "process", priority: 60, box: { x: 0.05, y: 0.88, w: 0.3, h: 0.08 } },
];

function layout(overrides = {}) {
  return {
    id: "TEST-01",
    category: "single_figure",
    density: "中",
    max_text_chars: 180,
    preferred_visual_aspect_ratio: 1.6,
    content_roles: ["headline", "primary_visual"],
    content_profile: { image_capacity: 2, table_capacity: 1, chart_capacity: 1, media_area_capacity: 0.55 },
    slots,
    ...overrides,
  };
}

test("readability utilities cover viewing, typography, geometry, and active-slot branches", () => {
  assert.equal(getViewingProfile("DESKTOP").id, "desktop");
  assert.equal(getViewingProfile("").id, "projector");
  assert.equal(getViewingProfile("unknown").id, "projector");
  assert.equal(estimateSlotTextCapacity({}, 18), 0);
  assert.equal(estimateSlotTextCapacity(slots[1], 0), 0);
  assert.ok(estimateSlotTextCapacity(slots[0], 35, 1) > 0);
  assert.ok(estimateSlotTextCapacity(slots[2], 16) > 0);
  assert.deepEqual(enrichSlotReadability(slots[3], "single_figure"), slots[3]);
  assert.deepEqual(enrichSlotReadability(null, "summary"), {});

  const enriched = [
    enrichSlotReadability(slots[0], "cover", "handout"),
    enrichSlotReadability({ ...slots[1], type: "subtitle" }, "summary"),
    enrichSlotReadability({ ...slots[1], type: "callout" }, "summary"),
    enrichSlotReadability({ ...slots[1], type: "question" }, "summary"),
    enrichSlotReadability(slots[2], "summary"),
    enrichSlotReadability({ ...slots[1], type: "meta" }, "summary"),
    enrichSlotReadability(slots[7], "workflow"),
    enrichSlotReadability({ ...slots[7], type: "timeline" }, "timeline"),
  ];
  assert.ok(enriched.every((slot) => slot.min_font_pt >= 16));

  assert.equal(computeSlotGeometry([]).largest_horizontal_empty_band, 1);
  const geometry = computeSlotGeometry([
    { box: { x: -0.1, y: 0.1, w: 0.7, h: 0.3 } },
    { box: { x: 0.4, y: 0.2, w: 0.7, h: 0.3 } },
    { pptx_in: { x: 1, y: 5, w: 3, h: 1 } },
    {},
  ], 0.5);
  assert.ok(geometry.element_area_ratio > 0);
  assert.ok(geometry.footprint <= 1);

  const active = activeSlotsForMetrics(layout(), { textChars: 150, imageCount: 2, chartCount: 1, tableCount: 1 });
  assert.ok(active.some((slot) => slot.id === "optional"));
  assert.ok(active.some((slot) => slot.id === "figure2"));
  assert.ok(active.some((slot) => slot.id === "chart"));
  assert.ok(active.some((slot) => slot.id === "table"));
  assert.ok(activeSlotsForMetrics(layout({ category: "cover" }), {}).some((slot) => slot.id === "body"));
});

test("readability scoring covers visual, occupancy, and fit boundaries", () => {
  const base = layoutReadability(layout(), { textChars: 80, imageCount: 1 });
  assert.equal(base.profile.id, "projector");
  assert.ok(base.title_capacity_chars > 0);
  const cover = enrichLayoutReadability(layout({ category: "cover", constraints: { default_body_font_pt: 30, minimum_body_font_pt: 20 } }), "desktop");
  assert.equal(cover.constraints.default_title_font_pt, 50);
  assert.equal(cover.constraints.default_body_font_pt, 30);

  assert.ok(typographyFit(layout(), { titleChars: 10, textChars: 50, slotMetrics: [{ slotId: "body", textChars: 10 }, { slotId: "missing", textChars: 999 }] }) > 0);
  assert.equal(requiredVisualWidth({ minDisplayWidth: 2 }), 1);
  assert.ok(Math.abs(requiredVisualWidth({ visualType: "multi_panel_figure", panelCount: 6 }) - 0.62) < 1e-9);
  assert.ok(Math.abs(requiredVisualWidth({ visualType: "multi_panel_figure", panelCount: 4 }) - 0.58) < 1e-9);
  assert.equal(requiredVisualWidth({ visualType: "unknown", hasEmbeddedText: true }), 0.44);

  const placements = analyzeVisualPlacements(layout(), { visuals: [
    { slotId: "figure2", visualType: "dense_plot", panelCount: 6, hasEmbeddedText: true },
    { visualType: "photo" },
    { slotId: "missing", visualType: "simple_plot" },
  ] });
  assert.equal(placements[0].slot_id, "figure2");
  assert.equal(placements[2].display_width, 0);
  assert.equal(visualComplexityFit(layout(), {}), 0.85);
  assert.ok(visualComplexityFit(layout(), { visuals: placements.map((item) => ({ visualType: item.visual_type, panelCount: item.panel_count })) }) < 1);
  assert.ok(occupancyFit(layout(), { textChars: 20 }) >= 0);
  assert.ok(occupancyFit(layout({ category: "qa", slots: [slots[0]] }), {}) >= 0);
});

test("layout retrieval scores silhouettes and hard compatibility without admitting invalid layouts", () => {
  const scenarios = [
    { textChars: 0, titleChars: 0, imageCount: 0, tableCount: 0, chartCount: 0, processStepCount: 0 },
    { textChars: 30, titleChars: 10, imageCount: 1, tableCount: 0, chartCount: 0, processStepCount: 0, visualAspectRatio: 0, densityPreference: "低" },
    { textChars: 120, titleChars: 10, imageCount: 2, tableCount: 0, chartCount: 0, processStepCount: 1, contentRoles: ["headline", "unknown"] },
    { textChars: 170, titleChars: 10, imageCount: 3, tableCount: 0, chartCount: 0, processStepCount: 0 },
    { textChars: 300, titleChars: 200, imageCount: 4, tableCount: 2, chartCount: 3, processStepCount: 4, visuals: [{ visualType: "dense_plot" }, { visualType: "dense_plot" }] },
    { textChars: 80, titleChars: 10, imageCount: 0, tableCount: 1, chartCount: 0, processStepCount: 0 },
    { textChars: 80, titleChars: 10, imageCount: 0, tableCount: 1, chartCount: 1, processStepCount: 0 },
    { textChars: 80, titleChars: 10, imageCount: 0, tableCount: 0, chartCount: 1, processStepCount: 0 },
  ];
  for (const input of scenarios) assert.equal(typeof scoreLayout(layout(), input).score, "number");

  const invalid = evaluateLayoutCompatibility(layout({
    max_text_chars: 10,
    slots: [{ id: "body", type: "text", box: { x: 0, y: 0, w: 0.2, h: 0.2 } }],
    content_profile: {},
  }), { text_chars: 20, title_chars: 5, image_count: 1, table_count: 1, chart_count: 1, process_step_count: 1 });
  assert.equal(invalid.compatible, false);
  assert.deepEqual(new Set(invalid.violations.map((item) => item.code)), new Set([
    "TEXT_CAPACITY_EXCEEDED", "MISSING_REQUIRED_TITLE", "FIGURE_CAPACITY_EXCEEDED", "TABLE_CAPACITY_EXCEEDED", "CHART_CAPACITY_EXCEEDED", "PROCESS_CAPACITY_EXCEEDED",
  ]));

  const alternateTitle = evaluateLayoutCompatibility(layout({ slots: [{ slot_id: "title", slot_type: "text", box: { x: 0, y: 0, w: 1, h: 0.2 } }] }), {});
  assert.equal(alternateTitle.compatible, true);
  const ranked = topKLayouts([layout({ id: "B" }), layout({ id: "A" })], { ...scenarios[0], k: 1 });
  assert.deepEqual(ranked.map((item) => item.id), ["A"]);
});
