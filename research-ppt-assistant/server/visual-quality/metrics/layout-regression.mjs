function visualKey(element) {
  return element.image?.visual_id ?? element.image?.content_id ?? element.element_id;
}

function normalizedBox(element, slide) {
  const box = element.image?.display_bbox ?? element.bbox;
  if (!box) return null;
  return { x: box.x / slide.width, y: box.y / slide.height, width: box.width / slide.width, height: box.height / slide.height };
}

function maximumDeviation(left, right) {
  if (!left || !right) return null;
  return Math.max(...["x", "y", "width", "height"].map((field) => Math.abs(left[field] - right[field])));
}

function visualMap(telemetry) {
  return new Map((telemetry.elements ?? [])
    .filter((element) => element.type === "image")
    .map((element) => [visualKey(element), element]));
}

function readingOrder(telemetry, keys) {
  const selected = new Set(keys);
  return (telemetry.elements ?? [])
    .filter((element) => element.type === "image" && selected.has(visualKey(element)))
    .map(visualKey);
}

function containerStyle(container) {
  if (!container) return null;
  return Object.fromEntries(["role", "fit_policy", "crop_policy", "whitespace_policy", "mismatch_policy"]
    .map((field) => [field, container[field]]));
}

export function computeLayoutRegression(telemetry, baseline, { tolerance = 0.08 } = {}) {
  if (!baseline) return { measurable: true, applicable: false, compared_visual_count: 0, issue_count: 0, issues: [] };
  const current = visualMap(telemetry);
  const previous = visualMap(baseline);
  const shared = [...previous.keys()].filter((key) => current.has(key)).sort();
  const issues = [];
  for (const key of shared) {
    const before = previous.get(key);
    const after = current.get(key);
    const beforeParent = before.image?.visual_parent_id ?? null;
    const afterParent = after.image?.visual_parent_id ?? null;
    if (beforeParent !== afterParent) {
      issues.push({ code: "VISUAL_PARENT_CHANGED", visual_id: key, before: beforeParent, after: afterParent });
    }
    const deviation = maximumDeviation(normalizedBox(before, baseline.slide), normalizedBox(after, telemetry.slide));
    if (deviation !== null && deviation > tolerance) {
      issues.push({ code: "UNNECESSARY_LAYOUT_DRIFT", visual_id: key, before: normalizedBox(before, baseline.slide), after: normalizedBox(after, telemetry.slide), deviation, tolerance });
    }
  }
  for (const container of baseline.visual_containers ?? []) {
    const baselineChildren = container.child_visual_ids.filter((id) => previous.has(id)).sort();
    if (baselineChildren.length < 2 || !baselineChildren.every((id) => current.has(id))) continue;
    const currentParents = new Set(baselineChildren.map((id) => current.get(id).image?.visual_parent_id ?? null));
    if (currentParents.size !== 1 || currentParents.has(null)) {
      issues.push({ code: "SIBLING_GROUP_BROKEN", visual_id: container.container_id, before: baselineChildren, after: [...currentParents].sort() });
    }
    const currentContainer = (telemetry.visual_containers ?? []).find((item) => item.container_id === container.container_id);
    if (!currentContainer || JSON.stringify(containerStyle(container)) !== JSON.stringify(containerStyle(currentContainer))) {
      issues.push({ code: "SHARED_CONTAINER_STYLE_CHANGED", visual_id: container.container_id, before: containerStyle(container), after: containerStyle(currentContainer) });
    }
  }
  const beforeOrder = readingOrder(baseline, shared);
  const afterOrder = readingOrder(telemetry, shared);
  if (shared.length >= 2 && JSON.stringify(beforeOrder) !== JSON.stringify(afterOrder)) {
    issues.push({ code: "READING_ORDER_CHANGED", visual_id: "reading_order", before: beforeOrder, after: afterOrder });
  }
  return {
    measurable: true,
    applicable: true,
    compared_visual_count: shared.length,
    issue_count: issues.length,
    issues,
  };
}
