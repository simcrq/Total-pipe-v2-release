import {
  createAdaptationLogEntry,
  createViolation,
} from "./content-model.mjs";

export const SLOT_BINDING_VERSION = "1.0.1";

const own = (value, key) => Object.prototype.hasOwnProperty.call(value, key);
const isRecord = (value) => Boolean(value) && typeof value === "object" && !Array.isArray(value);

function clone(value) {
  if (value === undefined) return undefined;
  return structuredClone(value);
}

function stringValue(value) {
  return typeof value === "string" || typeof value === "number" ? String(value).trim() : "";
}

function firstPresent(value, keys) {
  for (const key of keys) if (own(value, key) && value[key] !== undefined && value[key] !== null) return value[key];
  return undefined;
}

function arrayValue(value) {
  return Array.isArray(value) ? value : [];
}

function canonicalSlotType(value) {
  const type = stringValue(value).toLowerCase();
  if (["title", "subtitle", "meta", "text", "callout", "caption", "question", "reference", "citation", "metadata", "body", "label"].includes(type)) return "text";
  if (["figure", "image", "visual", "photo", "diagram", "illustration"].includes(type)) return "image";
  return type;
}

export function canonicalAssignmentType(value) {
  const type = stringValue(value).toLowerCase();
  if (["title", "subtitle", "meta", "text", "callout", "caption", "question", "reference", "citation", "metadata", "body", "label"].includes(type)) return "text";
  if (["figure", "image", "visual", "photo", "diagram", "illustration"].includes(type)) return "image";
  return type;
}

function rawSlotId(slot) {
  return stringValue(firstPresent(slot, ["slot_id", "id", "slotId"]));
}

function rawSlotType(slot) {
  return stringValue(firstPresent(slot, ["slot_type", "type", "slotType"]));
}

function publicSlot(slot) {
  const source = isRecord(slot) ? slot : {};
  const id = rawSlotId(source);
  const rawType = rawSlotType(source);
  const capacity = isRecord(source.capacity) ? clone(source.capacity) : {
    max_chars: firstPresent(source, ["max_chars", "maxChars", "max_chars_at_min_font"]),
    max_chars_at_absolute_min: firstPresent(source, ["max_chars_at_absolute_min", "maxCharsAtAbsoluteMin"]),
    max_lines: firstPresent(source, ["max_lines", "maxLines"]),
    max_items: firstPresent(source, ["max_items", "maxItems", "max_count", "maxCount"]),
  };
  if (!own(capacity, "max_chars")) capacity.max_chars = null;
  const required = own(source, "required") ? source.required : !Boolean(source.optional);
  return {
    slot_id: id,
    slot_type: canonicalSlotType(rawType),
    raw_slot_type: rawType.toLowerCase(),
    required: Boolean(required),
    capacity,
    label_zh: firstPresent(source, ["label_zh", "label", "name"]),
    priority: Number.isFinite(Number(source.priority)) ? Number(source.priority) : 0,
    reading_order: Number.isFinite(Number(source.reading_order)) ? Number(source.reading_order) : undefined,
    box: clone(source.box),
    pptx_in: clone(source.pptx_in),
    collapse_when_empty: Boolean(source.collapse_when_empty),
  };
}

function capacityNumber(slot, keys) {
  const capacity = isRecord(slot?.capacity) ? slot.capacity : {};
  const value = firstPresent(capacity, keys);
  if (value === null || value === undefined || value === "") return undefined;
  const number = Number(value);
  return Number.isFinite(number) && number >= 0 ? Math.floor(number) : undefined;
}

function slotSortKey(slot, index, readingOrder) {
  const reading = Number.isFinite(slot.reading_order)
    ? slot.reading_order
    : (readingOrder.get(slot.slot_id) ?? index);
  return { priority: slot.priority ?? 0, reading, index };
}

function compareSlots(a, b) {
  return b.key.priority - a.key.priority || a.key.reading - b.key.reading || a.key.index - b.key.index || a.slot.slot_id.localeCompare(b.slot.slot_id);
}

function layoutViolation(code, field, actual, capacity, recommendedAction, message, details, recoverable = true) {
  return createViolation({
    code,
    field,
    actual,
    capacity,
    severity: "error",
    recoverable,
    recommended_action: recommendedAction,
    message,
    details,
  });
}

function adaptation(input) {
  return createAdaptationLogEntry(input);
}

function layoutRawSlots(layout) {
  if (!isRecord(layout)) return undefined;
  if (Array.isArray(layout.slot_specs)) return layout.slot_specs;
  if (Array.isArray(layout.slots)) return layout.slots;
  return undefined;
}

function sameContractValue(left, right, key) {
  if (key === "slot_type") return canonicalSlotType(left) === canonicalSlotType(right);
  if (key === "required") return Boolean(left) === Boolean(right);
  if (key === "capacity") return JSON.stringify(left ?? {}) === JSON.stringify(right ?? {});
  return true;
}

function normalizeLayout(input = {}) {
  const layout = input.layout_spec;
  const embeddedLayoutId = stringValue(firstPresent(layout ?? {}, ["layout_id", "id", "layoutId"]));
  const requestedLayoutId = stringValue(firstPresent(input, ["layout_id", "layoutId"]));
  const layoutId = embeddedLayoutId || requestedLayoutId;
  const errors = [];
  if (!isRecord(layout)) {
    errors.push(layoutViolation("INVALID_LAYOUT_SPEC", "layout_spec", layout, "object", "provide_layout_spec", "layout_spec must be an object.", undefined, false));
  }

  const embeddedSlots = layoutRawSlots(layout);
  const overrideSlots = input.slot_specs;
  if (overrideSlots !== undefined && !Array.isArray(overrideSlots)) {
    errors.push(layoutViolation("INVALID_LAYOUT_SPEC", "slot_specs", overrideSlots, "array", "provide_public_slot_specs", "slot_specs must be an array.", undefined, false));
  }
  if (embeddedSlots === undefined && !Array.isArray(overrideSlots)) {
    errors.push(layoutViolation("INVALID_LAYOUT_SPEC", "slot_specs", null, "non-empty array", "provide_public_slot_specs", "layout_spec must expose slot_specs or slots.", undefined, false));
  }

  const baseSlots = embeddedSlots ?? (Array.isArray(overrideSlots) ? overrideSlots : []);
  const suppliedSlots = Array.isArray(overrideSlots) ? overrideSlots : undefined;
  if (embeddedSlots && suppliedSlots) {
    const embeddedPublic = embeddedSlots.map(publicSlot);
    const suppliedPublic = suppliedSlots.map(publicSlot);
    const embeddedById = new Map(embeddedPublic.map((slot) => [slot.slot_id, slot]));
    const suppliedById = new Map(suppliedPublic.map((slot) => [slot.slot_id, slot]));
    if (embeddedById.size !== suppliedById.size || [...embeddedById.keys()].some((id) => !suppliedById.has(id))) {
      errors.push(layoutViolation("INVALID_LAYOUT_SPEC", "slot_specs", suppliedSlots, embeddedSlots, "use_complete_layout_slot_specs", "slot_specs must describe the complete layout without changing its slot contract.", undefined, false));
    } else {
      for (const [id, embedded] of embeddedById) {
        const supplied = suppliedById.get(id);
        if (!sameContractValue(embedded.slot_type, supplied.slot_type, "slot_type") || !sameContractValue(embedded.required, supplied.required, "required") || !sameContractValue(embedded.capacity, supplied.capacity, "capacity")) {
          errors.push(layoutViolation("INVALID_LAYOUT_SPEC", `slot_specs.${id}`, supplied, embedded, "use_layout_slot_values", `slot_specs[${id}] may override location only; type, required, and capacity must remain unchanged.`, { slot_id: id }, false));
        }
      }
    }
  }

  const slots = (suppliedSlots ?? baseSlots).map(publicSlot);
  const seen = new Set();
  for (const [index, slot] of slots.entries()) {
    if (!slot.slot_id || !slot.slot_type || !isRecord(slot.capacity)) {
      errors.push(layoutViolation("INVALID_LAYOUT_SPEC", `slot_specs[${index}]`, slot, "slot_id, slot_type, required, capacity", "provide_valid_slot_spec", "Every slot spec needs slot_id, slot_type, required, and capacity.", { index }, false));
      continue;
    }
    if (seen.has(slot.slot_id)) {
      errors.push(layoutViolation("INVALID_LAYOUT_SPEC", `slot_specs[${index}].slot_id`, slot.slot_id, "unique slot_id", "remove_duplicate_slot", `slot_id ${slot.slot_id} is defined more than once.`, { slot_id: slot.slot_id }, false));
    }
    seen.add(slot.slot_id);
    for (const key of ["max_chars", "max_chars_at_absolute_min", "max_lines", "max_items", "max_count"]) {
      if (!own(slot.capacity, key) || slot.capacity[key] === null || slot.capacity[key] === undefined) continue;
      const number = Number(slot.capacity[key]);
      if (!Number.isFinite(number) || number < 0) {
        errors.push(layoutViolation("INVALID_LAYOUT_SPEC", `slot_specs.${slot.slot_id}.capacity.${key}`, slot.capacity[key], "non-negative number or null", "provide_valid_capacity", "Slot capacity values must be non-negative numbers or null.", { slot_id: slot.slot_id, key }, false));
      }
    }
  }
  if (!slots.length) errors.push(layoutViolation("INVALID_LAYOUT_SPEC", "slot_specs", slots, "at least one slot", "provide_non_empty_slot_specs", "A layout must contain at least one slot.", undefined, false));
  if (!layoutId) errors.push(layoutViolation("INVALID_LAYOUT_SPEC", "layout_id", layoutId, "non-empty layout id", "provide_layout_id", "layout_spec must identify the layout.", undefined, false));
  if (embeddedLayoutId && requestedLayoutId && embeddedLayoutId !== requestedLayoutId) {
    errors.push(layoutViolation("INVALID_LAYOUT_SPEC", "layout_id", embeddedLayoutId, requestedLayoutId, "use_the_selected_layout", "layout_spec id must match the selected layout_id.", { expected_layout_id: requestedLayoutId, actual_layout_id: embeddedLayoutId }, false));
  }

  const readingOrder = new Map(arrayValue(layout?.reading_order).map((id, index) => [stringValue(id), index]));
  const ordered = slots.map((slot, index) => ({ slot, key: slotSortKey(slot, index, readingOrder), index }));
  ordered.sort(compareSlots);
  return {
    layout_id: layoutId,
    slots,
    ordered,
    byId: new Map(slots.map((slot) => [slot.slot_id, slot])),
    readingOrder,
    errors,
    slot_specs: clone(suppliedSlots ?? baseSlots),
  };
}

function textFromValue(value) {
  if (typeof value === "string" || typeof value === "number") return String(value).trim();
  if (!isRecord(value)) return "";
  for (const key of ["text", "claim_text", "evidence_text", "description", "label", "title", "caption", "heading", "name", "goal", "takeaway", "question", "note", "value"]) {
    if (typeof value[key] === "string" || typeof value[key] === "number") {
      const text = String(value[key]).trim();
      if (text) return text;
    }
  }
  return "";
}

function itemId(value, fallback) {
  if (isRecord(value)) {
    const found = firstPresent(value, ["content_id", "contentId", "id", "evidence_id", "citation_id", "visual_id", "step_id", "event_id", "dimension_id", "series_id"]);
    const result = stringValue(found);
    if (result) return result;
  }
  return fallback;
}

function explicitSlot(value) {
  return isRecord(value) ? stringValue(firstPresent(value, ["slot_id", "slotId"])) : "";
}

function contentRole(value, fallback) {
  return stringValue(firstPresent(value ?? {}, ["content_role", "contentRole", "role"])) || fallback;
}

function mustKeep(value) {
  return isRecord(value) && (value.must_keep === true || value.mustKeep === true || value.must_keep === "true" || value.mustKeep === "true");
}

function makeItem({ field, value, index, slideId, type, role, structural = false, allowTrim = false, preferredSlotTypes = [] }) {
  const id = itemId(value, `${slideId || "slide"}:${field}:${index + 1}`);
  const rawType = type;
  return {
    content_id: id,
    field,
    index,
    value: clone(value),
    type: rawType,
    role: contentRole(value, role),
    structural: Boolean(structural),
    must_keep: mustKeep(value),
    allow_trim: Boolean(allowTrim),
    preferred_slot_types: preferredSlotTypes,
    explicit_slot_id: explicitSlot(value),
    text: textFromValue(value),
  };
}

function briefField(brief, snake, camel = snake) {
  return firstPresent(brief, [snake, camel]);
}

function collectContentItems(brief) {
  const slideId = stringValue(firstPresent(brief, ["slide_id", "slideId", "id"])) || "slide";
  const items = [];
  const pushArray = (field, type, role, options = {}) => {
    const values = arrayValue(briefField(brief, field, options.camel ?? field));
    values.forEach((value, index) => items.push(makeItem({ field, value, index, slideId, type, role, ...options })));
  };

  const title = stringValue(briefField(brief, "title"));
  if (title) items.push(makeItem({ field: "title", value: title, index: 0, slideId, type: "text", role: "title", allowTrim: false, preferredSlotTypes: ["title", "text"] }));

  const scalarFields = [
    ["goal", "context", false, ["text", "callout"]],
    ["takeaway", "primary_claim", false, ["callout", "text"]],
    ["question", "question", false, ["question", "text"]],
    ["notes", "context", true, ["text", "caption"]],
    // body is the page's full prose (the scientific argument). It binds into a
    // "text" slot and is trimmable so an over-long paragraph truncates rather
    // than failing the whole page.
    ["body", "context", true, ["text"]],
  ];
  for (const [field, role, allowTrim, preferred] of scalarFields) {
    const value = stringValue(briefField(brief, field));
    if (value) items.push(makeItem({ field, value, index: 0, slideId, type: "text", role, allowTrim, preferredSlotTypes: preferred }));
  }

  pushArray("claims", "text", "primary_claim", { structural: false, allowTrim: false, preferredSlotTypes: ["callout", "text"] });
  for (const [field, camel] of [["key_points", "keyPoints"], ["secondary_messages", "secondaryMessages"]]) {
    const values = arrayValue(briefField(brief, field, camel));
    const rows = values.map(textFromValue).filter(Boolean);
    if (rows.length) {
      items.push(makeItem({
        field,
        value: { text: rows.join("\n"), items: clone(values) },
        index: 0,
        slideId,
        type: "text",
        role: "supporting_detail",
        structural: false,
        allowTrim: false,
        preferredSlotTypes: ["text", "callout"],
      }));
    }
  }
  pushArray("process_steps", "process", "process", { structural: true, camel: "processSteps", preferredSlotTypes: ["process"] });
  pushArray("timeline_events", "timeline", "timeline", { structural: true, camel: "timelineEvents", preferredSlotTypes: ["timeline"] });
  pushArray("timeline", "timeline", "timeline", { structural: true, preferredSlotTypes: ["timeline"] });
  pushArray("comparison_dimensions", "comparison", "comparison", { structural: true, camel: "comparisonDimensions", preferredSlotTypes: ["comparison"] });
  pushArray("comparisons", "comparison", "comparison", { structural: true, preferredSlotTypes: ["comparison"] });
  pushArray("experiment_groups", "experiment", "experiment", { structural: true, camel: "experimentGroups", preferredSlotTypes: ["experiment", "table", "text"] });
  pushArray("data_series", "data_series", "data_series", { structural: true, camel: "dataSeries", preferredSlotTypes: ["chart", "table"] });

  const visuals = arrayValue(briefField(brief, "visuals"));
  visuals.forEach((visual, index) => {
    const visualType = stringValue(firstPresent(visual ?? {}, ["visual_type", "visualType", "type"])).toLowerCase();
    const type = visualType.includes("chart") || visualType === "plot" || visualType === "graph"
      ? "chart"
      : visualType.includes("table") ? "table" : "image";
    items.push(makeItem({
      field: "visuals",
      value: visual,
      index,
      slideId,
      type,
      role: contentRole(visual, "optional_visual"),
      structural: false,
      allowTrim: true,
      preferredSlotTypes: [type, "image"],
    }));
  });

  const citationIds = arrayValue(briefField(brief, "citation_ids", "citationIds"));
  citationIds.forEach((citationId, index) => items.push(makeItem({
    field: "citation_ids",
    value: { citation_id: stringValue(citationId), citation_ids: [stringValue(citationId)] },
    index,
    slideId,
    type: "reference",
    role: "mandatory_citation",
    structural: true,
    allowTrim: false,
    preferredSlotTypes: ["reference", "citation", "text"],
  })));

  const evidenceIds = arrayValue(briefField(brief, "evidence_ids", "evidenceIds"));
  evidenceIds.forEach((evidenceId, index) => items.push(makeItem({
    field: "evidence_ids",
    value: { evidence_id: stringValue(evidenceId), evidence_ids: [stringValue(evidenceId)] },
    index,
    slideId,
    type: "evidence",
    role: "primary_evidence",
    structural: true,
    allowTrim: false,
    preferredSlotTypes: ["reference", "citation", "text"],
  })));

  return items.filter((item) => item.content_id || item.text || isRecord(item.value));
}

function genericPlanningBrief(brief) {
  return brief?.generic === true
    || brief?.planning_mode === "guidance"
    || brief?.metadata?.generic_planning === true
    || brief?.metadata?.planning_mode === "guidance";
}

function slotSemanticRoles(slot) {
  return new Set([slot.slot_id, slot.raw_slot_type, slot.slot_type, stringValue(slot.label_zh).toLowerCase()].filter(Boolean));
}

function slotAcceptsItem(slot, item) {
  const slotType = slot.slot_type;
  if (item.type === "guidance") return true;
  if (item.type === "image") return ["image", "figure", "visual"].includes(slotType) || (slotType === "chart" && item.preferred_slot_types.includes("chart"));
  if (item.type === "chart") return slotType === "chart" || slotType === "image";
  if (item.type === "table") return slotType === "table" || slotType === "image";
  if (item.type === "reference") return ["text", "reference", "citation"].includes(slotType);
  if (item.type === "evidence") return ["text", "reference", "citation"].includes(slotType);
  if (item.type === "process" || item.type === "timeline" || item.type === "comparison" || item.type === "experiment" || item.type === "data_series") {
    const structuralText = slotType === "text" && slot.raw_slot_type !== "title" && slot.slot_id !== "title";
    return slotType === item.type
      || (item.type === "comparison" && structuralText)
      || (item.type === "experiment" && (slotType === "table" || structuralText))
      || (item.type === "data_series" && ["chart", "table"].includes(slotType));
  }
  if (item.type === "text") {
    if (slotType === "text") return true;
    return item.preferred_slot_types.includes(slotType) || item.preferred_slot_types.some((type) => slotSemanticRoles(slot).has(type));
  }
  return false;
}

function itemSlotAffinity(slot, item) {
  const roles = slotSemanticRoles(slot);
  if (item.field === "title" && roles.has("title")) return 100;
  if (item.preferred_slot_types.some((type) => roles.has(type))) return 90;
  if (item.type === slot.slot_type) return 80;
  if (item.type === "text" && slot.slot_type === "text") return 50;
  if (item.type === "image" && slot.slot_type === "image") return 70;
  return 0;
}

function candidateSlots(layout, item, occupied) {
  return layout.ordered
    .filter(({ slot }) => !occupied.has(slot.slot_id) && slotAcceptsItem(slot, item))
    .map(({ slot, key, index }) => ({ slot, key, index, affinity: itemSlotAffinity(slot, item) }))
    .sort((a, b) => b.affinity - a.affinity || compareSlots(a, b));
}

export function assignmentHasContent(value) {
  if (!isRecord(value)) return false;
  for (const key of ["text", "asset_uri", "uri", "visual_id", "content_id", "citation_id", "citation_ids", "evidence_id", "evidence_ids", "items", "content", "value", "visual", "guidance"]) {
    const child = value[key];
    if (Array.isArray(child) ? child.length > 0 : child !== undefined && child !== null && String(child).length > 0) return true;
  }
  return Object.keys(value).some((key) => !["type", "slot_id", "slotId"].includes(key) && value[key] !== undefined && value[key] !== null);
}

function assignmentContentIds(assignment) {
  if (!isRecord(assignment)) return [];
  const ids = [];
  for (const key of ["content_id", "contentId", "visual_id", "visualId", "evidence_id", "evidenceId", "citation_id", "citationId"]) {
    const value = stringValue(assignment[key]);
    if (value) ids.push(value);
  }
  for (const key of ["evidence_ids", "evidenceIds", "citation_ids", "citationIds"]) {
    if (Array.isArray(assignment[key])) for (const value of assignment[key]) if (stringValue(value)) ids.push(stringValue(value));
  }
  if (isRecord(assignment.visual)) ids.push(...assignmentContentIds(assignment.visual));
  return [...new Set(ids)];
}

// Content IDs determine exclusive slot ownership. Evidence and citation IDs
// are traceability references and may legitimately appear in multiple slots.
function assignmentOwnershipIds(assignment) {
  if (!isRecord(assignment)) return [];
  const ids = [];
  for (const key of ["content_id", "contentId", "visual_id", "visualId"]) {
    const value = stringValue(assignment[key]);
    if (value) ids.push(value);
  }
  if (isRecord(assignment.visual)) ids.push(...assignmentOwnershipIds(assignment.visual));
  return [...new Set(ids)];
}

function assignmentText(value) {
  if (!isRecord(value)) return "";
  if (typeof value.text === "string") return value.text;
  if (typeof value.caption === "string") return value.caption;
  if (typeof value.description === "string") return value.description;
  if (typeof value.guidance === "string") return value.guidance;
  return "";
}

function makeAssignment(item) {
  const value = item.value;
  const assignment = isRecord(value) ? clone(value) : {};
  delete assignment.slot_id;
  delete assignment.slotId;
  delete assignment.type;
  const text = item.text;
  if (text && !assignment.text && item.type !== "image" && item.type !== "chart" && item.type !== "table") assignment.text = text;
  if (item.type === "image" || item.type === "chart" || item.type === "table") {
    assignment.visual = clone(value);
    if (!assignment.asset_uri && !assignment.uri && !assignment.visual_id && !assignment.visualId) assignment.visual_id = item.content_id;
    if (text && !assignment.text && (value?.caption || value?.description)) assignment.text = text;
  }
  if (item.type === "reference") {
    assignment.citation_ids = [stringValue(value.citation_id) || item.content_id];
  }
  if (item.type === "evidence") {
    assignment.evidence_ids = [stringValue(value.evidence_id) || item.content_id];
  }
  assignment.type = ["reference", "evidence"].includes(item.type) ? "reference" : item.type;
  assignment.content_id = item.content_id;
  if (item.role) assignment.content_role = item.role;
  return assignment;
}

function guideForSlot(slot, brief) {
  const title = stringValue(briefField(brief, "title"));
  if (slot.slot_id === "title" && title) return title;
  const label = stringValue(slot.label_zh) || slot.slot_id;
  const byType = {
    image: "放置与本页结论直接相关的图像或实验图",
    chart: "放置支持本页结论的数据图表",
    table: "放置结构化数值或实验设置",
    process: "写明阶段、动作或输入输出",
    timeline: "写明里程碑、时间或当前进度",
    question: "写出需要回答或讨论的问题",
    text: "用短句解释证据、机制或条件",
  };
  return byType[slot.slot_type] ?? `填入${label}内容`;
}

function logTrim(log, item, before, after, slot) {
  log.push(adaptation({
    action: "truncate_text",
    content_id: item.content_id,
    reason: "slot_capacity",
    before_chars: [...before].length,
    after_chars: [...after].length,
    before,
    after,
    details: { field: item.field, slot_id: slot.slot_id },
  }));
}

function adaptAssignmentToCapacity(assignment, item, slot, logs, violations) {
  const maxChars = capacityNumber(slot, ["max_chars", "max_chars_at_min_font", "max_chars_at_absolute_min"]);
  if (maxChars === undefined) return;
  const textKey = typeof assignment.text === "string" ? "text" : typeof assignment.caption === "string" ? "caption" : typeof assignment.description === "string" ? "description" : undefined;
  if (!textKey) return;
  const before = assignment[textKey];
  if ([...before].length <= maxChars) return;
  if (!item.allow_trim) {
    violations.push(layoutViolation(
      item.field === "process_steps" ? "PROCESS_CAPACITY_EXCEEDED" : "SLOT_CAPACITY_EXCEEDED",
      `${item.field}[${item.index}]`,
      [...before].length,
      maxChars,
      "replan_or_split",
      `${item.content_id} cannot be safely trimmed for slot ${slot.slot_id}.`,
      { content_id: item.content_id, slot_id: slot.slot_id },
    ));
    return;
  }
  const after = truncateTextDeterministically(before, maxChars);
  assignment[textKey] = after;
  logTrim(logs, item, before, after, slot);
}

function explicitAssignmentError(violations, code, field, actual, capacity, message, details) {
  violations.push(layoutViolation(code, field, actual, capacity, "fix_explicit_slot_assignment", message, details, false));
}

function dedupeViolations(violations) {
  const seen = new Set();
  return violations.filter((violation) => {
    const key = JSON.stringify([violation.code, violation.field, violation.details, violation.actual, violation.capacity]);
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

/**
 * Truncate by Unicode code points. A sentence boundary in the final 30% of
 * the allowed range wins; otherwise a bounded hard cut with an ellipsis is
 * used. The returned string is always at most maxChars code points.
 */
export function truncateTextDeterministically(text, maxChars) {
  const value = String(text ?? "");
  const codePoints = [...value];
  const numericLimit = Number(maxChars);
  if (!Number.isFinite(numericLimit)) return value;
  const limit = Math.max(0, Math.floor(numericLimit));
  if (limit === 0) return "";
  if (codePoints.length <= limit) return value;
  const lower = Math.ceil(limit * 0.70);
  const boundaryCharacters = new Set(["。", "！", "？", "!", "?", "；", ";", "\n", "\r"]);
  let boundary = -1;
  for (let index = lower - 1; index < Math.min(limit, codePoints.length); index += 1) {
    if (boundaryCharacters.has(codePoints[index])) boundary = index + 1;
  }
  if (boundary > 0) return codePoints.slice(0, boundary).join("").trimEnd();
  if (limit <= 2) return "…".slice(0, limit);
  return `${codePoints.slice(0, limit - 3).join("")}...`;
}

function validateLayoutAndInput(input) {
  const layout = normalizeLayout(input);
  const violations = [...layout.errors];
  const brief = input.slide_brief;
  if (!isRecord(brief)) violations.push(layoutViolation("INVALID_INPUT", "slide_brief", brief, "object", "provide_slide_brief", "slide_brief must be an object.", undefined, false));
  return { layout, brief, violations };
}

function missingStructuralViolation(item, layout) {
  const countByType = new Map();
  for (const slot of layout.slots) countByType.set(slot.slot_type, (countByType.get(slot.slot_type) ?? 0) + 1);
  const codeByType = {
    process: "PROCESS_CAPACITY_EXCEEDED",
    timeline: "TIMELINE_CAPACITY_EXCEEDED",
    comparison: "COMPARISON_CAPACITY_EXCEEDED",
    experiment: "EXPERIMENT_GROUP_CAPACITY_EXCEEDED",
    data_series: "DATA_SERIES_CAPACITY_EXCEEDED",
    reference: "CITATION_CAPACITY_EXCEEDED",
    evidence: "EVIDENCE_CAPACITY_EXCEEDED",
  };
  return layoutViolation(
    codeByType[item.type] ?? "SLOT_CAPACITY_EXCEEDED",
    item.field,
    item.index + 1,
    countByType.get(item.type) ?? 0,
    "replan_or_split",
    `No compatible slot remains for ${item.content_id}.`,
    { content_id: item.content_id, slot_type: item.type },
  );
}

function explicitItemViolations(items, layout, assignments, violations) {
  const claimedSlots = new Map();
  for (const item of items) {
    if (!item.explicit_slot_id) continue;
    const slot = layout.byId.get(item.explicit_slot_id);
    if (!slot) {
      explicitAssignmentError(violations, "INVALID_EXPLICIT_SLOT", `${item.field}[${item.index}].slot_id`, item.explicit_slot_id, [...layout.byId.keys()], `Explicit content references unknown slot ${item.explicit_slot_id}.`, { slot_id: item.explicit_slot_id, content_id: item.content_id });
      continue;
    }
    if (!slotAcceptsItem(slot, item)) {
      explicitAssignmentError(violations, "SLOT_TYPE_MISMATCH", `${item.field}[${item.index}].slot_id`, item.type, slot.slot_type, `Explicit content ${item.content_id} is incompatible with slot ${item.explicit_slot_id}.`, { slot_id: item.explicit_slot_id, content_id: item.content_id });
    }
    if (claimedSlots.has(item.explicit_slot_id) || assignments.has(item.explicit_slot_id)) {
      explicitAssignmentError(violations, "DUPLICATE_SLOT_OWNERSHIP", `${item.field}[${item.index}].slot_id`, item.explicit_slot_id, "one owner", `Slot ${item.explicit_slot_id} is explicitly claimed more than once.`, { slot_id: item.explicit_slot_id, content_id: item.content_id });
    } else {
      claimedSlots.set(item.explicit_slot_id, item);
    }
  }
  return claimedSlots;
}

function inspectExplicitAssignments(input, layout, assignments, violations, allowGuidance) {
  const source = input.slot_assignments;
  if (source === undefined) return new Map();
  if (!isRecord(source)) {
    explicitAssignmentError(violations, "INVALID_SLOT_ASSIGNMENTS", "slot_assignments", source, "object keyed by slot_id", "slot_assignments must be an object keyed by slot_id.");
    return new Map();
  }
  const contentOwners = new Map();
  for (const [slotId, rawAssignment] of Object.entries(source)) {
    const slot = layout.byId.get(slotId);
    if (!slot) {
      explicitAssignmentError(violations, "INVALID_EXPLICIT_SLOT", `slot_assignments.${slotId}`, slotId, [...layout.byId.keys()], `Explicit assignment references unknown slot ${slotId}.`, { slot_id: slotId });
      continue;
    }
    if (!isRecord(rawAssignment) || typeof rawAssignment.type !== "string" || !assignmentHasContent(rawAssignment)) {
      explicitAssignmentError(violations, "INVALID_SLOT_ASSIGNMENT", `slot_assignments.${slotId}`, rawAssignment, "non-empty assignment with type", `slot_assignments.${slotId} must contain a type and non-empty content.`, { slot_id: slotId });
      continue;
    }
    const type = canonicalAssignmentType(rawAssignment.type);
    const item = { type, preferred_slot_types: [type] };
    if (type === "guidance" && !allowGuidance) {
      explicitAssignmentError(violations, "INVALID_SLOT_ASSIGNMENT", `slot_assignments.${slotId}.type`, rawAssignment.type, "guidance only for generic planning content", "guidance assignments require an explicitly generic planning brief.", { slot_id: slotId });
    }
    if (!slotAcceptsItem(slot, item) && type !== "guidance") {
      explicitAssignmentError(violations, "SLOT_TYPE_MISMATCH", `slot_assignments.${slotId}.type`, rawAssignment.type, slot.slot_type, `Assignment type ${rawAssignment.type} is incompatible with slot ${slotId}.`, { slot_id: slotId });
    }
    for (const contentId of assignmentOwnershipIds(rawAssignment)) {
      if (contentOwners.has(contentId)) {
        explicitAssignmentError(violations, "DUPLICATE_SLOT_OWNERSHIP", `slot_assignments.${slotId}`, contentId, "one slot owner", `Content ${contentId} is assigned to more than one slot.`, { content_id: contentId, slot_id: slotId });
      } else contentOwners.set(contentId, slotId);
    }
    assignments.set(slotId, clone(rawAssignment));
  }
  return contentOwners;
}

function visualSelection(items, layout, assignments, logs, violations) {
  const visuals = items.filter((item) => item.field === "visuals");
  const selected = new Set();
  const occupied = new Set(assignments.keys());
  const explicit = visuals.filter((item) => item.explicit_slot_id);
  const automatic = visuals.filter((item) => !item.explicit_slot_id).sort((a, b) => Number(b.must_keep) - Number(a.must_keep) || (Number(a.value?.importance ?? Infinity) - Number(b.value?.importance ?? Infinity)) || a.index - b.index);

  for (const item of explicit) {
    const slot = layout.byId.get(item.explicit_slot_id);
    if (!slot || !slotAcceptsItem(slot, item)) continue;
    if (occupied.has(slot.slot_id)) continue;
    assignments.set(slot.slot_id, makeAssignment(item));
    occupied.add(slot.slot_id);
    selected.add(item.content_id);
  }

  for (const item of automatic) {
    const candidates = candidateSlots(layout, item, occupied);
    const candidate = candidates[0];
    if (candidate) {
      assignments.set(candidate.slot.slot_id, makeAssignment(item));
      occupied.add(candidate.slot.slot_id);
      selected.add(item.content_id);
      continue;
    }
    if (item.must_keep) {
      violations.push(layoutViolation("FIGURE_CAPACITY_EXCEEDED", "visuals", visuals.length, layout.slots.filter((slot) => ["image", "chart", "table"].includes(slot.slot_type)).length, "replan_or_split", `Must-keep visual ${item.content_id} cannot fit the layout.`, { content_id: item.content_id }));
    } else {
      logs.push(adaptation({ action: "drop_optional_visual", content_id: item.content_id, reason: "visual_capacity", before: clone(item.value), after: null, details: { importance: item.value?.importance ?? null } }));
    }
  }
  return selected;
}

function finalAssignmentOrder(assignments, layout) {
  return Object.fromEntries(layout.ordered.filter(({ slot }) => assignments.has(slot.slot_id)).map(({ slot }) => [slot.slot_id, assignments.get(slot.slot_id)]));
}

function mergeTraceabilityAssignment(item, assignments, layout) {
  if (!["reference", "evidence"].includes(item.type)) return false;
  const candidates = [...assignments.entries()]
    .map(([slotId, assignment], index) => ({ slotId, assignment, slot: layout.byId.get(slotId), index }))
    .filter(({ slot, assignment }) => slot && slotAcceptsItem(slot, item) && canonicalAssignmentType(assignment?.type) === "text")
    .sort((left, right) => {
      const leftReference = String(left.assignment?.type).toLowerCase() === "reference" ? 1 : 0;
      const rightReference = String(right.assignment?.type).toLowerCase() === "reference" ? 1 : 0;
      const leftSemantic = slotSemanticRoles(left.slot).has("reference") || slotSemanticRoles(left.slot).has("citation") ? 1 : 0;
      const rightSemantic = slotSemanticRoles(right.slot).has("reference") || slotSemanticRoles(right.slot).has("citation") ? 1 : 0;
      return rightReference - leftReference || rightSemantic - leftSemantic || left.index - right.index;
    });
  for (const { assignment } of candidates) {
    const key = item.type === "reference" ? "citation_ids" : "evidence_ids";
    const current = arrayValue(assignment[key]);
    if (!current.includes(item.content_id)) assignment[key] = [...current, item.content_id];
    return true;
  }
  return false;
}

function addMissingRequiredSlots(layout, assignments, violations) {
  for (const slot of layout.slots) {
    if (slot.required && (!assignments.has(slot.slot_id) || !assignmentHasContent(assignments.get(slot.slot_id)))) {
      violations.push(layoutViolation("MISSING_REQUIRED_SLOT", "slot_assignments", slot.slot_id, "assigned content", "replan_or_split", `Required slot ${slot.slot_id} is not assigned.`, { slot_id: slot.slot_id }));
    }
  }
}

function statusFrom(violations, logs) {
  const hardFailure = violations.some((violation) => ["INVALID_INPUT", "INVALID_LAYOUT_SPEC", "INVALID_EXPLICIT_SLOT", "INVALID_SLOT_ASSIGNMENTS", "INVALID_SLOT_ASSIGNMENT", "SLOT_TYPE_MISMATCH", "DUPLICATE_SLOT_OWNERSHIP"].includes(violation.code));
  if (hardFailure) return "failed";
  if (violations.length) return "needs_replan";
  return logs.length ? "adapted" : "success";
}

/**
 * Bind content to a fixed public layout. Layout selection is deliberately
 * outside this module: a capacity failure returns needs_replan instead of
 * silently choosing a different layout.
 */
export function bindSlideToLayout(input = {}) {
  const { layout, brief, violations } = validateLayoutAndInput(input);
  const logs = [];
  const assignments = new Map();
  const output = {
    status: "failed",
    layout_id: layout.layout_id || null,
    slot_specs: clone(layout.slot_specs),
    slot_assignments: {},
    adaptation_log: logs,
    violations,
  };
  if (violations.some((violation) => !violation.recoverable) || !isRecord(brief)) return output;

  const items = collectContentItems(brief);
  const owners = inspectExplicitAssignments(input, layout, assignments, violations, genericPlanningBrief(brief));
  for (const ownerSlot of owners.values()) {
    if (layout.byId.has(ownerSlot)) continue;
  }
  const explicitContentSlots = explicitItemViolations(items, layout, assignments, violations);
  for (const [slotId, item] of explicitContentSlots) {
    if (assignments.has(slotId)) continue;
    assignments.set(slotId, makeAssignment(item));
  }

  if (violations.some((violation) => !violation.recoverable)) {
    output.slot_assignments = finalAssignmentOrder(assignments, layout);
    output.status = "failed";
    return output;
  }

  const selectedVisuals = visualSelection(items, layout, assignments, logs, violations);
  const assignedIds = new Set([...owners.keys(), ...selectedVisuals]);
  for (const [slotId, item] of explicitContentSlots) assignedIds.add(item.content_id);
  const occupied = new Set(assignments.keys());
  for (const item of items) {
    if (item.field === "visuals" || assignedIds.has(item.content_id)) continue;
    const candidates = candidateSlots(layout, item, occupied);
    const candidate = candidates[0];
    if (!candidate) {
      if (mergeTraceabilityAssignment(item, assignments, layout)) {
        assignedIds.add(item.content_id);
        continue;
      }
      violations.push(missingStructuralViolation(item, layout));
      continue;
    }
    const assignment = makeAssignment(item);
    adaptAssignmentToCapacity(assignment, item, candidate.slot, logs, violations);
    assignments.set(candidate.slot.slot_id, assignment);
    occupied.add(candidate.slot.slot_id);
    assignedIds.add(item.content_id);
  }

  if (genericPlanningBrief(brief)) {
    for (const { slot } of layout.ordered) {
      if (!slot.required || assignments.has(slot.slot_id)) continue;
      const item = { content_id: `${stringValue(firstPresent(brief, ["slide_id", "slideId", "id"])) || "slide"}:guidance:${slot.slot_id}`, field: "guidance", index: 0, value: guideForSlot(slot, brief), type: "guidance", role: "guidance", allow_trim: true, preferred_slot_types: [slot.slot_type], text: guideForSlot(slot, brief) };
      const assignment = { type: "guidance", text: item.text, content_id: item.content_id, content_role: "guidance" };
      adaptAssignmentToCapacity(assignment, item, slot, logs, violations);
      assignments.set(slot.slot_id, assignment);
    }
  }

  for (const assignment of assignments.values()) {
    const text = assignmentText(assignment);
    if (text && assignment.type !== "guidance") {
      const item = items.find((candidate) => assignmentContentIds(assignment).includes(candidate.content_id));
      if (item) adaptAssignmentToCapacity(assignment, item, layout.byId.get([...assignments.entries()].find(([, value]) => value === assignment)?.[0]), logs, violations);
    }
  }
  addMissingRequiredSlots(layout, assignments, violations);
  output.slot_assignments = finalAssignmentOrder(assignments, layout);
  output.adaptation_log = logs;
  output.violations = dedupeViolations(violations);
  const contract = validateSlotBindingContract({ ...input, layout_spec: input.layout_spec, slot_specs: output.slot_specs, slot_assignments: output.slot_assignments, adaptation_log: logs, slide_brief: brief });
  output.contract_valid = contract.valid;
  output.contract_violations = contract.violations;
  output.violations = dedupeViolations([...output.violations, ...contract.violations.filter((violation) => !output.violations.some((existing) => JSON.stringify(existing) === JSON.stringify(violation)))]);
  output.status = statusFrom(output.violations, logs);
  return output;
}

function assignmentMatchesExpected(item, assignments) {
  const values = assignments instanceof Map ? [...assignments.values()] : Object.values(assignments ?? {});
  return values.some((assignment) => assignmentContentIds(assignment).includes(item.content_id));
}

function validateAssignmentCapacity(slot, assignment, violations) {
  const text = assignmentText(assignment);
  const maxChars = capacityNumber(slot, ["max_chars", "max_chars_at_min_font", "max_chars_at_absolute_min"]);
  if (text && maxChars !== undefined && [...text].length > maxChars) violations.push(layoutViolation("SLOT_CAPACITY_EXCEEDED", `slot_assignments.${slot.slot_id}`, [...text].length, maxChars, "replan_or_split", `Assignment in ${slot.slot_id} exceeds its text capacity.`, { slot_id: slot.slot_id }));
  const maxItems = capacityNumber(slot, ["max_items", "max_count"]);
  if (maxItems !== undefined && Array.isArray(assignment.items) && assignment.items.length > maxItems) violations.push(layoutViolation("SLOT_CAPACITY_EXCEEDED", `slot_assignments.${slot.slot_id}.items`, assignment.items.length, maxItems, "replan_or_split", `Assignment in ${slot.slot_id} exceeds its item capacity.`, { slot_id: slot.slot_id }));
}

/**
 * Validate the Planner -> Binding contract without importing the planner or
 * renderer. The return shape intentionally includes both valid and status so
 * callers can use either the boolean or the existing status vocabulary.
 */
export function validateSlotBindingContract(input = {}) {
  const layoutInput = input.layout_spec ? input : { ...input, layout_spec: { id: input.layout_id, slot_specs: input.slot_specs } };
  const { layout, brief, violations } = validateLayoutAndInput(layoutInput);
  const assignments = input.slot_assignments;
  const assignmentMap = isRecord(assignments) ? assignments : {};
  if (assignments !== undefined && !isRecord(assignments)) violations.push(layoutViolation("INVALID_SLOT_ASSIGNMENTS", "slot_assignments", assignments, "object keyed by slot_id", "provide_slot_assignment_object", "slot_assignments must be an object keyed by slot_id.", undefined, false));

  const seenContent = new Map();
  for (const [slotId, assignment] of Object.entries(assignmentMap)) {
    const slot = layout.byId.get(slotId);
    if (!slot) {
      violations.push(layoutViolation("INVALID_EXPLICIT_SLOT", `slot_assignments.${slotId}`, slotId, [...layout.byId.keys()], "fix_explicit_slot_assignment", `Assignment references unknown slot ${slotId}.`, { slot_id: slotId }, false));
      continue;
    }
    if (!isRecord(assignment) || typeof assignment.type !== "string" || !assignmentHasContent(assignment)) {
      violations.push(layoutViolation("INVALID_SLOT_ASSIGNMENT", `slot_assignments.${slotId}`, assignment, "non-empty assignment with type", "fix_slot_assignment", `Assignment ${slotId} is not a non-empty typed object.`, { slot_id: slotId }, false));
      continue;
    }
    const assignmentType = canonicalAssignmentType(assignment.type);
    if (assignmentType !== "guidance" && !slotAcceptsItem(slot, { type: assignmentType, preferred_slot_types: [assignmentType] })) violations.push(layoutViolation("SLOT_TYPE_MISMATCH", `slot_assignments.${slotId}.type`, assignment.type, slot.slot_type, "fix_slot_assignment_type", `Assignment type ${assignment.type} does not match slot ${slotId}.`, { slot_id: slotId }, false));
    validateAssignmentCapacity(slot, assignment, violations);
    for (const contentId of assignmentOwnershipIds(assignment)) {
      if (seenContent.has(contentId)) violations.push(layoutViolation("DUPLICATE_SLOT_OWNERSHIP", `slot_assignments.${slotId}`, contentId, "one assignment", "fix_duplicate_content_assignment", `Content ${contentId} is owned by multiple slots.`, { content_id: contentId, first_slot_id: seenContent.get(contentId), slot_id: slotId }, false));
      else seenContent.set(contentId, slotId);
    }
  }
  if (isRecord(brief)) {
    for (const slot of layout.slots) {
      if (slot.required && (!assignmentMap[slot.slot_id] || !assignmentHasContent(assignmentMap[slot.slot_id]))) violations.push(layoutViolation("MISSING_REQUIRED_SLOT", "slot_assignments", slot.slot_id, "assigned content", "assign_required_slot", `Required slot ${slot.slot_id} is missing.`, { slot_id: slot.slot_id }));
    }
    const items = collectContentItems(brief);
    for (const item of items) {
      const owners = Object.entries(assignmentMap).filter(([, assignment]) => assignmentContentIds(assignment).includes(item.content_id)).map(([slotId]) => slotId);
      const preserved = owners.length > 0;
      const optionalVisualDropped = item.field === "visuals" && !item.must_keep && arrayValue(input.adaptation_log).some((entry) => entry.action === "drop_optional_visual" && entry.content_id === item.content_id);
      if (item.explicit_slot_id && owners.length && !owners.includes(item.explicit_slot_id)) {
        violations.push(layoutViolation("INVALID_EXPLICIT_SLOT", `${item.field}[${item.index}].slot_id`, item.explicit_slot_id, owners[0], "preserve_explicit_slot_assignment", `Explicit content ${item.content_id} was bound to ${owners[0]} instead of ${item.explicit_slot_id}.`, { slot_id: item.explicit_slot_id, actual_slot_id: owners[0], content_id: item.content_id }, false));
      }
      if (preserved || optionalVisualDropped) continue;
      if (item.structural || item.must_keep || item.type === "reference" || item.field === "title") {
        violations.push(layoutViolation(item.must_keep ? "MUST_KEEP_CONTENT_DROPPED" : "STRUCTURAL_CONTENT_DROPPED", item.field, item.content_id, "preserved in slot_assignments", "replan_or_split", `Content ${item.content_id} is not represented by a slot assignment.`, { content_id: item.content_id }));
      }
      if (item.explicit_slot_id) {
        if (assignmentMap[item.explicit_slot_id] && !assignmentContentIds(assignmentMap[item.explicit_slot_id]).includes(item.content_id)) violations.push(layoutViolation("INVALID_EXPLICIT_SLOT", `${item.field}[${item.index}].slot_id`, item.explicit_slot_id, item.content_id, "preserve_explicit_slot_assignment", `Explicit content ${item.content_id} was not preserved in ${item.explicit_slot_id}.`, { slot_id: item.explicit_slot_id, content_id: item.content_id }, false));
      }
    }
    const structuralFields = ["process_steps", "timeline_events", "timeline", "comparison_dimensions", "comparisons", "experiment_groups", "data_series"];
    for (const field of structuralFields) {
      const count = arrayValue(briefField(brief, field, field)).length;
      if (!count) continue;
      const type = field === "process_steps" ? "process" : field === "timeline_events" || field === "timeline" ? "timeline" : field === "comparison_dimensions" || field === "comparisons" ? "comparison" : field === "experiment_groups" ? "experiment" : "data_series";
      const capacity = layout.slots.filter((slot) => {
        const structuralText = slot.slot_type === "text" && slot.raw_slot_type !== "title" && slot.slot_id !== "title";
        return slot.slot_type === type
          || (type === "comparison" && structuralText)
          || (type === "experiment" && (slot.slot_type === "table" || structuralText))
          || (type === "data_series" && ["chart", "table"].includes(slot.slot_type));
      }).length;
      if (count > capacity) violations.push(layoutViolation(`${type.toUpperCase()}_CAPACITY_EXCEEDED`, field, count, capacity, "replan_or_split", `${field} exceeds the structural slot capacity.`, { field, actual: count, capacity }));
    }
  }
  const uniqueViolations = dedupeViolations(violations);
  return {
    valid: uniqueViolations.length === 0,
    legal: uniqueViolations.length === 0,
    status: uniqueViolations.length === 0 ? "valid" : "invalid",
    layout_id: layout.layout_id || null,
    slot_specs: clone(layout.slot_specs),
    slot_assignments: clone(assignmentMap),
    violations: uniqueViolations,
  };
}
