export const VISUAL_OBSERVER_VERSION = "1.0.0";
export const REPAIR_CONTROLLER_VERSION = "1.0.0";
export const BOUNDED_REPAIR_LOOP_VERSION = "1.0.0";

export const DESIGN_OBSERVATION_STATUSES = Object.freeze(["pass", "repairable", "manual_review_required", "blocked"]);
export const REPAIR_ACTIONS = Object.freeze([
  "KEEP",
  "REDECORATE",
  "CHANGE_TREATMENT",
  "RESELECT_LAYOUT",
  "REBIND",
  "REDUCE_SECONDARY_CONTENT",
  "SPLIT_PAGE",
  "ESCALATE",
]);
export const REPAIR_STATUSES = Object.freeze(["keep", "repair_required", "manual_review_required", "blocked"]);

const nullableScore = { type: ["number", "null"], minimum: 0, maximum: 1 };
const metricSchema = {
  type: "object",
  properties: {
    measurable: { type: "boolean" },
    value: nullableScore,
    evidence: {},
    unavailable_reason: { type: "string" },
  },
  required: ["measurable", "value", "evidence"],
  additionalProperties: false,
};

export const VISUAL_OBSERVATION_SCHEMA = Object.freeze({
  $id: "VisualObservation",
  type: "object",
  properties: {
    observer_version: { const: VISUAL_OBSERVER_VERSION },
    slide_id: { type: "string" },
    production_status: { enum: ["pass", "warning", "fail", "not_evaluable"] },
    design_status: { enum: DESIGN_OBSERVATION_STATUSES },
    observation_status: { enum: ["complete", "partial", "blocked"] },
    design_metrics: {
      type: "object",
      properties: {
        hierarchy: metricSchema,
        balance: metricSchema,
        whitespace: metricSchema,
        visual_focus: metricSchema,
        decoration_variety: metricSchema,
      },
      required: ["hierarchy", "balance", "whitespace", "visual_focus", "decoration_variety"],
      additionalProperties: false,
    },
    issues: { type: "array", items: { type: "string" }, uniqueItems: true },
    diagnoses: {
      type: "array",
      items: {
        type: "object",
        properties: {
          code: { type: "string" },
          source: { enum: ["production_qa", "design_qa", "observer"] },
          severity: { enum: ["error", "warning", "info"] },
          source_codes: { type: "array", items: { type: "string" }, uniqueItems: true },
          message: { type: "string" },
        },
        required: ["code", "source", "severity", "source_codes", "message"],
        additionalProperties: false,
      },
    },
    recommended_actions: { type: "array", items: { enum: REPAIR_ACTIONS }, uniqueItems: true },
    design_context_used: { type: "boolean" },
    render_artifact: { type: ["object", "null"], additionalProperties: true },
  },
  required: ["observer_version", "slide_id", "production_status", "design_status", "observation_status", "design_metrics", "issues", "diagnoses", "recommended_actions", "design_context_used", "render_artifact"],
  additionalProperties: false,
});

export const REPAIR_PLAN_SCHEMA = Object.freeze({
  $id: "RepairPlan",
  type: "object",
  properties: {
    controller_version: { const: REPAIR_CONTROLLER_VERSION },
    status: { enum: REPAIR_STATUSES },
    action: { enum: REPAIR_ACTIONS },
    iteration: { type: "integer", minimum: 0, maximum: 2 },
    next_iteration: { type: ["integer", "null"], minimum: 1, maximum: 2 },
    max_repair_iterations: { const: 2 },
    bounded: { const: true },
    trigger_codes: { type: "array", items: { type: "string" }, uniqueItems: true },
    reason: { type: "string" },
    target: { type: "object", additionalProperties: true },
    repair_lineage: {
      type: "array",
      maxItems: 3,
      items: {
        type: "object",
        properties: {
          iteration: { type: "integer", minimum: 0, maximum: 2 },
          action: { enum: REPAIR_ACTIONS },
          trigger_codes: { type: "array", items: { type: "string" }, uniqueItems: true },
          slide_id: { type: "string" },
        },
        required: ["iteration", "action", "trigger_codes", "slide_id"],
        additionalProperties: false,
      },
    },
    human_escalation: {
      type: ["object", "null"],
      properties: {
        required: { const: true },
        reason: { type: "string" },
        unresolved_codes: { type: "array", items: { type: "string" }, uniqueItems: true },
      },
      required: ["required", "reason", "unresolved_codes"],
      additionalProperties: false,
    },
  },
  required: ["controller_version", "status", "action", "iteration", "next_iteration", "max_repair_iterations", "bounded", "trigger_codes", "reason", "target", "repair_lineage", "human_escalation"],
  additionalProperties: false,
});
