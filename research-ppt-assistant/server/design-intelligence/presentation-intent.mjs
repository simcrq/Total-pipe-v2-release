// Opt-in authoring contract. Routing fields are plans, not evidence of delivery.
export function normalizePresentationIntent(value) {
  if (value === undefined) return undefined;
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new TypeError('presentation_intent must be an object');
  const allowed = ['objective', 'emphasis', 'required_on_screen', 'speaker_notes', 'appendix'];
  if (Object.keys(value).some(k => !allowed.includes(k))) throw new TypeError('Unknown presentation_intent field');
  if (typeof value.objective !== 'string' || !value.objective.trim()) throw new TypeError('presentation_intent.objective is required');
  const emphasis = value.emphasis ?? 'medium';
  if (!['low', 'medium', 'high'].includes(emphasis)) throw new TypeError('Invalid presentation_intent.emphasis');
  const result = { objective: value.objective.trim(), emphasis };
  for (const key of allowed.slice(2)) {
    const items = value[key] ?? [];
    if (!Array.isArray(items) || items.some(x => typeof x !== 'string' || !x.trim())) throw new TypeError(`Invalid presentation_intent.${key}`);
    result[key] = [...new Set(items.map(x => x.trim()))];
  }
  return result;
}
