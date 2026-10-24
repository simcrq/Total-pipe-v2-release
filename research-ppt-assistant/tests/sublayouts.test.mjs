import assert from "node:assert/strict";
import test from "node:test";
import { composeSublayout, searchSublayouts } from "../server/sublayouts.mjs";
import { normalizeContentModel } from "../server/content-model.mjs";

function request() {
  return { sublayout_id: "three-panels", layout_id: "RM-TRIPLE_FIGURE-01",
    consumer_capabilities: { layout_tree: { contract: "totalpipe.layout-tree", version: "1.0", regions: ["body"],
      containers: ["columns", "stack", "panel", "image_grid"], leaves: ["block", "figure", "graphic"],
      native: ["native_equation", "native_flowchart", "native_bezier"], graphic_types: ["path"],
      limits: { max_depth: 6, max_nodes: 64, max_columns: 4, max_graphics: 8, max_grid_figures: 12 } } },
    content_refs: { blocks: [{ id: "context", component: "body" }, { id: "equation", component: "formula", anchor: "context" }],
      figure_count: 1, graphics: [{ id: "curve", type: "path" }] },
    groups: [
      { id: "math", title: "Cholesky 分解与完整说明", items: [{ kind: "block", ref: "context" }, { kind: "block", ref: "equation" }] },
      { id: "evidence", title: "原始科研证据", items: [{ kind: "figure", ref: 0 }] },
      { id: "geometry", title: "贝塞尔曲线", items: [{ kind: "graphic", ref: "curve" }] },
    ] };
}

test("sublayout retrieval filters capabilities and group count", () => {
  const input = request();
  const result = searchSublayouts({ consumer_capabilities: input.consumer_capabilities, group_count: 3, query: "科研三栏" });
  assert.equal(result.candidates[0].id, "three-panels");
  assert.equal(searchSublayouts({ consumer_capabilities: {} }).status, "legacy_fallback_required");
  input.consumer_capabilities.layout_tree.limits.max_columns = 2;
  assert.ok(searchSublayouts({ consumer_capabilities: input.consumer_capabilities, group_count: 3 }).candidates.every(c => c.id !== 'three-panels'));
});

test("composition is deterministic, source-preserving and coordinate-free", () => {
  const input = request(), before = structuredClone(input);
  const result = composeSublayout(input);
  assert.equal(result.status, "structure_planned");
  assert.equal(result.geometry_status, "requires_compiler_measurement");
  assert.equal(result.layout_id, input.layout_id);
  assert.deepEqual(input, before);
  assert.deepEqual(result, composeSublayout(input));
  const tree = result.composition_patch.layout_tree;
  assert.equal(tree.regions.body.children[0].title, input.groups[0].title);
  assert.ok(!JSON.stringify(tree).includes('"bbox"'));
});

test("current compiler 1.2 capabilities retain existing sublayout and table planning", () => {
  const input = request();
  input.consumer_capabilities.layout_tree.version = '1.2';
  input.consumer_capabilities.layout_tree.supported_versions = ['1.0', '1.1', '1.2'];
  assert.equal(composeSublayout(input).status, 'structure_planned');
  assert.equal(searchSublayouts({ consumer_capabilities: input.consumer_capabilities, group_count: 3 }).candidates[0].id, 'three-panels');
  input.content_refs.tables = [{ id: 'results', has_formulas: false }];
  input.groups[0].items.push({ kind: 'table', ref: 'results' });
  input.consumer_capabilities.layout_tree.leaves.push('table');
  input.consumer_capabilities.layout_tree.native.push('native_table');
  input.consumer_capabilities.layout_tree.limits.max_tables = 4;
  const result = composeSublayout(input);
  assert.equal(result.status, 'structure_planned');
  assert.equal(result.composition_patch.layout_tree.version, '1.1');
});

test("missing, duplicate and unknown references cannot silently disappear", () => {
  for (const mutation of ["missing", "duplicate", "unknown"]) {
    const input = request();
    if (mutation === "missing") input.groups[0].items.pop();
    if (mutation === "duplicate") input.groups[0].items.push({ ...input.groups[0].items[0] });
    if (mutation === "unknown") input.groups[0].items[1].ref = "unknown";
    assert.equal(composeSublayout(input).errors[0].code, "SUBLAYOUT_CONTENT_COVERAGE");
  }
});

test("native capability, ID and shape limits cause replanning", () => {
  const unsupported = request();
  unsupported.consumer_capabilities.layout_tree.native = [];
  assert.equal(composeSublayout(unsupported).errors[0].code, "SUBLAYOUT_CAPABILITY_UNAVAILABLE");
  const geometry = request(); geometry.groups[0].bbox = [0, 0, 1, 1];
  assert.equal(composeSublayout(geometry).errors[0].code, "SUBLAYOUT_INPUT_INVALID");
  const duplicate = request(); duplicate.groups[1].id = duplicate.groups[0].id;
  assert.equal(composeSublayout(duplicate).errors[0].code, "SUBLAYOUT_TREE_LIMIT");
});

test("equation anchor stays before the equation in the same group", () => {
  const input = request(); input.groups[0].items.reverse();
  assert.equal(composeSublayout(input).errors[0].code, "FORMULA_ANCHOR_GROUP_SPLIT");
});

test("image grids reject non-images and retain the full panel title", () => {
  const bad = request(); bad.groups[0].arrangement = "image_grid";
  assert.equal(composeSublayout(bad).errors[0].code, "SUBLAYOUT_GRID_INVALID");
  const input = request(); input.sublayout_id = "image-grid";
  input.groups = [input.groups[1]];
  input.content_refs.blocks = []; input.content_refs.graphics = [];
  const result = composeSublayout(input);
  assert.equal(result.status, "structure_planned");
  assert.equal(result.composition_patch.layout_tree.regions.body.title, input.groups[0].title);
});

test("normalization retains image dimensions, identity and conservative crop permission", () => {
  const visual = { visual_id: "image-1", visual_type: "simple_plot", source_width_px: 1600, source_height_px: 800,
    source_asset_id: "images/figure-1.png", image_kind: "raster", image_format: "png", crop_allowed: false };
  const result = normalizeContentModel({ slide_briefs: [{ title: "Full figure", goal: "Retain source identity", visuals: [visual] }] });
  assert.equal(result.status, "valid");
  const normalized = result.slide_briefs[0].visuals[0];
  for (const key of Object.keys(visual)) assert.equal(normalized[key], visual[key], key);
});
