const FORBIDDEN_OUTPUT_KEYS = new Set([
  "layout_id",
  "layout",
  "slot_specs",
  "slot_assignments",
]);

const SOURCE_ID_PATTERN = /^SRC\d{4}$/u;
const CITATION_ID_PATTERN = /^CIT\d{4}$/u;
const EVIDENCE_ID_PATTERN = /^EV\d{4}$/u;
const SLIDE_ID_PATTERN = /^SLIDE\d{4}$/u;
const SPAN_ID_PATTERN = /^S\d{4}$/u;
const CHUNK_ID_PATTERN = /^E\d{3}$/u;

const own = (object, key) => Object.prototype.hasOwnProperty.call(object, key);
const isRecord = (value) => value !== null && typeof value === "object" && !Array.isArray(value);

function deepFreeze(value, seen = new WeakSet()) {
  if (value === null || typeof value !== "object" || seen.has(value)) return value;
  seen.add(value);
  for (const child of Object.values(value)) deepFreeze(child, seen);
  return Object.freeze(value);
}

function stableSerialize(value, seen = new WeakSet()) {
  if (value === undefined) return "undefined";
  if (value === null || typeof value !== "object") {
    if (typeof value === "number" && !Number.isFinite(value)) return String(value);
    return JSON.stringify(value);
  }
  if (seen.has(value)) return '"[Circular]"';
  seen.add(value);
  if (Array.isArray(value)) return `[${value.map((item) => stableSerialize(item, seen)).join(",")}]`;
  return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${stableSerialize(value[key], seen)}`).join(",")}}`;
}

function cloneValue(value, seen = new WeakMap()) {
  if (value === null || typeof value !== "object") return value;
  if (seen.has(value)) return null;
  seen.set(value, true);
  if (Array.isArray(value)) return value.map((item) => cloneValue(item, seen));
  const result = {};
  for (const key of Object.keys(value).sort()) {
    if (FORBIDDEN_OUTPUT_KEYS.has(key)) continue;
    result[key] = cloneValue(value[key], seen);
  }
  return result;
}

function noteForbiddenFields(value, path, context, seen = new WeakSet()) {
  if (value === null || typeof value !== "object" || seen.has(value)) return;
  seen.add(value);
  if (Array.isArray(value)) {
    value.forEach((item, index) => noteForbiddenFields(item, `${path}[${index}]`, context, seen));
    return;
  }
  for (const [key, child] of Object.entries(value)) {
    const childPath = path ? `${path}.${key}` : key;
    if (FORBIDDEN_OUTPUT_KEYS.has(key)) {
      context.log({
        action: "ignore_unsupported_field",
        content_id: path || "input",
        reason: "outside_content_model_scope",
        details: { field_kind: "unsupported_planning_field" },
      });
      continue;
    }
    noteForbiddenFields(child, childPath, context, seen);
  }
}

function firstPresent(object, keys) {
  if (!isRecord(object)) return undefined;
  for (const key of keys) if (own(object, key) && object[key] !== undefined) return object[key];
  return undefined;
}

function nonEmptyString(value) {
  if (value === undefined || value === null) return undefined;
  const result = String(value).trim();
  return result || undefined;
}

function titleString(value) {
  if (value === undefined || value === null) return "";
  return String(value).replace(/\s+/gu, " ").trim();
}

function textString(value) {
  if (value === undefined || value === null) return "";
  return String(value).trim();
}

function logTextCleanup(context, contentId, field, before, after, path) {
  if (before === after) return;
  context.log({
    action: "whitespace_cleanup",
    content_id: contentId,
    reason: "normalize_outer_or_title_whitespace",
    before_chars: [...before].length,
    after_chars: [...after].length,
    before,
    after,
    details: { field, path },
  });
}

function normalizeText(value, context, contentId, field, path, titleLike = false) {
  if (value === undefined || value === null) return undefined;
  const before = String(value);
  const after = titleLike ? titleString(before) : textString(before);
  logTextCleanup(context, contentId, field, before, after, path);
  return after;
}

function normalizeIndex(value, context, field, path, { minimum = 0, fallback = undefined } = {}) {
  if (value === undefined || value === null || value === "") return fallback;
  const parsed = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(parsed)) {
    context.violation({
      code: "INVALID_INPUT",
      field,
      path,
      actual: value,
      capacity: "finite number",
      recommended_action: "provide_a_finite_number",
      message: `${field} must be a finite number.`,
    });
    return fallback;
  }
  const rounded = Math.round(parsed);
  return Math.max(minimum, rounded);
}

function normalizePositiveNumber(value, context, field, path, fallback = 1) {
  if (value === undefined || value === null || value === "") return fallback;
  const parsed = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(parsed) || parsed <= 0) {
    context.violation({
      code: "INVALID_INPUT",
      field,
      path,
      actual: value,
      capacity: "> 0",
      recommended_action: "provide_a_positive_number",
      message: `${field} must be a positive number.`,
    });
    return fallback;
  }
  return parsed;
}

function normalizeNonnegativeNumber(value, context, field, path, fallback = 0) {
  if (value === undefined || value === null || value === "") return fallback;
  const parsed = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(parsed) || parsed < 0) {
    context.violation({
      code: "INVALID_INPUT",
      field,
      path,
      actual: value,
      capacity: ">= 0",
      recommended_action: "provide_a_nonnegative_number",
      message: `${field} must be a non-negative number.`,
    });
    return fallback;
  }
  return parsed;
}

function normalizeBoolean(value, context, field, path, fallback = false) {
  if (value === undefined || value === null || value === "") return fallback;
  if (typeof value === "boolean") return value;
  if (typeof value === "number" && (value === 0 || value === 1)) return value === 1;
  if (typeof value === "string") {
    const normalized = value.trim().toLowerCase();
    if (["true", "1", "yes"].includes(normalized)) return true;
    if (["false", "0", "no"].includes(normalized)) return false;
  }
  context.violation({
    code: "INVALID_INPUT",
    field,
    path,
    actual: value,
    capacity: "boolean or true/false/1/0/yes/no",
    recommended_action: "provide_a_boolean",
    message: `${field} must be boolean.`,
  });
  return fallback;
}

function createIdFactory(prefix, width, pattern) {
  const used = new Set();
  let next = 1;
  return {
    reserve(value) {
      if (typeof value === "string" && pattern.test(value)) used.add(value);
    },
    next() {
      let candidate;
      do {
        candidate = `${prefix}${String(next).padStart(width, "0")}`;
        next += 1;
      } while (used.has(candidate));
      used.add(candidate);
      return candidate;
    },
  };
}

function createFactories() {
  return {
    source: createIdFactory("SRC", 4, SOURCE_ID_PATTERN),
    citation: createIdFactory("CIT", 4, CITATION_ID_PATTERN),
    evidence: createIdFactory("EV", 4, EVIDENCE_ID_PATTERN),
    slide: createIdFactory("SLIDE", 4, SLIDE_ID_PATTERN),
    span: createIdFactory("S", 4, SPAN_ID_PATTERN),
    chunk: createIdFactory("E", 3, CHUNK_ID_PATTERN),
  };
}

function reserveCandidateIds(factories, value, kind) {
  const factory = factories[kind];
  if (!factory || value === undefined || value === null) return;
  factory.reserve(typeof value === "string" ? value.trim() : String(value));
}

function reserveRawIds(factories, input, { upstream = false } = {}) {
  if (!isRecord(input)) return;
  const sources = Array.isArray(input.sources) ? input.sources : [];
  for (const item of sources) reserveCandidateIds(factories, firstPresent(item, ["source_id", "sourceId", "id"]), "source");
  const citations = Array.isArray(input.citations) ? input.citations : [];
  for (const item of citations) reserveCandidateIds(factories, firstPresent(item, ["citation_id", "citationId", "id"]), "citation");
  const evidence = Array.isArray(input.evidence) ? input.evidence : [];
  for (const item of evidence) reserveCandidateIds(factories, firstPresent(item, ["evidence_id", "evidenceId", "id"]), "evidence");
  const briefs = Array.isArray(input.slide_briefs) ? input.slide_briefs : [];
  for (const item of briefs) reserveCandidateIds(factories, firstPresent(item, ["slide_id", "slideId", "id"]), "slide");
  if (!upstream) return;
  if (isRecord(input.source)) reserveCandidateIds(factories, firstPresent(input.source, ["source_id", "sourceId", "id"]), "source");
  const registry = upstreamEntries(input);
  for (const [key, item] of registry) {
    reserveCandidateIds(factories, firstPresent(item, ["citation_id", "citationId"]), "citation");
    reserveCandidateIds(factories, firstPresent(item, ["evidence_id", "evidenceId"]) ?? key, "evidence");
    reserveCandidateIds(factories, firstPresent(item, ["span_id", "spanId"]), "span");
    reserveCandidateIds(factories, firstPresent(item, ["chunk_id", "chunkId"]), "chunk");
  }
  const options = isRecord(input.__adapter_options) ? input.__adapter_options : undefined;
  if (options) reserveRawIds(factories, options);
}

function idInfo(rawValue, factory, pattern, context, field, path) {
  const before = rawValue === undefined || rawValue === null ? undefined : String(rawValue);
  const normalized = nonEmptyString(rawValue);
  if (before !== undefined && normalized !== before) {
    context.log({
      action: "whitespace_cleanup",
      content_id: normalized || field,
      reason: "normalize_identifier_whitespace",
      before_chars: [...before].length,
      after_chars: normalized ? [...normalized].length : 0,
      before,
      after: normalized ?? "",
      details: { field, path },
    });
  }
  if (normalized && pattern.test(normalized)) {
    factory.reserve(normalized);
    return { id: normalized, original: normalized, generated: false, aliases: [normalized] };
  }
  const generated = factory.next();
  context.log({
    action: "generate_id",
    content_id: generated,
    reason: normalized ? "caller_id_missing_or_invalid" : "caller_id_missing",
    before: normalized,
    after: generated,
    details: { field, path },
  });
  return {
    id: generated,
    original: normalized,
    generated: true,
    aliases: normalized ? [normalized, generated] : [generated],
  };
}

function arrayInput(value, context, field, path) {
  if (value === undefined || value === null) return [];
  if (Array.isArray(value)) return value;
  context.violation({
    code: "INVALID_INPUT",
    field,
    path,
    actual: value,
    capacity: "array",
    recommended_action: "provide_an_array",
    message: `${field} must be an array.`,
  });
  return [];
}

function normalizeStringArray(value, context, contentId, field, path, { splitCommas = false } = {}) {
  if (value === undefined || value === null) return [];
  let values;
  if (Array.isArray(value)) values = value;
  else if (typeof value === "string" && splitCommas) values = value.split(",");
  else values = [value];
  const output = [];
  const seen = new Set();
  values.forEach((item, index) => {
    if (item === undefined || item === null) return;
    if (typeof item === "object") {
      context.violation({
        code: "INVALID_INPUT",
        field: `${field}[${index}]`,
        path: `${path}[${index}]`,
        actual: item,
        capacity: "string",
        recommended_action: "provide_string_references",
        message: `${field}[${index}] must be a string.`,
      });
      return;
    }
    const before = String(item);
    const normalized = before.trim();
    if (before !== normalized) logTextCleanup(context, contentId, `${field}[${index}]`, before, normalized, `${path}[${index}]`);
    if (!normalized) {
      context.log({ action: "drop_empty_value", content_id: contentId, reason: "empty_reference_after_cleanup", details: { field, index } });
      return;
    }
    if (seen.has(normalized)) {
      context.log({ action: "deduplicate_exact", content_id: normalized, reason: "first_seen_reference_wins", details: { field, index } });
      return;
    }
    seen.add(normalized);
    output.push(normalized);
  });
  return output;
}

function normalizeRange(value, startValue, endValue, context, field, path, { endExclusive = false } = {}) {
  if (value === undefined || value === null) {
    if (startValue === undefined && endValue === undefined) return undefined;
    value = {};
  }
  let start = startValue;
  let end = endValue;
  if (Array.isArray(value)) {
    start ??= value[0];
    end ??= value[1];
  } else if (isRecord(value)) {
    start ??= firstPresent(value, ["start", "from"]);
    end ??= firstPresent(value, ["end", "to"]);
    if (endExclusive && value.end_exclusive === false) {
      context.violation({
        code: "INVALID_INPUT",
        field,
        path,
        actual: value.end_exclusive,
        capacity: true,
        recommended_action: "use_end_exclusive_character_ranges",
        message: `${field} uses end-exclusive ranges.`,
      });
    }
  }
  const normalizedStart = normalizeIndex(start, context, `${field}.start`, `${path}.start`, { minimum: 0 });
  const normalizedEnd = normalizeIndex(end, context, `${field}.end`, `${path}.end`, { minimum: 0 });
  if (normalizedStart === undefined || normalizedEnd === undefined) {
    context.violation({
      code: "INVALID_INPUT",
      field,
      path,
      actual: value,
      capacity: { start: "integer", end: "integer" },
      recommended_action: "provide_complete_ranges",
      message: `${field} must contain start and end.`,
    });
    return undefined;
  }
  if (normalizedEnd < normalizedStart) {
    context.violation({
      code: "INVALID_INPUT",
      field,
      path,
      actual: { start: normalizedStart, end: normalizedEnd },
      capacity: "end >= start",
      recommended_action: "fix_range_endpoints",
      message: `${field} end must not precede start.`,
    });
  }
  return { start: normalizedStart, end: normalizedEnd };
}

function normalizeAddressId(value, factory, pattern, context, field, path, generateMissing) {
  if (value === undefined || value === null || value === "") return undefined;
  const normalized = nonEmptyString(value);
  if (normalized && pattern.test(normalized)) {
    factory.reserve(normalized);
    return normalized;
  }
  context.violation({
    code: "INVALID_INPUT",
    field,
    path,
    actual: value,
    capacity: pattern.source,
    recommended_action: "preserve_valid_upstream_address_ids",
    message: `${field} has an invalid address identifier.`,
  });
  return normalized;
}

function normalizeQueryFields(out, raw, context, contentId, path) {
  if (own(raw, "query_ids") || own(raw, "queryIds")) {
    out.query_ids = normalizeStringArray(firstPresent(raw, ["query_ids", "queryIds"]), context, contentId, "query_ids", `${path}.query_ids`);
  }
  if (own(raw, "queries")) {
    out.queries = normalizeStringArray(raw.queries, context, contentId, "queries", `${path}.queries`);
  }
}

function normalizeSupportType(value, context, field, path) {
  const normalized = nonEmptyString(value);
  if (!normalized) return undefined;
  if (!EVIDENCE_TYPES.includes(normalized)) {
    context.violation({
      code: "INVALID_INPUT",
      field,
      path,
      actual: normalized,
      capacity: EVIDENCE_TYPES,
      recommended_action: "use_supported_evidence_type",
      message: `${field} is not a supported evidence type.`,
    });
  }
  return normalized;
}

function normalizeMetadata(out, raw, context, path) {
  if (own(raw, "metadata") && isRecord(raw.metadata)) out.metadata = cloneValue(raw.metadata);
}

function normalizeSource(raw, index, context, factories, path) {
  if (!isRecord(raw)) {
    context.violation({
      code: "INVALID_INPUT",
      field: path,
      path,
      actual: raw,
      capacity: "object",
      recommended_action: "provide_source_objects",
      message: `${path} must be an object.`,
    });
    return null;
  }
  noteForbiddenFields(raw, path, context);
  const identifier = idInfo(firstPresent(raw, ["source_id", "sourceId", "id"]), factories.source, SOURCE_ID_PATTERN, context, "source_id", `${path}.source_id`);
  const out = { source_id: identifier.id };
  const fields = [
    ["source_sha256", ["source_sha256", "sourceSha256"]],
    ["markdown_sha256", ["markdown_sha256", "markdownSha256"]],
    ["source_fingerprint", ["source_fingerprint", "sourceFingerprint"]],
    ["input_path", ["input_path", "inputPath"]],
    ["input_type", ["input_type", "inputType"]],
    ["markdown_path", ["markdown_path", "markdownPath"]],
    ["title", ["title", "name"]],
    ["label", ["label"]],
    ["uri", ["uri"]],
    ["url", ["url"]],
    ["doi", ["doi"]],
  ];
  for (const [name, aliases] of fields) {
    if (!aliases.some((key) => own(raw, key))) continue;
    const value = normalizeText(firstPresent(raw, aliases), context, identifier.id, name, `${path}.${name}`, name === "title" || name === "label");
    if (value) out[name] = value;
  }
  const identity = out.source_sha256 ?? out.markdown_sha256 ?? out.source_fingerprint;
  if (identity) out.source_identity = identity;
  normalizeMetadata(out, raw, context, path);
  return { record: out, aliases: identifier.aliases, original: identifier.original, generated: identifier.generated, index };
}

function normalizeCitation(raw, index, context, factories, path, { defaultSourceId = undefined, upstream = false } = {}) {
  if (!isRecord(raw)) {
    context.violation({
      code: "INVALID_INPUT",
      field: path,
      path,
      actual: raw,
      capacity: "object",
      recommended_action: "provide_citation_objects",
      message: `${path} must be an object.`,
    });
    return null;
  }
  noteForbiddenFields(raw, path, context);
  const identifier = idInfo(firstPresent(raw, ["citation_id", "citationId", "id"]), factories.citation, CITATION_ID_PATTERN, context, "citation_id", `${path}.citation_id`);
  const sourceValue = firstPresent(raw, ["source_id", "sourceId"]);
  const out = {
    citation_id: identifier.id,
    source_id: nonEmptyString(sourceValue ?? defaultSourceId) ?? "",
  };
  const addressFields = [
    ["evidence_id", ["evidence_id", "evidenceId"]],
    ["span_id", ["span_id", "spanId"]],
    ["chunk_id", ["chunk_id", "chunkId"]],
  ];
  for (const [name, aliases] of addressFields) {
    if (!aliases.some((key) => own(raw, key))) continue;
    const value = firstPresent(raw, aliases);
    if (name === "evidence_id") {
      const normalized = nonEmptyString(value);
      if (normalized) out[name] = normalized;
    } else if (name === "span_id") {
      const normalized = normalizeAddressId(value, factories.span, SPAN_ID_PATTERN, context, name, `${path}.${name}`, upstream);
      if (normalized) out[name] = normalized;
    } else {
      const normalized = normalizeAddressId(value, factories.chunk, CHUNK_ID_PATTERN, context, name, `${path}.${name}`, upstream);
      if (normalized) out[name] = normalized;
    }
  }
  const sourceLines = normalizeRange(firstPresent(raw, ["source_lines", "sourceLines"]), firstPresent(raw, ["line_start", "lineStart"]), firstPresent(raw, ["line_end", "lineEnd"]), context, "source_lines", `${path}.source_lines`);
  const sourceChars = normalizeRange(firstPresent(raw, ["source_chars", "sourceChars"]), firstPresent(raw, ["char_start", "charStart"]), firstPresent(raw, ["char_end", "charEnd"]), context, "source_chars", `${path}.source_chars`, { endExclusive: true });
  if (sourceLines) out.source_lines = sourceLines;
  if (sourceChars) out.source_chars = sourceChars;
  out.source_chars_end_exclusive = true;
  const text = normalizeText(firstPresent(raw, ["text", "snippet"]), context, identifier.id, "text", `${path}.text`);
  if (text) out.text = text;
  const modality = normalizeText(firstPresent(raw, ["modality"]), context, identifier.id, "modality", `${path}.modality`);
  if (modality) out.modality = modality;
  const support = normalizeSupportType(firstPresent(raw, ["support_type", "supportType", "evidence_type", "evidenceType"]), context, "support_type", `${path}.support_type`);
  if (support) {
    out.support_type = support;
    out.evidence_type = support;
  }
  normalizeQueryFields(out, raw, context, identifier.id, path);
  for (const [name, aliases] of [["label", ["label"]], ["reference_number", ["reference_number", "referenceNumber"]], ["bibliography_id", ["bibliography_id", "bibliographyId"]]]) {
    if (!aliases.some((key) => own(raw, key))) continue;
    const value = normalizeText(firstPresent(raw, aliases), context, identifier.id, name, `${path}.${name}`, name === "label");
    if (value) out[name] = value;
  }
  normalizeMetadata(out, raw, context, path);
  return { record: out, aliases: identifier.aliases, original: identifier.original, generated: identifier.generated, index };
}

function normalizeEvidenceTextFields(out, raw, context, contentId, path) {
  for (const [name, aliases] of [
    ["claim", ["claim"]],
    ["claim_text", ["claim_text", "claimText"]],
    ["evidence", ["evidence"]],
    ["evidence_text", ["evidence_text", "evidenceText"]],
    ["text", ["text", "snippet"]],
  ]) {
    if (!aliases.some((key) => own(raw, key))) continue;
    const rawValue = firstPresent(raw, aliases);
    if (isRecord(rawValue) || Array.isArray(rawValue)) {
      out[name] = cloneValue(rawValue);
      continue;
    }
    const value = normalizeText(rawValue, context, contentId, name, `${path}.${name}`);
    if (value) out[name] = value;
  }
}

function normalizeEvidence(raw, index, context, factories, path, { defaultSourceId = undefined, defaultCitationId = undefined, upstream = false } = {}) {
  if (!isRecord(raw)) {
    context.violation({
      code: "INVALID_INPUT",
      field: path,
      path,
      actual: raw,
      capacity: "object",
      recommended_action: "provide_evidence_objects",
      message: `${path} must be an object.`,
    });
    return null;
  }
  noteForbiddenFields(raw, path, context);
  const identifier = idInfo(firstPresent(raw, ["evidence_id", "evidenceId", "id"]), factories.evidence, EVIDENCE_ID_PATTERN, context, "evidence_id", `${path}.evidence_id`);
  const importanceRaw = firstPresent(raw, ["importance", "priority"]);
  const importance = normalizeIndex(importanceRaw, context, "importance", `${path}.importance`, { minimum: 1, fallback: 1 });
  if (importanceRaw === undefined) {
    context.log({ action: "default_normalization", content_id: identifier.id, reason: "default_importance", after: importance, details: { field: `${path}.importance` } });
  } else if (Number(importanceRaw) !== importance) {
    context.log({ action: "normalize_priority", content_id: identifier.id, reason: "importance_must_be_a_positive_integer", before: importanceRaw, after: importance, details: { field: `${path}.importance` } });
  }
  const mustKeep = normalizeBoolean(firstPresent(raw, ["must_keep", "mustKeep"]), context, "must_keep", `${path}.must_keep`, false);
  if (!own(raw, "must_keep") && !own(raw, "mustKeep")) {
    context.log({ action: "default_normalization", content_id: identifier.id, reason: "default_must_keep", after: mustKeep, details: { field: `${path}.must_keep` } });
  }
  const roleRaw = firstPresent(raw, ["content_role", "contentRole", "role"]);
  const contentRole = nonEmptyString(roleRaw) ?? "supporting_evidence";
  if (roleRaw === undefined) {
    context.log({ action: "default_normalization", content_id: identifier.id, reason: "default_content_role", after: contentRole, details: { field: `${path}.content_role` } });
  } else if (!CONTENT_ROLES.includes(contentRole)) {
    context.violation({
      code: "INVALID_INPUT",
      field: "content_role",
      path: `${path}.content_role`,
      actual: contentRole,
      capacity: CONTENT_ROLES,
      recommended_action: "use_supported_content_role",
      message: "content_role is not supported.",
    });
  }
  const out = {
    evidence_id: identifier.id,
    importance,
    must_keep: mustKeep,
    content_role: CONTENT_ROLES.includes(contentRole) ? contentRole : "supporting_evidence",
    citation_ids: [],
  };
  const sourceValue = firstPresent(raw, ["source_id", "sourceId"]);
  if (sourceValue !== undefined || defaultSourceId !== undefined) out.source_id = nonEmptyString(sourceValue ?? defaultSourceId) ?? "";
  const citationValues = firstPresent(raw, ["citation_ids", "citationIds"]);
  const singularCitation = firstPresent(raw, ["citation_id", "citationId"]);
  const citations = [];
  if (defaultCitationId) citations.push(defaultCitationId);
  if (singularCitation !== undefined) citations.push(singularCitation);
  if (citationValues !== undefined) citations.push(...(Array.isArray(citationValues) ? citationValues : [citationValues]));
  out.citation_ids = normalizeStringArray(citations, context, identifier.id, "citation_ids", `${path}.citation_ids`);
  const span = normalizeAddressId(firstPresent(raw, ["span_id", "spanId"]), factories.span, SPAN_ID_PATTERN, context, "span_id", `${path}.span_id`, upstream);
  const chunk = normalizeAddressId(firstPresent(raw, ["chunk_id", "chunkId"]), factories.chunk, CHUNK_ID_PATTERN, context, "chunk_id", `${path}.chunk_id`, upstream);
  if (span) out.span_id = span;
  if (chunk) out.chunk_id = chunk;
  const sourceLines = normalizeRange(firstPresent(raw, ["source_lines", "sourceLines"]), firstPresent(raw, ["line_start", "lineStart"]), firstPresent(raw, ["line_end", "lineEnd"]), context, "source_lines", `${path}.source_lines`);
  const sourceChars = normalizeRange(firstPresent(raw, ["source_chars", "sourceChars"]), firstPresent(raw, ["char_start", "charStart"]), firstPresent(raw, ["char_end", "charEnd"]), context, "source_chars", `${path}.source_chars`, { endExclusive: true });
  if (sourceLines) out.source_lines = sourceLines;
  if (sourceChars) out.source_chars = sourceChars;
  out.source_chars_end_exclusive = true;
  normalizeEvidenceTextFields(out, raw, context, identifier.id, path);
  const sourceSection = normalizeText(firstPresent(raw, ["source_section", "sourceSection", "section", "heading"]), context, identifier.id, "source_section", `${path}.source_section`, true);
  if (sourceSection) out.source_section = sourceSection;
  const figureTable = normalizeText(firstPresent(raw, ["figure_table_ref", "figureTableRef", "figure_ref", "table_ref"]), context, identifier.id, "figure_table_ref", `${path}.figure_table_ref`, true);
  if (figureTable) out.figure_table_ref = figureTable;
  if (own(raw, "confidence") && raw.confidence !== null && raw.confidence !== "") {
    const confidence = typeof raw.confidence === "number" ? raw.confidence : Number(raw.confidence);
    if (Number.isFinite(confidence)) out.confidence = confidence;
    else context.violation({ code: "INVALID_INPUT", field: "confidence", path: `${path}.confidence`, actual: raw.confidence, capacity: "finite number", recommended_action: "provide_a_finite_confidence", message: "confidence must be finite." });
  }
  if (own(raw, "recommended_crop") || own(raw, "recommendedCrop")) out.recommended_crop = cloneValue(firstPresent(raw, ["recommended_crop", "recommendedCrop"]));
  const modality = normalizeText(firstPresent(raw, ["modality"]), context, identifier.id, "modality", `${path}.modality`);
  if (modality) out.modality = modality;
  const support = normalizeSupportType(firstPresent(raw, ["support_type", "supportType", "evidence_type", "evidenceType"]), context, "support_type", `${path}.support_type`);
  if (support) {
    out.support_type = support;
    out.evidence_type = support;
  }
  normalizeQueryFields(out, raw, context, identifier.id, path);
  normalizeMetadata(out, raw, context, path);
  return { record: out, aliases: identifier.aliases, original: identifier.original, generated: identifier.generated, index };
}

function normalizeStructuredItem(value, context, contentId, field, path) {
  if (value === undefined || value === null) return undefined;
  if (!isRecord(value)) {
    const normalized = normalizeText(value, context, contentId, field, path, true);
    return normalized || undefined;
  }
  noteForbiddenFields(value, path, context);
  const out = {};
  for (const key of Object.keys(value).sort()) {
    if (FORBIDDEN_OUTPUT_KEYS.has(key)) continue;
    const child = value[key];
    if (["title", "caption", "label", "heading", "name", "description", "text", "goal"].includes(key)) {
      const normalized = normalizeText(child, context, contentId, `${field}.${key}`, `${path}.${key}`, true);
      if (normalized) out[key] = normalized;
    } else if (["evidence_ids", "citation_ids"].includes(key)) {
      out[key] = normalizeStringArray(child, context, contentId, `${field}.${key}`, `${path}.${key}`);
    } else {
      out[key] = cloneValue(child);
    }
  }
  return Object.keys(out).length ? out : undefined;
}

function normalizeStructuredList(value, context, contentId, field, path) {
  if (value === undefined || value === null) return [];
  const values = Array.isArray(value) ? value : [value];
  const out = [];
  const seen = new Set();
  values.forEach((item, index) => {
    const normalized = normalizeStructuredItem(item, context, contentId, field, `${path}[${index}]`);
    if (normalized === undefined) {
      context.log({ action: "drop_empty_value", content_id: contentId, reason: "empty_structured_item_after_cleanup", details: { field, index } });
      return;
    }
    const signature = stableSerialize(normalized);
    if (seen.has(signature)) {
      context.log({ action: "deduplicate_exact", content_id: contentId, reason: "first_seen_structured_item_wins", details: { field, index } });
      return;
    }
    seen.add(signature);
    out.push(normalized);
  });
  return out;
}

const VISUAL_KEYS = new Set([
  "visual_id", "visual_type", "title", "caption", "description", "alt_text", "label", "asset_uri", "uri",
  "source_id", "source_width_px", "source_height_px", "figure_table_ref", "evidence_ids", "citation_ids", "panel_count", "has_embedded_text",
  "min_display_width", "display_width_norm", "display_height_norm", "rendered_embedded_text_px", "importance",
  "must_keep", "recommended_crop", "data", "metadata",
  "source_visual_id", "region_id", "semantic_relation", "semantic_regions", "visual_aspect_ratio",
  "embedded_text_density", "caption_chars",
]);

function normalizeVisual(value, context, contentId, index, path) {
  if (typeof value === "string" || typeof value === "number") {
    const description = normalizeText(value, context, contentId, "visuals.description", path, true);
    return description ? { visual_type: "visual_evidence", description } : undefined;
  }
  if (!isRecord(value)) {
    context.violation({ code: "INVALID_INPUT", field: path, path, actual: value, capacity: "object or string", recommended_action: "provide_visual_objects", message: `${path} must be a visual object.` });
    return undefined;
  }
  noteForbiddenFields(value, path, context);
  if (own(value, "slot_id") || own(value, "slotId")) {
    context.log({ action: "ignore_unsupported_field", content_id: contentId, reason: "normalizer_does_not_assign_slots", details: { field: `${path}.slot_id` } });
  }
  const out = {};
  for (const key of Object.keys(value).sort()) {
    if (FORBIDDEN_OUTPUT_KEYS.has(key)) continue;
    if (!VISUAL_KEYS.has(key)) continue;
    const child = value[key];
    if (["title", "caption", "description", "alt_text", "label", "figure_table_ref"].includes(key)) {
      const normalized = normalizeText(child, context, contentId, `visuals.${key}`, `${path}.${key}`, true);
      if (normalized) out[key] = normalized;
    } else if (["evidence_ids", "citation_ids"].includes(key)) {
      out[key] = normalizeStringArray(child, context, contentId, `visuals.${key}`, `${path}.${key}`);
    } else if (key === "visual_type") {
      const normalized = nonEmptyString(child);
      if (normalized) out[key] = normalized;
    } else if (key === "panel_count" || key === "importance" || key === "caption_chars" || key === "source_width_px" || key === "source_height_px") {
      const normalized = normalizeIndex(child, context, `visuals.${key}`, `${path}.${key}`, { minimum: key === "caption_chars" ? 0 : 1 });
      if (normalized !== undefined) out[key] = normalized;
    } else if (key === "has_embedded_text" || key === "must_keep") {
      out[key] = normalizeBoolean(child, context, `visuals.${key}`, `${path}.${key}`, false);
    } else if (key === "min_display_width" || key === "visual_aspect_ratio") {
      const normalized = normalizePositiveNumber(child, context, `visuals.${key}`, `${path}.${key}`, undefined);
      if (normalized !== undefined) out[key] = normalized;
    } else if (["display_width_norm", "display_height_norm", "rendered_embedded_text_px", "embedded_text_density"].includes(key)) {
      const normalized = normalizeNonnegativeNumber(child, context, `visuals.${key}`, `${path}.${key}`, undefined);
      if (normalized !== undefined) out[key] = normalized;
    } else if (["source_id", "visual_id", "source_visual_id", "region_id", "semantic_relation"].includes(key)) {
      const normalized = nonEmptyString(child);
      if (normalized) out[key] = normalized;
    } else {
      out[key] = cloneValue(child);
    }
  }
  if (!out.visual_type) {
    out.visual_type = "visual_evidence";
    context.log({ action: "default_normalization", content_id: contentId, reason: "default_visual_type", after: out.visual_type, details: { field: `${path}.visual_type` } });
  }
  return Object.keys(out).length ? out : undefined;
}

function normalizeVisualList(value, context, contentId, path) {
  if (value === undefined || value === null) return [];
  const values = Array.isArray(value) ? value : [value];
  const out = [];
  const seen = new Set();
  values.forEach((item, index) => {
    const normalized = normalizeVisual(item, context, contentId, index, `${path}[${index}]`);
    if (!normalized) {
      context.log({ action: "drop_empty_value", content_id: contentId, reason: "empty_visual_after_cleanup", details: { index } });
      return;
    }
    const signature = stableSerialize(normalized);
    if (seen.has(signature)) {
      context.log({ action: "deduplicate_exact", content_id: contentId, reason: "first_seen_visual_wins", details: { index } });
      return;
    }
    seen.add(signature);
    out.push(normalized);
  });
  return out;
}

function normalizeTextCharsByRole(value, context, contentId, path) {
  if (value === undefined || value === null) return undefined;
  if (!isRecord(value)) {
    context.violation({ code: "INVALID_INPUT", field: "text_chars_by_role", path, actual: value, capacity: "object", recommended_action: "provide_text_counts_by_role", message: "text_chars_by_role must be an object." });
    return {};
  }
  const out = {};
  for (const key of Object.keys(value).sort()) {
    const role = key.trim();
    if (!role) continue;
    out[role] = normalizeIndex(value[key], context, `text_chars_by_role.${role}`, `${path}.${key}`, { minimum: 0, fallback: 0 });
  }
  return out;
}

function normalizeSlotMetrics(value, context, contentId, path) {
  if (value === undefined || value === null) return undefined;
  const values = arrayInput(value, context, "slot_metrics", path);
  return values.map((item, index) => {
    if (!isRecord(item)) {
      context.violation({ code: "INVALID_INPUT", field: `${path}[${index}]`, path: `${path}[${index}]`, actual: item, capacity: "object", recommended_action: "provide_slot_metric_objects", message: "slot_metrics entries must be objects." });
      return {};
    }
    const out = {};
    for (const [key, aliases] of [
      ["slot_id", ["slot_id", "slotId"]], ["role", ["role"]], ["text_chars", ["text_chars", "textChars"]],
      ["font_pt", ["font_pt", "fontPt"]], ["line_count", ["line_count", "lineCount"]],
      ["intended_single_line", ["intended_single_line", "intendedSingleLine"]],
    ]) {
      if (!aliases.some((alias) => own(item, alias))) continue;
      if (key === "slot_id" || key === "role") {
        const normalized = normalizeText(firstPresent(item, aliases), context, contentId, key, `${path}[${index}].${key}`, true);
        if (normalized) out[key] = normalized;
      } else if (key === "intended_single_line") {
        out[key] = normalizeBoolean(firstPresent(item, aliases), context, key, `${path}[${index}].${key}`, false);
      } else if (key === "font_pt") {
        const normalized = normalizePositiveNumber(firstPresent(item, aliases), context, key, `${path}[${index}].${key}`, undefined);
        if (normalized !== undefined) out[key] = normalized;
      } else {
        const normalized = normalizeIndex(firstPresent(item, aliases), context, key, `${path}[${index}].${key}`, { minimum: 0 });
        if (normalized !== undefined) out[key] = normalized;
      }
    }
    return out;
  });
}

function normalizePlannerFields(out, raw, context, contentId, path) {
  const category = firstPresent(raw, ["category"]);
  const categoryHint = firstPresent(raw, ["category_hint", "categoryHint"]) ?? category;
  if (categoryHint !== undefined) {
    const value = normalizeText(categoryHint, context, contentId, "category_hint", `${path}.category_hint`, true);
    if (value) out.category_hint = value;
  }
  if (category !== undefined) {
    const value = normalizeText(category, context, contentId, "category", `${path}.category`, true);
    if (value) out.category = value;
  }
  for (const [name, aliases] of [["narrative_job", ["narrative_job", "narrativeJob"]], ["question", ["question"]], ["takeaway", ["takeaway"]], ["notes", ["notes"]]]) {
    if (!aliases.some((key) => own(raw, key))) continue;
    const value = normalizeText(firstPresent(raw, aliases), context, contentId, name, `${path}.${name}`, true);
    if (value) out[name] = value;
  }
  const integerFields = [
    ["text_chars", ["text_chars", "textChars"]], ["title_chars", ["title_chars", "titleChars"]],
    ["image_count", ["image_count", "imageCount"]], ["table_count", ["table_count", "tableCount"]],
    ["chart_count", ["chart_count", "chartCount"]], ["process_step_count", ["process_step_count", "processStepCount"]],
  ];
  for (const [name, aliases] of integerFields) {
    if (!aliases.some((key) => own(raw, key))) continue;
    const value = normalizeIndex(firstPresent(raw, aliases), context, name, `${path}.${name}`, { minimum: 0 });
    if (value !== undefined) out[name] = value;
  }
  if (own(raw, "text_chars_by_role") || own(raw, "textCharsByRole")) {
    const value = normalizeTextCharsByRole(firstPresent(raw, ["text_chars_by_role", "textCharsByRole"]), context, contentId, `${path}.text_chars_by_role`);
    if (value !== undefined) out.text_chars_by_role = value;
  }
  if (own(raw, "visual_aspect_ratio") || own(raw, "visualAspectRatio")) {
    const value = normalizePositiveNumber(firstPresent(raw, ["visual_aspect_ratio", "visualAspectRatio"]), context, "visual_aspect_ratio", `${path}.visual_aspect_ratio`, undefined);
    if (value !== undefined) out.visual_aspect_ratio = value;
  }
  if (own(raw, "visual_safety_margin") || own(raw, "visualSafetyMargin")) {
    const value = normalizeNonnegativeNumber(firstPresent(raw, ["visual_safety_margin", "visualSafetyMargin"]), context, "visual_safety_margin", `${path}.visual_safety_margin`, 0.1);
    if (value !== undefined) out.visual_safety_margin = value;
  }
  if (own(raw, "content_roles") || own(raw, "contentRoles")) {
    out.content_roles = normalizeStringArray(firstPresent(raw, ["content_roles", "contentRoles"]), context, contentId, "content_roles", `${path}.content_roles`, { splitCommas: true });
  }
  for (const [name, aliases] of [["viewing_mode", ["viewing_mode", "viewingMode"]], ["density_preference", ["density_preference", "densityPreference"]]]) {
    if (!aliases.some((key) => own(raw, key))) continue;
    const value = normalizeText(firstPresent(raw, aliases), context, contentId, name, `${path}.${name}`);
    if (value) out[name] = value;
  }
  if (own(raw, "allow_auto_split") || own(raw, "allowAutoSplit")) out.allow_auto_split = normalizeBoolean(firstPresent(raw, ["allow_auto_split", "allowAutoSplit"]), context, "allow_auto_split", `${path}.allow_auto_split`, true);
  if (own(raw, "slot_metrics") || own(raw, "slotMetrics")) {
    const value = normalizeSlotMetrics(firstPresent(raw, ["slot_metrics", "slotMetrics"]), context, contentId, `${path}.slot_metrics`);
    if (value !== undefined) out.slot_metrics = value;
  }
}

function normalizeSlideBrief(raw, index, context, factories, path) {
  if (!isRecord(raw)) {
    context.violation({ code: "INVALID_INPUT", field: path, path, actual: raw, capacity: "object", recommended_action: "provide_slide_brief_objects", message: `${path} must be an object.` });
    return null;
  }
  noteForbiddenFields(raw, path, context);
  const identifier = idInfo(firstPresent(raw, ["slide_id", "slideId", "id"]), factories.slide, SLIDE_ID_PATTERN, context, "slide_id", `${path}.slide_id`);
  const category = firstPresent(raw, ["category", "category_hint", "categoryHint"]);
  const slideType = normalizeText(firstPresent(raw, ["slide_type", "slideType", "type"]) ?? category ?? "custom", context, identifier.id, "slide_type", `${path}.slide_type`, true) || "custom";
  const titleRaw = firstPresent(raw, ["title", "heading"]);
  const goalRaw = firstPresent(raw, ["goal", "objective"]);
  const title = normalizeText(titleRaw ?? "", context, identifier.id, "title", `${path}.title`, true) ?? "";
  const goal = normalizeText(goalRaw ?? "", context, identifier.id, "goal", `${path}.goal`, true) ?? "";
  const claims = normalizeStructuredList(firstPresent(raw, ["claims"]), context, identifier.id, "claims", `${path}.claims`);
  const processSteps = normalizeStructuredList(firstPresent(raw, ["process_steps", "processSteps"]), context, identifier.id, "process_steps", `${path}.process_steps`);
  const timelineEvents = normalizeStructuredList(firstPresent(raw, ["timeline_events", "timelineEvents", "timeline"]), context, identifier.id, "timeline_events", `${path}.timeline_events`);
  const comparisonDimensions = normalizeStructuredList(firstPresent(raw, ["comparison_dimensions", "comparisonDimensions", "comparisons"]), context, identifier.id, "comparison_dimensions", `${path}.comparison_dimensions`);
  const experimentGroups = normalizeStructuredList(firstPresent(raw, ["experiment_groups", "experimentGroups"]), context, identifier.id, "experiment_groups", `${path}.experiment_groups`);
  const dataSeries = normalizeStructuredList(firstPresent(raw, ["data_series", "dataSeries"]), context, identifier.id, "data_series", `${path}.data_series`);
  const visuals = normalizeVisualList(firstPresent(raw, ["visuals"]), context, identifier.id, `${path}.visuals`);
  const citationIds = normalizeStringArray(firstPresent(raw, ["citation_ids", "citationIds"]), context, identifier.id, "citation_ids", `${path}.citation_ids`);
  const evidenceIds = normalizeStringArray(firstPresent(raw, ["evidence_ids", "evidenceIds"]), context, identifier.id, "evidence_ids", `${path}.evidence_ids`);
  const duration = normalizePositiveNumber(firstPresent(raw, ["duration_weight", "durationWeight"]), context, "duration_weight", `${path}.duration_weight`, 1);
  if (!own(raw, "duration_weight") && !own(raw, "durationWeight")) context.log({ action: "default_normalization", content_id: identifier.id, reason: "default_duration_weight", after: duration, details: { field: `${path}.duration_weight` } });
  const out = {
    slide_id: identifier.id,
    slide_type: slideType,
    title,
    goal,
    claims,
    process_steps: processSteps,
    timeline_events: timelineEvents,
    comparison_dimensions: comparisonDimensions,
    experiment_groups: experimentGroups,
    data_series: dataSeries,
    visuals,
    citation_ids: citationIds,
    evidence_ids: evidenceIds,
    duration_weight: duration,
  };
  const body = normalizeText(firstPresent(raw, ["body"]), context, identifier.id, "body", `${path}.body`, false);
  if (body) out.body = body;
  for (const [field, aliases] of [
    ["key_points", ["key_points", "keyPoints"]],
    ["secondary_messages", ["secondary_messages", "secondaryMessages"]],
  ]) {
    if (aliases.some((key) => own(raw, key))) {
      out[field] = normalizeStringArray(firstPresent(raw, aliases), context, identifier.id, field, `${path}.${field}`);
    }
  }
  if (own(raw, "text_flow") || own(raw, "textFlow")) {
    const textFlow = normalizeText(firstPresent(raw, ["text_flow", "textFlow"]), context, identifier.id, "text_flow", `${path}.text_flow`, true);
    if (!["auto", "plain", "distributed_arrow_list"].includes(textFlow)) {
      context.violation({
        code: "INVALID_INPUT",
        field: "text_flow",
        path: `${path}.text_flow`,
        actual: textFlow,
        capacity: ["auto", "plain", "distributed_arrow_list"],
        recommended_action: "use_supported_text_flow",
        message: "text_flow must be auto, plain, or distributed_arrow_list.",
      });
    } else out.text_flow = textFlow;
  }
  if (own(raw, "evidence_texts") || own(raw, "evidenceTexts")) {
    const evidenceTexts = firstPresent(raw, ["evidence_texts", "evidenceTexts"]);
    if (Array.isArray(evidenceTexts)) {
      out.evidence_texts = evidenceTexts.map((entry) => (isRecord(entry) ? cloneValue(entry) : entry));
    } else if (isRecord(evidenceTexts)) {
      out.evidence_texts = cloneValue(evidenceTexts);
    }
  }
  normalizePlannerFields(out, raw, context, identifier.id, path);
  normalizeMetadata(out, raw, context, path);
  return { record: out, aliases: identifier.aliases, original: identifier.original, generated: identifier.generated, index };
}

function candidateFingerprint(record, idKey) {
  const copy = { ...record };
  delete copy[idKey];
  return stableSerialize(copy);
}

function sourceIdentity(record) {
  if (record.source_sha256) return `source_sha256:${record.source_sha256}`;
  if (record.markdown_sha256) return `markdown_sha256:${record.markdown_sha256}`;
  if (record.source_fingerprint) return `source_fingerprint:${record.source_fingerprint}`;
  return undefined;
}

function mapAliases(map, candidate, id, idKey) {
  for (const alias of candidate.aliases ?? []) if (!map.has(alias)) map.set(alias, id);
  const recordId = candidate.record?.[idKey];
  if (recordId !== undefined && !map.has(recordId)) map.set(recordId, id);
}

function mergeCandidates(candidates, collection, idKey, factory, context) {
  const records = [];
  const byId = new Map();
  const byFingerprint = new Map();
  const byIdentity = new Map();
  const idMap = new Map();
  for (const candidate of candidates) {
    if (!candidate) continue;
    const record = { ...candidate.record };
    const id = record[idKey];
    const fingerprint = candidateFingerprint(record, idKey);
    const identity = collection === "sources" ? sourceIdentity(record) : undefined;
    const existingById = byId.get(id);
    if (existingById) {
      if (stableSerialize(existingById.record) === stableSerialize(record)) {
        mapAliases(idMap, candidate, existingById.record[idKey], idKey);
        context.log({ action: "deduplicate_exact", content_id: existingById.record[idKey], reason: "duplicate_record_first_seen_wins", details: { collection, duplicate_id: id } });
        continue;
      }
      const field = `${collection}[${candidate.index}].${idKey}`;
      context.violation({
        code: "INVALID_INPUT",
        field,
        path: field,
        actual: id,
        capacity: "unique ID with one content value",
        severity: "error",
        recoverable: true,
        recommended_action: "reconcile_duplicate_id",
        message: `Duplicate ${idKey} ${id} has conflicting content.`,
      });
      const replacement = factory.next();
      context.log({ action: "reassign_generated_id", content_id: replacement, reason: "conflicting_duplicate_id", before: id, after: replacement, details: { collection, field } });
      record[idKey] = replacement;
    } else {
      const existingByIdentity = identity ? byIdentity.get(identity) : undefined;
      const existingByFingerprint = byFingerprint.get(fingerprint);
      const duplicate = existingByIdentity ?? existingByFingerprint;
      if (duplicate) {
        mapAliases(idMap, candidate, duplicate.record[idKey], idKey);
        context.log({
          action: existingByIdentity && stableSerialize(duplicate.record) !== stableSerialize(record) ? "deduplicate_identity" : "deduplicate_exact",
          content_id: duplicate.record[idKey],
          reason: existingByIdentity ? "source_content_identity_first_seen_wins" : "duplicate_record_first_seen_wins",
          details: { collection, duplicate_id: id },
        });
        continue;
      }
    }
    const stored = { ...candidate, record };
    records.push(stored.record);
    byId.set(record[idKey], stored);
    byFingerprint.set(candidateFingerprint(record, idKey), stored);
    if (identity) byIdentity.set(identity, stored);
    mapAliases(idMap, stored, record[idKey], idKey);
  }
  return { records, idMap };
}

function remapId(value, idMap) {
  if (typeof value !== "string") return value;
  return idMap.get(value) ?? value;
}

function remapCandidates(candidates, field, idMap) {
  for (const candidate of candidates) {
    if (!candidate) continue;
    const record = candidate.record;
    if (field === "source_id" && own(record, "source_id")) record.source_id = remapId(record.source_id, idMap);
    if (field === "citation_ids" && Array.isArray(record.citation_ids)) record.citation_ids = record.citation_ids.map((id) => remapId(id, idMap));
    if (field === "evidence_ids" && Array.isArray(record.evidence_ids)) record.evidence_ids = record.evidence_ids.map((id) => remapId(id, idMap));
    if (Array.isArray(record.visuals)) {
      for (const visual of record.visuals) {
        if (isRecord(visual) && Array.isArray(visual.citation_ids)) visual.citation_ids = visual.citation_ids.map((id) => remapId(id, idMap));
        if (isRecord(visual) && Array.isArray(visual.evidence_ids)) visual.evidence_ids = visual.evidence_ids.map((id) => remapId(id, idMap));
      }
    }
  }
}

function validateReferenceArray(values, validIds, field, recommendedAction, message, context) {
  for (const [index, id] of (Array.isArray(values) ? values : []).entries()) {
    if (validIds.has(id)) continue;
    const path = `${field}[${index}]`;
    context.violation({
      code: "INVALID_INPUT",
      field,
      path,
      actual: id,
      capacity: [...validIds],
      recommended_action: recommendedAction,
      message,
    });
  }
}

function validateReferences(sources, citations, evidence, slideBriefs, context) {
  const sourceIds = new Set(sources.map((item) => item.source_id));
  const citationIds = new Set(citations.map((item) => item.citation_id));
  const evidenceIds = new Set(evidence.map((item) => item.evidence_id));
  citations.forEach((citation, index) => {
    if (!sourceIds.has(citation.source_id)) {
      const field = `citations[${index}].source_id`;
      context.violation({ code: "INVALID_INPUT", field, path: field, actual: citation.source_id, capacity: [...sourceIds], recommended_action: "add_source_or_fix_source_id", message: "Citation source_id does not resolve to a Source." });
    }
  });
  evidence.forEach((item, index) => {
    validateReferenceArray(item.citation_ids, citationIds, `evidence[${index}].citation_ids`, "add_citation_or_fix_citation_ids", "Evidence citation_id does not resolve to a Citation.", context);
  });
  slideBriefs.forEach((brief, index) => {
    validateReferenceArray(brief.evidence_ids, evidenceIds, `slide_briefs[${index}].evidence_ids`, "add_evidence_or_fix_evidence_ids", "Slide Brief evidence_id does not resolve to Evidence.", context);
    validateReferenceArray(brief.citation_ids, citationIds, `slide_briefs[${index}].citation_ids`, "add_citation_or_fix_citation_ids", "Slide Brief citation_id does not resolve to a Citation.", context);
    for (const [visualIndex, visual] of (Array.isArray(brief.visuals) ? brief.visuals : []).entries()) {
      if (!isRecord(visual)) continue;
      validateReferenceArray(
        visual.evidence_ids,
        evidenceIds,
        `slide_briefs[${index}].visuals[${visualIndex}].evidence_ids`,
        "add_evidence_or_fix_evidence_ids",
        "Visual evidence_id does not resolve to Evidence.",
        context,
      );
      validateReferenceArray(
        visual.citation_ids,
        citationIds,
        `slide_briefs[${index}].visuals[${visualIndex}].citation_ids`,
        "add_citation_or_fix_citation_ids",
        "Visual citation_id does not resolve to a Citation.",
        context,
      );
      for (const [regionIndex, region] of (Array.isArray(visual.semantic_regions) ? visual.semantic_regions : []).entries()) {
        if (!isRecord(region)) continue;
        validateReferenceArray(
          region.evidence_ids,
          evidenceIds,
          `slide_briefs[${index}].visuals[${visualIndex}].semantic_regions[${regionIndex}].evidence_ids`,
          "add_evidence_or_fix_evidence_ids",
          "Visual semantic region evidence_id does not resolve to Evidence.",
          context,
        );
        validateReferenceArray(
          region.citation_ids,
          citationIds,
          `slide_briefs[${index}].visuals[${visualIndex}].semantic_regions[${regionIndex}].citation_ids`,
          "add_citation_or_fix_citation_ids",
          "Visual semantic region citation_id does not resolve to a Citation.",
          context,
        );
      }
    }
  });
}

function collectCoverageFindings(sources, citations, evidence, slideBriefs) {
  const referencedEvidence = new Set();
  const referencedCitations = new Set();
  const addReferences = (target, values) => {
    for (const id of Array.isArray(values) ? values : []) target.add(id);
  };
  for (const brief of slideBriefs) {
    addReferences(referencedEvidence, brief.evidence_ids);
    addReferences(referencedCitations, brief.citation_ids);
    for (const visual of Array.isArray(brief.visuals) ? brief.visuals : []) {
      if (!isRecord(visual)) continue;
      addReferences(referencedEvidence, visual.evidence_ids);
      addReferences(referencedCitations, visual.citation_ids);
      for (const region of Array.isArray(visual.semantic_regions) ? visual.semantic_regions : []) {
        if (!isRecord(region)) continue;
        addReferences(referencedEvidence, region.evidence_ids);
        addReferences(referencedCitations, region.citation_ids);
      }
    }
  }
  for (const item of evidence) {
    for (const id of item.citation_ids ?? []) referencedCitations.add(id);
  }
  const orphanMustKeepEvidence = evidence
    .filter((item) => item.must_keep === true && !referencedEvidence.has(item.evidence_id))
    .map((item) => item.evidence_id);
  const unusedCitations = citations
    .filter((item) => !referencedCitations.has(item.citation_id))
    .map((item) => item.citation_id);
  return {
    orphan_must_keep_evidence: orphanMustKeepEvidence,
    unused_citations: unusedCitations,
  };
}

function finalClean(value) {
  if (Array.isArray(value)) return value.map((item) => finalClean(item));
  if (!isRecord(value)) return value;
  const out = {};
  for (const key of Object.keys(value)) {
    if (FORBIDDEN_OUTPUT_KEYS.has(key)) continue;
    out[key] = finalClean(value[key]);
  }
  return out;
}

function makeEnvelope(sources, citations, evidence, slideBriefs, context) {
  validateReferences(sources, citations, evidence, slideBriefs, context);
  const coverage = collectCoverageFindings(sources, citations, evidence, slideBriefs);
  return finalClean({
    schema_version: CONTENT_MODEL_VERSION,
    status: context.violations.length ? "invalid" : "valid",
    sources,
    citations,
    evidence,
    slide_briefs: slideBriefs,
    violations: context.violations,
    coverage,
    adaptation_log: context.adaptation_log,
  });
}

function upstreamEntries(workflow) {
  if (!isRecord(workflow)) return [];
  const registry = workflow.evidence_registry ?? workflow.evidenceRegistry ?? workflow.evidence;
  if (registry === undefined || registry === null) return [];
  if (Array.isArray(registry)) return registry.map((item, index) => [undefined, item, index]);
  if (isRecord(registry)) return Object.entries(registry).map(([key, item], index) => [key, item, index]);
  return [];
}

function adaptWorkflow(workflow, options, context, factories) {
  if (!isRecord(workflow)) {
    context.violation({ code: "INVALID_INPUT", field: "paperworkflow_v4", path: "paperworkflow_v4", actual: workflow, capacity: "object", recommended_action: "provide_an_in_memory_workflow_object", message: "paperworkflow_v4 must be an object." });
    return { sources: [], citations: [], evidence: [], slideBriefs: [] };
  }
  noteForbiddenFields(workflow, "paperworkflow_v4", context);
  if (own(workflow, "schema_version") && ![4, "4", "4.0", "4.0.0"].includes(workflow.schema_version)) {
    context.violation({ code: "INVALID_INPUT", field: "paperworkflow_v4.schema_version", path: "paperworkflow_v4.schema_version", actual: workflow.schema_version, capacity: "4", recommended_action: "provide_paperworkflow_v4_input", message: "The upstream workflow is not PaperWorkflow v4." });
  }
  const sourceCandidates = [];
  if (workflow.source !== undefined && workflow.source !== null) {
    const sourceCandidate = normalizeSource(workflow.source, 0, context, factories, "paperworkflow_v4.source");
    if (sourceCandidate) sourceCandidates.push(sourceCandidate);
  }
  const defaultSourceId = sourceCandidates[0]?.record.source_id;
  const citationCandidates = [];
  const evidenceCandidates = [];
  const registryValue = workflow.evidence_registry ?? workflow.evidenceRegistry ?? workflow.evidence;
  if (registryValue !== undefined && registryValue !== null && !Array.isArray(registryValue) && !isRecord(registryValue)) {
    context.violation({ code: "INVALID_INPUT", field: "paperworkflow_v4.evidence_registry", path: "paperworkflow_v4.evidence_registry", actual: registryValue, capacity: "array or object", recommended_action: "provide_an_evidence_registry", message: "evidence_registry must be an array or object." });
  }
  for (const [key, raw, index] of upstreamEntries(workflow)) {
    if (!isRecord(raw)) {
      context.violation({ code: "INVALID_INPUT", field: `paperworkflow_v4.evidence_registry[${index}]`, path: `paperworkflow_v4.evidence_registry[${index}]`, actual: raw, capacity: "object", recommended_action: "provide_evidence_registry_objects", message: "Evidence registry entries must be objects." });
      continue;
    }
    const entry = { ...raw };
    if (firstPresent(entry, ["evidence_id", "evidenceId"]) === undefined && key !== undefined) entry.evidence_id = key;
    if (firstPresent(entry, ["source_id", "sourceId"]) === undefined && defaultSourceId !== undefined) entry.source_id = defaultSourceId;
    const citation = normalizeCitation(entry, index, context, factories, `paperworkflow_v4.evidence_registry[${index}]`, { defaultSourceId, upstream: true });
    if (citation) {
      citationCandidates.push(citation);
    }
    const evidence = normalizeEvidence(entry, index, context, factories, `paperworkflow_v4.evidence_registry[${index}]`, { defaultSourceId, defaultCitationId: citation?.record.citation_id, upstream: true });
    if (evidence) evidenceCandidates.push(evidence);
  }
  const slideBriefCandidates = [];
  const optionBriefs = options?.slide_briefs;
  if (optionBriefs !== undefined && optionBriefs !== null) {
    for (const [index, raw] of arrayInput(optionBriefs, context, "slide_briefs", "options.slide_briefs").entries()) {
      const brief = normalizeSlideBrief(raw, index, context, factories, `options.slide_briefs[${index}]`);
      if (brief) slideBriefCandidates.push(brief);
    }
  }
  return { sources: sourceCandidates, citations: citationCandidates, evidence: evidenceCandidates, slideBriefs: slideBriefCandidates };
}

function assembleContent(canonical, upstream, context, factories) {
  const sourceCandidates = [...canonical.sources, ...upstream.sources];
  const citationCandidates = [...canonical.citations, ...upstream.citations];
  const evidenceCandidates = [...canonical.evidence, ...upstream.evidence];
  const slideBriefCandidates = [...canonical.slideBriefs, ...upstream.slideBriefs];
  const mergedSources = mergeCandidates(sourceCandidates, "sources", "source_id", factories.source, context);
  remapCandidates(citationCandidates, "source_id", mergedSources.idMap);
  remapCandidates(evidenceCandidates, "source_id", mergedSources.idMap);
  const mergedCitations = mergeCandidates(citationCandidates, "citations", "citation_id", factories.citation, context);
  remapCandidates(evidenceCandidates, "citation_ids", mergedCitations.idMap);
  const mergedEvidence = mergeCandidates(evidenceCandidates, "evidence", "evidence_id", factories.evidence, context);
  remapCandidates(slideBriefCandidates, "evidence_ids", mergedEvidence.idMap);
  remapCandidates(slideBriefCandidates, "citation_ids", mergedCitations.idMap);
  const mergedSlideBriefs = mergeCandidates(slideBriefCandidates, "slide_briefs", "slide_id", factories.slide, context);
  return makeEnvelope(mergedSources.records, mergedCitations.records, mergedEvidence.records, mergedSlideBriefs.records, context);
}

class NormalizationContext {
  constructor() {
    this.violations = [];
    this.adaptation_log = [];
  }

  violation(input) {
    this.violations.push(createViolation(input));
  }

  log(input) {
    this.adaptation_log.push(createAdaptationLogEntry(input));
  }
}

export const CONTENT_MODEL_VERSION = "0.3.3";
export const CONTENT_ROLES = deepFreeze([
  "primary_claim",
  "primary_evidence",
  "supporting_evidence",
  "caption",
  "context",
  "optional_visual",
]);
export const EVIDENCE_TYPES = deepFreeze([
  "direct_observation",
  "measurement",
  "simulation",
  "fit",
  "author_inference",
  "reviewer_inference",
  "extrapolation",
  "method_protocol",
  "figure_caption",
]);

const RANGE_SCHEMA = {
  type: "object",
  properties: {
    start: { type: "integer", minimum: 0 },
    end: { type: "integer", minimum: 0 },
  },
  required: ["start", "end"],
  additionalProperties: false,
};

const STRING_ARRAY_SCHEMA = { type: "array", items: { type: "string" } };
const METADATA_SCHEMA = { type: "object", additionalProperties: true };
const JSON_VALUE_SCHEMA = {};
export const VISUAL_SOURCE_DIMENSIONS_SCHEMA = deepFreeze({
  source_width_px: { type: "integer", minimum: 1 },
  source_height_px: { type: "integer", minimum: 1 },
});
const SLOT_METRIC_SCHEMA = {
  type: "object",
  properties: {
    slot_id: { type: "string" },
    role: { type: "string" },
    text_chars: { type: "integer", minimum: 0 },
    font_pt: { type: "number", exclusiveMinimum: 0 },
    line_count: { type: "integer", minimum: 0 },
    intended_single_line: { type: "boolean" },
  },
  additionalProperties: false,
};
const VISUAL_SCHEMA = {
  type: "object",
  properties: {
    visual_id: { type: "string" },
    visual_type: { type: "string" },
    title: { type: "string" },
    caption: { type: "string" },
    description: { type: "string" },
    alt_text: { type: "string" },
    label: { type: "string" },
    asset_uri: { type: "string" },
    uri: { type: "string" },
    source_id: { type: "string" },
    ...VISUAL_SOURCE_DIMENSIONS_SCHEMA,
    figure_table_ref: { type: "string" },
    evidence_ids: STRING_ARRAY_SCHEMA,
    citation_ids: STRING_ARRAY_SCHEMA,
    panel_count: { type: "integer", minimum: 1 },
    has_embedded_text: { type: "boolean" },
    min_display_width: { type: "number", exclusiveMinimum: 0 },
    display_width_norm: { type: "number", minimum: 0, maximum: 1 },
    display_height_norm: { type: "number", minimum: 0, maximum: 1 },
    rendered_embedded_text_px: { type: "number", minimum: 0 },
    visual_aspect_ratio: { type: "number", exclusiveMinimum: 0 },
    visual_safety_margin: { type: "number", minimum: 0, maximum: 0.5 },
    embedded_text_density: { type: "number", minimum: 0, maximum: 1 },
    caption_chars: { type: "integer", minimum: 0 },
    source_visual_id: { type: "string" },
    region_id: { type: "string" },
    semantic_relation: { enum: ["parallel_evidence", "support", "causal", "comparison", "sequence"] },
    semantic_regions: {
      type: "array",
      items: {
        type: "object",
        properties: {
          region_id: { type: "string" },
          label: { type: "string" },
          roi: JSON_VALUE_SCHEMA,
          evidence_ids: STRING_ARRAY_SCHEMA,
          citation_ids: STRING_ARRAY_SCHEMA,
        },
        required: ["region_id", "roi"],
        additionalProperties: false,
      },
    },
    importance: { type: "integer", minimum: 1 },
    must_keep: { type: "boolean" },
    recommended_crop: JSON_VALUE_SCHEMA,
    data: JSON_VALUE_SCHEMA,
    metadata: METADATA_SCHEMA,
  },
  additionalProperties: false,
};

export const SOURCE_SCHEMA = deepFreeze({
  $id: "Source",
  type: "object",
  properties: {
    source_id: { type: "string", pattern: "^SRC[0-9]{4}$" },
    source_identity: { type: "string" },
    source_sha256: { type: "string" },
    markdown_sha256: { type: "string" },
    source_fingerprint: { type: "string" },
    input_path: { type: "string" },
    input_type: { type: "string" },
    markdown_path: { type: "string" },
    title: { type: "string" },
    label: { type: "string" },
    uri: { type: "string" },
    url: { type: "string" },
    doi: { type: "string" },
    metadata: METADATA_SCHEMA,
  },
  required: ["source_id"],
  additionalProperties: false,
});

export const CITATION_SCHEMA = deepFreeze({
  $id: "Citation",
  type: "object",
  properties: {
    citation_id: { type: "string", pattern: "^CIT[0-9]{4}$" },
    source_id: { type: "string", pattern: "^SRC[0-9]{4}$" },
    evidence_id: { type: "string", pattern: "^EV[0-9]{4}$" },
    span_id: { type: "string", pattern: "^S[0-9]{4}$" },
    chunk_id: { type: "string", pattern: "^E[0-9]{3}$" },
    source_lines: RANGE_SCHEMA,
    source_chars: RANGE_SCHEMA,
    source_chars_end_exclusive: { type: "boolean", const: true },
    modality: { type: "string" },
    support_type: { enum: EVIDENCE_TYPES },
    evidence_type: { enum: EVIDENCE_TYPES },
    text: { type: "string" },
    query_ids: STRING_ARRAY_SCHEMA,
    queries: STRING_ARRAY_SCHEMA,
    label: { type: "string" },
    reference_number: { type: "string" },
    bibliography_id: { type: "string" },
    metadata: METADATA_SCHEMA,
  },
  required: ["citation_id", "source_id"],
  additionalProperties: false,
});

export const EVIDENCE_SCHEMA = deepFreeze({
  $id: "Evidence",
  type: "object",
  properties: {
    evidence_id: { type: "string", pattern: "^EV[0-9]{4}$" },
    importance: { type: "integer", minimum: 1 },
    must_keep: { type: "boolean" },
    content_role: { enum: CONTENT_ROLES },
    citation_ids: STRING_ARRAY_SCHEMA,
    source_id: { type: "string", pattern: "^SRC[0-9]{4}$" },
    span_id: { type: "string", pattern: "^S[0-9]{4}$" },
    chunk_id: { type: "string", pattern: "^E[0-9]{3}$" },
    source_lines: RANGE_SCHEMA,
    source_chars: RANGE_SCHEMA,
    source_chars_end_exclusive: { type: "boolean", const: true },
    claim: JSON_VALUE_SCHEMA,
    claim_text: { type: "string" },
    evidence: JSON_VALUE_SCHEMA,
    evidence_text: { type: "string" },
    text: { type: "string" },
    source_section: { type: "string" },
    figure_table_ref: { type: "string" },
    confidence: { type: "number" },
    recommended_crop: JSON_VALUE_SCHEMA,
    modality: { type: "string" },
    support_type: { enum: EVIDENCE_TYPES },
    evidence_type: { enum: EVIDENCE_TYPES },
    query_ids: STRING_ARRAY_SCHEMA,
    queries: STRING_ARRAY_SCHEMA,
    metadata: METADATA_SCHEMA,
  },
  required: ["evidence_id", "importance", "must_keep", "content_role", "citation_ids"],
  additionalProperties: false,
});

export const SLIDE_BRIEF_SCHEMA = deepFreeze({
  $id: "SlideBrief",
  type: "object",
  properties: {
    slide_id: { type: "string", pattern: "^SLIDE[0-9]{4}$" },
    slide_type: { type: "string" },
    title: { type: "string" },
    goal: { type: "string" },
    claims: { type: "array", items: JSON_VALUE_SCHEMA },
    process_steps: { type: "array", items: JSON_VALUE_SCHEMA },
    timeline_events: { type: "array", items: JSON_VALUE_SCHEMA },
    comparison_dimensions: { type: "array", items: JSON_VALUE_SCHEMA },
    experiment_groups: { type: "array", items: JSON_VALUE_SCHEMA },
    data_series: { type: "array", items: JSON_VALUE_SCHEMA },
    visuals: { type: "array", items: VISUAL_SCHEMA },
    citation_ids: STRING_ARRAY_SCHEMA,
    evidence_ids: STRING_ARRAY_SCHEMA,
    duration_weight: { type: "number", exclusiveMinimum: 0 },
    category_hint: { type: "string" },
    category: { type: "string" },
    narrative_job: { type: "string" },
    question: { type: "string" },
    takeaway: { type: "string" },
    notes: { type: "string" },
    body: { type: "string" },
    key_points: STRING_ARRAY_SCHEMA,
    secondary_messages: STRING_ARRAY_SCHEMA,
    text_flow: { enum: ["auto", "plain", "distributed_arrow_list"] },
    evidence_texts: { type: "array", items: { type: "object", additionalProperties: true } },
    text_chars: { type: "integer", minimum: 0 },
    text_chars_by_role: { type: "object", additionalProperties: { type: "integer", minimum: 0 } },
    title_chars: { type: "integer", minimum: 0 },
    image_count: { type: "integer", minimum: 0 },
    table_count: { type: "integer", minimum: 0 },
    chart_count: { type: "integer", minimum: 0 },
    process_step_count: { type: "integer", minimum: 0 },
    visual_aspect_ratio: { type: "number", exclusiveMinimum: 0 },
    content_roles: STRING_ARRAY_SCHEMA,
    viewing_mode: { type: "string" },
    density_preference: { type: "string" },
    allow_auto_split: { type: "boolean" },
    slot_metrics: { type: "array", items: SLOT_METRIC_SCHEMA },
    metadata: METADATA_SCHEMA,
  },
  required: ["slide_id", "slide_type", "title", "goal", "claims", "process_steps", "timeline_events", "comparison_dimensions", "experiment_groups", "data_series", "visuals", "citation_ids", "evidence_ids", "duration_weight"],
  additionalProperties: false,
});

export const VIOLATION_SCHEMA = deepFreeze({
  $id: "Violation",
  type: "object",
  properties: {
    code: { type: "string" },
    field: { type: "string" },
    actual: JSON_VALUE_SCHEMA,
    capacity: JSON_VALUE_SCHEMA,
    severity: { enum: ["error", "warning", "info"] },
    recoverable: { type: "boolean" },
    recommended_action: { type: "string" },
    message: { type: "string" },
    suggestion: { type: "string" },
    path: { type: "string" },
    details: JSON_VALUE_SCHEMA,
  },
  required: ["code", "field", "actual", "capacity", "severity", "recoverable", "recommended_action"],
  additionalProperties: false,
});

export const ADAPTATION_LOG_SCHEMA = deepFreeze({
  $id: "AdaptationLogEntry",
  type: "object",
  properties: {
    action: { type: "string" },
    content_id: { type: "string" },
    reason: { type: "string" },
    before_chars: { type: "integer", minimum: 0 },
    after_chars: { type: "integer", minimum: 0 },
    before: JSON_VALUE_SCHEMA,
    after: JSON_VALUE_SCHEMA,
    details: JSON_VALUE_SCHEMA,
  },
  required: ["action", "content_id", "reason"],
  additionalProperties: false,
});

export const CONTENT_MODEL_INPUT_SCHEMA = deepFreeze({
  $id: "ContentModelInput",
  type: "object",
  properties: {
    sources: { type: "array", items: { type: "object", properties: SOURCE_SCHEMA.properties, additionalProperties: false } },
    citations: { type: "array", items: { type: "object", properties: CITATION_SCHEMA.properties, additionalProperties: false } },
    evidence: { type: "array", items: { type: "object", properties: EVIDENCE_SCHEMA.properties, additionalProperties: false } },
    slide_briefs: { type: "array", items: { type: "object", properties: SLIDE_BRIEF_SCHEMA.properties, additionalProperties: false } },
    paperworkflow_v4: {
      type: "object",
      description: "In-memory PaperWorkflow v4 JSON adapter input; no file paths are read.",
      properties: {
        schema_version: { type: ["integer", "string"] },
        source: { type: "object" },
        evidence_registry: { type: ["array", "object"] },
      },
      additionalProperties: true,
    },
  },
  additionalProperties: false,
});

export function createViolation(input = {}) {
  if (!isRecord(input)) throw new TypeError("createViolation expects an object.");
  const code = nonEmptyString(input.code);
  const field = nonEmptyString(input.field);
  const recommendedAction = nonEmptyString(input.recommended_action ?? input.recommendedAction);
  if (!code || !field || !recommendedAction) throw new TypeError("Violation code, field, and recommended_action are required.");
  const severity = input.severity ?? "error";
  if (!["error", "warning", "info"].includes(severity)) throw new TypeError("Violation severity must be error, warning, or info.");
  let recoverable = input.recoverable;
  if (recoverable === undefined) recoverable = true;
  if (typeof recoverable !== "boolean") {
    if (recoverable === 1 || recoverable === "true" || recoverable === "1" || recoverable === "yes") recoverable = true;
    else if (recoverable === 0 || recoverable === "false" || recoverable === "0" || recoverable === "no") recoverable = false;
    else throw new TypeError("Violation recoverable must be boolean.");
  }
  const output = {
    code,
    field,
    actual: own(input, "actual") && input.actual !== undefined ? cloneValue(input.actual) : null,
    capacity: own(input, "capacity") && input.capacity !== undefined ? cloneValue(input.capacity) : null,
    severity,
    recoverable,
    recommended_action: recommendedAction,
  };
  for (const key of ["message", "suggestion", "path", "details"]) {
    if (!own(input, key) || input[key] === undefined) continue;
    if (["message", "suggestion", "path"].includes(key)) {
      const value = nonEmptyString(input[key]);
      if (value) output[key] = value;
    } else output[key] = cloneValue(input[key]);
  }
  return output;
}

export function createAdaptationLogEntry(input = {}) {
  if (!isRecord(input)) throw new TypeError("createAdaptationLogEntry expects an object.");
  const action = nonEmptyString(input.action);
  const contentId = nonEmptyString(input.content_id ?? input.contentId);
  const reason = nonEmptyString(input.reason);
  if (!action || !contentId || !reason) throw new TypeError("Adaptation log action, content_id, and reason are required.");
  const output = { action, content_id: contentId, reason };
  for (const key of ["before_chars", "after_chars"]) {
    if (!own(input, key) || input[key] === undefined || input[key] === null) continue;
    const value = Number(input[key]);
    if (!Number.isFinite(value) || value < 0) throw new TypeError(`${key} must be a non-negative finite number.`);
    output[key] = Math.round(value);
  }
  for (const key of ["before", "after", "details"]) {
    if (own(input, key) && input[key] !== undefined) output[key] = cloneValue(input[key]);
  }
  return output;
}

export function normalizePaperWorkflowV4(workflow, options = {}) {
  const context = new NormalizationContext();
  const factories = createFactories();
  reserveRawIds(factories, workflow, { upstream: true });
  if (isRecord(options)) reserveRawIds(factories, { slide_briefs: options.slide_briefs });
  const adapted = adaptWorkflow(workflow, isRecord(options) ? options : {}, context, factories);
  return assembleContent({ sources: [], citations: [], evidence: [], slideBriefs: [] }, adapted, context, factories);
}

export function normalizeContentModel(input = {}) {
  const context = new NormalizationContext();
  if (!isRecord(input)) {
    context.violation({ code: "INVALID_INPUT", field: "input", path: "input", actual: input, capacity: "object", recommended_action: "provide_a_content_model_object", message: "Content model input must be an object." });
    return makeEnvelope([], [], [], [], context);
  }
  noteForbiddenFields(input, "input", context);
  const factories = createFactories();
  reserveRawIds(factories, input);
  reserveRawIds(factories, input.paperworkflow_v4, { upstream: true });
  const canonicalSources = [];
  const canonicalCitations = [];
  const canonicalEvidence = [];
  const canonicalSlideBriefs = [];
  for (const [index, raw] of arrayInput(input.sources, context, "sources", "sources").entries()) {
    const item = normalizeSource(raw, index, context, factories, `sources[${index}]`);
    if (item) canonicalSources.push(item);
  }
  for (const [index, raw] of arrayInput(input.citations, context, "citations", "citations").entries()) {
    const item = normalizeCitation(raw, index, context, factories, `citations[${index}]`);
    if (item) canonicalCitations.push(item);
  }
  for (const [index, raw] of arrayInput(input.evidence, context, "evidence", "evidence").entries()) {
    const item = normalizeEvidence(raw, index, context, factories, `evidence[${index}]`);
    if (item) canonicalEvidence.push(item);
  }
  for (const [index, raw] of arrayInput(input.slide_briefs, context, "slide_briefs", "slide_briefs").entries()) {
    const item = normalizeSlideBrief(raw, index, context, factories, `slide_briefs[${index}]`);
    if (item) canonicalSlideBriefs.push(item);
  }
  const adapted = input.paperworkflow_v4 === undefined || input.paperworkflow_v4 === null
    ? { sources: [], citations: [], evidence: [], slideBriefs: [] }
    : adaptWorkflow(input.paperworkflow_v4, {}, context, factories);
  return assembleContent(
    { sources: canonicalSources, citations: canonicalCitations, evidence: canonicalEvidence, slideBriefs: canonicalSlideBriefs },
    adapted,
    context,
    factories,
  );
}
