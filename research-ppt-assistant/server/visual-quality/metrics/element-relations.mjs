function isThinDecoration(element, slide) {
  if (element?.quality_role !== "decoration" || !element.bbox) return false;
  const kind = String(element.geometry_kind ?? element.type ?? "").toLowerCase();
  if (/line|rule|separator|divider|connector/u.test(kind)) return true;
  const { width, height } = element.bbox;
  if (width === 0 || height === 0) return true;
  const ratio = Math.max(width / height, height / width);
  const areaRatio = width * height / (slide.width * slide.height);
  return ratio >= 18 && areaRatio <= 0.02;
}

function orientation(element) {
  return element.bbox.width >= element.bbox.height ? "horizontal" : "vertical";
}

function duplicatePair(left, right, slide) {
  const axis = orientation(left);
  if (axis !== orientation(right)) return false;
  const a = left.bbox;
  const b = right.bbox;
  if (axis === "horizontal") {
    const delta = Math.abs((a.y + a.height / 2) - (b.y + b.height / 2)) / slide.height;
    const overlap = Math.max(0, Math.min(a.x + a.width, b.x + b.width) - Math.max(a.x, b.x));
    return delta <= 0.012 && overlap / Math.max(1e-9, Math.min(a.width, b.width)) >= 0.8;
  }
  const delta = Math.abs((a.x + a.width / 2) - (b.x + b.width / 2)) / slide.width;
  const overlap = Math.max(0, Math.min(a.y + a.height, b.y + b.height) - Math.max(a.y, b.y));
  return delta <= 0.012 && overlap / Math.max(1e-9, Math.min(a.height, b.height)) >= 0.8;
}

function actualContentRegion(elements) {
  const boxes = elements
    .filter((element) => element.quality_role === "content" && element.bbox && element.bbox.width >= 0 && element.bbox.height >= 0)
    .map((element) => element.bbox);
  if (!boxes.length) return null;
  const left = Math.min(...boxes.map((box) => box.x));
  const top = Math.min(...boxes.map((box) => box.y));
  const right = Math.max(...boxes.map((box) => box.x + box.width));
  const bottom = Math.max(...boxes.map((box) => box.y + box.height));
  return { x: left, y: top, width: right - left, height: bottom - top };
}

function liesInContentRegion(element, region) {
  if (!region || !element.bbox) return false;
  const center = { x: element.bbox.x + element.bbox.width / 2, y: element.bbox.y + element.bbox.height / 2 };
  return center.x >= region.x && center.x <= region.x + region.width
    && center.y >= region.y && center.y <= region.y + region.height;
}

export function computeElementRelations(telemetry, { baseline_telemetry: baseline } = {}) {
  if ((telemetry.unavailable ?? []).some((item) => item.field === "elements")) {
    return {
      measurable: false,
      applicable: true,
      candidate_count: 0,
      related_count: 0,
      issue_count: 0,
      candidates: [],
      issues: [],
      missing_element_ids: [],
      unavailable_reason: "element_collection_unavailable",
    };
  }
  const elements = telemetry.elements ?? [];
  const ids = new Set(elements.map((element) => element.element_id));
  const containerIds = new Set((telemetry.visual_containers ?? []).map((container) => container.container_id));
  const baselineIds = baseline ? new Set((baseline.elements ?? []).map((element) => element.element_id)) : null;
  const contentRegion = actualContentRegion(elements);
  const candidates = elements.filter((element) => isThinDecoration(element, telemetry.slide) && liesInContentRegion(element, contentRegion));
  const missing = elements.filter((element) => element.quality_role === "decoration" && !element.bbox).map((element) => element.element_id);
  const issues = [];
  for (const element of candidates) {
    const relation = element.relation;
    if (!relation) {
      issues.push({ code: "ORPHAN_DECORATIVE_ELEMENT", element_id: element.element_id, related_element_ids: [], reason: "thin decorative element has no title, container, flow, annotation, or peer relation" });
    } else if (!ids.has(relation.target_id) && !containerIds.has(relation.target_id)) {
      issues.push({ code: "DECORATIVE_RELATION_TARGET_MISSING", element_id: element.element_id, related_element_ids: [relation.target_id], reason: "declared relation target is absent from rendered telemetry" });
    }
    if (baselineIds && !baselineIds.has(element.element_id) && !element.source_element_id) {
      issues.push({ code: "UNSOURCED_ELEMENT_ADDED", element_id: element.element_id, related_element_ids: [], reason: "element is new relative to the baseline and has no source_element_id" });
    }
  }
  for (let left = 0; left < candidates.length; left += 1) {
    for (let right = left + 1; right < candidates.length; right += 1) {
      if (duplicatePair(candidates[left], candidates[right], telemetry.slide)) {
        issues.push({
          code: "DUPLICATE_SEPARATOR",
          element_id: candidates[right].element_id,
          related_element_ids: [candidates[left].element_id],
          reason: "two thin decorations are nearly collinear and substantially overlap",
        });
      }
    }
  }
  issues.sort((a, b) => a.code.localeCompare(b.code) || a.element_id.localeCompare(b.element_id));
  return {
    measurable: missing.length === 0,
    applicable: candidates.length > 0,
    candidate_count: candidates.length,
    related_count: candidates.filter((element) => element.relation).length,
    issue_count: issues.length,
    candidates: candidates.map((element) => ({
      element_id: element.element_id,
      geometry_kind: element.geometry_kind ?? null,
      orientation: orientation(element),
      relation: element.relation ?? null,
    })),
    content_region: contentRegion,
    issues,
    missing_element_ids: missing,
    ...(missing.length ? { unavailable_reason: "decoration_bbox_telemetry_incomplete" } : {}),
  };
}
