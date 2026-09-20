import {
  bindSlideToLayout,
  validateSlotBindingContract,
} from "./slot-binding.mjs";
import { createViolation } from "./content-model.mjs";

export const PLANNING_LOOP_VERSION = "1.0.0";

const own = (value, key) => Object.prototype.hasOwnProperty.call(value, key);
const isRecord = (value) => Boolean(value) && typeof value === "object" && !Array.isArray(value);
const asArray = (value) => (Array.isArray(value) ? value : []);
const clone = (value) => (value === undefined ? undefined : structuredClone(value));

const STRUCTURAL_FIELDS = [
  ["process_steps", "process", "processSteps"],
  ["timeline_events", "timeline", "timelineEvents"],
  ["timeline", "timeline", "timeline"],
  ["comparison_dimensions", "comparison", "comparisonDimensions"],
  ["comparisons", "comparison", "comparisons"],
  ["experiment_groups", "experiment", "experimentGroups"],
  ["data_series", "data_series", "dataSeries"],
];

const VIOLATION_CODES = new Set([
  "PROCESS_CAPACITY_EXCEEDED",
  "TIMELINE_CAPACITY_EXCEEDED",
  "COMPARISON_CAPACITY_EXCEEDED",
  "EXPERIMENT_CAPACITY_EXCEEDED",
  "EXPERIMENT_GROUP_CAPACITY_EXCEEDED",
  "DATA_SERIES_CAPACITY_EXCEEDED",
  "FIGURE_CAPACITY_EXCEEDED",
  "TABLE_CAPACITY_EXCEEDED",
  "CHART_CAPACITY_EXCEEDED",
  "SLOT_CAPACITY_EXCEEDED",
]);

function textValue(value) {
  return typeof value === "string" || typeof value === "number" ? String(value) : "";
}

function first(value, keys) {
  if (!isRecord(value)) return undefined;
  for (const key of keys) if (own(value, key) && value[key] !== undefined && value[key] !== null) return value[key];
  return undefined;
}

function violation(input) {
  return createViolation({
    severity: "error",
    recoverable: true,
    recommended_action: "replan_or_split",
    ...input,
  });
}

function uniqueStrings(values) {
  return [...new Set(asArray(values).map((value) => textValue(value).trim()).filter(Boolean))];
}

function fieldValue(brief, snake, camel) {
  if (!isRecord(brief)) return [];
  const value = first(brief, [snake, camel ?? snake]);
  return Array.isArray(value) ? value : [];
}

function countStructuralItems(brief) {
  const counts = {};
  for (const [field, type, camel] of STRUCTURAL_FIELDS) {
    const count = fieldValue(brief, field, camel).length;
    if (count) counts[type] = Math.max(counts[type] ?? 0, count);
  }
  return counts;
}

function getCapacityValue(source, keys) {
  if (!isRecord(source)) return undefined;
  for (const key of keys) {
    if (!own(source, key) || source[key] === null || source[key] === undefined) continue;
    const value = Number(source[key]);
    if (Number.isFinite(value) && value >= 0) return Math.floor(value);
  }
  return undefined;
}

function slotType(slot) {
  const type = textValue(first(slot, ["slot_type", "type", "slotType"])).toLowerCase();
  if (["title", "subtitle", "meta", "text", "callout", "caption", "question", "reference", "citation", "metadata", "body", "label"].includes(type)) return "text";
  if (["figure", "image", "visual"].includes(type)) return "image";
  return type;
}

function capacitiesFromLayout(layout) {
  const slots = asArray(layout?.slot_specs ?? layout?.slots);
  const result = {};
  for (const slot of slots) {
    const type = slotType(slot);
    if (!type) continue;
    result[type] = (result[type] ?? 0) + 1;
  }
  return result;
}

function capacitiesFromCandidate(candidate) {
  const direct = candidate?.capacity ?? candidate?.capacities;
  const result = {};
  if (isRecord(direct)) {
    const aliases = {
      process: ["process_capacity", "processCapacity"],
      timeline: ["timeline_capacity", "timelineCapacity"],
      comparison: ["comparison_capacity", "comparisonCapacity"],
      experiment: ["experiment_capacity", "experimentCapacity"],
      data_series: ["data_series_capacity", "dataSeriesCapacity"],
      image: ["image_capacity", "visual_capacity", "figure_capacity"],
    };
    for (const [type, keys] of Object.entries(aliases)) {
      const value = getCapacityValue(direct, keys);
      if (value !== undefined) result[type] = value;
    }
  }
  const layoutCapacities = capacitiesFromLayout(candidate?.layout ?? candidate);
  for (const [type, value] of Object.entries(layoutCapacities)) result[type] = Math.max(result[type] ?? 0, value);
  return result;
}

function capacityForType(capacities, type, fallback) {
  if (capacities && Number.isFinite(capacities[type])) return capacities[type];
  return fallback;
}

function briefHasOverload(brief, capacities) {
  const counts = countStructuralItems(brief);
  for (const [type, count] of Object.entries(counts)) {
    const capacity = capacityForType(capacities, type, undefined);
    if (capacity !== undefined && count > capacity) return true;
  }
  return false;
}

function splitCapacityFromOptions(options = {}, type, fallback = 5) {
  const direct = first(options, [`${type}_capacity`, `${type}Capacity`, `max_${type}_per_slide`, `max${type[0].toUpperCase()}${type.slice(1)}PerSlide`]);
  const nested = first(options.capacities, [type, `${type}_capacity`]);
  const value = Number(direct ?? nested ?? options.max_items_per_slide ?? options.maxItemsPerSlide ?? fallback);
  return Number.isFinite(value) && value > 0 ? Math.max(1, Math.floor(value)) : fallback;
}

function splitArray(values, partIndex, partCount, chunkSize) {
  const list = asArray(values);
  if (!list.length) return [];
  const start = Math.min(list.length, partIndex * chunkSize);
  return list.slice(start, Math.min(list.length, start + chunkSize));
}

function fieldListForSplit(brief, field, camel) {
  const list = fieldValue(brief, field, camel);
  return { key: own(brief, field) ? field : camel, values: list };
}

/**
 * Split only when a structural field is over its declared capacity. The
 * operation is deterministic, order preserving, and never discards an item.
 */
export function splitSlideBrief(slideBrief, options = {}) {
  if (!isRecord(slideBrief)) return [];
  const capacities = {};
  for (const [field, type] of STRUCTURAL_FIELDS) capacities[type] = splitCapacityFromOptions(options, type, 5);
  const overloads = [];
  for (const [field, type, camel] of STRUCTURAL_FIELDS) {
    const { key, values } = fieldListForSplit(slideBrief, field, camel);
    const capacity = splitCapacityFromOptions(options, type, capacities[type]);
    if (values.length > capacity) overloads.push({ field, camel, key, type, values, capacity });
  }
  if (!overloads.length) return [clone(slideBrief)];
  const parts = Math.max(...overloads.map((item) => Math.ceil(item.values.length / item.capacity)));
  const title = textValue(first(slideBrief, ["title", "heading"])).trim();
  const parentId = textValue(first(slideBrief, ["slide_id", "slideId", "id"])).trim() || "slide";
  const children = [];
  for (let index = 0; index < parts; index += 1) {
    const child = clone(slideBrief);
    child.slide_id = `${parentId}-part-${index + 1}`;
    delete child.id;
    child.title = title ? `${title}（${index + 1}/${parts}）` : `第 ${index + 1}/${parts} 页`;
    child.metadata = isRecord(child.metadata) ? child.metadata : {};
    child.metadata.planning_split_parent_id = parentId;
    child.metadata.planning_split_index = index + 1;
    child.metadata.planning_split_count = parts;

    for (const [field, type, camel] of STRUCTURAL_FIELDS) {
      const list = fieldValue(slideBrief, field, camel);
      if (!list.length) continue;
      const overloaded = overloads.find((item) => item.field === field);
      const capacity = overloaded?.capacity ?? Math.max(1, Math.ceil(list.length / parts));
      const key = own(slideBrief, field) ? field : camel;
      child[key] = splitArray(list, index, parts, capacity);
    }
    const childCounts = {
      process_step_count: fieldValue(child, "process_steps", "processSteps").length,
      timeline_event_count: Math.max(fieldValue(child, "timeline_events", "timelineEvents").length, fieldValue(child, "timeline", "timeline").length),
      comparison_dimension_count: Math.max(fieldValue(child, "comparison_dimensions", "comparisonDimensions").length, fieldValue(child, "comparisons", "comparisons").length),
      experiment_group_count: fieldValue(child, "experiment_groups", "experimentGroups").length,
      data_series_count: fieldValue(child, "data_series", "dataSeries").length,
    };
    for (const [countField, count] of Object.entries(childCounts)) {
      if (own(slideBrief, countField) || count > 0) child[countField] = count;
    }
    const originalTextChars = Number(first(slideBrief, ["text_chars", "textChars"]));
    if (Number.isFinite(originalTextChars) && originalTextChars >= 0) {
      const start = Math.floor((originalTextChars * index) / parts);
      const end = Math.floor((originalTextChars * (index + 1)) / parts);
      child.text_chars = end - start;
    }
    if (isRecord(first(slideBrief, ["text_chars_by_role", "textCharsByRole"]))) {
      child.text_chars_by_role = {};
      for (const [role, rawCount] of Object.entries(first(slideBrief, ["text_chars_by_role", "textCharsByRole"]))) {
        const count = Number(rawCount);
        if (!Number.isFinite(count) || count < 0) continue;
        const start = Math.floor((count * index) / parts);
        const end = Math.floor((count * (index + 1)) / parts);
        child.text_chars_by_role[role] = end - start;
      }
    }
    child.title_chars = [...child.title].length;
    const durationWeight = Number(first(slideBrief, ["duration_weight", "durationWeight"]));
    if (Number.isFinite(durationWeight) && durationWeight > 0) child.duration_weight = durationWeight / parts;
    children.push(child);
  }
  return children;
}

function candidateId(candidate) {
  return textValue(first(candidate, ["layout_id", "layoutId", "id"])).trim()
    || textValue(first(candidate?.layout ?? {}, ["layout_id", "layoutId", "id"])).trim();
}

function candidateLayout(candidate, fetched) {
  if (isRecord(fetched?.layout)) return fetched.layout;
  if (isRecord(fetched) && (Array.isArray(fetched.slot_specs) || Array.isArray(fetched.slots))) return fetched;
  if (isRecord(candidate?.layout)) return candidate.layout;
  return candidate;
}

function resultCandidates(searchResult) {
  if (Array.isArray(searchResult)) return searchResult;
  return asArray(searchResult?.results ?? searchResult?.layouts ?? searchResult?.candidates);
}

function capacityEvidence(searchResult, candidates) {
  const values = [];
  for (const candidate of candidates) values.push(capacitiesFromCandidate(candidate));
  for (const excluded of asArray(searchResult?.compatibility?.excluded_layouts)) values.push(capacitiesFromCandidate(excluded));
  const max = {};
  for (const current of values) for (const [type, capacity] of Object.entries(current)) max[type] = Math.max(max[type] ?? 0, capacity);
  return max;
}

/**
 * RPA-1: 解析单个 visual 的宽高比。
 * 优先使用显式声明的 visual_aspect_ratio / aspect_ratio，
 * 缺失时回退到源像素尺寸 source_width_px / source_height_px 推导。
 */
function visualAspectRatioOf(visual) {
  if (!isRecord(visual)) return undefined;
  for (const key of ["visual_aspect_ratio", "aspect_ratio", "visualAspectRatio", "aspectRatio"]) {
    const value = Number(visual[key]);
    if (Number.isFinite(value) && value > 0) return value;
  }
  const width = Number(first(visual, ["source_width_px", "sourceWidthPx"]));
  const height = Number(first(visual, ["source_height_px", "sourceHeightPx"]));
  if (Number.isFinite(width) && Number.isFinite(height) && width > 0 && height > 0) return width / height;
  return undefined;
}

/**
 * RPA-1: 取"主导"宽高比——即约束最强（最偏离 1）的那个 visual，
 * 因为把它塞进不匹配的槽位造成的空白最多。
 */
function dominantVisualAspectRatio(visuals, fallback) {
  const ratios = asArray(visuals).map(visualAspectRatioOf).filter((value) => Number.isFinite(value) && value > 0);
  const explicit = Number(fallback);
  if (Number.isFinite(explicit) && explicit > 0) return explicit;
  if (!ratios.length) return undefined;
  return ratios.reduce((worst, current) => (
    Math.abs(Math.log(current)) > Math.abs(Math.log(worst)) ? current : worst
  ), ratios[0]);
}

/**
 * RPA-5: 从 slide brief 正文中识别"语义类别信号"。
 * 解决 category_hint 与正文语义冲突（如把 Arrhenius 外推这类机理内容标成 decision）
 * 时，选型被 hint 单点绑死、选到语义错位版面的问题。
 */
const SEMANTIC_SIGNALS = [
  {
    category: "theory",
    label_zh: "理论 / 机制推导",
    patterns: [
      /机理|机制|推导|外推|理论|定理|定律|本构|解析解|近似假设|假设推导/i,
      /公式|方程|方程组|微分方程|表达式|解析式|闭式解/i,
      /Arrhenius|活化能|扩散系数|玻尔兹曼|Boltzmann|能垒|势垒|跃迁速率/i,
      /标度律|幂律|指数律|相关系数|拟合关系|经验公式/i,
    ],
  },
  {
    category: "decision",
    label_zh: "方案决策",
    patterns: [
      /决策|取舍|权衡|二选一|方案\s*[AB]|选项\s*[AB]|go\s*\/\s*no-?go/i,
      /建议采用|推荐方案|是否采用|决策依据|选型建议/i,
    ],
  },
  {
    category: "algorithm",
    label_zh: "算法 / 流程",
    patterns: [/算法|伪代码|复杂度|迭代求解|收敛判据|流程图/i],
  },
];

/**
 * 与"理论/机制推导"语义互斥的类别提示：这些类别承载的是结论、决策或结构，
 * 一旦正文真正在做推导/外推，把它们压过去会造成语义错位。
 * 落在清单外的类别（experiment / background / metrics / ablation …）允许
 * 与机制内容共存，不触发改写。
 */
const THEORY_CONFLICTING_HINTS = new Set([
  "decision", "chart_takeaway", "chart_compare", "next_steps", "summary",
  "qualitative", "case", "failure", "weekly", "timeline",
  "agenda", "section", "cover", "qa", "references", "appendix",
]);

/** 至少命中多少组信号才认为语义足够强、值得改写 category hint。 */
const SEMANTIC_CONFLICT_MIN_STRENGTH = 2;

function collectBriefText(value, depth = 0, out = []) {
  if (depth > 4) return out;
  if (typeof value === "string") {
    if (value.trim()) out.push(value);
    return out;
  }
  if (Array.isArray(value)) {
    for (const item of value) collectBriefText(item, depth + 1, out);
    return out;
  }
  if (isRecord(value)) {
    for (const [key, item] of Object.entries(value)) {
      if (["visual_id", "source_visual_id", "source_path", "preview_path", "slide_id"].includes(key)) continue;
      collectBriefText(item, depth + 1, out);
    }
  }
  return out;
}

export function inferSemanticCategory(brief, hintedCategories) {
  const text = collectBriefText(brief).join(" \n ");
  if (!text.trim()) return { category: null, signals: [], conflict: false, hinted_category: null, label_zh: null };
  const scored = [];
  for (const signal of SEMANTIC_SIGNALS) {
    const hits = signal.patterns.filter((pattern) => pattern.test(text));
    if (hits.length) scored.push({ category: signal.category, label_zh: signal.label_zh, strength: hits.length });
  }
  scored.sort((a, b) => b.strength - a.strength);
  const hints = uniqueStrings(hintedCategories);
  const hinted = hints[0] ?? null;
  const top = scored[0] ?? null;
  if (!top) return { category: null, signals: [], conflict: false, hinted_category: hinted, label_zh: null };
  const conflict = Boolean(hinted)
    && top.category !== hinted
    && top.strength >= SEMANTIC_CONFLICT_MIN_STRENGTH
    && (top.category === "theory" ? THEORY_CONFLICTING_HINTS.has(hinted) : false);
  return {
    category: top.category,
    label_zh: top.label_zh,
    signals: scored.map((item) => ({ category: item.category, label_zh: item.label_zh, strength: item.strength })),
    hinted_category: hinted,
    conflict,
  };
}

function queryForBrief(input, brief, excludedIds) {
  const query = {};
  if (isRecord(input)) {
    for (const [key, value] of Object.entries(input)) {
      if (["slide_brief", "allow_auto_split", "max_replan_attempts", "exclude_ids", "excludeIds", "slot_assignments", "adapters", "searchLayouts", "getLayout", "bindSlide"].includes(key)) continue;
      if (value !== undefined) query[key] = clone(value);
    }
  }
  const visuals = asArray(first(brief, ["visuals"]));
  const title = textValue(first(brief, ["title", "heading"]));
  const processSteps = fieldValue(brief, "process_steps", "processSteps");
  const imageCount = visuals.length;
  const textChars = Number(first(brief, ["text_chars", "textChars"]));
  const dominantAspect = dominantVisualAspectRatio(visuals, first(brief, ["visual_aspect_ratio", "visualAspectRatio"]));
  const derived = {
    title_chars: Number.isFinite(Number(first(brief, ["title_chars", "titleChars"]))) ? Number(first(brief, ["title_chars", "titleChars"])) : [...title].length,
    process_step_count: Number.isFinite(Number(first(brief, ["process_step_count", "processStepCount"]))) ? Number(first(brief, ["process_step_count", "processStepCount"])) : processSteps.length,
    image_count: Number.isFinite(Number(first(brief, ["image_count", "imageCount"]))) ? Number(first(brief, ["image_count", "imageCount"])) : imageCount,
    text_chars: Number.isFinite(textChars) ? textChars : undefined,
    content_roles: clone(first(brief, ["content_roles", "contentRoles"])),
    category: first(brief, ["category_hint", "categoryHint", "category"]),
    include_slots: true,
    exclude_ids: [...excludedIds],
  };
  if (visuals.length) derived.visuals = clone(visuals);
  if (dominantAspect !== undefined) derived.visual_aspect_ratio = dominantAspect;
  // RPA-5: 正文语义与 category hint 冲突时，让语义类别优先参与检索。
  derived.semantic_category_signals = inferSemanticCategory(brief, [
    ...asArray(input?.categories ?? input?.category ? [input.category] : []),
    derived.category,
  ]);
  for (const [key, value] of Object.entries(derived)) if (value !== undefined) query[key] = value;
  const categoryHints = uniqueStrings(input?.category_hints ?? input?.categoryHints);
  if (!query.categories && categoryHints.length) query.categories = categoryHints;
  if (!query.categories && derived.category) query.categories = [derived.category];
  // RPA-5: 语义冲突时把检索限制到语义类别，避免被 category hint 单点绑死。
  // 若该类别下无可用版面，上游会走 categoryRelaxed 回退到全库检索。
  if (derived.semantic_category_signals?.conflict && derived.semantic_category_signals.category) {
    query.categories = [derived.semantic_category_signals.category];
    query.category = undefined;
  }
  return query;
}

function mergeViolations(target, values) {
  for (const value of asArray(values)) {
    if (!value || typeof value !== "object") continue;
    const key = JSON.stringify([value.code, value.field, value.details, value.actual, value.capacity]);
    if (!target.some((item) => JSON.stringify([item.code, item.field, item.details, item.actual, item.capacity]) === key)) target.push(clone(value));
  }
}

function maxAttempts(value) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return 3;
  return Math.min(20, Math.max(0, Math.floor(parsed)));
}

function makeExhaustedViolation(attempt, maximum) {
  return violation({
    code: "REPLAN_EXHAUSTED",
    field: "replan_attempt",
    actual: attempt,
    capacity: maximum,
    recoverable: false,
    recommended_action: "allow_auto_split_or_choose_layout",
    message: `Replan attempts exhausted after ${attempt} attempt(s).`,
    details: { replan_attempt: attempt, max_replan_attempts: maximum },
  });
}

function outputContext(context) {
  return {
    rejected_layout_ids: [...context.rejected_layout_ids],
    violations: clone(context.violations),
    replan_attempt: context.replan_attempt,
    max_replan_attempts: context.max_replan_attempts,
  };
}

function unplannedResult(brief, context, status = "needs_replan", planningDecision = "single") {
  return {
    status,
    slides: [],
    slide_briefs: [clone(brief)],
    unplanned_slide_briefs: [clone(brief)],
    planning_decision: planningDecision,
    replan_context: outputContext(context),
  };
}

async function resolveLayout(candidate, adapters) {
  const id = candidateId(candidate);
  let layout = candidateLayout(candidate);
  if ((!Array.isArray(layout?.slot_specs) && !Array.isArray(layout?.slots)) && typeof adapters.getLayout === "function" && id) {
    const fetched = await adapters.getLayout(id);
    layout = candidateLayout(candidate, fetched);
  }
  return { id, layout };
}

function bindingForOutput(binding, brief, layout) {
  return {
    ...clone(binding),
    slide_brief: clone(brief),
    layout_spec: clone(layout),
    slot_specs: clone(binding.slot_specs ?? layout?.slot_specs ?? layout?.slots),
  };
}

function legalBinding(binding, brief, layout) {
  if (!isRecord(binding) || !["success", "adapted"].includes(binding.status)) return { legal: false, violations: [] };
  if (!isRecord(binding.slot_assignments)) {
    return {
      legal: false,
      violations: [violation({
        code: "INVALID_SLOT_ASSIGNMENTS",
        field: "slot_assignments",
        actual: binding.slot_assignments,
        capacity: "object keyed by slot_id",
        recoverable: false,
        recommended_action: "fix_slot_binding_adapter",
        message: "A successful binding must expose slot_assignments.",
      })],
    };
  }
  const contract = validateSlotBindingContract({
    slide_brief: brief,
    layout_spec: layout,
    slot_specs: binding.slot_specs ?? layout?.slot_specs ?? layout?.slots,
    slot_assignments: binding.slot_assignments,
    adaptation_log: binding.adaptation_log,
  });
  return { legal: contract.valid, violations: contract.violations };
}

function structuralSplitCapacity(brief, observed, input) {
  const counts = countStructuralItems(brief);
  const result = {};
  for (const type of Object.keys(counts)) {
    const direct = Number(first(input, [`${type}_capacity`, `${type}Capacity`, "split_capacity"]));
    if (Number.isFinite(direct) && direct > 0) result[type] = Math.floor(direct);
    else if (Number.isFinite(observed[type]) && observed[type] > 0) result[type] = observed[type];
    else result[type] = 5;
  }
  return result;
}

function hasStructuralViolation(violations) {
  return asArray(violations).some((item) => VIOLATION_CODES.has(item?.code));
}

async function planOne(brief, input, adapters, context, options = {}) {
  const initialExcluded = options.initialExcluded;
  const max = context.max_replan_attempts;
  let attempt = 0;
  const observedCapacities = {};
  let lastViolations = [];

  while (true) {
    context.replan_attempt = Math.max(context.replan_attempt, attempt);
    const excluded = new Set([...initialExcluded, ...context.rejected_layout_ids]);
    let searchResult;
    try {
      searchResult = await adapters.searchLayouts(queryForBrief(input, brief, excluded));
    } catch (error) {
      const issue = violation({ code: "INTERNAL_ERROR", field: "searchLayouts", actual: error?.message ?? String(error), capacity: "successful adapter call", recoverable: false, recommended_action: "fix_layout_search_adapter", message: "searchLayouts adapter failed." });
      mergeViolations(context.violations, [issue]);
      return { result: unplannedResult(brief, context, "failed"), split: false };
    }
    const candidates = resultCandidates(searchResult);
    const evidence = capacityEvidence(searchResult, candidates);
    for (const [type, capacity] of Object.entries(evidence)) observedCapacities[type] = Math.max(observedCapacities[type] ?? 0, capacity);
    let triedCandidate = false;
    let candidateNeedsReplan = false;
    for (const candidate of candidates) {
      const id = candidateId(candidate);
      if (!id || context.rejected_layout_ids.includes(id)) continue;
      triedCandidate = true;
      let resolved;
      try {
        resolved = await resolveLayout(candidate, adapters);
      } catch (error) {
        const issue = violation({ code: "LAYOUT_NOT_FOUND", field: "layout_id", actual: id, capacity: "resolvable layout", recoverable: true, recommended_action: "choose_another_layout", message: error?.message ?? `Unable to resolve layout ${id}.`, details: { layout_id: id } });
        context.rejected_layout_ids.push(id);
        mergeViolations(context.violations, [issue]);
        lastViolations = [issue];
        candidateNeedsReplan = true;
        continue;
      }
      const layout = resolved.layout;
      if (id && candidateId(layout) && candidateId(layout) !== id) {
        const issue = violation({ code: "INVALID_LAYOUT_SPEC", field: "layout_id", actual: candidateId(layout), capacity: id, recoverable: false, recommended_action: "fix_layout_adapter", message: "Resolved layout id does not match the retrieved candidate.", details: { expected_layout_id: id, actual_layout_id: candidateId(layout) } });
        mergeViolations(context.violations, [issue]);
        return { result: unplannedResult(brief, context, "failed"), split: false };
      }
      let binding;
      try {
        binding = await adapters.bindSlide({
          slide_brief: clone(brief),
          layout_spec: clone(layout),
          slot_specs: clone(layout?.slot_specs ?? layout?.slots),
          slot_assignments: clone(input.slot_assignments),
        });
      } catch (error) {
        const issue = violation({ code: "INTERNAL_ERROR", field: "bindSlide", actual: error?.message ?? String(error), capacity: "successful adapter call", recoverable: false, recommended_action: "fix_slot_binding_adapter", message: "bindSlide adapter failed.", details: { layout_id: id } });
        mergeViolations(context.violations, [issue]);
        return { result: unplannedResult(brief, context, "failed"), split: false };
      }
      const bindingViolations = asArray(binding?.violations);
      const status = binding?.status;
      if (["success", "adapted"].includes(status)) {
        const contract = legalBinding(binding, brief, layout);
        if (contract.legal) return { result: { status, slides: [bindingForOutput(binding, brief, layout)], planning_decision: "single", replan_context: outputContext(context) }, split: false };
        mergeViolations(context.violations, contract.violations);
        lastViolations = contract.violations;
        candidateNeedsReplan = true;
      } else if (status === "needs_replan") {
        mergeViolations(context.violations, bindingViolations);
        lastViolations = bindingViolations;
        candidateNeedsReplan = true;
      } else {
        mergeViolations(context.violations, bindingViolations);
        return { result: { status: "failed", slides: [], slide_briefs: [clone(brief)], unplanned_slide_briefs: [clone(brief)], planning_decision: "single", replan_context: outputContext(context), violations: clone(bindingViolations) }, split: false };
      }
      const candidateCapacity = capacitiesFromCandidate(layout);
      for (const [type, capacity] of Object.entries(candidateCapacity)) observedCapacities[type] = Math.max(observedCapacities[type] ?? 0, capacity);
      if (!context.rejected_layout_ids.includes(id)) context.rejected_layout_ids.push(id);
    }

    const structuralOverload = briefHasOverload(brief, observedCapacities) || (candidateNeedsReplan && hasStructuralViolation(lastViolations));
    if (input.allow_auto_split !== false && !options.splitAttempted && structuralOverload) {
      const splitCapacities = structuralSplitCapacity(brief, observedCapacities, input);
      const children = splitSlideBrief(brief, { capacities: splitCapacities });
      if (children.length > 1) return { split: true, children, context };
    }

    if (!triedCandidate && !candidates.length && !structuralOverload) {
      lastViolations = [violation({ code: "LAYOUT_NOT_FOUND", field: "results", actual: 0, capacity: "at least one legal layout", recommended_action: "choose_layout_or_split", message: "Layout search returned no candidates." })];
      mergeViolations(context.violations, lastViolations);
    }
    if (attempt >= max) {
      const exhausted = makeExhaustedViolation(attempt, max);
      mergeViolations(context.violations, [exhausted]);
      return { result: unplannedResult(brief, context, "needs_replan"), split: false };
    }
    attempt += 1;
    context.replan_attempt = Math.max(context.replan_attempt, attempt);
  }
}

/**
 * Planner -> Slot Binding closed loop. Retrieval and layout resolution are
 * injected so this module remains deterministic and independent of core.mjs.
 */
export async function planSlideClosedLoop(input = {}, adapters = {}) {
  const brief = input.slide_brief;
  const context = {
    rejected_layout_ids: [],
    violations: [],
    replan_attempt: 0,
    max_replan_attempts: maxAttempts(input.max_replan_attempts),
  };
  if (!isRecord(brief)) {
    const issue = violation({ code: "INVALID_INPUT", field: "slide_brief", actual: brief, capacity: "object", recoverable: false, recommended_action: "provide_slide_brief", message: "slide_brief must be an object." });
    context.violations.push(issue);
    return unplannedResult(brief, context, "failed");
  }
  if (!isRecord(adapters) || typeof adapters.searchLayouts !== "function") {
    const issue = violation({ code: "INVALID_INPUT", field: "adapters.searchLayouts", actual: adapters?.searchLayouts, capacity: "function", recoverable: false, recommended_action: "provide_search_layouts_adapter", message: "searchLayouts adapter is required." });
    context.violations.push(issue);
    return unplannedResult(brief, context, "failed");
  }
  const initialExcluded = new Set(uniqueStrings(input.exclude_ids ?? input.excludeIds));
  const normalizedAdapters = {
    searchLayouts: adapters.searchLayouts,
    getLayout: adapters.getLayout,
    bindSlide: adapters.bindSlide ?? bindSlideToLayout,
  };
  const result = await planOne(brief, { ...input, allow_auto_split: input.allow_auto_split !== false }, normalizedAdapters, context, { initialExcluded, splitAttempted: false });
  if (!result.split) return result.result;

  const childSlides = [];
  const childUnplanned = [];
  let finalStatus = "success";
  for (const child of result.children) {
    const childContext = { rejected_layout_ids: [], violations: [], replan_attempt: 0, max_replan_attempts: context.max_replan_attempts };
    const childResult = await planOne(child, { ...input, allow_auto_split: false }, normalizedAdapters, childContext, { initialExcluded, splitAttempted: true });
    mergeViolations(context.violations, childContext.violations);
    for (const id of childContext.rejected_layout_ids) if (!context.rejected_layout_ids.includes(id)) context.rejected_layout_ids.push(id);
    context.replan_attempt = Math.max(context.replan_attempt, childContext.replan_attempt);
    if (childResult.split) {
      finalStatus = "needs_replan";
      childUnplanned.push(...result.children.slice(childResult.children?.length ?? 0).map(clone));
      continue;
    }
    if (childResult.result?.status === "failed") finalStatus = "failed";
    else if (childResult.result?.status === "needs_replan") finalStatus = "needs_replan";
    childSlides.push(...asArray(childResult.result?.slides));
    childUnplanned.push(...asArray(childResult.result?.unplanned_slide_briefs));
  }
  if (finalStatus === "success" && childSlides.length === result.children.length) {
    return {
      status: childSlides.some((slide) => slide.status === "adapted") ? "adapted" : "success",
      slides: childSlides,
      planning_decision: "split",
      replan_context: outputContext(context),
    };
  }
  return {
    status: finalStatus,
    slides: childSlides,
    slide_briefs: childUnplanned.length ? childUnplanned : result.children.map(clone),
    unplanned_slide_briefs: childUnplanned.length ? childUnplanned : result.children.map(clone),
    planning_decision: "split",
    replan_context: outputContext(context),
  };
}
