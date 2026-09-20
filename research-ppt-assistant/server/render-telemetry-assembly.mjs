import { adaptArtifactToolTelemetry } from "./renderer-adapters/artifact-tool.mjs";
import { ARTIFACT_TOOL_GEOMETRY_PROFILE, computeArtifactDisplayGeometry } from "./renderer-adapters/artifact-tool-geometry.mjs";
import { assertRenderTelemetry } from "./visual-quality/telemetry.mjs";

export const RENDER_EVIDENCE_CONTRACT_VERSION = "0.4.7";
export const RENDER_EVIDENCE_STATUSES = Object.freeze(["pass", "fail", "manual_review_required", "blocked"]);

const CANONICAL_TELEMETRY_VERSION = "1.4.0";
const ZERO_INSET = Object.freeze({ left: 0, right: 0, top: 0, bottom: 0 });
const FULL_REGION = Object.freeze({ x: 0, y: 0, width: 1, height: 1 });
const SHA256_PATTERN = /^[a-f0-9]{64}$/u;
const SUPPORTED_CROP_MODES = new Set(["full_figure", "preprocessed_fixed_region"]);
const DEFAULT_MAX_LETTERBOX_RATIO = 0.35;

function isRecord(value) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function finite(value) {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function positiveInteger(value) {
  return Number.isInteger(value) && value > 0 ? value : null;
}

function nonEmpty(value) {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function localBox(value) {
  if (Array.isArray(value) && value.length >= 4 && value.slice(0, 4).every(Number.isFinite)) {
    return { x: value[0], y: value[1], width: value[2], height: value[3] };
  }
  if (!isRecord(value)) return null;
  const box = {
    x: finite(value.x ?? value.left),
    y: finite(value.y ?? value.top),
    width: finite(value.width ?? value.w),
    height: finite(value.height ?? value.h),
  };
  return Object.values(box).every(Number.isFinite) && box.width >= 0 && box.height >= 0 ? box : null;
}

function firstDocument(input) {
  for (const value of [input, input?.layout, input?.renderer_output, input?.rendererOutput, input?.data]) {
    if (isRecord(value) && (String(value.schema ?? "").startsWith("openai.presentation.layout/") || Array.isArray(value.elements))) return value;
  }
  throw new TypeError("assemble_render_telemetry requires an artifact-tool openai.presentation.layout document");
}

function normalizeHash(value) {
  if (typeof value !== "string") return null;
  const normalized = value.trim().toLowerCase().replace(/^sha256:/u, "");
  return SHA256_PATTERN.test(normalized) ? normalized : null;
}

function rawAssetHash(element, registry) {
  for (const value of [element.asset_sha256, element.assetSha256, element.asset?.sha256, element.asset?.hash]) {
    const hash = normalizeHash(value);
    if (hash) return { hash, source: "renderer_reported_sha256" };
  }
  const assetId = nonEmpty(element.assetId ?? element.asset_id ?? element.asset?.id);
  if (assetId) {
    const registered = normalizeHash(registry?.[assetId]);
    if (registered) return { hash: registered, source: "asset_registry" };
    const hashLikeId = normalizeHash(assetId);
    if (hashLikeId) return { hash: hashLikeId, source: "renderer_hash_identifier" };
  }
  return { hash: null, source: null };
}

function rawAlt(element) {
  for (const value of [element.alt, element.altText, element.alt_text, element.accessibility?.description, element.description]) {
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  return null;
}

function visualKeyFromAlt(value) {
  const match = String(value ?? "").match(/(?:^|\s)rpa:([a-z0-9][a-z0-9._-]*)\b/iu);
  return match?.[1] ?? null;
}

function rawVisualIdentity(element) {
  const explicit = nonEmpty(element.visual_key ?? element.visualKey ?? element.metadata?.visual_key ?? element.metadata?.visualKey);
  if (explicit) return { key: explicit.replace(/^rpa:/u, ""), source: "renderer_visual_key" };
  const fallback = visualKeyFromAlt(rawAlt(element));
  return { key: fallback, source: fallback ? "image_alt_visual_key" : null };
}

function normalizeVisualEntry(entry) {
  const semantic = isRecord(entry.semantic) ? entry.semantic : {};
  const source = isRecord(entry.source) ? entry.source : {};
  return {
    ...entry,
    visual_key: entry.visual_key,
    slide_id: entry.slide_id ?? semantic.slide_id,
    description: entry.description ?? semantic.description,
    slot_id: entry.slot_id ?? semantic.slot_id,
    container_id: entry.container_id ?? semantic.container_id,
    group_id: entry.group_id ?? semantic.group_id ?? null,
    sibling_index: entry.sibling_index ?? semantic.sibling_index ?? null,
    source_visual_id: entry.source_visual_id ?? source.source_visual_id ?? entry.visual_key,
    region_id: entry.region_id ?? source.region_id ?? null,
    visual_type: entry.visual_type ?? source.visual_type,
    panel_count: entry.panel_count ?? source.panel_count,
    has_embedded_text: entry.has_embedded_text ?? source.has_embedded_text,
    source_width_px: entry.source_width_px ?? source.source_width_px,
    source_height_px: entry.source_height_px ?? source.source_height_px,
    source_region: entry.source_region ?? source.source_region,
    coordinate_space: entry.coordinate_space ?? source.coordinate_space ?? "source_normalized_0_1",
    asset_sha256: entry.asset_sha256 ?? source.asset_sha256,
    crop_mode: entry.crop_mode ?? source.crop_mode,
    parent_asset_sha256: entry.parent_asset_sha256 ?? source.parent_asset_sha256,
    parent_source_region: entry.parent_source_region ?? source.parent_source_region,
    parent_coordinate_space: entry.parent_coordinate_space ?? source.parent_coordinate_space ?? "source_normalized_0_1",
    parent_source_width_px: entry.parent_source_width_px ?? source.parent_source_width_px,
    parent_source_height_px: entry.parent_source_height_px ?? source.parent_source_height_px,
    derived_asset_sha256: entry.derived_asset_sha256 ?? source.derived_asset_sha256,
  };
}

function normalizeManifest(value) {
  if (Array.isArray(value)) {
    return {
      present: true, manifest_schema_version: null, producer_version: null, deck_id: null,
      visuals: value.filter((entry) => isRecord(entry) && typeof entry.visual_key === "string").map(normalizeVisualEntry),
      containers: value.filter((entry) => isRecord(entry) && typeof entry.container_id === "string" && typeof entry.shape_name === "string" && !entry.visual_key),
      groups: [], element_annotations: [],
    };
  }
  if (!isRecord(value)) return { present: false, manifest_schema_version: null, producer_version: null, deck_id: null, visuals: [], containers: [], groups: [], element_annotations: [] };
  if (typeof value.visual_key === "string") {
    return {
      present: true, manifest_schema_version: null, producer_version: null, deck_id: null,
      visuals: [normalizeVisualEntry(value)], containers: isRecord(value.container) ? [value.container] : [], groups: [],
      element_annotations: Array.isArray(value.element_annotations) ? value.element_annotations.filter(isRecord) : [],
    };
  }
  return {
    present: true,
    manifest_schema_version: nonEmpty(value.manifest_schema_version ?? value.manifestSchemaVersion ?? value.manifest_version),
    producer_version: nonEmpty(value.producer_version ?? value.producerVersion),
    deck_id: nonEmpty(value.deck_id ?? value.deckId),
    visuals: Array.isArray(value.visuals) ? value.visuals.filter(isRecord).map(normalizeVisualEntry) : [],
    containers: Array.isArray(value.containers) ? value.containers.filter(isRecord) : [],
    groups: Array.isArray(value.visual_groups ?? value.groups) ? (value.visual_groups ?? value.groups).filter(isRecord) : [],
    element_annotations: Array.isArray(value.element_annotations) ? value.element_annotations.filter(isRecord) : [],
  };
}

function contentBox(outer, inset = ZERO_INSET) {
  const normalized = {
    left: Math.max(0, finite(inset.left) ?? 0), right: Math.max(0, finite(inset.right) ?? 0),
    top: Math.max(0, finite(inset.top) ?? 0), bottom: Math.max(0, finite(inset.bottom) ?? 0),
  };
  const box = {
    x: outer.x + normalized.left, y: outer.y + normalized.top,
    width: outer.width - normalized.left - normalized.right, height: outer.height - normalized.top - normalized.bottom,
  };
  return box.width > 0 && box.height > 0 ? { box, inset: normalized } : null;
}

function contains(outer, inner, epsilon = 1e-6) {
  return outer && inner && inner.x >= outer.x - epsilon && inner.y >= outer.y - epsilon
    && inner.x + inner.width <= outer.x + outer.width + epsilon && inner.y + inner.height <= outer.y + outer.height + epsilon;
}

function boxesNear(left, right, tolerance = 1e-4) {
  return left && right && ["x", "y", "width", "height"].every((field) => Math.abs(left[field] - right[field]) <= tolerance);
}

function fullRegion(region, coordinateSpace, sourceWidth, sourceHeight) {
  if (!region) return false;
  if (coordinateSpace === "source_normalized_0_1") return boxesNear(region, FULL_REGION, 1e-9);
  return coordinateSpace === "source_pixels" && boxesNear(region, { x: 0, y: 0, width: sourceWidth, height: sourceHeight }, 1e-6);
}

function normalizeRegion(value, coordinateSpace, sourceWidth, sourceHeight) {
  const region = localBox(value);
  if (!region || region.width <= 0 || region.height <= 0) return null;
  if (coordinateSpace === "source_normalized_0_1") {
    if (region.x < 0 || region.y < 0 || region.x + region.width > 1 || region.y + region.height > 1) return null;
    return region;
  }
  if (coordinateSpace === "source_pixels") {
    if (!(sourceWidth > 0) || !(sourceHeight > 0) || region.x < 0 || region.y < 0 || region.x + region.width > sourceWidth || region.y + region.height > sourceHeight) return null;
    return region;
  }
  return null;
}

function removeUnavailable(telemetry, fields) {
  const resolved = new Set(fields);
  telemetry.unavailable = telemetry.unavailable.filter((item) => !resolved.has(item.field));
}

function addUnavailable(telemetry, field, reason) {
  const existing = telemetry.unavailable.find((item) => item.field === field);
  if (existing) existing.reason = reason;
  else telemetry.unavailable.push({ field, reason });
}

function issueRecord(status, code, field, message, responsibleParty, context = {}) {
  return { status, code, field, message, reason: message, responsible_party: responsibleParty, source: "render_evidence_gate", visual_key: context.visual_key ?? null, group_id: context.group_id ?? null, details: context.details ?? null };
}

function annotateElements({ annotations, rawElements, telemetry, block, fail, log }) {
  for (const [index, annotation] of annotations.entries()) {
    const matches = rawElements.map((raw, rawIndex) => ({ raw, rawIndex })).filter(({ raw }) => raw.name === annotation.shape_name);
    if (matches.length !== 1) {
      const reporter = matches.length ? block : fail;
      reporter(matches.length ? "SHAPE_NAME_AMBIGUOUS" : "SHAPE_SEMANTIC_TARGET_MISSING", `visual_manifest.element_annotations[${index}].shape_name`, matches.length ? "shape_name matched multiple renderer elements" : "declared semantic shape was not rendered", matches.length ? "deck_builder" : "renderer");
      continue;
    }
    const match = matches[0];
    const element = telemetry.elements[match.rawIndex];
    if (["content", "decoration", "background", "ignore"].includes(annotation.quality_role)) element.quality_role = annotation.quality_role;
    if (isRecord(annotation.relation)) {
      const targets = rawElements.map((raw, rawIndex) => ({ raw, rawIndex })).filter(({ raw }) => raw.name === annotation.relation.target_shape_name);
      if (targets.length !== 1) {
        const reporter = targets.length ? block : fail;
        reporter(targets.length ? "SHAPE_NAME_AMBIGUOUS" : "DECORATIVE_RELATION_TARGET_MISSING", `visual_manifest.element_annotations[${index}].relation.target_shape_name`, targets.length ? "relation target shape_name is ambiguous" : "declared relation target was not rendered", targets.length ? "deck_builder" : "renderer");
      } else {
        element.relation = { type: annotation.relation.type, target_id: telemetry.elements[targets[0].rawIndex].element_id, source: "renderer" };
      }
    }
    log.push({ kind: "element_annotation", shape_name: annotation.shape_name, element_id: element.element_id, source: "visual_manifest" });
  }
}

function cropIntent(entry, entryIndex, block, fail) {
  const context = { visual_key: entry.visual_key };
  const cropMode = nonEmpty(entry.crop_mode);
  if (!SUPPORTED_CROP_MODES.has(cropMode)) {
    block("UNSUPPORTED_RENDERER_CROP", `visual_manifest.visuals[${entryIndex}].crop_mode`, `crop mode ${cropMode ?? "missing"} is not an auditable v0.4.7 path`, "deck_builder", context);
    return null;
  }
  const sourceWidth = positiveInteger(entry.source_width_px);
  const sourceHeight = positiveInteger(entry.source_height_px);
  if (!sourceWidth || !sourceHeight) {
    block("SOURCE_DIMENSIONS_MISSING", `visual_manifest.visuals[${entryIndex}].source_width_px`, "positive source dimensions for the rendered asset are required", "deck_builder", context);
    return null;
  }
  if (cropMode === "full_figure") {
    const coordinateSpace = entry.coordinate_space === "normalized" ? "source_normalized_0_1" : entry.coordinate_space;
    const region = normalizeRegion(entry.source_region, coordinateSpace, sourceWidth, sourceHeight);
    if (!region) {
      block("SOURCE_REGION_MISSING", `visual_manifest.visuals[${entryIndex}].source_region`, "full_figure requires a valid complete source region", "deck_builder", context);
      return null;
    }
    if (!fullRegion(region, coordinateSpace, sourceWidth, sourceHeight)) fail("SEMANTIC_CROP_MISMATCH", `visual_manifest.visuals[${entryIndex}].source_region`, "full_figure intent declares a partial source region", "deck_builder", context);
    return { crop_mode: cropMode, expected_hash: normalizeHash(entry.asset_sha256), asset_width_px: sourceWidth, asset_height_px: sourceHeight, source_region: region, coordinate_space: coordinateSpace, parent_asset_sha256: null, parent_source_region: null, derived_asset_sha256: null };
  }
  const parentHash = normalizeHash(entry.parent_asset_sha256);
  const derivedHash = normalizeHash(entry.derived_asset_sha256);
  const parentCoordinateSpace = entry.parent_coordinate_space === "normalized" ? "source_normalized_0_1" : entry.parent_coordinate_space;
  const parentWidth = positiveInteger(entry.parent_source_width_px);
  const parentHeight = positiveInteger(entry.parent_source_height_px);
  const parentRegion = normalizeRegion(entry.parent_source_region, parentCoordinateSpace, parentWidth, parentHeight);
  if (!parentHash) block("PARENT_ASSET_HASH_MISSING", `visual_manifest.visuals[${entryIndex}].parent_asset_sha256`, "fixed-region lineage requires the parent asset SHA-256", "deck_builder", context);
  if (!derivedHash) block("DERIVED_ASSET_HASH_MISSING", `visual_manifest.visuals[${entryIndex}].derived_asset_sha256`, "fixed-region lineage requires the derived asset SHA-256", "deck_builder", context);
  if (!parentRegion) block("PARENT_SOURCE_REGION_MISSING", `visual_manifest.visuals[${entryIndex}].parent_source_region`, "fixed-region lineage requires a valid parent source region and parent dimensions", "deck_builder", context);
  const compatibilityHash = normalizeHash(entry.asset_sha256);
  if (compatibilityHash && derivedHash && compatibilityHash !== derivedHash) block("MANIFEST_ASSET_IDENTITY_CONFLICT", `visual_manifest.visuals[${entryIndex}].asset_sha256`, "asset_sha256 and derived_asset_sha256 disagree", "deck_builder", context);
  return { crop_mode: cropMode, expected_hash: derivedHash, asset_width_px: sourceWidth, asset_height_px: sourceHeight, source_region: FULL_REGION, coordinate_space: "source_normalized_0_1", parent_asset_sha256: parentHash, parent_source_region: parentRegion, parent_coordinate_space: parentCoordinateSpace, parent_source_width_px: parentWidth, parent_source_height_px: parentHeight, derived_asset_sha256: derivedHash };
}

function baselineValue(box, baseline) {
  if (baseline === "top") return box.y;
  if (baseline === "center") return box.y + box.height / 2;
  if (baseline === "bottom") return box.y + box.height;
  return null;
}

function verifyGroups({ manifest, telemetry, assembledByKey, block, fail }) {
  const groupsById = new Map();
  const canonicalGroups = [];
  for (const [index, group] of manifest.groups.entries()) {
    const groupId = nonEmpty(group.group_id);
    if (!groupId) { block("VISUAL_GROUP_ID_MISSING", `visual_manifest.visual_groups[${index}].group_id`, "visual group requires group_id", "deck_builder"); continue; }
    if (groupsById.has(groupId)) { block("VISUAL_GROUP_ID_DUPLICATE", `visual_manifest.visual_groups[${index}].group_id`, `duplicate group_id: ${groupId}`, "deck_builder", { group_id: groupId }); continue; }
    groupsById.set(groupId, { ...group, index });
  }
  for (const entry of manifest.visuals) {
    if (entry.group_id && !groupsById.has(entry.group_id)) block("VISUAL_GROUP_CONTRACT_MISSING", `visual_manifest.visuals.${entry.visual_key}.group_id`, `group ${entry.group_id} is not declared`, "deck_builder", { visual_key: entry.visual_key, group_id: entry.group_id });
  }
  for (const [groupId, group] of groupsById) {
    const context = { group_id: groupId };
    const expectedCount = positiveInteger(group.expected_sibling_count);
    const readingOrder = Array.isArray(group.reading_order) ? group.reading_order.map(String) : [];
    const sharedBaseline = nonEmpty(group.shared_baseline);
    const tolerance = finite(group.baseline_tolerance);
    if (!expectedCount || readingOrder.length !== expectedCount || !["none", "top", "center", "bottom"].includes(sharedBaseline) || !(tolerance >= 0 && tolerance <= 1)) {
      block("VISUAL_GROUP_CONTRACT_INCOMPLETE", `visual_manifest.visual_groups[${group.index}]`, "group requires expected_sibling_count, complete reading_order, shared_baseline, and normalized baseline_tolerance", "deck_builder", context);
      continue;
    }
    const members = manifest.visuals.filter((entry) => entry.group_id === groupId);
    const rendered = members.map((entry) => assembledByKey.get(entry.visual_key)).filter(Boolean);
    const indexes = members.map((entry) => entry.sibling_index).filter(Number.isInteger).sort((a, b) => a - b);
    const expectedIndexes = Array.from({ length: expectedCount }, (_, index) => index);
    if (members.length !== expectedCount || rendered.length !== expectedCount || JSON.stringify(indexes) !== JSON.stringify(expectedIndexes)) fail("VISUAL_GROUP_STRUCTURE_MISMATCH", `visual_manifest.visual_groups[${group.index}]`, `expected ${expectedCount} independently tracked siblings but found ${members.length} manifest and ${rendered.length} rendered members`, "renderer", context);
    const declaredOrder = [...members].sort((a, b) => a.sibling_index - b.sibling_index).map((entry) => entry.visual_key);
    const actualOrder = [...rendered].sort((a, b) => a.raw_index - b.raw_index).map((item) => item.entry.visual_key);
    if (JSON.stringify(readingOrder) !== JSON.stringify(declaredOrder) || JSON.stringify(readingOrder) !== JSON.stringify(actualOrder)) fail("VISUAL_GROUP_STRUCTURE_MISMATCH", `visual_manifest.visual_groups[${group.index}].reading_order`, "declared sibling indexes or renderer reading order do not match the group contract", "renderer", { ...context, details: { expected: readingOrder, declared: declaredOrder, actual: actualOrder } });
    if (group.require_unique_containers === true && new Set(rendered.map((item) => item.entry.container_id)).size !== expectedCount) fail("VISUAL_GROUP_STRUCTURE_MISMATCH", `visual_manifest.visual_groups[${group.index}].require_unique_containers`, "parallel siblings do not retain independent containers", "renderer", context);
    if (group.require_unique_assets === true && new Set(rendered.map((item) => item.actual_hash)).size !== expectedCount) fail("VISUAL_GROUP_STRUCTURE_MISMATCH", `visual_manifest.visual_groups[${group.index}].require_unique_assets`, "parallel siblings do not retain independent asset identities", "renderer", context);
    const sharedParent = normalizeHash(group.shared_parent_asset_sha256);
    if (sharedParent && members.some((entry) => normalizeHash(entry.parent_asset_sha256) !== sharedParent)) fail("SEMANTIC_CROP_ASSET_MISMATCH", `visual_manifest.visual_groups[${group.index}].shared_parent_asset_sha256`, "fixed-region siblings do not share the declared parent composite asset", "deck_builder", context);
    let baselineSpread = null;
    if (sharedBaseline !== "none" && rendered.length === expectedCount) {
      const values = rendered.map((item) => baselineValue(item.display_bbox, sharedBaseline) / telemetry.slide.height);
      baselineSpread = Math.max(...values) - Math.min(...values);
      if (baselineSpread > tolerance) fail("VISUAL_GROUP_STRUCTURE_MISMATCH", `visual_manifest.visual_groups[${group.index}].shared_baseline`, `shared ${sharedBaseline} baseline spread ${baselineSpread.toFixed(6)} exceeds tolerance ${tolerance}`, "renderer", context);
    }
    canonicalGroups.push({ group_id: groupId, relation_type: nonEmpty(group.relation_type) ?? "parallel_siblings", expected_sibling_count: expectedCount, actual_sibling_count: rendered.length, reading_order: readingOrder, actual_reading_order: actualOrder, shared_baseline: sharedBaseline, baseline_tolerance: tolerance, baseline_spread: baselineSpread, child_visual_ids: members.map((entry) => entry.visual_key) });
  }
  return canonicalGroups;
}

export function assembleRenderTelemetry(input = {}) {
  const rendererProfile = input.renderer_profile ?? input.rendererProfile ?? "artifact-tool";
  if (rendererProfile !== "artifact-tool") throw new RangeError(`Unsupported renderer_profile: ${rendererProfile}`);
  const document = firstDocument(input.renderer_output ?? input.rendererOutput);
  const telemetry = adaptArtifactToolTelemetry(document);
  const rawElements = Array.isArray(document.elements) ? document.elements : [];
  const manifest = normalizeManifest(input.visual_manifest ?? input.visualManifest);
  const assetRegistry = isRecord(input.asset_registry ?? input.assetRegistry) ? (input.asset_registry ?? input.assetRegistry) : {};
  const blockedIssues = [];
  const failures = [];
  const manualReview = [];
  const matchLog = [];
  const report = (collection, status) => (code, field, message, responsibleParty, context = {}) => {
    const issue = issueRecord(status, code, field, message, responsibleParty, context);
    if (!collection.some((item) => item.code === issue.code && item.field === issue.field && item.message === issue.message)) collection.push(issue);
  };
  const block = report(blockedIssues, "blocked");
  const fail = report(failures, "fail");

  if (!manifest.present) block("VISUAL_MANIFEST_MISSING", "visual_manifest", "production visual manifest is required, including for slides with an empty visuals array", "deck_builder");
  else {
    if (manifest.manifest_schema_version !== RENDER_EVIDENCE_CONTRACT_VERSION) block("TELEMETRY_SCHEMA_INCOMPATIBLE", "visual_manifest.manifest_schema_version", `expected ${RENDER_EVIDENCE_CONTRACT_VERSION}, received ${manifest.manifest_schema_version ?? "missing"}`, "deck_builder");
    if (!manifest.producer_version) block("PRODUCER_VERSION_MISSING", "visual_manifest.producer_version", "producer_version is required for release evidence", "deck_builder");
    if (!manifest.deck_id) block("DECK_ID_MISSING", "visual_manifest.deck_id", "deck_id is required for release evidence", "deck_builder");
  }

  annotateElements({ annotations: manifest.element_annotations, rawElements, telemetry, block, fail, log: matchLog });
  const keyIndexes = new Map();
  for (const [index, entry] of manifest.visuals.entries()) {
    const key = nonEmpty(entry.visual_key);
    if (!key) { block("VISUAL_KEY_MISSING", `visual_manifest.visuals[${index}].visual_key`, "scientific visual requires a stable visual_key", "deck_builder"); continue; }
    const indexes = keyIndexes.get(key) ?? [];
    indexes.push(index);
    keyIndexes.set(key, indexes);
  }
  for (const [key, indexes] of keyIndexes) if (indexes.length > 1) block("VISUAL_KEY_DUPLICATE", `visual_manifest.visuals[${indexes[1]}].visual_key`, `duplicate visual_key: ${key}`, "deck_builder", { visual_key: key });
  for (const [index, entry] of manifest.visuals.entries()) {
    if (!nonEmpty(entry.slide_id)) block("VISUAL_MANIFEST_FACT_MISSING", `visual_manifest.visuals[${index}].slide_id`, "slide_id is required to route a deck-level visual manifest", "deck_builder", { visual_key: entry.visual_key });
  }

  const rawImageKeys = new Map();
  for (const [index, raw] of rawElements.entries()) {
    if (String(raw.kind ?? raw.type ?? "").toLowerCase() !== "image") continue;
    const identity = rawVisualIdentity(raw);
    if (!identity.key) continue;
    const matches = rawImageKeys.get(identity.key) ?? [];
    matches.push({ index, raw, identity });
    rawImageKeys.set(identity.key, matches);
  }
  for (const [key, matches] of rawImageKeys) {
    if (matches.length > 1) block("VISUAL_KEY_DUPLICATE", `renderer_output.elements[${matches[1].index}].visual_key`, `duplicate renderer visual_key: ${key}`, "renderer", { visual_key: key });
    if (!keyIndexes.has(key)) fail("UNDECLARED_RENDERED_VISUAL", `renderer_output.elements[${matches[0].index}].visual_key`, `rendered visual_key ${key} has no manifest entry`, "deck_builder", { visual_key: key });
    else {
      const declared = manifest.visuals[keyIndexes.get(key)[0]];
      if (declared?.slide_id !== telemetry.slide_id) fail("VISUAL_SLIDE_BINDING_MISMATCH", `renderer_output.elements[${matches[0].index}].visual_key`, `visual_key ${key} is declared for ${declared?.slide_id ?? "an unknown slide"}, not ${telemetry.slide_id}`, "deck_builder", { visual_key: key });
    }
  }

  const pageVisuals = manifest.visuals
    .map((entry, manifestIndex) => ({ ...entry, manifest_index: manifestIndex }))
    .filter((entry) => entry.slide_id === telemetry.slide_id);

  const containersById = new Map();
  for (const [index, container] of manifest.containers.entries()) {
    const containerId = nonEmpty(container.container_id);
    if (!containerId) { block("CONTAINER_BINDING_MISSING", `visual_manifest.containers[${index}].container_id`, "container_id is required", "deck_builder"); continue; }
    const missingFields = ["shape_name", "role", "fit_policy", "crop_policy", "whitespace_policy", "mismatch_policy"].filter((field) => !nonEmpty(container[field]));
    for (const field of missingFields) block("CONTAINER_BINDING_MISSING", `visual_manifest.containers[${index}].${field}`, "required container manifest fact is missing", "deck_builder");
    if (missingFields.length) continue;
    if (containersById.has(containerId)) { block("CONTAINER_BINDING_AMBIGUOUS", `visual_manifest.containers[${index}].container_id`, `duplicate container_id: ${containerId}`, "deck_builder"); continue; }
    containersById.set(containerId, { ...container, container_id: containerId, manifest_index: index });
  }

  telemetry.visual_containers = [];
  const assembledContainers = new Map();
  const assembledByKey = new Map();
  for (const entry of pageVisuals) {
    const entryIndex = entry.manifest_index;
    const key = nonEmpty(entry.visual_key);
    if (!key || (keyIndexes.get(key)?.length ?? 0) !== 1) continue;
    const context = { visual_key: key };
    const required = ["slide_id", "visual_type", "panel_count", "has_embedded_text", "slot_id", "container_id"];
    const missing = required.filter((field) => entry[field] === undefined || entry[field] === null || entry[field] === "");
    for (const field of missing) block("VISUAL_MANIFEST_FACT_MISSING", `visual_manifest.visuals[${entryIndex}].${field}`, "required visual manifest fact is missing", "deck_builder", context);
    const intent = cropIntent(entry, entryIndex, block, fail);
    const matches = rawImageKeys.get(key) ?? [];
    if (matches.length === 0) { fail("VISUAL_RENDER_ELEMENT_MISSING", `visual_manifest.visuals[${entryIndex}].visual_key`, "manifest visual was not present in renderer output", "renderer", context); continue; }
    if (matches.length !== 1 || missing.length || !intent) continue;
    const { index: rawIndex, raw, identity } = matches[0];
    if (entry.slide_id !== telemetry.slide_id) fail("VISUAL_SLIDE_BINDING_MISMATCH", `visual_manifest.visuals[${entryIndex}].slide_id`, `manifest slide_id ${entry.slide_id} does not match renderer slide ${telemetry.slide_id}`, "deck_builder", context);
    const container = containersById.get(entry.container_id);
    if (!container) { block("CONTAINER_BINDING_MISSING", `visual_manifest.visuals[${entryIndex}].container_id`, `container ${entry.container_id ?? ""} is not declared`, "deck_builder", context); continue; }
    const shapeMatches = rawElements.map((candidate, candidateIndex) => ({ candidate, candidateIndex })).filter(({ candidate }) => candidate.name === container.shape_name);
    if (shapeMatches.length !== 1) {
      const reporter = shapeMatches.length ? block : fail;
      reporter(shapeMatches.length ? "CONTAINER_BINDING_AMBIGUOUS" : "CONTAINER_RELATION_MISMATCH", `visual_manifest.containers[${container.manifest_index}].shape_name`, shapeMatches.length ? "container shape_name matched multiple elements" : "declared container shape was not rendered", shapeMatches.length ? "deck_builder" : "renderer", context);
      continue;
    }
    const outer = localBox(shapeMatches[0].candidate.bbox);
    const content = outer && contentBox(outer, container.content_inset);
    if (!content) { block("CONTAINER_GEOMETRY_MISSING", `renderer_output.elements[${shapeMatches[0].candidateIndex}].bbox`, "container geometry is missing or invalid", "renderer", context); continue; }
    const allocated = localBox(raw.allocatedBbox ?? raw.allocated_bbox ?? raw.bbox);
    if (!allocated) { block("DISPLAY_BBOX_MISSING", `renderer_output.elements[${rawIndex}].bbox`, "allocated image frame is missing or invalid", "renderer", context); continue; }
    if (!contains(content.box, allocated)) fail("CONTAINER_RELATION_MISMATCH", `renderer_output.elements[${rawIndex}].bbox`, "allocated image frame lies outside the declared container content box", "renderer", context);

    const assetIdentity = rawAssetHash(raw, assetRegistry);
    if (!intent.expected_hash) block(intent.crop_mode === "preprocessed_fixed_region" ? "DERIVED_ASSET_HASH_MISSING" : "ASSET_HASH_MISSING", `visual_manifest.visuals[${entryIndex}].asset_sha256`, "manifest does not provide a valid expected asset SHA-256", "deck_builder", context);
    if (!assetIdentity.hash) block("RENDER_ASSET_HASH_MISSING", `renderer_output.elements[${rawIndex}].asset_sha256`, "renderer output and asset registry do not expose a verifiable asset SHA-256", "builder_renderer_integration", context);
    else if (intent.expected_hash && intent.expected_hash !== assetIdentity.hash) fail(intent.crop_mode === "preprocessed_fixed_region" ? "SEMANTIC_CROP_ASSET_MISMATCH" : "ASSET_IDENTITY_MISMATCH", `renderer_output.elements[${rawIndex}].asset_sha256`, "rendered asset SHA-256 does not match the builder intent", "renderer", { ...context, details: { expected: intent.expected_hash, actual: assetIdentity.hash } });

    const fit = String(raw.imageFit ?? raw.image_fit ?? raw.fit ?? "").trim().toLowerCase();
    if (!ARTIFACT_TOOL_GEOMETRY_PROFILE.supported_fit_modes.includes(fit)) { block("DISPLAY_GEOMETRY_PROFILE_UNSUPPORTED", `renderer_output.elements[${rawIndex}].imageFit`, "renderer fit mode is missing or unsupported by the conformance profile", "renderer_adapter", context); continue; }
    if (fit !== container.fit_policy) fail("CONTAINER_RELATION_MISMATCH", `renderer_output.elements[${rawIndex}].imageFit`, `renderer fit ${fit} differs from declared container fit ${container.fit_policy}`, "renderer", context);
    if (intent.crop_mode === "preprocessed_fixed_region" && (container.crop_policy !== "fixed_region" || fit !== "contain")) fail("SEMANTIC_CROP_ASSET_MISMATCH", `visual_manifest.visuals[${entryIndex}].crop_mode`, "preprocessed fixed regions require fixed_region + contain so the renderer cannot crop the derived asset again", "renderer", context);
    const geometry = computeArtifactDisplayGeometry({ frame_bbox: allocated, asset_width_px: intent.asset_width_px, asset_height_px: intent.asset_height_px, image_fit: fit });
    const explicitDisplay = localBox(raw.effectiveDisplayBbox ?? raw.effective_display_bbox ?? raw.displayBbox ?? raw.display_bbox);
    let geometryProvenance = ARTIFACT_TOOL_GEOMETRY_PROFILE.geometry_provenance;
    let display = geometry.display_bbox;
    if (explicitDisplay) {
      geometryProvenance = "renderer_reported";
      display = explicitDisplay;
      if (!boxesNear(explicitDisplay, geometry.display_bbox)) fail("DISPLAY_GEOMETRY_MISMATCH", `renderer_output.elements[${rawIndex}].display_bbox`, "renderer-reported display geometry is inconsistent with the verified artifact-tool profile", "renderer_adapter", context);
    }
    if (!contains(content.box, display)) fail("CONTAINER_RELATION_MISMATCH", `renderer_output.elements[${rawIndex}].display_bbox`, "effective display lies outside the declared container", "renderer", context);
    const explicitEffectiveRegion = localBox(raw.effectiveSourceRegion ?? raw.effective_source_region);
    const effectiveRegion = explicitEffectiveRegion ?? geometry.profile_effective_source_region;
    if (!fullRegion(effectiveRegion, "source_normalized_0_1", 1, 1)) fail("SEMANTIC_CROP_MISMATCH", `renderer_output.elements[${rawIndex}].effective_source_region`, "renderer fit hides part of a full or fixed-region asset", "renderer", context);
    const maxLetterbox = finite(container.max_letterbox_ratio) ?? DEFAULT_MAX_LETTERBOX_RATIO;
    if (container.whitespace_policy === "minimal" && geometry.actual_letterbox_ratio > maxLetterbox) fail("UNEXPECTED_LETTERBOXING", `renderer_output.elements[${rawIndex}].display_bbox`, `letterbox ratio ${geometry.actual_letterbox_ratio} exceeds ${maxLetterbox}`, "deck_builder", { ...context, details: { actual_letterbox_ratio: geometry.actual_letterbox_ratio, maximum: maxLetterbox } });

    const element = telemetry.elements[rawIndex];
    element.bbox = display;
    element.render_bbox_px = display;
    element.image = {
      ...element.image, display_bbox: display, source_width_px: intent.asset_width_px, source_height_px: intent.asset_height_px,
      visual_id: key, content_id: entry.source_visual_id, slot_id: entry.slot_id, visual_type: entry.visual_type,
      panel_count: entry.panel_count, has_embedded_text: entry.has_embedded_text, min_display_width: finite(entry.min_display_width),
      allocated_bbox: allocated, container_bbox: content.box,
      rendered_embedded_text_px: finite(entry.rendered_embedded_text_px ?? entry.raster_text_measurement?.min_height_px),
      source_region_bbox: intent.source_region, visual_parent_id: entry.container_id, relation: { type: "visual_child" },
      effective_source_region: effectiveRegion, effective_placement: display, source_region_coordinate_space: intent.coordinate_space,
      effective_fit_mode: geometry.fit_mode, actual_letterbox_ratio: geometry.actual_letterbox_ratio,
      visible_region_ids: entry.region_id ? [String(entry.region_id)] : [],
      visible_label_ids: Array.isArray(entry.visible_label_ids) ? [...new Set(entry.visible_label_ids.map(String))] : [],
      geometry_provenance: geometryProvenance,
      renderer_profile_id: geometryProvenance === "profile_derived" ? ARTIFACT_TOOL_GEOMETRY_PROFILE.renderer_profile_id : null,
      expected_asset_sha256: intent.expected_hash, rendered_asset_sha256: assetIdentity.hash, asset_identity_provenance: assetIdentity.source,
      crop_mode: intent.crop_mode, parent_asset_sha256: intent.parent_asset_sha256, parent_source_region: intent.parent_source_region,
      parent_source_region_coordinate_space: intent.parent_coordinate_space ?? null, derived_asset_sha256: intent.derived_asset_sha256,
      group_id: entry.group_id ?? null, sibling_index: Number.isInteger(entry.sibling_index) ? entry.sibling_index : null,
    };
    const resolvedPaths = [`elements[${rawIndex}].bbox`, `elements[${rawIndex}].render_bbox_px`, `elements[${rawIndex}].image.display_bbox`, ...["source_width_px", "source_height_px", "visual_id", "content_id", "slot_id", "visual_type", "panel_count", "has_embedded_text", "allocated_bbox"].map((field) => `elements[${rawIndex}].image.${field}`)];
    if (entry.has_embedded_text === true && element.image.rendered_embedded_text_px === null) {
      const failed = entry.raster_text_measurement?.status === "failed";
      const reason = failed ? `raster text measurement failed: ${entry.raster_text_measurement.reason ?? "unspecified failure"}` : "raster text explicitly not measured; manual review required";
      addUnavailable(telemetry, `elements[${rawIndex}].image.rendered_embedded_text_px`, reason);
      manualReview.push({
        code: failed ? "SCIENTIFIC_VISUAL_MEASUREMENT_FAILED" : "SCIENTIFIC_VISUAL_MANUAL_REVIEW_REQUIRED",
        visual_key: key,
        field: `elements[${rawIndex}].image.rendered_embedded_text_px`,
        measurement_state: failed ? "measurement_failed" : "not_measured",
        reason,
        responsible_party: "deck_builder",
        recommended_action: failed ? "repair_raster_text_measurement_then_review" : "inspect_raster_text_readability",
      });
    } else resolvedPaths.push(`elements[${rawIndex}].image.rendered_embedded_text_px`);
    removeUnavailable(telemetry, resolvedPaths);

    const existingContainer = assembledContainers.get(entry.container_id);
    if (existingContainer) existingContainer.child_visual_ids.push(key);
    else {
      const canonicalContainer = { container_id: entry.container_id, role: container.role, outer_bbox: outer, content_bbox: content.box, content_inset: content.inset, child_visual_ids: [key], fit_policy: container.fit_policy, crop_policy: container.crop_policy, whitespace_policy: container.whitespace_policy, mismatch_policy: container.mismatch_policy, max_letterbox_ratio: maxLetterbox, inference_source: "visual_manifest_shape_name" };
      assembledContainers.set(entry.container_id, canonicalContainer);
      telemetry.visual_containers.push(canonicalContainer);
    }
    assembledByKey.set(key, { entry, raw_index: rawIndex, element, display_bbox: display, expected_hash: intent.expected_hash, actual_hash: assetIdentity.hash, geometry_provenance: geometryProvenance });
    matchLog.push({ kind: "scientific_visual", visual_key: key, element_id: element.element_id, container_id: entry.container_id, match_source: identity.source, asset_hash_verified: Boolean(intent.expected_hash && assetIdentity.hash && intent.expected_hash === assetIdentity.hash), asset_identity_provenance: assetIdentity.source, crop_lineage_verified: intent.crop_mode === "full_figure" || Boolean(intent.parent_asset_sha256 && intent.parent_source_region && intent.derived_asset_sha256), geometry_provenance: geometryProvenance, renderer_profile_id: geometryProvenance === "profile_derived" ? ARTIFACT_TOOL_GEOMETRY_PROFILE.renderer_profile_id : null });
  }

  const pageGroupIds = new Set(pageVisuals.map((entry) => entry.group_id).filter(Boolean));
  const pageManifest = { ...manifest, visuals: pageVisuals, groups: manifest.groups.filter((group) => pageGroupIds.has(group.group_id)) };
  telemetry.visual_groups = verifyGroups({ manifest: pageManifest, telemetry, assembledByKey, block, fail });
  const status = blockedIssues.length ? "blocked" : failures.length ? "fail" : manualReview.length ? "manual_review_required" : "pass";
  const readinessStatus = blockedIssues.length ? "blocked" : manualReview.length ? "manual_review_required" : "ready";
  const allIssues = [...blockedIssues, ...failures];
  const inspection = pageVisuals.map((entry) => {
    const assembled = assembledByKey.get(entry.visual_key);
    const relevantIssues = allIssues.filter((item) => item.visual_key === entry.visual_key || (entry.group_id && item.group_id === entry.group_id));
    const reviewRequired = manualReview.some((item) => item.visual_key === entry.visual_key);
    return {
      slide_id: entry.slide_id ?? null, visual_key: entry.visual_key ?? null,
      expected_asset_sha256: assembled?.expected_hash ?? normalizeHash(entry.derived_asset_sha256 ?? entry.asset_sha256), rendered_asset_sha256: assembled?.actual_hash ?? null,
      crop_mode: entry.crop_mode ?? null, container_id: entry.container_id ?? null, group_id: entry.group_id ?? null,
      geometry_provenance: assembled?.geometry_provenance ?? null,
      status: relevantIssues.length ? (relevantIssues.some((item) => item.status === "blocked") ? "blocked" : "fail") : reviewRequired ? "manual_review_required" : assembled ? "pass" : status,
      issue_codes: [...new Set(relevantIssues.map((item) => item.code))],
    };
  });

  telemetry.telemetry_version = CANONICAL_TELEMETRY_VERSION;
  telemetry.render_evidence = {
    evidence_contract_version: RENDER_EVIDENCE_CONTRACT_VERSION, manifest_schema_version: manifest.manifest_schema_version,
    telemetry_schema_version: RENDER_EVIDENCE_CONTRACT_VERSION, producer_version: manifest.producer_version, deck_id: manifest.deck_id,
    renderer_profile_id: ARTIFACT_TOOL_GEOMETRY_PROFILE.renderer_profile_id, status, issues: allIssues, manual_review: manualReview,
  };
  telemetry.unavailable.sort((left, right) => left.field.localeCompare(right.field) || left.reason.localeCompare(right.reason));
  blockedIssues.sort((left, right) => left.field.localeCompare(right.field) || left.code.localeCompare(right.code));
  failures.sort((left, right) => left.field.localeCompare(right.field) || left.code.localeCompare(right.code));
  matchLog.sort((left, right) => String(left.visual_key ?? left.shape_name).localeCompare(String(right.visual_key ?? right.shape_name)));
  assertRenderTelemetry(telemetry);
  return {
    pipeline_status: "render_telemetry_assembled", status, verification_status: status, readiness_status: readinessStatus,
    manifest_schema_version: manifest.manifest_schema_version, telemetry_schema_version: RENDER_EVIDENCE_CONTRACT_VERSION,
    producer_version: manifest.producer_version, deck_id: manifest.deck_id, canonical_telemetry: telemetry,
    missing_facts: blockedIssues, failures, verification_issues: allIssues, match_log: matchLog, inspection,
    geometry_provenance: blockedIssues.length ? null : [...new Set([...assembledByKey.values()].map((item) => item.geometry_provenance))],
    renderer_profile: { id: ARTIFACT_TOOL_GEOMETRY_PROFILE.renderer_profile_id, family: ARTIFACT_TOOL_GEOMETRY_PROFILE.profile_id, version: ARTIFACT_TOOL_GEOMETRY_PROFILE.profile_version, conformance_verified: ARTIFACT_TOOL_GEOMETRY_PROFILE.conformance_verified },
    manual_review: manualReview,
  };
}
