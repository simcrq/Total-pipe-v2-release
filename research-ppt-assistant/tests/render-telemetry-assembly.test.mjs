import assert from "node:assert/strict";
import test from "node:test";
import { ARTIFACT_TOOL_GEOMETRY_PROFILE, computeArtifactDisplayGeometry } from "../server/renderer-adapters/artifact-tool-geometry.mjs";
import { assembleRenderTelemetry } from "../server/render-telemetry-assembly.mjs";
import { evaluateVisualQuality } from "../server/visual-quality/index.mjs";

const HASH_A = "a".repeat(64);
const HASH_B = "b".repeat(64);
const HASH_PARENT = "c".repeat(64);

function manifestHeader(deckId = "meta-assembly-regression") {
  return { manifest_schema_version: "0.4.7", producer_version: "deck-builder@0.4.7-test", deck_id: deckId };
}

function artifactSlide({ duplicateAlt = false, hashMismatch = false, geometryMismatch = false, orphan = false } = {}) {
  return {
    schema: "openai.presentation.layout/v4",
    slide: {
      aid: "SLIDE0011",
      layoutId: "RM-DUAL_FIGURE-07",
      layoutType: "evidence",
      frame: { width: 1280, height: 720 },
      backgroundColor: "#FFFFFF",
    },
    elements: [
      { aid: "top-bar", kind: "shape", name: "global-top-bar", bbox: [0, 0, 1280, 8], fillColor: "#047857", order: 0 },
      { aid: "container-top", kind: "shape", name: "s11-ed5-top-panel", bbox: [80, 100, 1120, 224], order: 1 },
      {
        aid: "ed5-top",
        kind: "image",
        alt: "rpa:ed5-a-c | Extended Data Fig. 5 · a–c",
        bbox: [80, 100, 1120, 224],
        displayBbox: geometryMismatch ? [80, 100, 900, 224] : undefined,
        imageFit: "contain",
        assetSha256: hashMismatch ? HASH_B : HASH_A,
        order: 2,
      },
      { aid: "container-bottom", kind: "shape", name: "s11-ed5-bottom-panel", bbox: [80, 380, 1120, 224], order: 3 },
      {
        aid: "ed5-bottom",
        kind: "image",
        alt: duplicateAlt ? "rpa:ed5-a-c | duplicate" : "rpa:ed5-g-i | Extended Data Fig. 5 · g–i",
        bbox: [80, 380, 1120, 224],
        imageFit: "contain",
        assetSha256: HASH_B,
        order: 4,
      },
      ...(orphan ? [{ aid: "orphan-line", kind: "line", name: "custom-line", bbox: [120, 500, 500, 0], order: 5 }] : []),
    ],
  };
}

function visualEntry({ key, regionId, y, hash, measured = true } = {}) {
  return {
    visual_key: key,
    slide_id: "SLIDE0011",
    source_visual_id: "ed5",
    region_id: regionId,
    visual_type: "composite_figure_region",
    panel_count: 3,
    has_embedded_text: true,
    source_width_px: 1500,
    source_height_px: 300,
    parent_source_width_px: 1500,
    parent_source_height_px: 1500,
    parent_source_region: { x: 0, y, width: 1, height: 0.2 },
    parent_coordinate_space: "source_normalized_0_1",
    slot_id: key === "ed5-a-c" ? "case1" : "case2",
    container_id: key === "ed5-a-c" ? "s11-top" : "s11-bottom",
    parent_asset_sha256: HASH_PARENT,
    derived_asset_sha256: hash,
    crop_mode: "preprocessed_fixed_region",
    group_id: "s11-ed5",
    sibling_index: key === "ed5-a-c" ? 0 : 1,
    ...(measured ? { rendered_embedded_text_px: 16 } : {}),
  };
}

function manifest({ measured = true } = {}) {
  return {
    ...manifestHeader(),
    visuals: [
      visualEntry({ key: "ed5-a-c", regionId: "a-c", y: 0, hash: HASH_A, measured }),
      visualEntry({ key: "ed5-g-i", regionId: "g-i", y: 0.6, hash: HASH_B, measured }),
    ],
    visual_groups: [{
      group_id: "s11-ed5", relation_type: "composite_split", expected_sibling_count: 2,
      reading_order: ["ed5-a-c", "ed5-g-i"], shared_baseline: "none", baseline_tolerance: 0,
      require_unique_containers: true, require_unique_assets: true, shared_parent_asset_sha256: HASH_PARENT,
    }],
    containers: [
      {
        container_id: "s11-top", shape_name: "s11-ed5-top-panel", role: "comparison_region",
        fit_policy: "contain", crop_policy: "fixed_region", whitespace_policy: "minimal", mismatch_policy: "replan",
      },
      {
        container_id: "s11-bottom", shape_name: "s11-ed5-bottom-panel", role: "comparison_region",
        fit_policy: "contain", crop_policy: "fixed_region", whitespace_policy: "minimal", mismatch_policy: "replan",
      },
    ],
    element_annotations: [{ shape_name: "global-top-bar", quality_role: "background" }],
  };
}

test("artifact-tool geometry profile has verified contain and cover conformance", () => {
  assert.equal(ARTIFACT_TOOL_GEOMETRY_PROFILE.conformance_verified, true);
  assert.deepEqual(computeArtifactDisplayGeometry({
    frame_bbox: { x: 0, y: 0, width: 200, height: 200 },
    asset_width_px: 400,
    asset_height_px: 200,
    image_fit: "contain",
  }), {
    display_bbox: { x: 0, y: 50, width: 200, height: 100 },
    effective_placement: { x: 0, y: 50, width: 200, height: 100 },
    actual_letterbox_ratio: 0.5,
    profile_effective_source_region: { x: 0, y: 0, width: 1, height: 1 },
    source_visibility_ratio: 1,
    fit_mode: "contain",
  });
});

test("sidecar assembly binds two semantic regions by alt key and produces ready scientific telemetry", async () => {
  const output = assembleRenderTelemetry({ renderer_output: artifactSlide(), visual_manifest: manifest(), renderer_profile: "artifact-tool" });
  assert.equal(output.readiness_status, "ready");
  assert.equal(output.status, "pass");
  assert.deepEqual(output.geometry_provenance, ["profile_derived"]);
  assert.equal(output.missing_facts.length, 0);
  assert.equal(output.match_log.filter((item) => item.kind === "scientific_visual").length, 2);
  assert.equal(output.canonical_telemetry.visual_containers.length, 2);
  assert.equal(output.canonical_telemetry.visual_groups[0].actual_sibling_count, 2);
  assert.equal(output.canonical_telemetry.render_evidence.status, "pass");
  const images = output.canonical_telemetry.elements.filter((element) => element.type === "image");
  assert.deepEqual(images.map((element) => element.image.visual_id), ["ed5-a-c", "ed5-g-i"]);
  assert.deepEqual(images.map((element) => element.image.content_id), ["ed5", "ed5"]);
  assert.deepEqual(images.map((element) => element.image.visible_region_ids), [["a-c"], ["g-i"]]);
  assert.ok(images.every((element) => element.image.actual_letterbox_ratio === 0));
  assert.equal(output.canonical_telemetry.elements[0].quality_role, "background");

  const report = await evaluateVisualQuality({ telemetry: output.canonical_telemetry });
  assert.equal(report.checks.scientific_visual_readability.status, "pass");
  assert.equal(report.checks.visual_container_child_fit.status, "pass");
});

test("Slide 5 square and wide figures retain their material aspect ratios and pass visual QA", async () => {
  const rendererOutput = {
    schema: "openai.presentation.layout/v4",
    slide: { aid: "SLIDE0005", layoutId: "RM-DUAL_FIGURE-07", layoutType: "evidence", frame: { width: 1280, height: 720 }, backgroundColor: "#FFFFFF" },
    elements: [
      { aid: "square-frame", kind: "shape", name: "s5-square-frame", bbox: [40, 140, 480, 480], order: 1 },
      { aid: "fig-2a", kind: "image", alt: "rpa:fig2-a | Fig. 2a", bbox: [40, 140, 480, 480], imageFit: "contain", assetSha256: HASH_A, order: 2 },
      { aid: "wide-frame", kind: "shape", name: "s5-wide-frame", bbox: [600, 220, 640, 256], order: 3 },
      { aid: "fig-2b", kind: "image", alt: "rpa:fig2-b | Fig. 2b", bbox: [600, 220, 640, 256], imageFit: "contain", assetSha256: HASH_B, order: 4 },
    ],
  };
  const visualManifest = {
    ...manifestHeader("slide-5-regression"),
    visuals: [
      {
        visual_key: "fig2-a", slide_id: "SLIDE0005", source_visual_id: "fig2-a", visual_type: "simple_plot", panel_count: 1,
        has_embedded_text: false, source_width_px: 1000, source_height_px: 1000,
        source_region: { x: 0, y: 0, width: 1, height: 1 }, coordinate_space: "source_normalized_0_1",
        slot_id: "figure_left", container_id: "s5-square", asset_sha256: HASH_A, crop_mode: "full_figure",
      },
      {
        visual_key: "fig2-b", slide_id: "SLIDE0005", source_visual_id: "fig2-b", visual_type: "simple_plot", panel_count: 1,
        has_embedded_text: false, source_width_px: 1000, source_height_px: 400,
        source_region: { x: 0, y: 0, width: 1, height: 1 }, coordinate_space: "source_normalized_0_1",
        slot_id: "figure_right", container_id: "s5-wide", asset_sha256: HASH_B, crop_mode: "full_figure",
      },
    ],
    containers: [
      { container_id: "s5-square", shape_name: "s5-square-frame", role: "comparison_region", fit_policy: "contain", crop_policy: "full_figure", whitespace_policy: "minimal", mismatch_policy: "replan" },
      { container_id: "s5-wide", shape_name: "s5-wide-frame", role: "comparison_region", fit_policy: "contain", crop_policy: "full_figure", whitespace_policy: "minimal", mismatch_policy: "replan" },
    ],
  };
  const output = assembleRenderTelemetry({ renderer_output: rendererOutput, visual_manifest: visualManifest });
  assert.equal(output.readiness_status, "ready");
  assert.equal(output.status, "pass");
  const images = output.canonical_telemetry.elements.filter((element) => element.type === "image");
  assert.equal(images[0].image.display_bbox.width / images[0].image.display_bbox.height, 1);
  assert.equal(images[1].image.display_bbox.width / images[1].image.display_bbox.height, 2.5);
  const report = await evaluateVisualQuality({ telemetry: output.canonical_telemetry });
  assert.equal(report.checks.scientific_visual_readability.status, "pass");
  assert.equal(report.checks.visual_container_child_fit.status, "pass");
});

test("Slide 10 fixed-region telemetry preserves the declared ROI only when the preprocessed asset hash matches", async () => {
  const rendererOutput = {
    schema: "openai.presentation.layout/v4",
    slide: { aid: "SLIDE0010", layoutId: "RM-SINGLE_FIGURE-01", layoutType: "evidence", frame: { width: 1280, height: 720 }, backgroundColor: "#FFFFFF" },
    elements: [
      { aid: "fig4-frame", kind: "shape", name: "s10-fig4-panel", bbox: [80, 160, 1120, 280], order: 1 },
      { aid: "fig4", kind: "image", alt: "rpa:fig4-a-d | Fig. 4a–d", bbox: [80, 160, 1120, 280], imageFit: "contain", assetSha256: HASH_A, order: 2 },
    ],
  };
  const visualManifest = {
    ...manifestHeader("slide-10-regression"),
    visuals: [{
      visual_key: "fig4-a-d", slide_id: "SLIDE0010", source_visual_id: "fig4", region_id: "a-d",
      visual_type: "composite_figure_region", panel_count: 4, has_embedded_text: true,
      source_width_px: 1600, source_height_px: 400,
      parent_source_width_px: 1600, parent_source_height_px: 1600,
      parent_source_region: { x: 0, y: 0, width: 1, height: 0.25 }, parent_coordinate_space: "source_normalized_0_1",
      slot_id: "figure", container_id: "s10-fig4", parent_asset_sha256: HASH_PARENT,
      derived_asset_sha256: HASH_A, crop_mode: "preprocessed_fixed_region", rendered_embedded_text_px: 16,
    }],
    containers: [{
      container_id: "s10-fig4", shape_name: "s10-fig4-panel", role: "comparison_region",
      fit_policy: "contain", crop_policy: "fixed_region", whitespace_policy: "minimal", mismatch_policy: "replan",
    }],
  };
  const ready = assembleRenderTelemetry({ renderer_output: rendererOutput, visual_manifest: visualManifest });
  assert.equal(ready.readiness_status, "ready");
  assert.equal(ready.status, "pass");
  assert.deepEqual(ready.canonical_telemetry.elements[1].image.effective_source_region, { x: 0, y: 0, width: 1, height: 1 });
  assert.deepEqual(ready.canonical_telemetry.elements[1].image.parent_source_region, { x: 0, y: 0, width: 1, height: 0.25 });
  rendererOutput.elements[1].assetSha256 = HASH_B;
  const mismatch = assembleRenderTelemetry({ renderer_output: rendererOutput, visual_manifest: visualManifest });
  assert.equal(mismatch.readiness_status, "ready");
  assert.equal(mismatch.status, "fail");
  assert.ok(mismatch.failures.some((item) => item.code === "SEMANTIC_CROP_ASSET_MISMATCH"));
  const qa = await evaluateVisualQuality({ telemetry: mismatch.canonical_telemetry });
  assert.equal(qa.checks.render_evidence_closure.status, "fail");
  assert.ok(qa.violations.some((item) => item.code === "SEMANTIC_CROP_ASSET_MISMATCH"));
});

test("readiness blocks missing manifest, ambiguous alt keys, asset replacement, and profile geometry mismatch", () => {
  const noManifest = assembleRenderTelemetry({ renderer_output: artifactSlide() });
  assert.equal(noManifest.readiness_status, "blocked");
  assert.ok(noManifest.missing_facts.some((item) => item.field === "visual_manifest"));

  const duplicate = assembleRenderTelemetry({ renderer_output: artifactSlide({ duplicateAlt: true }), visual_manifest: manifest() });
  assert.equal(duplicate.readiness_status, "blocked");
  assert.ok(duplicate.missing_facts.some((item) => /duplicate renderer visual_key/u.test(item.reason)));

  const hashMismatch = assembleRenderTelemetry({ renderer_output: artifactSlide({ hashMismatch: true }), visual_manifest: manifest() });
  assert.equal(hashMismatch.readiness_status, "ready");
  assert.equal(hashMismatch.status, "fail");
  assert.ok(hashMismatch.failures.some((item) => item.code === "SEMANTIC_CROP_ASSET_MISMATCH"));

  const geometryMismatch = assembleRenderTelemetry({ renderer_output: artifactSlide({ geometryMismatch: true }), visual_manifest: manifest() });
  assert.equal(geometryMismatch.readiness_status, "ready");
  assert.equal(geometryMismatch.status, "fail");
  assert.ok(geometryMismatch.failures.some((item) => item.code === "DISPLAY_GEOMETRY_MISMATCH"));
});

test("unmeasured raster text requests manual review without blocking geometry readiness", async () => {
  const sidecar = manifest({ measured: false });
  const output = assembleRenderTelemetry({ renderer_output: artifactSlide(), visual_manifest: sidecar });
  assert.equal(output.readiness_status, "manual_review_required");
  assert.equal(output.status, "manual_review_required");
  assert.equal(output.missing_facts.length, 0);
  assert.equal(output.manual_review.length, 2);
  const report = await evaluateVisualQuality({ telemetry: output.canonical_telemetry });
  assert.equal(report.checks.scientific_visual_readability.status, "not_evaluable");
  assert.equal(report.checks.scientific_visual_readability.blocking, false);
});

test("a failed raster-text measurement remains QA-blocking without masquerading as optional manual review", async () => {
  const sidecar = manifest({ measured: false });
  for (const visual of sidecar.visuals) visual.raster_text_measurement = { status: "failed", reason: "inspection service error" };
  const output = assembleRenderTelemetry({ renderer_output: artifactSlide(), visual_manifest: sidecar });
  assert.equal(output.readiness_status, "manual_review_required");
  assert.equal(output.status, "manual_review_required");
  assert.equal(output.manual_review.length, 2);
  assert.ok(output.manual_review.every((item) => item.measurement_state === "measurement_failed"));
  const report = await evaluateVisualQuality({ telemetry: output.canonical_telemetry });
  assert.equal(report.checks.scientific_visual_readability.status, "not_evaluable");
  assert.equal(report.checks.scientific_visual_readability.blocking, true);
  assert.equal(report.status, "warning");
});

test("background top bars are excluded from orphan checks while an unbound content-area line is reported", async () => {
  const output = assembleRenderTelemetry({ renderer_output: artifactSlide({ orphan: true }), visual_manifest: manifest() });
  const report = await evaluateVisualQuality({ telemetry: output.canonical_telemetry });
  const relationCodes = report.metrics.element_relations.issues.map((item) => item.code);
  assert.equal(output.canonical_telemetry.elements.find((element) => element.element_id === "top-bar").quality_role, "background");
  assert.ok(relationCodes.includes("ORPHAN_DECORATIVE_ELEMENT"));
  assert.equal(report.metrics.element_relations.candidates.some((item) => item.element_id === "top-bar"), false);
});

test("Slide 2 with an explicit empty production manifest is not falsely blocked", () => {
  const output = assembleRenderTelemetry({
    renderer_output: {
      schema: "openai.presentation.layout/v4",
      slide: { aid: "SLIDE0002", layoutId: "RM-TEXT-01", layoutType: "context", frame: { width: 1280, height: 720 }, backgroundColor: "#FFFFFF" },
      elements: [{ aid: "body", kind: "shape", name: "body-panel", bbox: [80, 120, 1120, 500], order: 1 }],
    },
    visual_manifest: { ...manifestHeader("slide-2-regression"), visuals: [], containers: [] },
  });
  assert.equal(output.status, "pass");
  assert.equal(output.readiness_status, "ready");
  assert.deepEqual(output.inspection, []);
});

test("Slide 4 unexpected contain letterboxing fails while explicitly intentional whitespace passes", () => {
  const rendererOutput = {
    schema: "openai.presentation.layout/v4",
    slide: { aid: "SLIDE0004", layoutId: "RM-SINGLE_FIGURE-05", layoutType: "evidence", frame: { width: 1280, height: 720 }, backgroundColor: "#FFFFFF" },
    elements: [
      { aid: "frame", kind: "shape", name: "s4-figure-panel", bbox: [80, 160, 1120, 280], order: 1 },
      { aid: "ed1", kind: "image", visualKey: "extended-data-fig-1", bbox: [80, 160, 1120, 280], imageFit: "contain", assetId: "asset-ed1", order: 2 },
    ],
  };
  const visualManifest = {
    ...manifestHeader("slide-4-regression"),
    visuals: [{
      visual_key: "extended-data-fig-1", slide_id: "SLIDE0004", source_visual_id: "extended-data-fig-1",
      visual_type: "multi_panel_figure", panel_count: 4, has_embedded_text: false,
      source_width_px: 1200, source_height_px: 1000, source_region: { x: 0, y: 0, width: 1, height: 1 },
      coordinate_space: "source_normalized_0_1", slot_id: "figure", container_id: "s4-figure", asset_sha256: HASH_A, crop_mode: "full_figure",
    }],
    containers: [{
      container_id: "s4-figure", shape_name: "s4-figure-panel", role: "image_only", fit_policy: "contain",
      crop_policy: "full_figure", whitespace_policy: "minimal", mismatch_policy: "replan", max_letterbox_ratio: 0.35,
    }],
  };
  const failed = assembleRenderTelemetry({ renderer_output: rendererOutput, visual_manifest: visualManifest, asset_registry: { "asset-ed1": HASH_A } });
  assert.equal(failed.status, "fail");
  assert.ok(failed.failures.some((item) => item.code === "UNEXPECTED_LETTERBOXING"));
  assert.equal(failed.inspection[0].geometry_provenance, "profile_derived");

  visualManifest.containers[0].whitespace_policy = "intentional";
  const intentional = assembleRenderTelemetry({ renderer_output: rendererOutput, visual_manifest: visualManifest, asset_registry: { "asset-ed1": HASH_A } });
  assert.equal(intentional.status, "pass");
});

test("Slides 3 and 6 support nested production manifest records and assetId registry binding", () => {
  for (const slideNumber of [3, 6]) {
    const slideId = `SLIDE${String(slideNumber).padStart(4, "0")}`;
    const visualKey = `evidence-figure-${slideNumber}`;
    const assetId = `asset-${slideNumber}`;
    const rendererOutput = {
      schema: "openai.presentation.layout/v4",
      slide: { aid: slideId, layoutId: "RM-SINGLE_FIGURE-01", layoutType: "evidence", frame: { width: 1280, height: 720 }, backgroundColor: "#FFFFFF" },
      elements: [
        { aid: `frame-${slideNumber}`, kind: "shape", name: `figure-panel-${slideNumber}`, bbox: [240, 120, 800, 400], order: 1 },
        { aid: `visual-${slideNumber}`, kind: "image", visual_key: visualKey, bbox: [240, 120, 800, 400], imageFit: "contain", assetId, order: 2 },
      ],
    };
    const visualManifest = {
      ...manifestHeader(`slide-${slideNumber}-regression`),
      visuals: [{
        visual_key: visualKey,
        semantic: { slide_id: slideId, description: `Slide ${slideNumber} evidence`, slot_id: "figure", container_id: `container-${slideNumber}`, group_id: null, sibling_index: null },
        source: { source_visual_id: visualKey, visual_type: "simple_plot", panel_count: 1, has_embedded_text: false, source_width_px: 1200, source_height_px: 600, source_region: { x: 0, y: 0, width: 1, height: 1 }, coordinate_space: "source_normalized_0_1", asset_sha256: HASH_A, crop_mode: "full_figure" },
      }],
      containers: [{ container_id: `container-${slideNumber}`, shape_name: `figure-panel-${slideNumber}`, role: "image_only", fit_policy: "contain", crop_policy: "full_figure", whitespace_policy: "minimal", mismatch_policy: "replan" }],
    };
    const output = assembleRenderTelemetry({ renderer_output: rendererOutput, visual_manifest: visualManifest, asset_registry: { [assetId]: HASH_A } });
    assert.equal(output.status, "pass");
    assert.equal(output.match_log[0].asset_identity_provenance, "asset_registry");
  }
});

test("Slide 13 preserves four independent siblings, reading order, containers, and baseline", () => {
  const hashes = ["a", "b", "d", "e"].map((letter) => letter.repeat(64));
  const keys = ["robustness-uv", "robustness-dye", "robustness-temperature", "robustness-stretching"];
  const elements = [];
  const visuals = [];
  const containers = [];
  keys.forEach((key, index) => {
    const x = 40 + index * 310;
    elements.push({ aid: `frame-${index}`, kind: "shape", name: `s13-panel-${index}`, bbox: [x, 180, 280, 210], order: index * 2 + 1 });
    elements.push({ aid: `image-${index}`, kind: "image", alt: `rpa:${key} | ${key}`, bbox: [x, 180, 280, 210], imageFit: "contain", assetSha256: hashes[index], order: index * 2 + 2 });
    visuals.push({ visual_key: key, slide_id: "SLIDE0013", source_visual_id: key, visual_type: "simple_plot", panel_count: 1, has_embedded_text: false, source_width_px: 800, source_height_px: 600, source_region: { x: 0, y: 0, width: 1, height: 1 }, coordinate_space: "source_normalized_0_1", slot_id: `figure_${index + 1}`, container_id: `s13-container-${index}`, asset_sha256: hashes[index], crop_mode: "full_figure", group_id: "s13-robustness", sibling_index: index });
    containers.push({ container_id: `s13-container-${index}`, shape_name: `s13-panel-${index}`, role: "image_only", fit_policy: "contain", crop_policy: "full_figure", whitespace_policy: "minimal", mismatch_policy: "replan" });
  });
  const rendererOutput = { schema: "openai.presentation.layout/v4", slide: { aid: "SLIDE0013", layoutId: "RM-FOUR_PANEL-05", layoutType: "evidence", frame: { width: 1280, height: 720 }, backgroundColor: "#FFFFFF" }, elements };
  const visualManifest = {
    ...manifestHeader("slide-13-regression"), visuals, containers,
    visual_groups: [{ group_id: "s13-robustness", relation_type: "parallel_siblings", expected_sibling_count: 4, reading_order: keys, shared_baseline: "bottom", baseline_tolerance: 0.01, require_unique_containers: true, require_unique_assets: true }],
  };
  const passed = assembleRenderTelemetry({ renderer_output: rendererOutput, visual_manifest: visualManifest });
  assert.equal(passed.status, "pass");
  assert.equal(passed.canonical_telemetry.visual_groups[0].actual_sibling_count, 4);
  assert.equal(passed.canonical_telemetry.visual_groups[0].baseline_spread, 0);

  rendererOutput.elements = rendererOutput.elements.filter((element) => element.aid !== "image-3");
  const failed = assembleRenderTelemetry({ renderer_output: rendererOutput, visual_manifest: visualManifest });
  assert.equal(failed.status, "fail");
  assert.ok(failed.failures.some((item) => item.code === "VISUAL_GROUP_STRUCTURE_MISMATCH"));
});

test("legacy manifest versions remain blocked instead of receiving inferred v0.4.7 facts", () => {
  const legacy = manifest();
  legacy.manifest_schema_version = "0.4.6";
  const output = assembleRenderTelemetry({ renderer_output: artifactSlide(), visual_manifest: legacy });
  assert.equal(output.status, "blocked");
  assert.ok(output.missing_facts.some((item) => item.code === "TELEMETRY_SCHEMA_INCOMPATIBLE"));
});
