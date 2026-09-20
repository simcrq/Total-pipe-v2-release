import { REPAIR_CONTROLLER_VERSION } from "./contracts.mjs";

export const MAX_REPAIR_ITERATIONS = 2;

const asArray = (value) => (Array.isArray(value) ? value : []);

const POLICIES = Object.freeze({
  RENDER_OR_EVIDENCE_MISMATCH: ["ESCALATE"],
  OBSERVATION_INCOMPLETE: ["ESCALATE"],
  GEOMETRY_INVALID: ["REBIND", "RESELECT_LAYOUT", "ESCALATE"],
  TEXT_DENSITY_HIGH: ["REDUCE_SECONDARY_CONTENT", "SPLIT_PAGE", "ESCALATE"],
  VISUAL_TOO_SMALL: ["RESELECT_LAYOUT", "SPLIT_PAGE", "ESCALATE"],
  LOW_VISUAL_HIERARCHY: ["CHANGE_TREATMENT", "RESELECT_LAYOUT", "ESCALATE"],
  LOW_VISUAL_FOCUS: ["CHANGE_TREATMENT", "RESELECT_LAYOUT", "SPLIT_PAGE"],
  EXCESSIVE_CARDIFICATION: ["CHANGE_TREATMENT", "REDECORATE", "ESCALATE"],
  REPEATED_CONTAINER_LANGUAGE: ["REDECORATE", "CHANGE_TREATMENT", "ESCALATE"],
  REPEATED_TREATMENT: ["CHANGE_TREATMENT", "RESELECT_LAYOUT", "ESCALATE"],
  LOW_WHITESPACE: ["REDECORATE", "CHANGE_TREATMENT", "RESELECT_LAYOUT"],
  UNBALANCED_VISUAL_WEIGHT: ["CHANGE_TREATMENT", "RESELECT_LAYOUT", "ESCALATE"],
  LOW_DECK_RHYTHM: ["CHANGE_TREATMENT", "REDECORATE", "ESCALATE"],
});

const PRIORITY = Object.freeze([
  "RENDER_OR_EVIDENCE_MISMATCH",
  "OBSERVATION_INCOMPLETE",
  "GEOMETRY_INVALID",
  "TEXT_DENSITY_HIGH",
  "VISUAL_TOO_SMALL",
  "LOW_VISUAL_HIERARCHY",
  "LOW_VISUAL_FOCUS",
  "EXCESSIVE_CARDIFICATION",
  "UNBALANCED_VISUAL_WEIGHT",
  "LOW_WHITESPACE",
  "REPEATED_CONTAINER_LANGUAGE",
  "REPEATED_TREATMENT",
  "LOW_DECK_RHYTHM",
]);

function normalizedIteration(value) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? Math.min(MAX_REPAIR_ITERATIONS, Math.max(0, Math.floor(parsed))) : 0;
}

function lineageEntry(observation, iteration, action, triggerCodes) {
  return {
    iteration,
    action,
    trigger_codes: triggerCodes,
    slide_id: String(observation.slide_id ?? "unknown"),
  };
}

function targetFor(action, observation) {
  const first = observation.diagnoses?.[0];
  if (action === "CHANGE_TREATMENT") return { scope: "visual_treatment", strategy: "select_next_compatible_candidate" };
  if (action === "REDECORATE") return { scope: "decoration_profile", strategy: "select_lower_repetition_budget_compliant_profile" };
  if (action === "RESELECT_LAYOUT") return { scope: "layout", strategy: "return_to_hard_constraint_gate_then_aesthetic_rerank" };
  if (action === "REBIND") return { scope: "slot_binding", strategy: "rebind_without_dropping_must_keep_content" };
  if (action === "REDUCE_SECONDARY_CONTENT") return { scope: "secondary_content", strategy: "remove_optional_only" };
  if (action === "SPLIT_PAGE") return { scope: "slide_brief", strategy: "deterministic_order_preserving_split" };
  if (action === "ESCALATE") return { scope: "human_review", strategy: "preserve_artifact_and_evidence_lineage" };
  return { scope: "none", strategy: first ? "no_automatic_change" : "keep_rendered_artifact" };
}

export function createRepairPlan(observation, context = {}) {
  if (!observation || typeof observation !== "object") throw new TypeError("observation is required");
  const iteration = normalizedIteration(context.iteration);
  const priorLineage = asArray(context.repair_lineage ?? context.history).slice(0, MAX_REPAIR_ITERATIONS);
  const triggerCodes = PRIORITY.filter((code) => asArray(observation.issues).includes(code));
  if (!triggerCodes.length && observation.production_status === "pass" && observation.design_status === "pass") {
    return {
      controller_version: REPAIR_CONTROLLER_VERSION,
      status: "keep",
      action: "KEEP",
      iteration,
      next_iteration: null,
      max_repair_iterations: MAX_REPAIR_ITERATIONS,
      bounded: true,
      trigger_codes: [],
      reason: "Rendered artifact satisfies production and design observation.",
      target: targetFor("KEEP", observation),
      repair_lineage: priorLineage,
      human_escalation: null,
    };
  }

  const primaryCode = triggerCodes[0] ?? "OBSERVATION_INCOMPLETE";
  const policy = POLICIES[primaryCode] ?? ["ESCALATE"];
  const proposed = policy[Math.min(iteration, policy.length - 1)] ?? "ESCALATE";
  const exhausted = iteration >= MAX_REPAIR_ITERATIONS;
  const action = exhausted ? "ESCALATE" : proposed;
  const blocked = observation.observation_status === "blocked" || ["RENDER_OR_EVIDENCE_MISMATCH", "OBSERVATION_INCOMPLETE"].includes(primaryCode);
  const escalated = action === "ESCALATE";
  const status = blocked ? "blocked" : escalated ? "manual_review_required" : "repair_required";
  const lineage = [...priorLineage, lineageEntry(observation, iteration, action, triggerCodes.length ? triggerCodes : [primaryCode])].slice(0, MAX_REPAIR_ITERATIONS + 1);
  return {
    controller_version: REPAIR_CONTROLLER_VERSION,
    status,
    action,
    iteration,
    next_iteration: action === "ESCALATE" ? null : iteration + 1,
    max_repair_iterations: MAX_REPAIR_ITERATIONS,
    bounded: true,
    trigger_codes: triggerCodes.length ? triggerCodes : [primaryCode],
    reason: exhausted
      ? `Repair budget exhausted after ${MAX_REPAIR_ITERATIONS} iterations.`
      : blocked
        ? "Automatic repair is unsafe until missing or conflicting production evidence is resolved."
        : `Apply bounded policy action ${action} for ${primaryCode}.`,
    target: targetFor(action, observation),
    repair_lineage: lineage,
    human_escalation: escalated || blocked ? {
      required: true,
      reason: exhausted ? "max_repair_iterations_exhausted" : blocked ? "production_facts_or_evidence_blocked" : "policy_escalation",
      unresolved_codes: triggerCodes.length ? triggerCodes : [primaryCode],
    } : null,
  };
}
