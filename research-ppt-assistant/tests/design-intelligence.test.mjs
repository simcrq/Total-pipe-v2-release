import assert from "node:assert/strict";
import fs from "node:fs/promises";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { scoreAestheticCandidate } from "../server/design-intelligence/aesthetic-scorer.mjs";
import { createDesignCandidates } from "../server/design-intelligence/candidate-factory.mjs";
import { createDeckDesignState, updateDeckDesignState } from "../server/design-intelligence/deck-state.mjs";
import { compileSlideDesignIR, inferTextFlow } from "../server/design-intelligence/design-compiler.mjs";
import { DESIGN_QA_CODES, evaluateDeckDesign } from "../server/design-intelligence/design-qa.mjs";
import { loadDesignRegistry } from "../server/design-intelligence/registry.mjs";
import { createDeckPlan, searchLayouts, validateDeckPlan } from "../server/core.mjs";
import { validateJsonSchema } from "../server/schema-validator.mjs";

const TEST_DIR = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(TEST_DIR, "..");

test("Design Compiler emits deterministic schema-valid SlideDesignIR v1", async () => {
  const schema = JSON.parse(await fs.readFile(path.join(ROOT, "schemas", "slide-design-ir.schema.json"), "utf8"));
  const brief = {
    title: "PBG controls center while TIR organizes rim",
    goal: "Explain the measured mechanism",
    category_hint: "theory",
    image_count: 1,
    text_chars: 120,
    evidence_ids: ["EV0001"],
    citation_ids: ["CIT0001"],
  };
  const first = compileSlideDesignIR(brief);
  const second = compileSlideDesignIR(structuredClone(brief));
  assert.deepEqual(first, second);
  assert.equal(validateJsonSchema(schema, first).status, "valid");
  assert.equal(first.semantic_role, "mechanism_explanation");
  assert.equal(first.visual_priority, "dominant");
  assert.equal(first.allowed_transformations.citation_required, true);
  assert.deepEqual(first.design_intent.treatment_preferences.slice(0, 2), ["technical_annotation", "mechanism_diagram"]);
});

test("treatment and decoration registries enforce the v0.5 grammar and budget", async () => {
  const registry = await loadDesignRegistry();
  assert.equal(registry.treatments.length, 9);
  assert.ok(registry.decorations.length >= 8);
  for (const decoration of registry.decorations) {
    assert.ok(registry.grammar.container.includes(decoration.container));
    assert.ok(decoration.decoration_budget.decorative_area_ratio_max <= 0.12);
    assert.equal(decoration.decoration_budget.allow_evidence_overlap, false);
    assert.equal(decoration.decoration_budget.allow_visual_overlap, false);
  }
});

test("long parallel prose selects the distributed arrow-list treatment", async () => {
  const brief = {
    title: "Three implications",
    category_hint: "discussion",
    text_chars: 180,
    key_points: [
      "The first implication defines the operating boundary and the conditions under which it holds.",
      "The second implication links the measured response to the mechanism supported by the evidence.",
      "The third implication identifies the remaining uncertainty and the next discriminating experiment.",
    ],
  };
  const designIR = compileSlideDesignIR(brief);
  assert.equal(designIR.text_flow.mode, "distributed_arrow_list");
  assert.equal(designIR.text_flow.bullet_glyph, "➢");
  assert.equal(designIR.design_intent.treatment_preferences[0], "structured_text");
  const registry = await loadDesignRegistry();
  const structural = await searchLayouts({ categories: ["discussion"], image_count: 0, text_chars: 180, include_slots: true, k: 4 });
  const result = createDesignCandidates({ design_ir: designIR, layouts: structural.results, deck_state: createDeckDesignState(), registry });
  assert.ok(result.candidates.some((candidate) => candidate.treatment.id === "structured_text"));
});

test("single paragraphs and reference material stay plain", () => {
  assert.equal(inferTextFlow({ body: "One long paragraph remains prose. ".repeat(10), text_chars: 320 }, "discussion", 0).mode, "plain");
  assert.equal(inferTextFlow({ key_points: ["A".repeat(40), "B".repeat(40), "C".repeat(40)] }, "reference_material", 0).mode, "plain");
});

test("CJK prose uses display-weighted length for automatic text flow", () => {
  const flow = inferTextFlow({
    body: "第一条说明实验边界与适用条件。\n第二条连接观测结果与机制证据。\n第三条明确剩余不确定性和下一步实验。",
  }, "discussion", 0);
  assert.equal(flow.mode, "distributed_arrow_list");
});

test("Candidate Factory expands only structurally legal layouts and returns explainable Top-24 scores", async () => {
  const registry = await loadDesignRegistry();
  const designIR = compileSlideDesignIR({ title: "A versus B", category_hint: "dual_figure", image_count: 2, text_chars: 70 });
  const structural = await searchLayouts({ categories: ["dual_figure"], image_count: 2, text_chars: 70, include_slots: true, k: 8 });
  const result = createDesignCandidates({
    design_ir: designIR,
    layouts: structural.results,
    deck_state: createDeckDesignState(),
    registry,
  });
  assert.equal(result.hard_constraint_mode, "layout_gate_before_aesthetic_ranking");
  assert.ok(result.candidate_count >= 12 && result.candidate_count <= 24);
  assert.ok(result.candidates.every((candidate) => structural.results.some((layout) => layout.id === candidate.layout.id)));
  assert.ok(result.candidates.every((candidate) => candidate.treatment.compatible_roles.includes("results_comparison")));
  assert.ok(result.candidates.every((candidate) => Number.isFinite(candidate.aesthetic.components.repetition_penalty)));
  assert.ok(result.candidates.every((candidate) => candidate.aesthetic.explanation.hard_constraints_overridable === false));
});

test("aesthetic scorer penalizes repeated treatment, decoration, container, and composition", async () => {
  const registry = await loadDesignRegistry();
  const layout = (await searchLayouts({ categories: ["single_figure"], image_count: 1, text_chars: 60, include_slots: true, k: 1 })).results[0];
  const designIR = compileSlideDesignIR({ title: "Result", category_hint: "single_figure", image_count: 1, text_chars: 60 });
  const treatment = registry.treatments_by_id.get("figure_led");
  const decoration = registry.decorations_by_id.get("open_figure");
  const baseline = scoreAestheticCandidate({ layout, treatment, decoration, design_ir: designIR, deck_state: createDeckDesignState() });
  let repeatedState = createDeckDesignState();
  for (let index = 0; index < 3; index += 1) repeatedState = updateDeckDesignState(repeatedState, { layout, treatment, decoration, design_ir: designIR });
  const repeated = scoreAestheticCandidate({ layout, treatment, decoration, design_ir: designIR, deck_state: repeatedState });
  assert.ok(repeated.components.repetition_penalty > baseline.components.repetition_penalty);
  assert.ok(repeated.score < baseline.score);
  assert.equal(repeatedState.rhythm.dense_pages_in_row, 0);
  assert.equal(repeatedState.counts.pages, 3);
});

test("createDeckPlan integrates v0.5 design intelligence without weakening production validation", async () => {
  const plan = await createDeckPlan({ presentation_type: "group_meeting", slide_count: 12, topic: "Design intelligence" });
  assert.equal(plan.production_status, plan.status);
  assert.ok(["pass", "review_recommended"].includes(plan.design_status));
  assert.equal(plan.design_telemetry.length, plan.slides.length);
  assert.equal(plan.deck_design_state.counts.pages, plan.slides.length);
  assert.ok(plan.slides.every((slide) => slide.design_ir.schema_version === "1.0.0"));
  assert.ok(plan.slides.every((slide) => slide.visual_treatment && slide.decoration_profile?.id));
  assert.ok(plan.slides.every((slide) => slide.design_context?.deck_state_before));
  assert.equal(plan.design_telemetry[0].deck_state_before.counts.pages, 0);
  assert.equal(plan.design_telemetry.at(-1).deck_state_after.counts.pages, plan.slides.length);
  assert.ok(plan.slides.every((slide) => slide.aesthetic_score.explanation.hard_constraints_overridable === false));
  assert.ok(plan.design_qa.visual_diversity.treatment_diversity > 0.25);
  assert.equal(plan.design_qa.visual_diversity.cardification_rate, 0);
  const productionValidation = await validateDeckPlan({ theme_id: plan.theme.id, slides: plan.slides });
  assert.deepEqual(productionValidation.invalid_slides, []);
});

test("Design QA codes remain separate from the production plan status", () => {
  const slides = Array.from({ length: 3 }, (_, index) => ({
    index: index + 1,
    category: "summary",
    layout_family: "summary",
    visual_treatment: "summary_synthesis",
    decoration_profile: { id: "cards", container: "card" },
    container_density: 0.45,
    aesthetic_score: { score: 0.3, components: { hierarchy_fit: 0.3, visual_priority_fit: 0.3, whitespace_fit: 0.3, balance_proxy: 0.3 } },
  }));
  const qa = evaluateDeckDesign(slides);
  assert.equal(qa.status, "review_recommended");
  assert.ok(qa.issues.some((item) => item.code === "EXCESSIVE_CARDIFICATION"));
  assert.ok(qa.issues.some((item) => item.code === "REPEATED_TREATMENT"));
  assert.ok(DESIGN_QA_CODES.includes("LOW_DECK_RHYTHM"));
  assert.equal(qa.visual_diversity.cardification_rate, 0.45);
});
