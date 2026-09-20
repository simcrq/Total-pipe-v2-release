import { assertJsonSchema } from "../schema-validator.mjs";
import { RENDER_TELEMETRY_SCHEMA } from "./contracts.mjs";

function declaresUnavailable(telemetry, field) {
  return telemetry.unavailable.some((item) => item.field === field);
}

function requireValueOrUnavailable(telemetry, value, field) {
  if (value !== null && value !== undefined) return;
  if (!declaresUnavailable(telemetry, field)) {
    throw new TypeError(`${field} must be present or listed as unavailable`);
  }
}

export function assertRenderTelemetry(telemetry) {
  assertJsonSchema(RENDER_TELEMETRY_SCHEMA, telemetry, { toolName: "render_telemetry" });
  const hasRenderWidth = telemetry.slide.render_width_px !== null;
  const hasRenderHeight = telemetry.slide.render_height_px !== null;
  if (hasRenderWidth !== hasRenderHeight) {
    throw new TypeError("slide.render_width_px and slide.render_height_px must be provided together");
  }
  requireValueOrUnavailable(telemetry, telemetry.slide.render_width_px, "slide.render_width_px");
  requireValueOrUnavailable(telemetry, telemetry.slide.render_height_px, "slide.render_height_px");
  const requiresLayerTelemetry = ["1.1.0", "1.2.0", "1.3.0", "1.4.0"].includes(telemetry.telemetry_version);
  const requiresScientificVisualTelemetry = ["1.2.0", "1.3.0", "1.4.0"].includes(telemetry.telemetry_version);
  const requiresRenderEvidence = telemetry.telemetry_version === "1.4.0";
  if (requiresLayerTelemetry) {
    requireValueOrUnavailable(telemetry, telemetry.slide.layout_id, "slide.layout_id");
    requireValueOrUnavailable(telemetry, telemetry.slide.category, "slide.category");
  }
  if (requiresRenderEvidence) {
    if (!telemetry.render_evidence) throw new TypeError("render_evidence is required by Render Telemetry 1.4.0");
    if (!Array.isArray(telemetry.visual_groups)) throw new TypeError("visual_groups is required by Render Telemetry 1.4.0");
  }
  const seen = new Set();
  for (const [index, element] of telemetry.elements.entries()) {
    if (seen.has(element.element_id)) throw new TypeError(`Duplicate render telemetry element_id: ${element.element_id}`);
    seen.add(element.element_id);
    requireValueOrUnavailable(telemetry, element.bbox, `elements[${index}].bbox`);
    requireValueOrUnavailable(telemetry, element.render_bbox_px, `elements[${index}].render_bbox_px`);
    if (requiresLayerTelemetry) {
      requireValueOrUnavailable(telemetry, element.z_index, `elements[${index}].z_index`);
      requireValueOrUnavailable(telemetry, element.opacity, `elements[${index}].opacity`);
    }
    if (element.type === "text") {
      requireValueOrUnavailable(telemetry, element.text, `elements[${index}].text`);
      if (element.text) {
        requireValueOrUnavailable(telemetry, element.text.overflow, `elements[${index}].text.overflow`);
        requireValueOrUnavailable(telemetry, element.text.foreground_color, `elements[${index}].text.foreground_color`);
        if (requiresLayerTelemetry) requireValueOrUnavailable(telemetry, element.text.local_contrast_ratio, `elements[${index}].text.local_contrast_ratio`);
      }
    }
    if (element.type === "image") {
      requireValueOrUnavailable(telemetry, element.image, `elements[${index}].image`);
      if (requiresScientificVisualTelemetry && element.image) {
        for (const field of ["visual_id", "content_id", "slot_id", "visual_type", "panel_count", "has_embedded_text", "allocated_bbox"]) {
          requireValueOrUnavailable(telemetry, element.image[field], `elements[${index}].image.${field}`);
        }
        if (element.image.has_embedded_text === true) {
          requireValueOrUnavailable(telemetry, element.image.rendered_embedded_text_px, `elements[${index}].image.rendered_embedded_text_px`);
        }
      }
    }
  }
  return telemetry;
}

export function normalizeRenderTelemetry(telemetry) {
  assertRenderTelemetry(telemetry);
  return structuredClone(telemetry);
}

export { declaresUnavailable };
