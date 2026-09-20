import { scoreAestheticCandidate } from "./aesthetic-scorer.mjs";

export const CANDIDATE_FACTORY_VERSION = "1.0.0";

const asArray = (value) => (Array.isArray(value) ? value : []);
const clampInteger = (value, fallback, min, max) => {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? Math.min(max, Math.max(min, Math.floor(parsed))) : fallback;
};

function layoutId(layout) {
  return String(layout?.id ?? layout?.layout_id ?? "").trim();
}

function visualCapacity(layout) {
  return Number(layout?.capacity?.image_capacity ?? layout?.content_profile?.image_capacity ?? layout?.query?.image_count ?? 0);
}

function supportsDistributedText(layout) {
  return asArray(layout?.slot_specs ?? layout?.slots).some((slot) => {
    const type = String(slot?.slot_type ?? slot?.type ?? "").toLowerCase();
    const box = slot?.box ?? {};
    return ["text", "body", "callout"].includes(type)
      && Number(box.w ?? 0) >= 0.42
      && Number(box.h ?? 0) >= 0.28;
  });
}

function compatibleTreatment(designIR, layout, treatment) {
  if (!asArray(treatment.compatible_roles).includes(designIR.semantic_role)) return { compatible: false, reason: "semantic_role_incompatible" };
  if (treatment.id === "structured_text" && designIR.text_flow?.mode !== "distributed_arrow_list") {
    return { compatible: false, reason: "distributed_text_flow_required" };
  }
  if (treatment.id === "structured_text" && !supportsDistributedText(layout)) {
    return { compatible: false, reason: "distributed_text_slot_too_small" };
  }
  if (["figure_led", "technical_annotation"].includes(treatment.id) && designIR.visual_priority === "none" && visualCapacity(layout) === 0) {
    return { compatible: false, reason: "visual_treatment_without_visual_capacity" };
  }
  if (treatment.id === "metric_focus" && !["metric_summary", "results_evidence", "results_comparison", "summary_synthesis"].includes(designIR.semantic_role)) {
    return { compatible: false, reason: "metric_role_required" };
  }
  return { compatible: true };
}

function compatibleDecoration(layout, treatment, decoration) {
  if (!asArray(treatment.decoration_profiles).includes(decoration.id)) return { compatible: false, reason: "treatment_decoration_unlisted" };
  if (!asArray(decoration.compatible_treatments).includes(treatment.id)) return { compatible: false, reason: "decoration_treatment_incompatible" };
  const contentRoles = asArray(layout.content_roles);
  const slotIds = asArray(layout.slot_specs ?? layout.slots).map((slot) => String(slot.slot_id ?? slot.id ?? "").toLowerCase());
  if (decoration.figure_treatment === "caption_rail" && !contentRoles.includes("caption") && !slotIds.some((id) => id.includes("caption"))) {
    return { compatible: false, reason: "caption_rail_requires_caption_capability" };
  }
  const processCapacity = Number(layout?.capacity?.process_capacity ?? layout?.content_profile?.process_capacity ?? 0);
  if (decoration.figure_treatment === "annotated" && visualCapacity(layout) === 0 && processCapacity === 0) {
    return { compatible: false, reason: "annotation_requires_visual_or_process_capability" };
  }
  if (decoration.divider === "axis_rule" && !contentRoles.some((role) => ["data_visual", "metric", "process", "primary_visual", "secondary_visual"].includes(role))) {
    return { compatible: false, reason: "axis_rule_requires_relational_content" };
  }
  const budget = decoration.decoration_budget ?? {};
  if (Number(budget.background_motifs_max) > 1 || Number(budget.accent_elements_max) > 3 || Number(budget.decorative_area_ratio_max) > 0.12) {
    return { compatible: false, reason: "decoration_budget_exceeded" };
  }
  if (budget.allow_evidence_overlap || budget.allow_visual_overlap) return { compatible: false, reason: "evidence_overlap_forbidden" };
  return { compatible: true };
}

function orderedTreatments(designIR, registry) {
  const preference = new Map(asArray(designIR.design_intent?.treatment_preferences).map((id, index) => [id, index]));
  return [...registry.treatments].sort((left, right) => {
    const leftRank = preference.get(left.id) ?? 99;
    const rightRank = preference.get(right.id) ?? 99;
    return leftRank - rightRank || left.id.localeCompare(right.id);
  });
}

function publicCandidate(candidate) {
  return {
    candidate_id: candidate.candidate_id,
    layout_id: layoutId(candidate.layout),
    layout_family: candidate.layout.family ?? candidate.layout.category,
    treatment: candidate.treatment.id,
    decoration: candidate.decoration.id,
    structural_score: candidate.structural_score,
    aesthetic_score: candidate.aesthetic.score,
    aesthetic_components: candidate.aesthetic.components,
  };
}

export function createDesignCandidates(input = {}) {
  const designIR = input.design_ir;
  const layouts = asArray(input.layouts);
  const registry = input.registry;
  if (!designIR || !registry) throw new TypeError("design_ir and registry are required");
  const maxCandidates = clampInteger(input.max_candidates, 24, 1, 24);
  const maxTreatments = clampInteger(input.treatments_per_layout, 2, 1, 2);
  const maxDecorations = clampInteger(input.decorations_per_treatment, 2, 1, 2);
  const candidates = [];
  const rejected = [];

  for (const layout of layouts.slice(0, 8)) {
    let acceptedTreatments = 0;
    for (const treatment of orderedTreatments(designIR, registry)) {
      const treatmentCheck = compatibleTreatment(designIR, layout, treatment);
      if (!treatmentCheck.compatible) {
        rejected.push({ layout_id: layoutId(layout), treatment: treatment.id, reason: treatmentCheck.reason });
        continue;
      }
      acceptedTreatments += 1;
      let acceptedDecorations = 0;
      for (const decorationId of asArray(treatment.decoration_profiles)) {
        const decoration = registry.decorations_by_id.get(decorationId);
        const decorationCheck = decoration ? compatibleDecoration(layout, treatment, decoration) : { compatible: false, reason: "decoration_not_found" };
        if (!decorationCheck.compatible) {
          rejected.push({ layout_id: layoutId(layout), treatment: treatment.id, decoration: decorationId, reason: decorationCheck.reason });
          continue;
        }
        const aesthetic = scoreAestheticCandidate({
          layout,
          treatment,
          decoration,
          design_ir: designIR,
          deck_state: input.deck_state,
        });
        candidates.push({
          candidate_id: `${layoutId(layout)}:${treatment.id}:${decoration.id}`,
          layout,
          treatment,
          decoration,
          structural_score: Number(layout.score ?? 0),
          aesthetic,
        });
        acceptedDecorations += 1;
        if (acceptedDecorations >= maxDecorations) break;
      }
      if (acceptedTreatments >= maxTreatments) break;
    }
  }

  candidates.sort((left, right) => right.aesthetic.score - left.aesthetic.score
    || right.structural_score - left.structural_score
    || left.candidate_id.localeCompare(right.candidate_id));
  const selected = candidates.slice(0, maxCandidates);
  return {
    factory_version: CANDIDATE_FACTORY_VERSION,
    hard_constraint_mode: "layout_gate_before_aesthetic_ranking",
    raw_candidate_count: candidates.length,
    candidate_count: selected.length,
    candidates: selected,
    candidate_set: selected.map(publicCandidate),
    rejected_combinations: rejected,
  };
}

export function materializeRankedLayouts(candidateResult) {
  return asArray(candidateResult?.candidates).map((candidate) => ({
    ...structuredClone(candidate.layout),
    design_candidate: {
      candidate_id: candidate.candidate_id,
      treatment: structuredClone(candidate.treatment),
      decoration: structuredClone(candidate.decoration),
      structural_score: candidate.structural_score,
      aesthetic_score: candidate.aesthetic.score,
      aesthetic_components: structuredClone(candidate.aesthetic.components),
      aesthetic_explanation: structuredClone(candidate.aesthetic.explanation),
    },
  }));
}
