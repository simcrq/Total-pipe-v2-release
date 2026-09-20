import assert from "node:assert/strict";
import fs from "node:fs/promises";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { runFigurePlacementGolden } from "../server/figure-placement-benchmark.mjs";
import { computeFigurePlacement, resolveFigureRegion, runFigurePlacement } from "../server/figure-placement.mjs";

const TEST_DIR = path.dirname(fileURLToPath(import.meta.url));
const DATASET_PATH = path.resolve(TEST_DIR, "..", "benchmarks", "figure-placement-golden.json");
const dataset = JSON.parse(await fs.readFile(DATASET_PATH, "utf8"));

test("P5/P7/P11 golden fixtures reproduce the recorded deck geometry", async () => {
  const result = await runFigurePlacementGolden();
  assert.equal(result.status, "passed");
  assert.equal(result.source_deck_sha256, "a2b10b2afc520025a587643fcc08f5720d2fe3b343ae48eed1e6c837d8998af7");
  assert.deepEqual(result.cases.map((item) => item.fixture_id), ["P5-renderer-override", "P7-semantic-region", "P11-aspect-ratio-letterbox"]);
  assert.equal(result.cases[0].metrics.letterbox_ratio, 0.661);
  assert.equal(result.cases[1].actual_codes.includes("IMAGE_FOCUS_LOST"), true);
  assert.equal(result.cases[2].recommended_action, "reconsider_visual_placement");
});

test("corrected P7 renderer facts preserve panel intent and pass the closed loop", () => {
  const fixture = structuredClone(dataset.fixtures.find((item) => item.fixture_id === "P7-semantic-region"));
  const baseline = runFigurePlacement(fixture.input);
  fixture.input.renderer_result = {
    effective_placement: baseline.stages.renderer_input.requested_placement,
    effective_source_region: baseline.stages.renderer_input.requested_source_region,
    render_bbox_px: { x: 106, y: 404, width: 1114, height: 327 },
    visible_region_ids: ["panel_d"],
    visible_label_ids: ["d"],
  };
  const corrected = runFigurePlacement(fixture.input);
  assert.equal(corrected.status, "pass");
  assert.equal(corrected.stages.region_resolution.selected_region.region_id, "panel_d");
  assert.equal(corrected.stages.renderer_effective.placement_modified, false);
  assert.ok(Object.values(corrected.stages.visual_qa.checks).every((item) => item.status === "pass"));
  assert.deepEqual(Object.keys(corrected.artifacts), [
    "model_intent.json", "planner_output.json", "placement_output.json", "renderer_input.json", "pptx_geometry.json", "canonical_telemetry.json", "qa_report.json",
  ]);
});

test("missing renderer telemetry cannot pass", () => {
  const input = structuredClone(dataset.fixtures[2].input);
  delete input.renderer_result;
  const output = runFigurePlacement(input);
  assert.notEqual(output.status, "pass");
  assert.equal(output.stages.visual_qa.checks.renderer_placement.status, "not_evaluable");
  assert.equal(output.stages.visual_qa.checks.telemetry_completeness.code, "TELEMETRY_INCOMPLETE");
  assert.ok(output.artifacts["canonical_telemetry.json"].unavailable.length >= 4);
});

test("source-pixel crop telemetry is normalized and semantic visibility remains mandatory", () => {
  const fixture = structuredClone(dataset.fixtures[1].input);
  const baseline = runFigurePlacement({ ...fixture, renderer_result: undefined });
  const requested = baseline.stages.renderer_input.requested_source_region;
  fixture.renderer_result = {
    effective_placement: baseline.stages.renderer_input.requested_placement,
    effective_source_region: {
      x: requested.x * fixture.visual.source_width_px,
      y: requested.y * fixture.visual.source_height_px,
      width: requested.width * fixture.visual.source_width_px,
      height: requested.height * fixture.visual.source_height_px,
    },
    source_region_coordinate_space: "source_pixels",
    render_bbox_px: { x: 100, y: 100, width: 800, height: 500 },
  };
  const incomplete = runFigurePlacement(fixture);
  assert.equal(incomplete.stages.renderer_input.source_region_coordinate_space, "source_normalized_0_1");
  assert.deepEqual(incomplete.stages.renderer_effective.effective_source_region, requested);
  assert.equal(incomplete.stages.visual_qa.checks.semantic_region.status, "not_evaluable");
  assert.ok(incomplete.artifacts["canonical_telemetry.json"].unavailable.some((item) => item.field === "metrics.panel_visibility"));
});

test("region resolver reports absent, ambiguous, and unresolved semantic intent", () => {
  assert.equal(resolveFigureRegion({ visual: {} }).status, "not_evaluable");
  const visual = {
    visual_intent: { selection: { strategy: "panel", target: "panel_d" } },
    region_candidates: [
      { region_id: "d", roi: { x: 0, y: 0, width: 0.5, height: 1 } },
      { region_id: "panel_d", roi: { x: 0.5, y: 0, width: 0.5, height: 1 } },
    ],
  };
  assert.equal(resolveFigureRegion({ visual }).status, "ambiguous");
  visual.region_candidates.pop();
  visual.visual_intent.selection.target = "panel_z";
  assert.equal(resolveFigureRegion({ visual }).code, "SEMANTIC_REGION_NOT_RESOLVED");
  visual.visual_intent.selection.strategy = "auto";
  assert.equal(resolveFigureRegion({ visual }).code, "REGION_RESOLUTION_NOT_EVALUABLE");

  const migrated = resolveFigureRegion({ visual: {
    visual_intent: { selection: { strategy: "panel", target: "panel_d" } },
    recommended_crop: { region_id: "panel_d", roi: { x: 0.4, y: 0.1, width: 0.5, height: 0.8 }, confidence: 0.9 },
  } });
  assert.equal(migrated.status, "resolved");
  assert.deepEqual(migrated.selected_region.roi, { x: 0.4, y: 0.1, width: 0.5, height: 0.8 });

  const candidate = resolveFigureRegion({ visual: {
    visual_intent: { selection: { strategy: "semantic_focus", target: "colour_region" } },
    crop_candidate: { region_id: "colour_region", x: 0.5, y: 0, width: 0.5, height: 1, coordinate_space: "normalized" },
  } });
  assert.equal(candidate.selected_region.region_id, "colour_region");
});

test("placement validates source geometry, padding, fit policy, and collisions", () => {
  const base = {
    visual: { source_width_px: 1000, source_height_px: 500, visual_intent: { placement: { preferred_fit: "contain" } } },
    source_region: { x: 0, y: 0, width: 1, height: 1 },
    allocated_visual_bbox: { x: 1, y: 1, width: 4, height: 4 },
  };
  const contained = computeFigurePlacement(base);
  assert.deepEqual(contained.final_placement, { x: 1, y: 2, width: 4, height: 2 });
  const collided = computeFigurePlacement({ ...base, exclusion_bboxes: [{ x: 2, y: 2, width: 1, height: 1 }] });
  assert.equal(collided.status, "failed");
  assert.deepEqual(collided.collisions, [0]);
  assert.throws(() => computeFigurePlacement({ ...base, policy: { padding: 2 } }), /leaves no usable visual area/);
  assert.throws(() => computeFigurePlacement({ ...base, visual: { ...base.visual, source_width_px: 0 } }), /must be positive/);
  assert.throws(() => computeFigurePlacement({ ...base, visual: { ...base.visual, visual_intent: { placement: { preferred_fit: "stretch" } } } }), /unsupported preferred_fit/);
  const portrait = computeFigurePlacement({ ...base, visual: { ...base.visual, source_width_px: 250, source_height_px: 1000 } });
  assert.deepEqual(portrait.final_placement, { x: 2.5, y: 1, width: 1, height: 4 });
  const covered = computeFigurePlacement({
    ...base,
    allocated_visual_bbox: { x: 0, y: 0, width: 2, height: 2 },
    visual: { ...base.visual, visual_intent: { placement: { preferred_fit: "cover", allow_cover: true } } },
    policy: { allow_crop: true },
  });
  assert.equal(covered.fit_mode, "cover");
  assert.equal(covered.source_region.width, 0.5);
  assert.throws(() => computeFigurePlacement({ ...base, source_region: { x: -0.1, y: 0, width: 1, height: 1 } }), /normalized source coordinates/);
  assert.throws(() => computeFigurePlacement({ ...base, allocated_visual_bbox: { x: 0, y: 0, width: 0, height: 1 } }), /positive width\/height/);
});

test("derived pixels, semantic incompleteness, and placement input failures remain explicit", () => {
  const panelFixture = structuredClone(dataset.fixtures[1].input);
  delete panelFixture.renderer_result.effective_source_region;
  delete panelFixture.renderer_result.render_bbox_px;
  const incomplete = runFigurePlacement(panelFixture);
  assert.equal(incomplete.stages.visual_qa.checks.semantic_region.status, "not_evaluable");
  assert.ok(incomplete.metrics.effective_image_resolution.width_px > 1000);

  const invalid = structuredClone(dataset.fixtures[2].input);
  invalid.allocated_visual_bbox.width = 0;
  const failed = runFigurePlacement(invalid);
  assert.equal(failed.stages.visual_qa.checks.placement_geometry.code, "PLACEMENT_INPUT_INVALID");
  assert.equal(failed.stages.region_resolution.status, "resolved");
});
