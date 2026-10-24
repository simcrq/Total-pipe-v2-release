/** Semantic body composition. This module neither imports a compiler nor assigns coordinates. */
export const SUBLAYOUT_VERSION = "1.0";
export const SUBLAYOUTS = Object.freeze([
  { id: "three-panels", containers: ["columns", "panel", "stack"], groups: [3, 3], tags: ["comparison", "three", "科研三栏"] },
  { id: "two-panels", containers: ["columns", "panel", "stack"], groups: [2, 2], tags: ["comparison", "two", "科研双栏"] },
  { id: "four-panels", containers: ["columns", "panel", "stack"], groups: [4, 4], tags: ["comparison", "four", "四栏"] },
  { id: "vertical-stack", containers: ["stack", "panel"], groups: [1, 6], tags: ["derivation", "sequence", "推导", "整行图形"] },
  { id: "image-grid", containers: ["panel", "image_grid"], groups: [1, 1], tags: ["figures", "evidence", "图片网格"] },
]);

const identifier = { type: "string", pattern: "^[A-Za-z0-9_-]{1,64}$" };
const reference = {
  oneOf: [
    { type: "object", additionalProperties: false, required: ["kind", "ref"], properties: {
      kind: { enum: ["block", "graphic", "table"] }, ref: { type: "string", minLength: 1 } } },
    { type: "object", additionalProperties: false, required: ["kind", "ref"], properties: {
      kind: { const: "figure" }, ref: { type: "integer", minimum: 0 } } },
  ],
};
const consumer = { type: "object", description: "Fresh totalpipe_capabilities result, or its layout_tree object. Required: never assume capabilities of a different installed version." };
export const SEARCH_SUBLAYOUT_SCHEMA = {
  type: "object", additionalProperties: false, required: ["consumer_capabilities"],
  properties: { query: { type: "string" }, group_count: { type: "integer", minimum: 1, maximum: 6 },
    consumer_capabilities: consumer, k: { type: "integer", minimum: 1, maximum: 5 } },
};
export const COMPOSE_SUBLAYOUT_SCHEMA = {
  type: "object", additionalProperties: false,
  required: ["sublayout_id", "groups", "content_refs", "consumer_capabilities"],
  properties: {
    sublayout_id: { enum: SUBLAYOUTS.map(x => x.id) },
    layout_id: { type: "string", minLength: 1, description: "Existing whole-slide template ID, retained as provenance; it does not assign a body rectangle." },
    consumer_capabilities: consumer,
    weights: { type: "array", minItems: 1, maxItems: 6, items: { type: "number", minimum: .1, maximum: 10 } },
    groups: { type: "array", minItems: 1, maxItems: 6, items: {
      type: "object", additionalProperties: false, required: ["id", "title", "items"], properties: {
        id: identifier, title: { type: "string", minLength: 1, pattern: "\\S" },
        arrangement: { enum: ["stack", "image_grid"] }, columns: { type: "integer", minimum: 1, maximum: 4 },
        requirements: { type: 'object', additionalProperties: false, properties: {
          min_width_px: { type: 'number', exclusiveMinimum: 0 }, min_height_px: { type: 'number', exclusiveMinimum: 0 } },
          description: 'Optional measured component requirements, not page coordinates.' },
        items: { type: "array", minItems: 1, maxItems: 12, items: reference } } } },
    content_refs: { type: "object", additionalProperties: false,
      required: ["blocks", "figure_count", "graphics"], properties: {
        blocks: { type: "array", maxItems: 64, items: { type: "object", additionalProperties: false,
          required: ["id", "component"], properties: { id: { type: "string", minLength: 1 },
            component: { type: "string", minLength: 1 }, anchor: { type: "string", minLength: 1 } } } },
        figure_count: { type: "integer", minimum: 0, maximum: 12 },
        tables: { type: 'array', maxItems: 4, items: { type: 'object', additionalProperties: false,
          required: ['id'], properties: { id: identifier, has_formulas: { type: 'boolean' } } } },
        graphics: { type: "array", maxItems: 8, items: { type: "object", additionalProperties: false,
          required: ["id", "type"], properties: { id: identifier,
            type: { enum: ["process", "dag", "mechanism", "architecture", "funnel", "path", "composite"] } } } },
      } },
  },
};

export function sublayoutCapabilities() {
  return { version: SUBLAYOUT_VERSION, coordinate_output: false,
    layout_tree_versions: ["1.0", "1.1"], automatic_selection: true, catalog: SUBLAYOUTS.map(x => x.id),
    feedback_owner: "deck_compiler", fallback: "existing_whole_slide_layouts" };
}

function capabilityTree(input) {
  const value = input?.layout_tree ?? input;
  return ['1.0', '1.1'].includes(value?.version) && value?.contract === "totalpipe.layout-tree" ? value : null;
}

function supports(tree, containers, native = [], graphicTypes = []) {
  return tree?.regions?.includes("body") && containers.every(c => tree.containers?.includes(c))
    && ["block", "figure", "graphic"].every(c => tree.leaves?.includes(c))
    && native.every(c => tree.native?.includes(c))
    && graphicTypes.every(c => tree.graphic_types?.includes(c));
}

export function searchSublayouts(input = {}) {
  const validation = validateJsonSchema(SEARCH_SUBLAYOUT_SCHEMA, input);
  if (!validation.valid) return failure("SUBLAYOUT_INPUT_INVALID", JSON.stringify(validation.errors));
  const tree = capabilityTree(input.consumer_capabilities);
  const count = input.group_count;
  const query = String(input.query ?? "").trim().toLowerCase();
  const candidates = SUBLAYOUTS.filter(s => supports(tree, s.containers)
    && (!s.containers.includes('columns') || s.groups[0] <= (tree.limits?.max_columns ?? 0))
    && (count === undefined || count >= s.groups[0] && count <= s.groups[1]))
    .map(s => ({ ...s, score: s.tags.some(t => query.includes(t.toLowerCase())) ? 1 : .5,
      geometry_status: "requires_compiler_measurement" }))
    .sort((a, b) => b.score-a.score || a.id.localeCompare(b.id)).slice(0, input.k ?? 5);
  return { version: SUBLAYOUT_VERSION, status: candidates.length ? "candidates" : "legacy_fallback_required",
    candidates, fallback: candidates.length ? null : "Use the existing whole-slide layout search; do not emit an unsupported tree." };
}

function failure(code, message, details = {}) {
  return { version: SUBLAYOUT_VERSION, status: "needs_replan", geometry_status: "not_measured",
    errors: [{ code, message, ...details }], suggested_actions: ["revise_structure", "use_legacy_layout", "split_slide"] };
}

export function composeSublayout(input = {}) {
  // The same schema is used by MCP and direct callers; unknown geometry fields must not slip
  // through when this function is imported without going through the transport.
  const validation = validateCompose(input);
  if (validation) return failure("SUBLAYOUT_INPUT_INVALID", validation);
  const spec = SUBLAYOUTS.find(x => x.id === input.sublayout_id);
  const groups = input.groups;
  if (groups.length < spec.groups[0] || groups.length > spec.groups[1]) {
    return failure("SUBLAYOUT_GROUP_COUNT", `${spec.id} requires ${spec.groups.join("-")} groups.`);
  }
  if (input.weights && input.weights.length !== groups.length) return failure("SUBLAYOUT_WEIGHTS_INVALID", "Weights must match groups.");
  const registry = input.content_refs;
  const tree = capabilityTree(input.consumer_capabilities);
  const native = [];
  const tables = registry.tables ?? [];
  if (tables.length) native.push('native_table');
  if (tables.some(t => t.has_formulas)) native.push('native_equation');
  if (registry.blocks.some(b => b.component === "formula")) native.push("native_equation");
  if (registry.graphics.some(g => g.type === "path")) native.push("native_bezier");
  if (registry.graphics.some(g => ["process", "dag"].includes(g.type))) native.push("native_flowchart");
  const containers = [...spec.containers, ...groups.filter(g => g.arrangement === "image_grid").map(() => "image_grid")];
  if (!supports(tree, containers, native, registry.graphics.map(g => g.type))) {
    return failure("SUBLAYOUT_CAPABILITY_UNAVAILABLE", "Consumer cannot compile this structure. Retain legacy layout planning.");
  }
  if (tables.length && (tree.version !== '1.1' || !tree.leaves?.includes('table') || tables.length > (tree.limits?.max_tables ?? 0))) {
    return failure('SUBLAYOUT_CAPABILITY_UNAVAILABLE', 'Native tables require the declared 1.1 table contract.');
  }
  if ((spec.containers.includes('columns') && groups.length > (tree.limits?.max_columns ?? 0))
      || registry.graphics.length > (tree.limits?.max_graphics ?? 0)
      || groups.some(g => (g.arrangement === 'image_grid' || spec.id === 'image-grid') &&
        (g.items.length > (tree.limits?.max_grid_figures ?? 0) || (g.columns ?? 2) > (tree.limits?.max_columns ?? 0)))) {
    return failure('SUBLAYOUT_CAPABILITY_UNAVAILABLE', 'Requested columns, grid count or graphics exceed consumer limits.');
  }
  const expected = [...registry.blocks.map(b => `block:${b.id}`),
    ...Array.from({ length: registry.figure_count }, (_, i) => `figure:${i}`),
    ...registry.graphics.map(g => `graphic:${g.id}`)];
  expected.push(...tables.map(t => `table:${t.id}`));
  const actual = groups.flatMap(g => g.items.map(i => `${i.kind}:${i.ref}`));
  if (new Set(expected).size !== expected.length || expected.length !== actual.length
      || new Set(actual).size !== actual.length || expected.some(k => !actual.includes(k))) {
    return failure("SUBLAYOUT_CONTENT_COVERAGE", "Every canonical block, figure, graphic and table must occur exactly once.");
  }
  for (const block of registry.blocks.filter(b => b.anchor)) {
    const group = groups.find(g => g.items.some(i => i.kind === "block" && i.ref === block.id));
    const pos = id => group.items.findIndex(i => i.kind === "block" && i.ref === id);
    const anchor = registry.blocks.find(b => b.id === block.anchor);
    if (block.component !== "formula" || !anchor || anchor.component === "formula"
        || pos(block.anchor) < 0 || pos(block.anchor) >= pos(block.id)) {
      return failure("FORMULA_ANCHOR_GROUP_SPLIT", "An equation and its preceding explanation must stay in one vertical group.");
    }
  }
  const panel = (group, index) => {
    const children = group.items.map((item, i) => ({ id: `leaf-${index+1}-${i+1}`, type: item.kind, ref: item.ref }));
    const grid = group.arrangement === "image_grid" || spec.id === "image-grid";
    if (grid && children.some(c => c.type !== "figure")) throw new TypeError("Image grids accept figures only.");
    const body = grid ? { id: `group-${index+1}`, type: "image_grid", columns: group.columns ?? 2, gap: "compact", children }
      : { id: `group-${index+1}`, type: "stack", gap: "compact", children };
    return { id: group.id, type: "panel", title: group.title, gap: "compact", body };
  };
  let panels;
  try { panels = groups.map(panel); } catch (error) { return failure("SUBLAYOUT_GRID_INVALID", error.message); }
  const root = spec.id === "image-grid" ? panels[0] : {
    id: "body-layout", type: spec.id === "vertical-stack" ? "stack" : "columns", gap: "standard",
    ...(input.weights ? { weights: [...input.weights] } : {}), children: panels };
  const nodes = [];
  function walk(node, depth) {
    nodes.push({ id: node.id, depth });
    if (node.body) walk(node.body, depth+1);
    for (const child of node.children ?? []) walk(child, depth+1);
  }
  walk(root, 1);
  if (new Set(nodes.map(n => n.id)).size !== nodes.length
      || nodes.length > Math.min(64, tree.limits?.max_nodes ?? 0)
      || nodes.some(n => n.depth > Math.min(6, tree.limits?.max_depth ?? 0))) {
    return failure("SUBLAYOUT_TREE_LIMIT", "Node IDs, count or depth violate consumer limits.");
  }
  return { version: SUBLAYOUT_VERSION, status: "structure_planned", geometry_status: "requires_compiler_measurement",
    ...(input.layout_id ? { layout_id: input.layout_id } : {}),
    composition_patch: { layout_tree: { version: tables.length ? '1.1' : '1.0', regions: { body: root } } },
    required_native_capabilities: native, next_action: "merge_into_canonical_composition_then_compile",
    feedback_file: "layout_feedback.json", content_mutated: false };
}

// Importing the small schema validator keeps the RPA service independently runnable.
import { validateJsonSchema } from "./schema-validator.mjs";
function validateCompose(input) {
  const result = validateJsonSchema(COMPOSE_SUBLAYOUT_SCHEMA, input);
  return result.valid ? null : JSON.stringify(result.errors);
}
