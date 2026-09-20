import { computeContainerChildMetrics } from "../../visual-fit/metrics.mjs";

export function computeVisualContainerFit(telemetry = {}) {
  const containers = Array.isArray(telemetry.visual_containers) ? telemetry.visual_containers : [];
  const imageElements = (telemetry.elements ?? []).filter((element) => element.type === "image" && element.quality_role === "content");
  const declaredRelations = imageElements.filter((element) => element.image?.visual_parent_id || element.image?.relation?.type === "visual_child");
  if (!containers.length && !declaredRelations.length) {
    return { measurable: true, applicable: false, observation_count: 0, observations: [], missing_fields: [] };
  }
  const containersById = new Map(containers.map((container) => [container.container_id, container]));
  const imagesByVisualId = new Map(imageElements.map((element) => [element.image?.visual_id, element]));
  const observations = [];
  const missing = [];
  for (const container of containers) {
    for (const visualId of container.child_visual_ids) {
      const element = imagesByVisualId.get(visualId);
      if (!element) {
        missing.push(`visual_containers.${container.container_id}.child_visual_ids.${visualId}`);
        continue;
      }
      if (element.image?.visual_parent_id !== container.container_id || element.image?.relation?.type !== "visual_child") {
        missing.push(`elements.${element.element_id}.image.visual_parent_relation`);
        continue;
      }
      const display = element.image.display_bbox ?? element.bbox;
      if (!display) {
        missing.push(`elements.${element.element_id}.image.display_bbox`);
        continue;
      }
      observations.push({
        container_id: container.container_id,
        visual_id: visualId,
        element_id: element.element_id,
        visual_type: element.image.visual_type,
        container_role: container.role,
        fit_policy: container.fit_policy,
        crop_policy: container.crop_policy,
        whitespace_policy: container.whitespace_policy,
        mismatch_policy: container.mismatch_policy,
        metrics: computeContainerChildMetrics({ content_bbox: container.content_bbox, child_display_bbox: display }),
      });
    }
  }
  for (const element of declaredRelations) {
    const parentId = element.image?.visual_parent_id;
    if (!parentId || !containersById.has(parentId)) missing.push(`elements.${element.element_id}.image.visual_parent_id`);
  }
  const missingFields = [...new Set(missing)];
  return {
    measurable: missingFields.length === 0,
    applicable: true,
    observation_count: observations.length,
    observations,
    missing_fields: missingFields,
    ...(missingFields.length ? { unavailable_reason: "visual_container_contract_incomplete" } : {}),
  };
}
