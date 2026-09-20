import assert from "node:assert/strict";
import test from "node:test";
import { runBoundedRepairLoop } from "../server/perceptual-loop/bounded-loop.mjs";
import { REPAIR_PLAN_SCHEMA, VISUAL_OBSERVATION_SCHEMA } from "../server/perceptual-loop/contracts.mjs";
import { createRepairPlan } from "../server/perceptual-loop/repair-controller.mjs";
import { observeRenderedSlide } from "../server/perceptual-loop/visual-observer.mjs";
import { assertJsonSchema } from "../server/schema-validator.mjs";
import { evaluateVisualQuality } from "../server/visual-quality/index.mjs";

function telemetryFixture() {
  return {
    telemetry_version: "1.0.0",
    slide_id: "perceptual-1",
    renderer: "slidep",
    slide: {
      width: 10,
      height: 10,
      render_width_px: 1000,
      render_height_px: 1000,
      background: { kind: "solid", color: "#FFFFFF" },
    },
    elements: [{
      element_id: "body",
      type: "text",
      quality_role: "content",
      bbox: { x: 1, y: 1, width: 8, height: 8 },
      render_bbox_px: { x: 100, y: 100, width: 800, height: 800 },
      text: {
        content: "Readable", language: "en", script: "Latin", font_family: "Arial", font_size: 20,
        font_weight: 400, line_count: 1, overflow: false, foreground_color: "#111111",
        intended_single_line: false, role: "body",
      },
      image: null,
      fill_color: null,
      background_color: "#FFFFFF",
      theme_token: "text",
      theme_usage: "body_text",
    }],
    theme: { id: "fixture", tokens: { text: { color: "#111111", allowed_usage: ["body_text"], forbidden_usage: ["background"] } } },
    unavailable: [],
    provided_metrics: {},
  };
}

function observationFixture(overrides = {}) {
  const issues = overrides.issues ?? ["LOW_VISUAL_HIERARCHY"];
  return {
    observer_version: "1.0.0",
    slide_id: "perceptual-1",
    production_status: "pass",
    design_status: "repairable",
    observation_status: "complete",
    design_metrics: Object.fromEntries(["hierarchy", "balance", "whitespace", "visual_focus", "decoration_variety"].map((key) => [key, {
      measurable: true,
      value: key === "hierarchy" ? 0.2 : 0.8,
      evidence: {},
    }])),
    issues,
    diagnoses: issues.map((code) => ({
      code,
      source: code === "OBSERVATION_INCOMPLETE" ? "observer" : "design_qa",
      severity: "warning",
      source_codes: [],
      message: code,
    })),
    recommended_actions: ["CHANGE_TREATMENT"],
    design_context_used: true,
    render_artifact: null,
    ...overrides,
  };
}

test("Visual Observer and Repair Controller emit schema-valid deterministic contracts", async () => {
  const telemetry = telemetryFixture();
  const qaReport = await evaluateVisualQuality({ telemetry });
  const observation = observeRenderedSlide({ qa_report: qaReport, telemetry });
  const repairPlan = createRepairPlan(observation);
  assertJsonSchema(VISUAL_OBSERVATION_SCHEMA, observation);
  assertJsonSchema(REPAIR_PLAN_SCHEMA, repairPlan);
  assert.equal(observation.production_status, "pass");
  assert.equal(repairPlan.action, "KEEP");
});

test("Repair Controller advances a fixed policy and escalates at the two-iteration boundary", () => {
  const observation = observationFixture();
  const first = createRepairPlan(observation, { iteration: 0 });
  const second = createRepairPlan(observation, { iteration: 1, repair_lineage: first.repair_lineage });
  const final = createRepairPlan(observation, { iteration: 2, repair_lineage: second.repair_lineage });
  assert.equal(first.action, "CHANGE_TREATMENT");
  assert.equal(second.action, "RESELECT_LAYOUT");
  assert.equal(final.action, "ESCALATE");
  assert.equal(final.status, "manual_review_required");
  assert.equal(final.human_escalation.reason, "max_repair_iterations_exhausted");
  assert.equal(final.repair_lineage.length, 3);
  assertJsonSchema(REPAIR_PLAN_SCHEMA, final);
});

test("incomplete rendered facts block automatic repair", () => {
  const observation = observationFixture({
    production_status: "not_evaluable",
    design_status: "blocked",
    observation_status: "blocked",
    issues: ["OBSERVATION_INCOMPLETE"],
    recommended_actions: ["ESCALATE"],
  });
  const plan = createRepairPlan(observation);
  assert.equal(plan.status, "blocked");
  assert.equal(plan.action, "ESCALATE");
  assert.equal(plan.next_iteration, null);
});

test("text-density repair can only reduce optional content before splitting", () => {
  const observation = observationFixture({
    issues: ["TEXT_DENSITY_HIGH"],
    diagnoses: [{ code: "TEXT_DENSITY_HIGH", source: "production_qa", severity: "warning", source_codes: ["TEXT_VISUAL_OVERFLOW"], message: "dense" }],
    recommended_actions: ["REBIND"],
  });
  const first = createRepairPlan(observation, { iteration: 0 });
  const second = createRepairPlan(observation, { iteration: 1, repair_lineage: first.repair_lineage });
  assert.equal(first.action, "REDUCE_SECONDARY_CONTENT");
  assert.equal(first.target.strategy, "remove_optional_only");
  assert.equal(second.action, "SPLIT_PAGE");
});

test("bounded repair loop stops immediately after a successful re-render", async () => {
  let renders = 0;
  const result = await runBoundedRepairLoop({ initial_artifact: { revision: 0 } }, {
    observe: async (artifact) => artifact.revision ? observationFixture({ issues: [], diagnoses: [], recommended_actions: [], design_status: "pass" }) : observationFixture(),
    applyRepair: async (_plan, artifact) => ({ revision: artifact.revision + 1 }),
    render: async (artifact) => { renders += 1; return artifact; },
  });
  assert.equal(result.status, "pass");
  assert.equal(result.render_count, 1);
  assert.equal(renders, 1);
  assert.equal(result.iterations.at(-1).repair_plan.action, "KEEP");
});

test("bounded repair loop never renders a third repair and preserves escalation lineage", async () => {
  let renders = 0;
  const result = await runBoundedRepairLoop({ initial_artifact: { revision: 0 } }, {
    observe: async () => observationFixture(),
    applyRepair: async (_plan, artifact) => ({ revision: artifact.revision + 1 }),
    render: async (artifact) => { renders += 1; return artifact; },
  });
  assert.equal(result.status, "manual_review_required");
  assert.equal(result.render_count, 2);
  assert.equal(renders, 2);
  assert.equal(result.iterations.length, 3);
  assert.equal(result.iterations.at(-1).repair_plan.action, "ESCALATE");
  assert.equal(result.repair_lineage.length, 3);
});

test("Visual QA exposes production, design, observation, and repair contracts together", async () => {
  const report = await evaluateVisualQuality({
    telemetry: telemetryFixture(),
    design_context: {
      design_ir: { hierarchy: { primary: "headline" }, visual_priority: "none", whitespace: "medium" },
      visual_treatment: "editorial_open",
      decoration_profile: { id: "open", container: "none" },
      deck_state_before: { recent_history: { treatments: [], decoration_patterns: [], container_families: [] } },
    },
    render_artifact: { uri: "render://perceptual-1.png", sha256: "fixture" },
  });
  assert.equal(report.production_status, "pass");
  assert.equal(report.design_status, "pass");
  assert.equal(report.repair_status, "keep");
  assert.equal(report.repair_plan.action, "KEEP");
  assert.equal(report.design_observation.render_artifact.uri, "render://perceptual-1.png");
});

test("design-only whitespace failure cannot become a production diagnosis", async () => {
  const telemetry = telemetryFixture();
  telemetry.elements[0].bbox = { x: 4.9, y: 4.9, width: 0.2, height: 0.2 };
  telemetry.elements[0].render_bbox_px = { x: 490, y: 490, width: 20, height: 20 };
  const report = await evaluateVisualQuality({ telemetry });
  assert.equal(report.status, "fail");
  assert.equal(report.production_status, "pass");
  assert.equal(report.design_status, "repairable");
  assert.ok(report.design_observation.issues.includes("LOW_WHITESPACE"));
  assert.ok(!report.design_observation.issues.includes("GEOMETRY_INVALID"));
  assert.equal(report.repair_plan.action, "REDECORATE");
});
