import { normalizePresentationIntent } from '../../design-intelligence/presentation-intent.mjs';
import { createViolation } from '../../content-model.mjs';

export function evaluatePresentationIntent(telemetry, raw) {
  const intent = normalizePresentationIntent(raw);
  if (!intent || !intent.required_on_screen.length) return { checks: {}, violations: [] };
  const normalize = s => s.normalize('NFC').replace(/\s+/gu, '');
  const elements = telemetry.elements.filter(e => e.type === 'text' && e.quality_role === 'content');
  const unavailable = telemetry.unavailable.some(e => e.field === 'elements')
    || elements.some(e => typeof e.text?.content !== 'string');
  const content = elements.map(e => normalize(e.text?.content ?? ''));
  const missing = intent.required_on_screen.filter(s => !content.some(t => t.includes(normalize(s))));
  // A raster-only or incomplete text inventory cannot prove a phrase is absent.
  const uncertain = unavailable || telemetry.elements.some(e => e.type === 'image');
  const status = !missing.length ? 'pass' : uncertain ? 'not_evaluable' : 'fail';
  const violations = status !== 'fail' ? [] : missing.map(s => createViolation({
    code: 'REQUIRED_ON_SCREEN_MISSING', field: 'presentation_intent.required_on_screen',
    actual: s, capacity: 'literal phrase in rendered content text', severity: 'error',
    recoverable: true, recommended_action: 'restore_required_qualifier',
    message: `Required on-screen phrase is absent: ${s}`,
  }));
  return { checks: { presentation_intent: {
    rule_id: 'presentation_intent', metric: 'missing_required_phrase_count', status,
    actual: missing.length, threshold: { warning: null, fail: 0, triggered: missing.length ? 0 : null },
    code: status === 'fail' ? 'REQUIRED_ON_SCREEN_MISSING' : null,
    reason: uncertain && missing.length ? 'text_inventory_requires_visual_review' : 'literal_text_presence_only',
    recommended_action: status === 'pass' ? 'none' : uncertain ? 'complete_manual_visual_review' : 'restore_required_qualifier',
    evidence: { missing, scope: 'text_presence_not_visibility_or_semantic_equivalence' }, disabled: false, blocking: true,
  } }, violations };
}
