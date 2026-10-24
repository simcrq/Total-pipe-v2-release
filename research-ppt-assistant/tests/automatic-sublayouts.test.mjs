import assert from 'node:assert/strict';
import test from 'node:test';
import { spawnSync } from 'node:child_process';
import { planSublayout, attachBodyCompositions } from '../server/automatic-sublayouts.mjs';
import { createDeckPlan, validateDeckPlan } from '../server/core.mjs';
import { formatStructuredContent } from '../server/response-format.mjs';

const request = () => ({
  consumer_capabilities: { layout_tree: { contract: 'totalpipe.layout-tree', version: '1.1', regions: ['body'],
    containers: ['columns', 'stack', 'panel', 'image_grid'], leaves: ['block', 'figure', 'graphic', 'table'],
    native: ['native_equation', 'native_flowchart', 'native_bezier', 'native_table'], graphic_types: ['path'],
    limits: { max_depth: 6, max_nodes: 64, max_columns: 4, max_graphics: 8, max_grid_figures: 12, max_tables: 4 } } },
  content_refs: { blocks: [{ id: 'explanation', component: 'body' }, { id: 'formula', component: 'formula', anchor: 'explanation' }],
    figure_count: 1, graphics: [{ id: 'path', type: 'path' }] },
  groups: [
    { id: 'math-panel', title: 'Cholesky 分解与完整科学术语', items: [{ kind: 'block', ref: 'explanation' }, { kind: 'block', ref: 'formula' }] },
    { id: 'figure-panel', title: '原始科研证据', items: [{ kind: 'figure', ref: 0 }] },
    { id: 'path-panel', title: '曲线与边界条件', items: [{ kind: 'graphic', ref: 'path' }] },
  ],
});

test('automatic selection keeps every group and formula anchor, emits no geometry', () => {
  const input = request(), before = structuredClone(input);
  const result = planSublayout(input);
  assert.equal(result.status, 'structure_planned');
  assert.equal(result.selected_sublayout_id, 'three-panels');
  assert.equal(result.geometry_status, 'requires_compiler_measurement');
  assert.equal(result.automatic_compiler_calls, 0);
  assert.deepEqual(input, before);
  assert.deepEqual(planSublayout(input), result);
  const tree = result.composition_patch.layout_tree;
  assert.equal(tree.version, '1.0');
  assert.equal(tree.regions.body.children[0].title, input.groups[0].title);
  assert.deepEqual(tree.regions.body.children[0].body.children.map(c => c.ref), ['explanation', 'formula']);
  assert.doesNotMatch(JSON.stringify(tree), /"(?:bbox|x|y|width|height)":/);
});

test('measured group demands yield relative weights or reject impossible structures', () => {
  const input = request(); input.body_size_px = [1168, 460];
  input.groups.forEach((g, i) => { g.requirements = { min_width_px: [500, 220, 180][i], min_height_px: 150 }; });
  const result = planSublayout(input);
  assert.equal(result.selected_sublayout_id, 'three-panels');
  assert.ok(result.composition_patch.layout_tree.regions.body.weights[0] > result.composition_patch.layout_tree.regions.body.weights[1]);
  input.groups[0].requirements.min_width_px = 1200;
  const failed = planSublayout(input);
  assert.equal(failed.status, 'needs_replan');
  assert.equal(failed.errors[0].code, 'SUBLAYOUT_NO_LEGAL_CANDIDATE');
  assert.ok(failed.attempts.every(a => a.code === 'MEASURED_REQUIREMENTS_EXCEED_BODY'));
});

test('fresh compiler failures select a wider stack; stale feedback cannot steer a plan', () => {
  const input = request(); input.slide_id = 'slide-1'; input.ir_sha256 = 'a'.repeat(64);
  input.compiler_feedback = { version: '1.0', ir_sha256: input.ir_sha256, slides: [{ slide_id: 'slide-1',
    errors: [{ code: 'INSUFFICIENT_DRAWING_SPACE', severity: 'FAIL', component: 'body.children[1]' }] }] };
  const result = planSublayout(input);
  assert.equal(result.selected_sublayout_id, 'vertical-stack');
  assert.equal(result.used_compiler_feedback, true);
  input.compiler_feedback.ir_sha256 = 'b'.repeat(64);
  assert.equal(planSublayout(input).errors[0].code, 'SUBLAYOUT_FEEDBACK_STALE');
  input.compiler_feedback.ir_sha256 = input.ir_sha256; input.slide_id = 'missing';
  assert.equal(planSublayout(input).errors[0].code, 'SUBLAYOUT_FEEDBACK_INVALID');
});

test('failed structures are excluded and content coverage failures never discard content', () => {
  const input = request(); input.rejected_sublayout_ids = ['three-panels'];
  assert.equal(planSublayout(input).selected_sublayout_id, 'vertical-stack');
  input.rejected_sublayout_ids.push('vertical-stack');
  assert.equal(planSublayout(input).status, 'needs_replan');
  const missing = request(); missing.groups[0].items.pop();
  const failed = planSublayout(missing);
  assert.equal(failed.status, 'needs_replan');
  assert.ok(failed.attempts.every(a => a.errors[0].code === 'SUBLAYOUT_CONTENT_COVERAGE'));
  const coords = request(); coords.groups[0].requirements = { x: 0 };
  assert.equal(planSublayout(coords).errors[0].code, 'SUBLAYOUT_INPUT_INVALID');
});

test('native tables negotiate 1.1 and old consumers receive explicit fallback', () => {
  const input = request(); input.content_refs = { blocks: [], figure_count: 0, graphics: [], tables: [{ id: 'data', has_formulas: true }] };
  input.groups = [{ id: 'table-panel', title: '完整数据及单位', items: [{ kind: 'table', ref: 'data' }] }];
  assert.equal(planSublayout(input).composition_patch.layout_tree.version, '1.1');
  input.consumer_capabilities.layout_tree.version = '1.0';
  const failed = planSublayout(input);
  assert.equal(failed.status, 'needs_replan');
  assert.equal(failed.attempts[0].errors[0].code, 'SUBLAYOUT_CAPABILITY_UNAVAILABLE');
});

test('inline text and table cells require explicit consumer support without changing legacy composition', () => {
  const input = request(); input.content_refs.blocks[0].inline_math = true;
  assert.equal(planSublayout(input).status, 'needs_replan');
  input.consumer_capabilities.layout_tree.native.push('native_inline_equation');
  const planned = planSublayout(input);
  assert.equal(planned.status, 'structure_planned');
  assert.ok(planned.required_native_capabilities.includes('native_inline_equation'));
  input.content_refs = { blocks: [], figure_count: 0, graphics: [], tables: [{ id: 'mixed', has_inline_math: true }] };
  input.groups = [{ id: 'mixed-panel', title: '完整说明与公式', items: [{ kind: 'table', ref: 'mixed' }] }];
  assert.equal(planSublayout(input).status, 'structure_planned');
  input.consumer_capabilities.layout_tree.native = input.consumer_capabilities.layout_tree.native.filter(c => c !== 'native_inline_equation');
  assert.equal(planSublayout(input).status, 'needs_replan');
});

test('image-only groups use grids and sequence semantics prefer stacks', () => {
  const input = request(); input.query = 'Derivation';
  assert.equal(planSublayout(input).selected_sublayout_id, 'vertical-stack');
  input.content_refs = { blocks: [], figure_count: 2, graphics: [] };
  input.groups = [{ id: 'images', title: '原始多图证据', items: [{ kind: 'figure', ref: 0 }, { kind: 'figure', ref: 1 }] }];
  assert.equal(planSublayout(input).selected_sublayout_id, 'image-grid');
});

test('createDeckPlan attaches automatic body plans while preserving evidence and design gates', async () => {
  const input = { presentation_type: 'custom', slide_briefs: [{ slide_id: 'SLIDE0001', title: '科研复合内容', category_hint: 'summary' }],
    body_compositions: [{ slide_id: 'SLIDE0001', request: request() }] };
  const plan = await createDeckPlan(input);
  assert.equal(plan.body_composition.status, 'structure_planned');
  assert.equal(plan.slides[0].body_layout.layout_id, plan.slides[0].layout_id);
  assert.equal(plan.slides[0].body_layout.status, 'structure_planned');
  assert.ok(plan.slides[0].design_context.design_ir);
  const compact = formatStructuredContent('create_deck_plan', plan, 'compact');
  assert.deepEqual(compact.slides[0].body_layout, plan.slides[0].body_layout);
  assert.deepEqual(compact.body_composition, plan.body_composition);
  input.body_compositions[0].slide_id = 'nonexistent';
  const failed = await createDeckPlan(input);
  assert.equal(failed.status, 'needs_replan');
  assert.equal(failed.body_composition.errors[0].code, 'SUBLAYOUT_SLIDE_INVALID');
});

test('duplicate and invalid slide requests report replanning, not silent omissions', () => {
  const entry = { slide_id: 'slide-1', request: request() };
  assert.equal(attachBodyCompositions([entry, entry], [{ slide_id: 'slide-1', layout_id: 'legacy' }]).status, 'needs_replan');
  assert.equal(attachBodyCompositions([{ ...entry, request: { ...request(), slide_id: 'other' } }], [{ slide_id: 'slide-1' }]).status, 'needs_replan');
});

test('deck validation cannot turn a failed body composition into a valid plan', async () => {
  const plan = await createDeckPlan({ presentation_type: 'custom', slide_briefs: [{ title: '结论与边界', category_hint: 'summary' }] });
  plan.slides[0].body_layout = { status: 'needs_replan', errors: [{ code: 'SUBLAYOUT_NO_LEGAL_CANDIDATE' }] };
  const checked = await validateDeckPlan({ slides: plan.slides, content_model: plan.content_model });
  assert.ok(checked.deck_issues.some(i => i.code === 'BODY_COMPOSITION_REPLAN_REQUIRED'));
  assert.equal(checked.status, 'invalid');
});

test('CLI exposes the same deterministic planner', () => {
  const cli = spawnSync(process.execPath, ['server/cli.mjs', 'plan-sublayout', '--json', JSON.stringify(request())],
    { cwd: new URL('..', import.meta.url), encoding: 'utf8' });
  assert.equal(cli.status, 0, cli.stderr);
  assert.equal(JSON.parse(cli.stdout).selected_sublayout_id, 'three-panels');
});
