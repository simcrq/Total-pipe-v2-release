import { evaluateLegacyReadability } from './legacy-readability.mjs';

// Reuse role-specific point thresholds without enabling legacy occupancy rules.
export function evaluateProjectorTypography(telemetry, profile, context = {}) {
  const codes = new Set(['FONT_FLOOR_VIOLATION', 'FONT_BELOW_VIEWING_TARGET', 'TITLE_WRAPPED']);
  const violations = evaluateLegacyReadability(telemetry, profile, context).violations
    .filter(v => codes.has(v.code));
  const text = telemetry.elements.filter(e => e.type === 'text' && e.quality_role === 'content');
  const missing = telemetry.unavailable.some(e => e.field === 'elements')
    || text.some(e => !Number.isFinite(e.text?.font_size));
  const configured = Boolean(profile.legacy_rules?.viewing_modes?.[context.viewing_mode ?? 'projector']
    ?? profile.legacy_rules?.viewing_modes?.projector);
  const status = violations.some(v => v.severity === 'error') ? 'fail'
    : missing || !configured ? 'not_evaluable' : violations.length ? 'warning' : 'pass';
  return {
    checks: { projector_typography: {
      rule_id: 'projector_typography', metric: 'typography_violation_count', status,
      actual: violations.length, threshold: { warning: null, fail: null, triggered: null },
      code: null, reason: missing ? 'font_telemetry_incomplete' : !configured ? 'font_thresholds_missing' : 'role_specific_point_thresholds',
      recommended_action: missing ? 'provide_required_input' : violations[0]?.recommended_action ?? 'none',
      evidence: { unit: 'pt', text_count: text.length, viewing_mode: context.viewing_mode ?? 'projector' },
      disabled: false, blocking: true,
    } }, violations,
  };
}
