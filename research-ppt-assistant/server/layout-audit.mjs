import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { validateJsonSchema } from "./schema-validator.mjs";
import {
  boxContains,
  findSlotOverlaps,
  isOverlaySlot,
  isVisualSlotType,
  overlapKind,
  OVERLAP_EPSILON,
  resolveOverlayDeclaration,
} from "./layout-geometry.mjs";

export const LAYOUT_AUDIT_VERSION = "1.2.0";

const MODULE_DIR = path.dirname(fileURLToPath(import.meta.url));
const DEFAULT_LIBRARY_DIR = path.resolve(MODULE_DIR, "..", "assets", "layout-library");
const COLOR_FIELDS = ["bg", "panel", "text", "muted", "accent1", "accent2", "accent3", "border"];
const LAYOUT_ID_PATTERN = /^RM-[A-Z_]+-[0-9]{2}$/u;
const HEX_COLOR_PATTERN = /^#[0-9A-F]{6}$/iu;
const EPSILON = 0.002;

function issue(code, pathValue, message, actual, expected, severity = "error") {
  return {
    code,
    path: pathValue,
    severity,
    message,
    ...(actual === undefined ? {} : { actual }),
    ...(expected === undefined ? {} : { expected }),
  };
}

function unique(values) {
  return [...new Set(values)];
}

function addCountIssue(issues, code, pathValue, actual, expected) {
  if (actual !== expected) issues.push(issue(code, pathValue, `Expected ${expected}, received ${actual}.`, actual, expected));
}

function auditBox(layout, slot, layoutIndex, slotIndex, slideSize, issues) {
  const basePath = `layouts[${layoutIndex}].slots[${slotIndex}]`;
  const box = slot?.box;
  if (!box || typeof box !== "object" || Array.isArray(box)) return;
  if (!(box.w > 0) || !(box.h > 0)) {
    issues.push(issue("NON_POSITIVE_SLOT_SIZE", `${basePath}.box`, "Slot width and height must be positive.", box, "w > 0 and h > 0"));
  }
  if (box.x + box.w > 1 + EPSILON || box.y + box.h > 1 + EPSILON) {
    issues.push(issue("SLOT_OUT_OF_BOUNDS", `${basePath}.box`, "Slot geometry exceeds normalized slide bounds.", box, "x + w <= 1 and y + h <= 1"));
  }
  const pptx = slot.pptx_in;
  if (!pptx || typeof pptx !== "object" || Array.isArray(pptx)) {
    issues.push(issue("MISSING_PPTX_COORDINATES", `${basePath}.pptx_in`, "Every slot must provide PowerPoint-inch coordinates."));
    return;
  }
  const expected = {
    x: box.x * slideSize.w,
    y: box.y * slideSize.h,
    w: box.w * slideSize.w,
    h: box.h * slideSize.h,
  };
  for (const key of ["x", "y", "w", "h"]) {
    if (!Number.isFinite(pptx[key]) || Math.abs(pptx[key] - expected[key]) > EPSILON) {
      issues.push(issue("PPTX_COORDINATE_MISMATCH", `${basePath}.pptx_in.${key}`, "PowerPoint-inch coordinate does not match normalized geometry.", pptx[key], Math.round(expected[key] * 1000) / 1000));
    }
  }
}

function auditLayout(layout, index, schema, slideSize, issues) {
  const schemaResult = validateJsonSchema(schema, layout, { path: `$.layouts[${index}]` });
  for (const error of schemaResult.errors) {
    issues.push(issue("LAYOUT_SCHEMA_INVALID", error.path, error.message, error.actual, error.expected));
  }
  if (!LAYOUT_ID_PATTERN.test(String(layout?.id ?? ""))) {
    issues.push(issue("INVALID_LAYOUT_ID", `layouts[${index}].id`, "Layout ID must follow RM-CATEGORY-NN.", layout?.id, "RM-CATEGORY-NN"));
  }
  const slots = Array.isArray(layout?.slots) ? layout.slots : [];
  const slotIds = slots.map((slot) => slot?.id).filter((id) => typeof id === "string" && id.length > 0);
  if (unique(slotIds).length !== slotIds.length) {
    issues.push(issue("DUPLICATE_SLOT_ID", `layouts[${index}].slots`, "Slot IDs must be unique within one layout.", slotIds));
  }
  slots.forEach((slot, slotIndex) => auditBox(layout, slot, index, slotIndex, slideSize, issues));

  // `box` is the real placeholder rectangle, so how two boxes meet decides whether they are a
  // defect. Boxes that CROSS (neither contains the other) share a region that belongs to neither
  // slot: if both are mandatory, content is guaranteed to collide -> blocking error.
  //
  // Boxes where one sits entirely inside the other are a *stack*: a cover plate with its title on
  // top, a figure with pinned annotations, a reference block with a QR badge. Stacking is legal
  // but it must be declared (`overlay: true` on the contained slot), so intent lives in the data
  // instead of being guessed from the geometry. An undeclared stack is still an error, and a
  // declaration that does not actually describe a layer is an error too -- `resolveOverlayDeclaration`
  // only accepts the contained side, so `overlay` cannot be used as a blanket bypass.
  const overlapHits = findSlotOverlaps(layout, { includeOptional: true });
  for (const hit of overlapHits) {
    const firstSlot = slots[hit.first_index];
    const secondSlot = slots[hit.second_index];
    const optionalInvolved = firstSlot?.optional === true || secondSlot?.optional === true;
    const declaration = resolveOverlayDeclaration(firstSlot, secondSlot);
    const kind = overlapKind(firstSlot?.box, secondSlot?.box) ?? "crossing";
    const overlapType =
      isVisualSlotType(hit.first_type) === isVisualSlotType(hit.second_type)
        ? isVisualSlotType(hit.first_type)
          ? "visual_visual"
          : "text_text"
        : "text_visual";
    const actual = {
      first_slot: hit.first_slot_id,
      second_slot: hit.second_slot_id,
      overlap_type: overlapType,
      overlap_kind: kind,
      overlap: hit.rect,
      overlap_area: hit.overlap_area,
      smaller_slot_ratio: hit.smaller_slot_ratio,
      optional_involved: optionalInvolved,
    };

    if (declaration) {
      issues.push(
        issue(
          "SLOT_OVERLAY_DECLARED",
          `layouts[${index}].slots`,
          `Slot "${declaration.overlay_slot_id}" is declared as a layer stacked inside "${declaration.host_slot_id}".`,
          { ...actual, overlay_slot: declaration.overlay_slot_id, host_slot: declaration.host_slot_id },
          `no intersection deeper than ${OVERLAP_EPSILON} unless declared with overlay: true`,
          "warning",
        ),
      );
      continue;
    }

    // A declaration that exists but is not a layer (the declaring slot is the outer box, or it is
    // not contained by its partner) is reported as its own error rather than silently falling
    // through: the author has to either fix the geometry or fix the declaration.
    const declaresOverlay = isOverlaySlot(firstSlot) || isOverlaySlot(secondSlot);
    if (declaresOverlay) {
      issues.push(
        issue(
          "SLOT_OVERLAY_NOT_CONTAINED",
          `layouts[${index}].slots`,
          `Slot "${isOverlaySlot(firstSlot) ? hit.first_slot_id : hit.second_slot_id}" declares overlay: true but is not contained by the slot it intersects (${kind} intersection).`,
          actual,
          "a declared overlay must sit entirely inside the slot it layers onto",
        ),
      );
      continue;
    }

    const contained = boxContains(firstSlot?.box, secondSlot?.box) ? secondSlot : firstSlot;
    const host = contained === firstSlot ? secondSlot : firstSlot;
    const message = optionalInvolved
      ? `Slots "${hit.first_slot_id}" and "${hit.second_slot_id}" intersect, and at least one is optional.`
      : kind === "contained"
        ? `Slot "${contained?.id}" is stacked inside "${host?.id}"; declare overlay: true on the contained slot if this is intentional, or separate the boxes.`
        : `Slots "${hit.first_slot_id}" and "${hit.second_slot_id}" intersect; both are mandatory and will collide.`;
    issues.push(
      issue(
        optionalInvolved ? "SLOT_OVERLAP_OPTIONAL" : "SLOT_OVERLAP",
        `layouts[${index}].slots`,
        message,
        actual,
        `no intersection deeper than ${OVERLAP_EPSILON}`,
        optionalInvolved ? "warning" : "error",
      ),
    );
  }

  // Declaration hygiene: a slot that declares itself a layer must actually layer onto something.
  // A stale declaration is harmless to render but it lies about the layout, so it is reported.
  for (const [slotIndex, slot] of slots.entries()) {
    if (!isOverlaySlot(slot)) continue;
    const intersects = overlapHits.some(
      (hit) => hit.first_index === slotIndex || hit.second_index === slotIndex,
    );
    if (!intersects) {
      issues.push(
        issue(
          "SLOT_OVERLAY_UNUSED",
          `layouts[${index}].slots[${slotIndex}].overlay`,
          `Slot "${slot.id}" declares overlay: true but intersects no other slot.`,
          true,
          "remove the declaration or restore the stacked geometry",
          "warning",
        ),
      );
    }
  }

  const readingOrder = Array.isArray(layout?.reading_order) ? layout.reading_order : [];
  if (readingOrder.length !== unique(readingOrder).length) {
    issues.push(issue("DUPLICATE_READING_ORDER_SLOT", `layouts[${index}].reading_order`, "Reading order must not contain duplicates.", readingOrder));
  }
  const unknownReadingSlots = readingOrder.filter((id) => !slotIds.includes(id));
  if (unknownReadingSlots.length) {
    issues.push(issue("UNKNOWN_READING_ORDER_SLOT", `layouts[${index}].reading_order`, "Reading order references unknown slots.", unknownReadingSlots, slotIds));
  }
  const missingReadingSlots = slotIds.filter((id) => !readingOrder.includes(id));
  if (missingReadingSlots.length) {
    issues.push(issue("MISSING_READING_ORDER_SLOT", `layouts[${index}].reading_order`, "Reading order must include every slot exactly once.", missingReadingSlots, slotIds));
  }
  const dominant = layout?.content_profile?.dominant_visual_slot;
  if (dominant !== undefined && dominant !== null && !slotIds.includes(dominant)) {
    issues.push(issue("UNKNOWN_DOMINANT_VISUAL_SLOT", `layouts[${index}].content_profile.dominant_visual_slot`, "Dominant visual slot must reference an existing slot.", dominant, slotIds));
  }
}

function auditThemes(themesPayload, issues) {
  const themes = Array.isArray(themesPayload?.themes) ? themesPayload.themes : [];
  const themeIds = themes.map((theme) => theme?.id).filter((id) => typeof id === "string" && id.length > 0);
  if (themeIds.length !== unique(themeIds).length) {
    issues.push(issue("DUPLICATE_THEME_ID", "themes", "Theme IDs must be unique.", themeIds));
  }
  addCountIssue(issues, "THEME_COUNT_MISMATCH", "themes.meta.theme_count", themes.length, themesPayload?.meta?.theme_count);
  themes.forEach((theme, index) => {
    if (!theme?.id) issues.push(issue("MISSING_THEME_ID", `themes[${index}].id`, "Theme ID is required."));
    for (const field of COLOR_FIELDS) {
      if (!HEX_COLOR_PATTERN.test(String(theme?.[field] ?? ""))) {
        issues.push(issue("INVALID_THEME_COLOR", `themes[${index}].${field}`, "Theme colors must use six-digit hexadecimal notation.", theme?.[field], "#RRGGBB"));
      }
    }
  });
  const constraints = themesPayload?.meta?.token_usage_constraints;
  if (themesPayload?.meta?.token_contract_version || constraints) {
    for (const token of COLOR_FIELDS) {
      const policy = constraints?.[token];
      if (!policy || !Array.isArray(policy.allowed_usage) || !Array.isArray(policy.forbidden_usage)) {
        issues.push(issue("MISSING_THEME_USAGE_CONSTRAINT", `themes.meta.token_usage_constraints.${token}`, "Every theme color token must define allowed_usage and forbidden_usage arrays."));
        continue;
      }
      const overlap = policy.allowed_usage.filter((usage) => policy.forbidden_usage.includes(usage));
      if (overlap.length) {
        issues.push(issue("CONFLICTING_THEME_USAGE_CONSTRAINT", `themes.meta.token_usage_constraints.${token}`, "A usage cannot be both allowed and forbidden for the same token.", overlap));
      }
    }
  }
  return themes;
}

export function auditLayoutLibrary({ layoutsPayload, themesPayload, layoutSchema, previewIds } = {}) {
  const issues = [];
  const layouts = Array.isArray(layoutsPayload?.layouts) ? layoutsPayload.layouts : [];
  const meta = layoutsPayload?.meta ?? {};
  const slideSize = meta.slide_size_in ?? { w: 13.333, h: 7.5 };
  const schema = layoutSchema && typeof layoutSchema === "object" ? layoutSchema : {};
  const themes = auditThemes(themesPayload, issues);

  addCountIssue(issues, "LAYOUT_COUNT_MISMATCH", "layouts.meta.layout_count", layouts.length, meta.layout_count);
  const layoutIds = layouts.map((layout) => layout?.id).filter((id) => typeof id === "string" && id.length > 0);
  if (layoutIds.length !== unique(layoutIds).length) {
    issues.push(issue("DUPLICATE_LAYOUT_ID", "layouts", "Layout IDs must be globally unique.", layoutIds));
  }
  layouts.forEach((layout, index) => auditLayout(layout, index, schema, slideSize, issues));

  const categories = new Map();
  layouts.forEach((layout) => {
    const records = categories.get(layout.category) ?? [];
    records.push(layout.variant_index);
    categories.set(layout.category, records);
  });
  addCountIssue(issues, "CATEGORY_COUNT_MISMATCH", "layouts.meta.category_count", categories.size, meta.category_count);
  for (const [category, variants] of categories) {
    const actual = unique(variants).sort((left, right) => left - right);
    const expected = Array.from({ length: 8 }, (_, index) => index + 1);
    if (JSON.stringify(actual) !== JSON.stringify(expected)) {
      issues.push(issue("CATEGORY_VARIANT_SET_INVALID", `categories.${category}`, "Every category must contain variants 1 through 8 exactly once.", actual, expected));
    }
  }

  addCountIssue(issues, "LAYOUT_THEME_COUNT_MISMATCH", "layouts.meta.theme_count", themes.length, meta.theme_count);
  if (Array.isArray(previewIds)) {
    const expectedPreviews = new Set(layoutIds);
    const actualPreviews = new Set(previewIds);
    const missing = layoutIds.filter((id) => !actualPreviews.has(id));
    const extras = previewIds.filter((id) => !expectedPreviews.has(id));
    if (missing.length) issues.push(issue("MISSING_LAYOUT_PREVIEW", "previews", "Every layout must have an SVG preview.", missing));
    if (extras.length) issues.push(issue("ORPHAN_LAYOUT_PREVIEW", "previews", "SVG previews must reference an existing layout.", extras));
  }

  const issueCounts = {};
  for (const item of issues) issueCounts[item.code] = (issueCounts[item.code] ?? 0) + 1;
  const errors = issues.filter((item) => item.severity === "error");
  const warnings = issues.filter((item) => item.severity === "warning");
  return {
    audit_version: LAYOUT_AUDIT_VERSION,
    status: errors.length ? "invalid" : "valid",
    layout_count: layouts.length,
    category_count: categories.size,
    theme_count: themes.length,
    preview_count: Array.isArray(previewIds) ? previewIds.length : undefined,
    issue_count: issues.length,
    error_count: errors.length,
    warning_count: warnings.length,
    // Declared layers are legal, so they are warnings rather than errors; surfacing the count
    // directly keeps "0 errors, N intentional stacks" readable without scanning the issue list.
    declared_overlay_count: issueCounts.SLOT_OVERLAY_DECLARED ?? 0,
    issue_counts: issueCounts,
    issues,
  };
}

export async function auditBundledLayoutLibrary(options = {}) {
  const libraryDir = path.resolve(options.library_dir ?? options.libraryDir ?? DEFAULT_LIBRARY_DIR);
  const [layoutsPayload, themesPayload, layoutSchema, previewFiles] = await Promise.all([
    fs.readFile(path.join(libraryDir, "layouts.json"), "utf8").then(JSON.parse),
    fs.readFile(path.join(libraryDir, "themes.json"), "utf8").then(JSON.parse),
    fs.readFile(path.join(libraryDir, "layout.schema.json"), "utf8").then(JSON.parse),
    fs.readdir(path.join(libraryDir, "svg")),
  ]);
  const previewIds = previewFiles.filter((file) => file.toLowerCase().endsWith(".svg")).map((file) => path.parse(file).name);
  return auditLayoutLibrary({ layoutsPayload, themesPayload, layoutSchema, previewIds });
}
