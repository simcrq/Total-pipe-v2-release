export const GROUP_FIT_VERSION = "1.0.0";

export const RELATION_TYPES = Object.freeze([
  "parallel",
  "comparison",
  "sequence",
  "before_after",
  "control_treatment",
  "cause_effect",
  "supporting_evidence",
]);

export const RELATION_STRENGTHS = Object.freeze(["hard", "soft", "advisory"]);

export const DEFAULT_RELATION_FEATURE_FLAGS = Object.freeze({
  visual_fit_v045: true,
  relation_contract_v046: true,
  group_fit_preflight: true,
  relation_arbitration: "shadow",
  non_uniform_siblings: true,
  fallback_to_v045: true,
});

const isRecord = (value) => Boolean(value) && typeof value === "object" && !Array.isArray(value);
const nonEmpty = (value, field) => {
  const normalized = String(value ?? "").trim();
  if (!normalized) throw new TypeError(`${field} is required`);
  return normalized;
};

function positive(value, field) {
  const number = Number(value);
  if (!Number.isFinite(number) || number <= 0) throw new RangeError(`${field} must be a positive number`);
  return number;
}

function nonNegativeInteger(value, field, fallback = 0) {
  if (value === undefined || value === null) return fallback;
  const number = Number(value);
  if (!Number.isInteger(number) || number < 0) throw new RangeError(`${field} must be a non-negative integer`);
  return number;
}

function box(value, field) {
  if (!isRecord(value)) throw new TypeError(`${field} must be an object`);
  const x = Number(value.x);
  const y = Number(value.y);
  if (!Number.isFinite(x) || !Number.isFinite(y)) throw new RangeError(`${field}.x and ${field}.y must be finite numbers`);
  return {
    x,
    y,
    width: positive(value.width ?? value.w, `${field}.width`),
    height: positive(value.height ?? value.h, `${field}.height`),
  };
}

function normalizeIntent(value = {}) {
  if (!isRecord(value)) throw new TypeError("visual_intent must be an object");
  return {
    visual_type: String(value.visual_type ?? "scientific_figure"),
    crop_policy: String(value.crop_policy ?? "full_figure"),
    fit_policy: String(value.fit_policy ?? "contain"),
    semantic_crop_allowed: value.semantic_crop_allowed === true,
    whitespace_policy: String(value.whitespace_policy ?? "minimal"),
    priority: String(value.priority ?? "primary_visual"),
  };
}

function normalizeChild(value, index) {
  if (!isRecord(value)) throw new TypeError(`children[${index}] must be an object`);
  const source = value.source ?? {};
  const normalized = {
    visual_id: nonEmpty(value.visual_id, `children[${index}].visual_id`),
    source: {
      width: positive(source.width, `children[${index}].source.width`),
      height: positive(source.height, `children[${index}].source.height`),
    },
    visual_intent: normalizeIntent(value.visual_intent),
    priority: nonNegativeInteger(value.priority, `children[${index}].priority`, index + 1),
  };
  if (value.source_region) normalized.source_region = box(value.source_region, `children[${index}].source_region`);
  return normalized;
}

function normalizeCandidate(value, field, childIds) {
  if (!isRecord(value)) throw new TypeError(`${field} must be an object`);
  const allocations = Array.isArray(value.allocations) ? value.allocations : [];
  if (allocations.length !== childIds.length) throw new RangeError(`${field}.allocations must cover every visual child exactly once`);
  const seen = new Set();
  const normalizedAllocations = allocations.map((allocation, index) => {
    if (!isRecord(allocation)) throw new TypeError(`${field}.allocations[${index}] must be an object`);
    const visualId = nonEmpty(allocation.visual_id, `${field}.allocations[${index}].visual_id`);
    if (!childIds.includes(visualId)) throw new RangeError(`${field} contains unknown visual_id: ${visualId}`);
    if (seen.has(visualId)) throw new RangeError(`${field} contains duplicate visual_id: ${visualId}`);
    seen.add(visualId);
    return { visual_id: visualId, allocated_visual_bbox: box(allocation.allocated_visual_bbox ?? allocation.bbox, `${field}.allocations[${index}].allocated_visual_bbox`) };
  });
  const constraints = value.higher_priority_issues ?? {};
  return {
    layout_id: nonEmpty(value.layout_id ?? value.candidate_layout, `${field}.layout_id`),
    group_bbox: value.group_bbox ? box(value.group_bbox, `${field}.group_bbox`) : null,
    allocations: normalizedAllocations,
    child_order: Array.isArray(value.child_order) ? value.child_order.map(String) : normalizedAllocations.map((item) => item.visual_id),
    higher_priority_issues: {
      content_integrity: nonNegativeInteger(constraints.content_integrity, `${field}.higher_priority_issues.content_integrity`),
      legibility: nonNegativeInteger(constraints.legibility, `${field}.higher_priority_issues.legibility`),
    },
    source: String(value.source ?? "explicit"),
  };
}

function normalizeFlags(value = {}) {
  if (!isRecord(value)) throw new TypeError("feature_flags must be an object");
  const flags = { ...DEFAULT_RELATION_FEATURE_FLAGS, ...value };
  for (const key of ["visual_fit_v045", "relation_contract_v046", "group_fit_preflight", "non_uniform_siblings", "fallback_to_v045"]) {
    if (typeof flags[key] !== "boolean") throw new TypeError(`feature_flags.${key} must be boolean`);
  }
  if (![true, false, "shadow"].includes(flags.relation_arbitration)) {
    throw new RangeError("feature_flags.relation_arbitration must be true, false, or shadow");
  }
  return flags;
}

function normalizeCredits(value) {
  if (value === undefined || value === null) return null;
  if (!isRecord(value) || !isRecord(value.v045) || !isRecord(value.v046)) {
    throw new TypeError("credits must contain v045 and v046 telemetry objects");
  }
  const fields = ["median_credits_per_deck", "credits_per_slide", "credits_per_accepted_slide", "model_calls_per_slide", "replan_count", "escalation_rate"];
  const normalizeSide = (side, field) => Object.fromEntries(fields.map((key) => {
    const number = Number(side[key]);
    if (!Number.isFinite(number) || number < 0) throw new RangeError(`credits.${field}.${key} must be a non-negative number`);
    return [key, number];
  }));
  return { v045: normalizeSide(value.v045, "v045"), v046: normalizeSide(value.v046, "v046") };
}

export function normalizeGroupFitInput(input = {}) {
  if (!isRecord(input)) throw new TypeError("group fit input must be an object");
  const group = input.visual_group;
  if (!isRecord(group)) throw new TypeError("visual_group is required");
  const groupId = nonEmpty(group.group_id, "visual_group.group_id");
  const semanticRelation = String(group.semantic_relation ?? "");
  const relationStrength = String(group.relation_strength ?? "");
  if (!RELATION_TYPES.includes(semanticRelation)) throw new RangeError(`unsupported semantic_relation: ${semanticRelation}`);
  if (!RELATION_STRENGTHS.includes(relationStrength)) throw new RangeError(`unsupported relation_strength: ${relationStrength}`);
  const children = (input.children ?? []).map(normalizeChild);
  if (children.length < 2) throw new RangeError("children must contain at least two visuals");
  const childIds = children.map((child) => child.visual_id);
  if (new Set(childIds).size !== childIds.length) throw new RangeError("children visual_id values must be unique");
  const declaredChildren = Array.isArray(group.children) ? group.children.map(String) : [];
  if (declaredChildren.length !== childIds.length || declaredChildren.some((id, index) => id !== childIds[index])) {
    throw new RangeError("visual_group.children must exactly match children visual_id values in reading order");
  }
  const relation = input.layout_relation;
  if (!isRecord(relation)) throw new TypeError("layout_relation is required and must be explicit");
  const layoutRelation = {
    shared_alignment: relation.shared_alignment === true,
    shared_container_style: relation.shared_container_style === true,
    equal_size: relation.equal_size === true,
    equal_width: relation.equal_width === true,
    equal_height: relation.equal_height === true,
    preserve_order: relation.preserve_order !== false,
    intentional_unequal_weight: relation.intentional_unequal_weight === true,
  };
  const baseline = normalizeCandidate(input.baseline_candidate, "baseline_candidate", childIds);
  const alternatives = (input.relation_aware_candidates ?? []).map((candidate, index) => normalizeCandidate(candidate, `relation_aware_candidates[${index}]`, childIds));
  const maxAttempts = nonNegativeInteger(input.max_relation_replan_attempts, "max_relation_replan_attempts", 1);
  if (maxAttempts > 2) throw new RangeError("max_relation_replan_attempts must not exceed 2");
  return {
    group_id: groupId,
    visual_group: { group_id: groupId, semantic_relation: semanticRelation, relation_strength: relationStrength, children: childIds },
    layout_relation: layoutRelation,
    children,
    baseline_candidate: { ...baseline, source: "v0.4.5_baseline" },
    relation_aware_candidates: alternatives,
    feature_flags: normalizeFlags(input.feature_flags),
    max_relation_replan_attempts: maxAttempts,
    quality_profile: input.quality_profile,
    credits: normalizeCredits(input.credits),
    baseline_qa_passed: input.baseline_qa_passed === true,
  };
}

const boxSchema = {
  type: "object",
  properties: { x: { type: "number" }, y: { type: "number" }, width: { type: "number", exclusiveMinimum: 0 }, height: { type: "number", exclusiveMinimum: 0 } },
  required: ["x", "y", "width", "height"],
  additionalProperties: false,
};

const candidateSchema = {
  type: "object",
  properties: {
    layout_id: { type: "string", minLength: 1 },
    group_bbox: boxSchema,
    allocations: {
      type: "array", minItems: 2,
      items: { type: "object", properties: { visual_id: { type: "string", minLength: 1 }, allocated_visual_bbox: boxSchema }, required: ["visual_id", "allocated_visual_bbox"], additionalProperties: false },
    },
    child_order: { type: "array", minItems: 2, items: { type: "string", minLength: 1 } },
    higher_priority_issues: {
      type: "object",
      properties: { content_integrity: { type: "integer", minimum: 0 }, legibility: { type: "integer", minimum: 0 } },
      additionalProperties: false,
    },
    source: { type: "string" },
  },
  required: ["layout_id", "allocations"],
  additionalProperties: false,
};

const creditSideSchema = {
  type: "object",
  properties: Object.fromEntries(["median_credits_per_deck", "credits_per_slide", "credits_per_accepted_slide", "model_calls_per_slide", "replan_count", "escalation_rate"].map((key) => [key, { type: "number", minimum: 0 }])),
  required: ["median_credits_per_deck", "credits_per_slide", "credits_per_accepted_slide", "model_calls_per_slide", "replan_count", "escalation_rate"],
  additionalProperties: false,
};

export const GROUP_FIT_INPUT_SCHEMA = Object.freeze({
  type: "object",
  properties: {
    visual_group: {
      type: "object",
      properties: {
        group_id: { type: "string", minLength: 1 },
        semantic_relation: { enum: RELATION_TYPES },
        relation_strength: { enum: RELATION_STRENGTHS },
        children: { type: "array", minItems: 2, uniqueItems: true, items: { type: "string", minLength: 1 } },
      },
      required: ["group_id", "semantic_relation", "relation_strength", "children"],
      additionalProperties: false,
    },
    layout_relation: {
      type: "object",
      properties: {
        shared_alignment: { type: "boolean" }, shared_container_style: { type: "boolean" }, equal_size: { type: "boolean" }, equal_width: { type: "boolean" }, equal_height: { type: "boolean" }, preserve_order: { type: "boolean" }, intentional_unequal_weight: { type: "boolean" },
      },
      required: ["shared_alignment", "shared_container_style", "equal_size", "equal_width", "equal_height", "preserve_order"],
      additionalProperties: false,
    },
    children: {
      type: "array", minItems: 2,
      items: {
        type: "object",
        properties: {
          visual_id: { type: "string", minLength: 1 },
          source: { type: "object", properties: { width: { type: "number", exclusiveMinimum: 0 }, height: { type: "number", exclusiveMinimum: 0 } }, required: ["width", "height"], additionalProperties: false },
          source_region: boxSchema,
          visual_intent: {
            type: "object",
            properties: { visual_type: { type: "string" }, crop_policy: { enum: ["full_figure", "semantic_crop_allowed", "fixed_region"] }, fit_policy: { enum: ["contain", "cover"] }, semantic_crop_allowed: { type: "boolean" }, whitespace_policy: { enum: ["minimal", "intentional", "reserved"] }, priority: { type: "string" } },
            additionalProperties: false,
          },
          priority: { type: "integer", minimum: 0 },
        },
        required: ["visual_id", "source"],
        additionalProperties: false,
      },
    },
    baseline_candidate: candidateSchema,
    relation_aware_candidates: { type: "array", items: candidateSchema },
    feature_flags: {
      type: "object",
      properties: { visual_fit_v045: { type: "boolean" }, relation_contract_v046: { type: "boolean" }, group_fit_preflight: { type: "boolean" }, relation_arbitration: { enum: [true, false, "shadow"] }, non_uniform_siblings: { type: "boolean" }, fallback_to_v045: { type: "boolean" } },
      additionalProperties: false,
    },
    max_relation_replan_attempts: { type: "integer", minimum: 0, maximum: 2 },
    quality_profile: { type: "object", additionalProperties: true },
    credits: { type: "object", properties: { v045: creditSideSchema, v046: creditSideSchema }, required: ["v045", "v046"], additionalProperties: false },
    baseline_qa_passed: { type: "boolean" },
  },
  required: ["visual_group", "layout_relation", "children", "baseline_candidate"],
  additionalProperties: false,
});
