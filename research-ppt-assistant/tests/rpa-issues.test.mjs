import assert from "node:assert/strict";
import test from "node:test";
import { getLayout, searchLayouts, validateDeckPlan, createDeckPlan } from "../server/core.mjs";
import { inferSemanticCategory, planSlideClosedLoop } from "../server/planning-loop.mjs";
import { runVisualFitPreflight, evaluateVisualFit } from "../server/visual-fit/index.mjs";
import { resolveVisualFitProfile } from "../server/visual-fit/profile.mjs";

const SQUARE_VISUAL = [{ visual_type: "schematic", visual_aspect_ratio: 1.0, panel_count: 1 }];

// ---------------- RPA-1 ----------------

test("RPA-1: plan 选型消费 visual_aspect_ratio 并暴露几何打分", async () => {
  const withAr = await searchLayouts({ text_chars: 120, title_chars: 12, image_count: 1, k: 3, visuals: SQUARE_VISUAL });
  const withoutAr = await searchLayouts({ text_chars: 120, title_chars: 12, image_count: 1, k: 3 });
  const top = withAr.results[0];
  assert.notEqual(top.id, withoutAr.results[0].id, "选型应当因源图宽高比而改变");
  assert.ok(Number.isFinite(top.components.visual_geometry_score));
  assert.equal(top.visual_fill.geometry_known, true);
  assert.ok(Number.isFinite(top.visual_fill.estimated_contain_fill));
  // 1:1 方图应被分到宽高比更接近 1 的槽位。
  assert.ok(Math.abs(top.visual_fill.slot_aspect_ratio - 1) < 0.5, `槽位宽高比=${top.visual_fill.slot_aspect_ratio}`);
  assert.ok(top.components.visual_geometry_score > 0.7);
});

test("RPA-1: 缺失 visual_aspect_ratio 时从源像素尺寸推导", async () => {
  const explicit = await searchLayouts({
    text_chars: 120, title_chars: 12, image_count: 1, k: 1,
    visuals: SQUARE_VISUAL,
  });
  const fromPixels = await searchLayouts({
    text_chars: 120, title_chars: 12, image_count: 1, k: 1,
    visuals: [{ visual_type: "schematic", source_width_px: 1000, source_height_px: 1000, panel_count: 1 }],
  });
  assert.equal(fromPixels.results[0].id, explicit.results[0].id);
  assert.equal(fromPixels.results[0].visual_fill.source_aspect_ratio, 1);
});

test("RPA-1: 多个 visual 时取约束最强的宽高比参与选型", async () => {
  const seen = [];
  await planSlideClosedLoop({
    slide_brief: {
      slide_id: "P06",
      title: "器件结构与响应",
      goal: "对比两类器件的响应差异",
      narrative_job: "给出证据",
      text_chars: 110,
      title_chars: 8,
      visuals: [
        { visual_type: "schematic", visual_aspect_ratio: 0.95, panel_count: 1 },
        { visual_type: "simple_plot", visual_aspect_ratio: 0.30, panel_count: 1 },
      ],
    },
  }, {
    searchLayouts: async (query) => {
      seen.push(query.visual_aspect_ratio ?? null);
      return searchLayouts({ ...query, k: 4, include_slots: true });
    },
    getLayout: async (id, theme, mode) => (await getLayout(id, theme, mode)).layout,
  });
  // 0.30 比 0.95 更偏离 1，约束更强，应被选为主导宽高比
  assert.equal(seen[0], 0.3);
});

test("检索支持按类别/族去重排序", async () => {
  const byCategory = await searchLayouts({ text_chars: 120, title_chars: 12, k: 6, diversity: "category" });
  const byFamily = await searchLayouts({ text_chars: 120, title_chars: 12, k: 6, diversity: "family" });
  assert.equal(new Set(byCategory.results.map((r) => r.category)).size, byCategory.results.length);
  assert.equal(new Set(byFamily.results.map((r) => r.family)).size, byFamily.results.length);
  assert.ok(byCategory.results.length > 1);
});

// ---------------- RPA-2 ----------------

function visualFit(overrides = {}) {
  return runVisualFitPreflight({
    visual_id: "fig-1",
    source: { width: 1000, height: 1000 },
    allocated_visual_bbox: { x: 0, y: 0, width: 1000, height: 1000 },
    visual_intent: { visual_type: "schematic", crop_policy: "full_figure", fit_policy: "contain", whitespace_policy: "minimal" },
    ...overrides,
  });
}

test("RPA-2: schematic 严重欠填充不再静默 pass", () => {
  const squeezed = visualFit({ allocated_visual_bbox: { x: 0, y: 0, width: 1000, height: 139 } });
  assert.ok(squeezed.metrics.visual_fill.area_ratio < 0.2);
  assert.equal(squeezed.status, "warning");
  assert.equal(squeezed.reason, "ungoverned_visual_type_underfills_slot");
  assert.equal(squeezed.governance, "not_governed");
  assert.equal(squeezed.geometry_checked, true);
  assert.equal(squeezed.verified, true);
});

test("RPA-2: 未触发下限时仍是 pass，但显式标记为未校验", () => {
  const roomy = visualFit();
  assert.equal(roomy.status, "pass");
  assert.equal(roomy.governance, "not_governed");
  assert.equal(roomy.geometry_checked, false);
  assert.equal(roomy.verified, false);
  assert.equal(roomy.reason, "visual_type_not_governed_by_scientific_figure_profile");
});

test("RPA-2: schematic 宽高比严重错配给出 warning", () => {
  const stretched = visualFit({ allocated_visual_bbox: { x: 0, y: 0, width: 1000, height: 380 } });
  // area_fill 约 0.38 < 0.4，先命中欠填充阈值
  assert.equal(stretched.status, "warning");
  assert.equal(stretched.governance, "not_governed");
  const wide = visualFit({
    source: { width: 1000, height: 1000 },
    allocated_visual_bbox: { x: 0, y: 0, width: 1000, height: 620 },
    quality_profile: {
      visual_fit_rules: {
        scientific_figure: {
          visual_types: ["scientific_figure"], aspect_mismatch_warning: 1.6, aspect_mismatch_fail: 2,
          minimum_axis_fill_warning: 0.5, minimum_axis_fill_fail: 0.35, gap_symmetry_tolerance: 0.05,
        },
        ungoverned_visual_types: { minimum_area_fill_warning: 0.1, aspect_mismatch_warning: 1.3 },
      },
    },
  });
  assert.equal(wide.status, "warning");
  assert.equal(wide.reason, "ungoverned_visual_type_aspect_ratio_mismatch");
  assert.equal(wide.geometry_checked, true);
});

test("RPA-2: 声明为 intentional 留白或缺少填充率时不误报", () => {
  const intentional = visualFit({
    allocated_visual_bbox: { x: 0, y: 0, width: 1000, height: 139 },
    visual_intent: { visual_type: "schematic", crop_policy: "full_figure", fit_policy: "contain", whitespace_policy: "intentional" },
  });
  assert.equal(intentional.status, "pass");
  assert.equal(intentional.reason, "visual_type_not_governed_and_whitespace_declared_intentional");
  assert.equal(intentional.governance, "not_governed");

  const noFill = evaluateVisualFit(
    { visual_fill: {}, aspect_mismatch_factor: Number.NaN },
    { visual_type: "schematic", whitespace_policy: "minimal" },
    resolveVisualFitProfile(undefined),
  );
  assert.equal(noFill.status, "pass");
  assert.equal(noFill.governance, "not_governed");
  assert.equal(noFill.geometry_checked, false);
});

test("RPA-2: 受管辖类型与豁免路径的 governance 标记正确", () => {
  const profile = resolveVisualFitProfile(undefined);
  const governed = evaluateVisualFit(
    { visual_fill: { width_ratio: 1, height_ratio: 1, area_ratio: 1 }, aspect_mismatch_factor: 1 },
    { visual_type: "scientific_figure", fit_policy: "contain", container_role: "image_only", whitespace_policy: "minimal" },
    profile,
  );
  assert.equal(governed.governance, "governed");
  assert.equal(governed.geometry_checked, true);
  const notApplicable = evaluateVisualFit(
    { visual_fill: { width_ratio: 0.3, height_ratio: 1, area_ratio: 0.3 }, aspect_mismatch_factor: 3.2 },
    { visual_type: "scientific_figure", fit_policy: "contain", container_role: "mixed", whitespace_policy: "minimal" },
    profile,
  );
  assert.equal(notApplicable.status, "pass");
  assert.equal(notApplicable.reason, "scientific_figure_minimal_image_only_rule_not_applicable");
  assert.equal(notApplicable.governance, "skipped");
});

// ---------------- RPA-3 ----------------

test("RPA-3: get 返回与 layouts.json 原生 schema 对齐的镜像字段", async () => {
  const entry = JSON.parse((await import("node:fs")).default.readFileSync(new URL("../assets/layout-library/layouts.json", import.meta.url), "utf8"))
    .layouts.find((layout) => layout.id === "RM-THEORY-03");
  const { layout } = await getLayout("RM-THEORY-03");
  assert.equal(layout.slots.length, entry.slots.length);
  assert.deepEqual(layout.slots.map((slot) => slot.id), entry.slots.map((slot) => slot.id));
  assert.deepEqual(layout.slots.map((slot) => slot.type), entry.slots.map((slot) => slot.type));
  assert.equal(layout.capacity.image_capacity, entry.content_profile.image_capacity);
  assert.equal(layout.capacity.max_text_chars, entry.max_text_chars);
  assert.ok(layout.field_aliases["slots[].type"].includes("slot_type"));
  // 规范化视图保留原语义：库的 figure 槽在 slot_specs 里是 image
  assert.ok(layout.slots.some((slot) => slot.type === "figure"));
  assert.ok(layout.slot_specs.some((slot) => slot.slot_type === "image"));
});

// ---------------- RPA-4 ----------------

test("RPA-4: validate-deck 返回 summary 与结果契约说明", async () => {
  const result = await validateDeckPlan({
    slides: [{ layout_id: "RM-THEORY-03", title: "T", content_metrics: { text_chars: 50, title_chars: 1 } }],
  });
  assert.equal(result.summary.total_slides, 1);
  assert.equal(typeof result.summary.passed, "boolean");
  assert.equal(typeof result.summary.invalid_slides, "number");
  assert.equal(typeof result.summary.warning_slides, "number");
  assert.equal(result.result_contract.per_slide_field, "slides");
  assert.equal(result.result_contract.invalid_index_field, "invalid_slides");
  assert.deepEqual(result.result_contract.status_enum, ["valid", "warning", "invalid"]);
  assert.ok(Array.isArray(result.slides) && result.slides[0].index === 1);
});

test("RPA-4: summary 统计与 invalid_slides 保持一致", async () => {
  const result = await validateDeckPlan({
    slides: [
      { layout_id: "RM-THEORY-03", title: "T", content_metrics: { text_chars: 50, title_chars: 1 } },
      { layout_id: "RM-THEORY-03", title: "T", content_metrics: { text_chars: 99999, title_chars: 1 } },
    ],
  });
  assert.equal(result.summary.total_slides, 2);
  assert.equal(result.summary.invalid_slides, result.invalid_slides.length);
  assert.ok(result.summary.invalid_slides >= 1);
  assert.equal(result.summary.passed, false);
});

// ---------------- RPA-5 ----------------

test("RPA-5: 机制/推导信号与 decision 提示冲突时被识别", () => {
  const signals = inferSemanticCategory({
    title: "保持时间的 Arrhenius 外推",
    goal: "用 Arrhenius 关系由加速实验外推室温保持时间的机理",
    text_chars: 180,
  }, ["decision"]);
  assert.equal(signals.category, "theory");
  assert.equal(signals.hinted_category, "decision");
  assert.equal(signals.conflict, true);
});

test("RPA-5: 无信号或非冲突类别不产生冲突", () => {
  const plain = inferSemanticCategory({ title: "实验设置", text_chars: 80 }, ["experiment"]);
  assert.equal(plain.category, null);
  assert.equal(plain.conflict, false);
  const aligned = inferSemanticCategory({ title: "公式推导", text_chars: 80 }, ["theory"]);
  assert.equal(aligned.category, "theory");
  assert.equal(aligned.conflict, false);
});

test("RPA-5: 语义冲突时把检索限制到语义类别", async () => {
  const brief = {
    slide_id: "P10",
    title: "保持时间的 Arrhenius 外推",
    goal: "说明保持时间随温度变化的机理并外推室温寿命",
    narrative_job: "给出理论依据",
    text_chars: 120,
    title_chars: 10,
    category_hint: "decision",
  };
  const seen = [];
  await planSlideClosedLoop({ slide_brief: brief }, {
    searchLayouts: async (query) => {
      seen.push(query.categories ?? null);
      return searchLayouts({ ...query, k: 8, include_slots: true });
    },
    getLayout: async (id, theme, mode) => (await getLayout(id, theme, mode)).layout,
  });
  assert.deepEqual(seen[0], ["theory"], "decision hint 不应把机理内容绑死在 decision 版面");
});

test("RPA-5: 计划阶段对语义冲突给出显式 warning", async () => {
  const plan = await createDeckPlan({
    presentation_type: "group_meeting",
    slide_briefs: [{
      slide_id: "P10",
      title: "保持时间的 Arrhenius 外推",
      goal: "说明保持时间随温度变化的机理并外推室温寿命",
      narrative_job: "给出理论依据",
      text_chars: 120,
      title_chars: 10,
      category_hint: "decision",
    }],
  });
  const joined = (plan.warnings ?? []).join("\n");
  assert.match(joined, /理论 \/ 机制推导/);
  assert.match(joined, /decision/);
  assert.match(joined, /layout-override/);
});
