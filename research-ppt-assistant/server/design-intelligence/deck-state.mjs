export const DECK_DESIGN_STATE_VERSION = "1.0.0";

const HISTORY_WINDOW = 3;
const asArray = (value) => (Array.isArray(value) ? value : []);
const clone = (value) => structuredClone(value);

function recent(values, next) {
  return [...asArray(values), next].filter((value) => value !== undefined && value !== null).slice(-HISTORY_WINDOW);
}

function visualSlots(layout) {
  return asArray(layout?.slot_specs ?? layout?.slots).filter((slot) => {
    const type = String(slot?.slot_type ?? slot?.type ?? "").toLowerCase();
    return ["image", "figure", "visual", "chart"].includes(type);
  });
}

export function dominantVisualSide(layout) {
  const slots = visualSlots(layout);
  if (!slots.length) return "none";
  const dominant = slots.reduce((best, slot) => {
    const area = Number(slot?.box?.w ?? 0) * Number(slot?.box?.h ?? 0);
    return area > best.area ? { slot, area } : best;
  }, { slot: null, area: -1 }).slot;
  const center = Number(dominant?.box?.x ?? 0) + Number(dominant?.box?.w ?? 0) / 2;
  return center < 0.45 ? "left" : center > 0.55 ? "right" : "center";
}

export function estimateContainerDensity(decoration) {
  return {
    none: 0,
    open_group: 0.08,
    rule_group: 0.16,
    soft_panel: 0.28,
    card: 0.45,
  }[decoration?.container] ?? 0.12;
}

export function createDeckDesignState(input = {}) {
  return {
    schema_version: DECK_DESIGN_STATE_VERSION,
    deck_style: {
      tone: input.tone ?? "scientific_modern",
      accent_strength: input.accent_strength ?? "medium",
      preferred_density: input.preferred_density ?? "medium",
    },
    recent_history: {
      layout_families: [],
      treatments: [],
      container_density: [],
      container_families: [],
      decoration_patterns: [],
      dominant_visual_sides: [],
      page_densities: [],
    },
    rhythm: {
      dense_pages_in_row: 0,
      next_preference: null,
    },
    counts: {
      pages: 0,
      layout_families: {},
      treatments: {},
      decorations: {},
      containers: {},
    },
  };
}

function increment(target, key) {
  if (!key) return;
  target[key] = (target[key] ?? 0) + 1;
}

export function updateDeckDesignState(state, selection = {}) {
  const next = clone(state ?? createDeckDesignState());
  const layout = selection.layout ?? selection;
  const treatmentId = selection.treatment?.id ?? selection.treatment_id ?? selection.visual_treatment;
  const decoration = selection.decoration ?? selection.decoration_profile ?? {};
  const decorationId = decoration.id ?? selection.decoration_id;
  const family = layout.family ?? layout.category;
  const density = layout.density ?? selection.design_ir?.composition_intent?.text_density ?? "medium";
  const container = decoration.container ?? "none";
  const containerDensity = estimateContainerDensity(decoration);
  const dense = density === "高" || density === "high";

  next.recent_history.layout_families = recent(next.recent_history.layout_families, family);
  next.recent_history.treatments = recent(next.recent_history.treatments, treatmentId);
  next.recent_history.container_density = recent(next.recent_history.container_density, containerDensity);
  next.recent_history.container_families = recent(next.recent_history.container_families, container);
  next.recent_history.decoration_patterns = recent(next.recent_history.decoration_patterns, decorationId);
  next.recent_history.dominant_visual_sides = recent(next.recent_history.dominant_visual_sides, dominantVisualSide(layout));
  next.recent_history.page_densities = recent(next.recent_history.page_densities, density);
  next.rhythm.dense_pages_in_row = dense ? next.rhythm.dense_pages_in_row + 1 : 0;
  next.rhythm.next_preference = next.rhythm.dense_pages_in_row >= 2 ? "editorial_open" : null;
  next.counts.pages += 1;
  increment(next.counts.layout_families, family);
  increment(next.counts.treatments, treatmentId);
  increment(next.counts.decorations, decorationId);
  increment(next.counts.containers, container);
  return next;
}

export function publicDeckDesignState(state) {
  return clone(state ?? createDeckDesignState());
}
