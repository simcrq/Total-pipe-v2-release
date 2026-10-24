/** Finite semantic selection; measured fit and all final geometry belong to Deck Compiler. */
import { COMPOSE_SUBLAYOUT_SCHEMA, SUBLAYOUTS, composeSublayout } from './sublayouts.mjs';
import { validateJsonSchema } from './schema-validator.mjs';

const properties = { ...COMPOSE_SUBLAYOUT_SCHEMA.properties };
delete properties.sublayout_id;
delete properties.weights;
export const PLAN_SUBLAYOUT_SCHEMA = {
  type: 'object', additionalProperties: false,
  required: ['groups', 'content_refs', 'consumer_capabilities'], properties: {
    ...properties, slide_id: { type: 'string', minLength: 1 }, query: { type: 'string' },
    body_size_px: { type: 'array', minItems: 2, maxItems: 2, items: { type: 'number', exclusiveMinimum: 0 },
      description: 'Measured body dimensions only; no position or final geometry.' },
    ir_sha256: { type: 'string', pattern: '^[0-9a-f]{64}$' },
    compiler_feedback: { type: 'object', description: 'The current SHA-bound layout_feedback.json; stale feedback is rejected.' },
    rejected_sublayout_ids: { type: 'array', maxItems: 5, uniqueItems: true, items: { enum: SUBLAYOUTS.map(s => s.id) } },
  },
};
export const BODY_COMPOSITIONS_SCHEMA = { type: 'array', maxItems: 40, items: {
  type: 'object', additionalProperties: false, required: ['slide_id', 'request'],
  properties: { slide_id: { type: 'string', minLength: 1 }, request: PLAN_SUBLAYOUT_SCHEMA },
} };

const failed = (code, message) => ({ status: 'needs_replan', geometry_status: 'not_measured',
  errors: [{ code, message }], suggested_actions: ['revise_structure', 'use_legacy_layout', 'split_slide'] });

export function planSublayout(input = {}) {
  const validation = validateJsonSchema(PLAN_SUBLAYOUT_SCHEMA, input);
  if (!validation.valid) return failed('SUBLAYOUT_INPUT_INVALID', JSON.stringify(validation.errors));
  let feedbackErrors = [];
  if (input.compiler_feedback) {
    const feedback = input.compiler_feedback;
    if (!input.ir_sha256 || feedback.ir_sha256 !== input.ir_sha256 || feedback.version !== '1.0') {
      return failed('SUBLAYOUT_FEEDBACK_STALE', 'Feedback must bind to the current complete Deck IR SHA-256.');
    }
    const slide = input.slide_id && Array.isArray(feedback.slides) && feedback.slides.find(s => s?.slide_id === input.slide_id);
    if (!slide || !Array.isArray(slide.errors) || slide.errors.some(e => !e || typeof e.code !== 'string' || !['FAIL', 'REVIEW'].includes(e.severity))) {
      return failed('SUBLAYOUT_FEEDBACK_INVALID', 'Supply the exact slide_id and structured errors from compiler feedback.');
    }
    feedbackErrors = slide.errors.filter(e => e.severity === 'FAIL');
  }
  const groups = input.groups;
  const rejected = new Set(input.rejected_sublayout_ids ?? []);
  const preferStack = /derivation|sequence|推导|流程/i.test(input.query ?? '')
    || feedbackErrors.some(e => ['INSUFFICIENT_DRAWING_SPACE', 'INSUFFICIENT_FORMULA_SPACE', 'INSUFFICIENT_TABLE_SPACE', 'INSUFFICIENT_FIGURE_SPACE'].includes(e.code));
  const onlyFigures = groups.length === 1 && groups[0].items.every(i => i.kind === 'figure');
  const candidates = SUBLAYOUTS.filter(s => groups.length >= s.groups[0] && groups.length <= s.groups[1] && !rejected.has(s.id))
    .map(s => ({ spec: s, score: (s.id === 'image-grid' && onlyFigures ? 5 : 0)
      + (s.id === 'vertical-stack' ? preferStack ? 4 : 1 : s.containers.includes('columns') ? 3 : 0) }))
    .sort((a, b) => b.score-a.score || a.spec.id.localeCompare(b.spec.id));
  const attempts = [];
  for (const { spec } of candidates) {
    const horizontal = spec.containers.includes('columns');
    let weights;
    if (input.body_size_px) {
      const [width, height] = input.body_size_px;
      const minWidths = groups.map(g => g.requirements?.min_width_px ?? 0);
      const minHeights = groups.map(g => g.requirements?.min_height_px ?? 0);
      if (horizontal) {
        const usable = width-24*(groups.length-1);
        if (usable <= 0 || minWidths.reduce((a, b) => a+b, 0) > usable || Math.max(...minHeights) > height) {
          attempts.push({ sublayout_id: spec.id, code: 'MEASURED_REQUIREMENTS_EXCEED_BODY' }); continue;
        }
        const extra = (usable-minWidths.reduce((a, b) => a+b, 0))/groups.length;
        const widths = minWidths.map(w => w+extra);
        const minimum = Math.min(...widths);
        weights = widths.map(w => w/minimum);
        if (weights.some(w => !Number.isFinite(w) || w > 10)) {
          attempts.push({ sublayout_id: spec.id, code: 'RELATIVE_WEIGHTS_EXCEED_CONTRACT' }); continue;
        }
      } else if (Math.max(...minWidths) > width || minHeights.reduce((a, b) => a+b, 0)+24*(groups.length-1) > height) {
        attempts.push({ sublayout_id: spec.id, code: 'MEASURED_REQUIREMENTS_EXCEED_BODY' }); continue;
      }
    }
    const proposal = composeSublayout({ sublayout_id: spec.id, groups, content_refs: input.content_refs,
      consumer_capabilities: input.consumer_capabilities,
      ...(input.layout_id ? { layout_id: input.layout_id } : {}), ...(weights ? { weights } : {}) });
    attempts.push({ sublayout_id: spec.id, status: proposal.status, errors: proposal.errors ?? [] });
    if (proposal.status === 'structure_planned') return { ...proposal, selected_sublayout_id: spec.id,
      selection: 'automatic_bounded', attempts, source_ir_sha256: input.ir_sha256 ?? null,
      used_compiler_feedback: Boolean(input.compiler_feedback), automatic_compiler_calls: 0 };
  }
  return { ...failed('SUBLAYOUT_NO_LEGAL_CANDIDATE', 'No supported structure can preserve every group. Replan or split without rewriting scientific content.'), attempts };
}

export function attachBodyCompositions(requests, slides) {
  if (requests === undefined) return null;
  const validation = validateJsonSchema(BODY_COMPOSITIONS_SCHEMA, requests);
  if (!validation.valid) return { status: 'needs_replan', errors: [{ code: 'SUBLAYOUT_INPUT_INVALID', message: JSON.stringify(validation.errors) }] };
  const seen = new Set(), errors = [], plans = [];
  for (const entry of requests) {
    const slide = slides.find(s => s.slide_id === entry.slide_id);
    if (seen.has(entry.slide_id) || !slide || entry.request.slide_id && entry.request.slide_id !== entry.slide_id) {
      errors.push({ code: 'SUBLAYOUT_SLIDE_INVALID', slide_id: entry.slide_id }); continue;
    }
    seen.add(entry.slide_id);
    const plan = planSublayout({ ...entry.request, slide_id: entry.slide_id, layout_id: slide.layout_id });
    slide.body_layout = plan;
    plans.push({ slide_id: entry.slide_id, status: plan.status, geometry_status: plan.geometry_status });
    if (plan.status !== 'structure_planned') errors.push({ code: 'SUBLAYOUT_REPLAN_REQUIRED', slide_id: entry.slide_id, errors: plan.errors });
  }
  return { status: errors.length ? 'needs_replan' : 'structure_planned', plans, errors,
    geometry_status: 'requires_compiler_measurement' };
}
