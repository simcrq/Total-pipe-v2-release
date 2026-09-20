import assert from "node:assert/strict";
import test from "node:test";
import { runFigurePlacement } from "../server/figure-placement.mjs";
import { evaluateVisualQuality } from "../server/visual-quality/index.mjs";
import {
  computeContainerChildMetrics,
  computeVisualFitMetrics,
  evaluateContainerChildFit,
  resolveVisualFitProfile,
  runVisualFitPreflight,
} from "../server/visual-fit/index.mjs";

function container(overrides = {}) {
  return {
    container_id: "figure-panel",
    role: "image_only",
    outer_bbox: { x: 64, y: 148, width: 1152, height: 308 },
    content_bbox: { x: 72, y: 156, width: 1136, height: 292 },
    content_inset: { left: 8, right: 8, top: 8, bottom: 8 },
    child_visual_ids: ["extended-data-fig-1"],
    fit_policy: "contain",
    crop_policy: "full_figure",
    whitespace_policy: "minimal",
    mismatch_policy: "replan",
    ...overrides,
  };
}

function preflight(overrides = {}) {
  return runVisualFitPreflight({
    visual_id: "extended-data-fig-1",
    source: { width: 1432, height: 1189 },
    source_region: { x: 0, y: 0, width: 1432, height: 1189 },
    visual_intent: {
      visual_type: "scientific_figure",
      crop_policy: "full_figure",
      fit_policy: "contain",
      semantic_crop_allowed: false,
      whitespace_policy: "minimal",
      priority: "primary_visual",
    },
    allocated_visual_bbox: { x: 72, y: 156, width: 1136, height: 292 },
    visual_container: container(),
    ...overrides,
  });
}

test("meta-assembly slide 4 is blocked before renderer input", () => {
  const result = preflight();
  assert.equal(result.pipeline_status, "visual_fit_preflight_complete");
  assert.equal(result.status, "fail");
  assert.equal(result.decision, "needs_replan");
  assert.equal(result.issue.code, "VISUAL_SLOT_FIT_INCOMPATIBLE");
  assert.equal(result.recommended_action, "replan");
  assert.ok(Math.abs(result.metrics.source_aspect_ratio - 1.204) < 0.001);
  assert.ok(Math.abs(result.metrics.allocated_aspect_ratio - 3.89) < 0.01);
  assert.ok(Math.abs(result.metrics.visual_fill.width_ratio - 0.31) < 0.01);
  assert.equal(result.metrics.visual_fill.height_ratio, 1);

  const placement = runFigurePlacement({
    trace_id: "meta-assembly-slide-4",
    visual: {
      id: "extended-data-fig-1",
      source_width_px: 1432,
      source_height_px: 1189,
      visual_intent: {
        selection: { strategy: "full_figure" },
        placement: { preferred_fit: "contain" },
        visual_type: "scientific_figure",
        crop_policy: "full_figure",
        fit_policy: "contain",
        whitespace_policy: "minimal",
      },
    },
    allocated_visual_bbox: { x: 72, y: 156, width: 1136, height: 292 },
    visual_container: container(),
  });
  assert.equal(placement.status, "fail");
  assert.equal(placement.stages.visual_fit_preflight.status, "fail");
  assert.equal(placement.stages.placement, null);
  assert.equal(placement.stages.renderer_input, null);
  assert.equal(placement.stages.visual_qa.recommended_action, "replan");
});

test("fit profile covers near-match, portrait-wide, and wide-tall geometry", () => {
  const near = preflight({
    source: { width: 1330, height: 1000 },
    source_region: { x: 0, y: 0, width: 1330, height: 1000 },
    allocated_visual_bbox: { x: 0, y: 0, width: 1500, height: 1000 },
    visual_container: container({ content_bbox: { x: 0, y: 0, width: 1500, height: 1000 } }),
  });
  assert.equal(near.status, "pass");
  const portrait = preflight({
    source: { width: 800, height: 1000 },
    source_region: { x: 0, y: 0, width: 800, height: 1000 },
    allocated_visual_bbox: { x: 0, y: 0, width: 3000, height: 1000 },
    visual_container: container({ content_bbox: { x: 0, y: 0, width: 3000, height: 1000 } }),
  });
  assert.equal(portrait.status, "fail");
  const wide = preflight({
    source: { width: 3000, height: 1000 },
    source_region: { x: 0, y: 0, width: 3000, height: 1000 },
    allocated_visual_bbox: { x: 0, y: 0, width: 800, height: 1000 },
    visual_container: container({ content_bbox: { x: 0, y: 0, width: 800, height: 1000 } }),
  });
  assert.equal(wide.status, "fail");
});

test("intentional whitespace and composite containers do not false fail", () => {
  const intentional = preflight({
    visual_intent: { visual_type: "scientific_figure", crop_policy: "full_figure", fit_policy: "contain", whitespace_policy: "intentional" },
    visual_container: container({ whitespace_policy: "intentional" }),
  });
  assert.equal(intentional.status, "pass");
  assert.equal(intentional.recommended_action, "allow_whitespace");
  const annotated = preflight({ visual_container: container({ role: "image_annotation" }) });
  assert.equal(annotated.status, "pass");
});

test("semantic crop routes to region resolution while full figure routes to replan", () => {
  const semantic = preflight({
    visual_intent: { visual_type: "scientific_figure", crop_policy: "semantic_crop_allowed", fit_policy: "contain", semantic_crop_allowed: true, whitespace_policy: "minimal" },
    visual_container: container({ crop_policy: "semantic_crop_allowed", mismatch_policy: "resolve_region" }),
  });
  assert.equal(semantic.status, "fail");
  assert.equal(semantic.decision, "needs_region_resolution");
  assert.equal(semantic.recommended_action, "resolve_region");
  assert.equal(preflight().decision, "needs_replan");
});

test("metric facts are threshold-free and profile rules remain configurable", () => {
  const metrics = computeVisualFitMetrics({
    source: { width: 1204, height: 1000 },
    source_region: { x: 0, y: 0, width: 1204, height: 1000 },
    allocated_visual_bbox: { x: 0, y: 0, width: 3890, height: 1000 },
    fit_policy: "contain",
  });
  assert.equal(metrics.visual_fill.height_ratio, 1);
  assert.ok(metrics.gaps.gap_symmetry.horizontal_delta_ratio < 0.000001);
  const relaxed = preflight({
    quality_profile: {
      visual_fit_rules: {
        scientific_figure: {
          visual_types: ["scientific_figure"],
          aspect_mismatch_warning: 4,
          aspect_mismatch_fail: 5,
          minimum_axis_fill_warning: 0.2,
          minimum_axis_fill_fail: 0.1,
          gap_symmetry_tolerance: 0.05,
        },
      },
    },
  });
  assert.equal(relaxed.status, "pass");
});

test("cover geometry, profile warnings, and contract errors stay explicit", () => {
  const covered = computeVisualFitMetrics({
    source: { width: 2000, height: 1000 },
    allocated_visual_bbox: { x: 1, y: 2, width: 2, height: 2 },
    fit_policy: "cover",
  });
  assert.deepEqual(covered.predicted_display_bbox, { x: 1, y: 2, width: 2, height: 2 });
  assert.equal(covered.visual_fill.area_ratio, 1);
  const warning = preflight({
    source: { width: 1500, height: 1000 },
    source_region: { x: 0, y: 0, width: 1500, height: 1000 },
    allocated_visual_bbox: { x: 0, y: 0, width: 2600, height: 1000 },
    visual_container: container({ content_bbox: { x: 0, y: 0, width: 2600, height: 1000 } }),
  });
  assert.equal(warning.status, "warning");
  const coverConflict = preflight({
    visual_intent: { visual_type: "scientific_figure", crop_policy: "full_figure", fit_policy: "cover", whitespace_policy: "minimal" },
    visual_container: container({ fit_policy: "cover" }),
  });
  assert.equal(coverConflict.status, "fail");
  assert.equal(coverConflict.recommended_action, "change_fit_policy");
  // RPA-2: photo 不受 scientific_figure 管辖，但仍要跑宽松几何下限。
  // 该槽位 contain 面积填充率仅 ~0.31（< 0.4），因此不再是"静默 pass"。
  const photo = preflight({
    visual_intent: { visual_type: "photo", crop_policy: "full_figure", fit_policy: "contain", whitespace_policy: "minimal" },
  });
  assert.equal(photo.status, "warning");
  assert.equal(photo.governance, "not_governed");
  assert.equal(photo.geometry_checked, true);
  assert.equal(photo.verified, true);
  assert.equal(photo.reason, "ungoverned_visual_type_underfills_slot");
  // 未触发下限时仍保持 pass，但必须显式标记为"未校验"而非"质量合格"。
  const roomyPhoto = preflight({
    source: { width: 1136, height: 292 },
    source_region: { x: 0, y: 0, width: 1136, height: 292 },
    visual_intent: { visual_type: "photo", crop_policy: "full_figure", fit_policy: "contain", whitespace_policy: "minimal" },
  });
  assert.equal(roomyPhoto.status, "pass");
  assert.equal(roomyPhoto.governance, "not_governed");
  assert.equal(roomyPhoto.geometry_checked, false);
  assert.equal(roomyPhoto.verified, false);
  // 受管辖类型仍然走完整校验。
  const governed = preflight();
  assert.equal(governed.governance, "governed");
  assert.equal(governed.geometry_checked, true);
  assert.throws(() => computeVisualFitMetrics({ source: { width: 10, height: 10 }, source_region: { x: 9, y: 0, width: 2, height: 2 }, allocated_visual_bbox: { x: 0, y: 0, width: 1, height: 1 } }), /source bounds/);
  assert.throws(() => computeVisualFitMetrics({ source: { width: 10, height: 10 }, allocated_visual_bbox: { x: 0, y: 0, width: 1, height: 1 }, fit_policy: "stretch" }), /unsupported fit_policy/);
  assert.throws(() => runVisualFitPreflight({}), /visual_id is required/);
  assert.throws(() => preflight({ visual_container: container({ content_bbox: { x: 0, y: 0, width: 1, height: 1 } }) }), /must equal the inner/);
});

test("effective child symmetry is interpreted by profile rules, not metrics", () => {
  const facts = computeContainerChildMetrics({
    content_bbox: { x: 0, y: 0, width: 10, height: 5 },
    child_display_bbox: { x: 0, y: 0, width: 8, height: 5 },
  });
  assert.equal(facts.gaps.gap_symmetry.horizontal_delta_ratio, 0.2);
  const result = evaluateContainerChildFit(facts, {
    visual_type: "scientific_figure",
    container_role: "image_only",
    fit_policy: "contain",
    crop_policy: "full_figure",
    whitespace_policy: "minimal",
    mismatch_policy: "replan",
  }, resolveVisualFitProfile());
  assert.equal(result.status, "warning");
  assert.equal(result.recommended_action, "fix_renderer_adapter");
});

test("effective child containment rejects display geometry outside the content box", () => {
  const facts = computeContainerChildMetrics({
    content_bbox: { x: 0, y: 0, width: 10, height: 5 },
    child_display_bbox: { x: -1, y: 0, width: 12, height: 5 },
  });
  assert.equal(facts.visual_fill.width_ratio, 1.2);
  const result = evaluateContainerChildFit(facts, {
    visual_type: "scientific_figure",
    container_role: "image_only",
    fit_policy: "contain",
    crop_policy: "full_figure",
    whitespace_policy: "minimal",
    mismatch_policy: "replan",
  }, resolveVisualFitProfile());
  assert.equal(result.status, "fail");
  assert.equal(result.reason, "effective_child_outside_content_bbox");
  assert.equal(result.recommended_action, "fix_renderer_adapter");
});

function renderedTelemetry(whitespacePolicy = "minimal", role = "image_only") {
  const display = { x: 4.12, y: 1.56, width: 3.52, height: 2.92 };
  const content = { x: 0.72, y: 1.56, width: 11.36, height: 2.92 };
  return {
    telemetry_version: "1.2.0",
    slide_id: "meta-assembly-slide-4",
    renderer: "slidep",
    slide: {
      width: 12.8,
      height: 7.2,
      render_width_px: 1280,
      render_height_px: 720,
      background: { kind: "solid", color: "#FFFFFF" },
      layout_id: "RM-WORKFLOW-01",
      category: "workflow",
    },
    elements: [{
      element_id: "figure",
      type: "image",
      quality_role: "content",
      z_index: 1,
      opacity: 1,
      bbox: display,
      render_bbox_px: { x: 412, y: 156, width: 352, height: 292 },
      text: null,
      image: {
        display_bbox: display,
        source_width_px: 1432,
        source_height_px: 1189,
        visual_id: "extended-data-fig-1",
        content_id: "figure-content",
        slot_id: "figure",
        visual_type: "scientific_figure",
        panel_count: 4,
        has_embedded_text: false,
        min_display_width: null,
        allocated_bbox: content,
        rendered_embedded_text_px: null,
        visual_parent_id: "figure-panel",
        relation: { type: "visual_child" },
      },
      fill_color: null,
      background_color: null,
      theme_token: null,
      theme_usage: null,
    }],
    visual_containers: [container({
      role,
      outer_bbox: { x: 0.64, y: 1.48, width: 11.52, height: 3.08 },
      content_bbox: content,
      content_inset: { left: 0.08, right: 0.08, top: 0.08, bottom: 0.08 },
      whitespace_policy: whitespacePolicy,
    })],
    theme: null,
    unavailable: [{ field: "theme", reason: "fixture has no theme" }],
    provided_metrics: {},
  };
}

test("post-render Parent-Child QA catches the effective mismatch", async () => {
  const failed = await evaluateVisualQuality({ telemetry: renderedTelemetry() });
  assert.equal(failed.checks.visual_container_child_fit.status, "fail");
  assert.ok(failed.violations.some((item) => item.code === "VISUAL_CONTAINER_CHILD_MISMATCH"));
  const intentional = await evaluateVisualQuality({ telemetry: renderedTelemetry("intentional") });
  assert.equal(intentional.checks.visual_container_child_fit.status, "pass");
  const annotated = await evaluateVisualQuality({ telemetry: renderedTelemetry("minimal", "image_annotation") });
  assert.equal(annotated.checks.visual_container_child_fit.status, "pass");
  const incompleteTelemetry = renderedTelemetry();
  incompleteTelemetry.elements[0].image.relation = null;
  const incomplete = await evaluateVisualQuality({ telemetry: incompleteTelemetry });
  assert.equal(incomplete.checks.visual_container_child_fit.status, "warning");
  assert.ok(incomplete.violations.some((item) => item.code === "VISUAL_CONTAINER_RELATION_NOT_EVALUABLE"));
});

test("post-render Parent-Child QA fails a child that overflows the container but stays on the page", async () => {
  const overflowed = renderedTelemetry();
  overflowed.elements[0].image.display_bbox = { x: 0.5, y: 1.56, width: 12, height: 2.92 };
  const report = await evaluateVisualQuality({ telemetry: overflowed });
  assert.equal(report.checks.visual_container_child_fit.status, "fail");
  assert.equal(report.checks.visual_container_child_fit.code, "VISUAL_CONTAINER_CHILD_MISMATCH");
  assert.ok(report.violations.some((item) => item.code === "VISUAL_CONTAINER_CHILD_MISMATCH"
    && item.message === "effective_child_outside_content_bbox"));
  assert.equal(report.metrics.visual_container_fit.observations[0].metrics.visual_fill.width_ratio, 1.056338);
});
