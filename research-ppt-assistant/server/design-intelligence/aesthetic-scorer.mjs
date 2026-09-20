import { dominantVisualSide, estimateContainerDensity } from "./deck-state.mjs";

export const AESTHETIC_SCORER_VERSION = "1.0.0";

const asArray = (value) => (Array.isArray(value) ? value : []);
const clamp = (value, min = 0, max = 1) => Math.min(max, Math.max(min, value));
const round = (value, places = 3) => Number(value.toFixed(places));

function slotType(slot) {
  const type = String(slot?.slot_type ?? slot?.type ?? "").toLowerCase();
  if (["image", "figure", "visual", "chart"].includes(type)) return "visual";
  if (["title", "subtitle", "meta", "text", "callout", "caption", "question", "reference", "metadata"].includes(type)) return "text";
  return type;
}

function slots(layout) {
  return asArray(layout?.slot_specs ?? layout?.slots);
}

function area(slot) {
  return clamp(Number(slot?.box?.w ?? 0) * Number(slot?.box?.h ?? 0));
}

function totalArea(layout, type) {
  return clamp(slots(layout).filter((slot) => !type || slotType(slot) === type).reduce((sum, slot) => sum + area(slot), 0), 0, 0.95);
}

function hierarchyFit(layout, designIR) {
  const all = slots(layout);
  if (!all.length) return 0.5;
  const priorities = all.map((slot) => Number(slot.priority ?? 1));
  const priorityRange = Math.max(...priorities) - Math.min(...priorities);
  const visualAreas = all.filter((slot) => slotType(slot) === "visual").map(area);
  const dominantVisualRatio = visualAreas.length ? Math.max(...visualAreas) / Math.max(0.001, visualAreas.reduce((sum, value) => sum + value, 0)) : 0;
  const wantsDominantVisual = designIR.visual_priority === "dominant";
  const visualContribution = wantsDominantVisual ? dominantVisualRatio : visualAreas.length > 1 ? 1 - Math.abs(dominantVisualRatio - 0.5) : 0.8;
  return clamp(0.55 + Math.min(0.25, priorityRange * 0.06) + visualContribution * 0.2);
}

function visualPriorityFit(layout, designIR) {
  const visualArea = totalArea(layout, "visual");
  const targets = { none: 0, supporting: 0.16, coequal: 0.28, dominant: 0.42 };
  const target = targets[designIR.visual_priority] ?? 0.22;
  if (target === 0) return clamp(1 - visualArea * 2.5);
  return clamp(1 - Math.abs(visualArea - target) / Math.max(0.25, target));
}

function whitespaceFit(layout, designIR) {
  const occupied = totalArea(layout);
  const whitespace = clamp(1 - occupied);
  const targets = { low: 0.2, medium: 0.3, medium_high: 0.4, high: 0.5 };
  const target = targets[designIR.whitespace] ?? 0.3;
  return clamp(1 - Math.abs(whitespace - target) / 0.5);
}

function balanceProxy(layout, designIR) {
  const weighted = slots(layout).map((slot) => ({
    area: Math.max(0.001, area(slot)),
    x: Number(slot?.box?.x ?? 0) + Number(slot?.box?.w ?? 0) / 2,
    y: Number(slot?.box?.y ?? 0) + Number(slot?.box?.h ?? 0) / 2,
  }));
  if (!weighted.length) return 0.5;
  const total = weighted.reduce((sum, item) => sum + item.area, 0);
  const centerX = weighted.reduce((sum, item) => sum + item.x * item.area, 0) / total;
  const centerY = weighted.reduce((sum, item) => sum + item.y * item.area, 0) / total;
  const asymmetryAllowance = designIR.composition_intent.family === "asymmetric" ? 0.14 : 0.04;
  const distance = Math.max(0, Math.hypot(centerX - 0.5, centerY - 0.5) - asymmetryAllowance);
  return clamp(1 - distance / 0.45);
}

function treatmentMatch(layout, treatment, designIR) {
  const preferences = asArray(designIR.design_intent?.treatment_preferences);
  const preferenceIndex = preferences.indexOf(treatment.id);
  const preferenceScore = preferenceIndex < 0 ? 0.45 : 1 - preferenceIndex * 0.16;
  const preferredFamilies = asArray(treatment.preferred_layout_families);
  const preferredFamily = preferredFamilies.includes(layout.family) || preferredFamilies.includes(layout.category);
  return clamp(preferenceScore * 0.75 + (preferredFamily ? 0.25 : 0.12));
}

function repetitions(deckState, layout, treatment, decoration) {
  const history = deckState?.recent_history ?? {};
  const countRecent = (values, target) => asArray(values).filter((value) => value === target).length;
  const family = layout.family ?? layout.category;
  const layoutRepeat = countRecent(history.layout_families, family) / 3;
  const treatmentRepeat = countRecent(history.treatments, treatment.id) / 3;
  const decorationRepeat = countRecent(history.decoration_patterns, decoration.id) / 3;
  const containerRepeat = countRecent(history.container_families, decoration.container) / 3;
  const sideRepeat = countRecent(history.dominant_visual_sides, dominantVisualSide(layout)) / 3;
  return clamp(layoutRepeat * 0.2 + treatmentRepeat * 0.3 + decorationRepeat * 0.2 + containerRepeat * 0.2 + sideRepeat * 0.1);
}

function rhythmBonus(deckState, layout, treatment) {
  if (!deckState?.counts?.pages) return 0.5;
  if (deckState.rhythm?.next_preference === treatment.id) return 1;
  const recentDensity = asArray(deckState.recent_history?.page_densities).at(-1);
  const densityChanged = recentDensity !== undefined && recentDensity !== layout.density;
  const treatmentChanged = asArray(deckState.recent_history?.treatments).at(-1) !== treatment.id;
  return clamp(0.35 + (densityChanged ? 0.3 : 0) + (treatmentChanged ? 0.25 : 0));
}

function containerPenalty(decoration, designIR) {
  const density = estimateContainerDensity(decoration);
  const allowed = { none: 0.05, minimal: 0.15, structured: 0.25, audit_only: 0.32 }[designIR.container_policy] ?? 0.15;
  const excess = Math.max(0, density - allowed);
  const cardPenalty = decoration.container === "card" ? 0.35 : 0;
  return clamp(excess * 1.8 + cardPenalty);
}

export function scoreAestheticCandidate({ layout, treatment, decoration, design_ir: designIR, deck_state: deckState }) {
  if (!layout || !treatment || !decoration || !designIR) throw new TypeError("layout, treatment, decoration, and design_ir are required");
  const components = {
    hierarchy_fit: hierarchyFit(layout, designIR),
    visual_priority_fit: visualPriorityFit(layout, designIR),
    whitespace_fit: whitespaceFit(layout, designIR),
    balance_proxy: balanceProxy(layout, designIR),
    treatment_match: treatmentMatch(layout, treatment, designIR),
    rhythm_bonus: rhythmBonus(deckState, layout, treatment),
    repetition_penalty: repetitions(deckState, layout, treatment, decoration),
    container_penalty: containerPenalty(decoration, designIR),
  };
  const positive = 0.25 * components.hierarchy_fit
    + 0.2 * components.visual_priority_fit
    + 0.15 * components.whitespace_fit
    + 0.15 * components.balance_proxy
    + 0.15 * components.treatment_match
    + 0.1 * components.rhythm_bonus;
  const penalty = 0.16 * components.repetition_penalty + 0.14 * components.container_penalty;
  const score = clamp(positive - penalty);
  return {
    scorer_version: AESTHETIC_SCORER_VERSION,
    score: round(score),
    components: Object.fromEntries(Object.entries(components).map(([key, value]) => [key, round(value)])),
    explanation: {
      positive_score: round(positive),
      penalty: round(penalty),
      hard_constraints_overridable: false,
    },
  };
}
