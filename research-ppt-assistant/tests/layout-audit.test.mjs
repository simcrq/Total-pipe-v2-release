import assert from "node:assert/strict";
import test from "node:test";
import { auditBundledLayoutLibrary, auditLayoutLibrary } from "../server/layout-audit.mjs";
import { boxToPptxInches } from "../server/layout-geometry.mjs";

test("bundled 320-layout library passes the blocking static audit", async () => {
  const result = await auditBundledLayoutLibrary();
  assert.equal(result.status, "valid");
  assert.equal(result.layout_count, 320);
  assert.equal(result.category_count, 40);
  assert.equal(result.theme_count, 16);
  assert.equal(result.preview_count, 320);
  // The library ships deliberate stacks (a cover plate with its title on top, a figure with pinned
  // annotations). Those are legal but they are reported, so "clean" now means "no errors and every
  // remaining issue is a declared layer" rather than "no issues at all".
  assert.equal(result.error_count, 0);
  assert.equal(result.declared_overlay_count, 38);
  assert.equal(result.issue_count, result.declared_overlay_count);
  assert.ok(result.issues.every((item) => item.code === "SLOT_OVERLAY_DECLARED"));
  assert.ok(result.issues.every((item) => item.severity === "warning"));
});

test("layout audit separates declared stacks from undeclared overlap", () => {
  // A synthetic category must satisfy the "variants 1..8" contract and carry `pptx_in`, otherwise
  // unrelated issues (CATEGORY_VARIANT_SET_INVALID / MISSING_PPTX_COORDINATES) mask the codes
  // under test. Variant 1 holds the slots of interest, the rest are minimal placeholders.
  const slideSize = { w: 13.333, h: 7.5 };
  const audit = (variantOneSlots) =>
    auditLayoutLibrary({
      layoutsPayload: {
        meta: { layout_count: 8, category_count: 1, theme_count: 0, slide_size_in: slideSize },
        layouts: Array.from({ length: 8 }, (_, index) => {
          const variant = index + 1;
          const slots =
            variant === 1
              ? variantOneSlots
              : [{ id: "title", type: "title", box: { x: 0.05, y: 0.05, w: 0.9, h: 0.1 } }];
          return {
            id: `RM-TEST-${String(variant).padStart(2, "0")}`,
            category: "test",
            variant_index: variant,
            slots: slots.map((slot) => ({ ...slot, pptx_in: boxToPptxInches(slot.box, slideSize) })),
            reading_order: slots.map((slot) => slot.id),
            content_profile: {},
          };
        }),
      },
      themesPayload: { meta: { theme_count: 0 }, themes: [] },
      layoutSchema: {},
    });
  const plate = { id: "plate", type: "figure", box: { x: 0.04, y: 0.04, w: 0.92, h: 0.92 } };
  const label = { id: "label", type: "title", box: { x: 0.08, y: 0.52, w: 0.62, h: 0.18 } };
  const codes = (result) => result.issues.map((item) => item.code);
  const only = (result, code) => result.issues.filter((item) => item.code === code);

  const declared = audit([plate, { ...label, overlay: true }]);
  assert.deepEqual(codes(declared), ["SLOT_OVERLAY_DECLARED"]);
  assert.equal(declared.status, "valid", "a declared stack must not block CI");
  assert.equal(declared.declared_overlay_count, 1);
  assert.equal(only(declared, "SLOT_OVERLAY_DECLARED")[0].actual.overlay_slot, "label");
  assert.equal(only(declared, "SLOT_OVERLAY_DECLARED")[0].actual.host_slot, "plate");

  // Same geometry, no declaration: still blocked, and the message has to point at both remedies.
  const undeclared = audit([plate, label]);
  assert.equal(undeclared.status, "invalid");
  assert.deepEqual(codes(undeclared), ["SLOT_OVERLAP"]);
  assert.equal(only(undeclared, "SLOT_OVERLAP")[0].actual.overlap_kind, "contained");
  assert.match(only(undeclared, "SLOT_OVERLAP")[0].message, /declare overlay: true/);

  // A crossing pair stays a plain collision: `overlay` is not a blanket bypass.
  const crossing = audit([
    { id: "a", type: "text", box: { x: 0, y: 0, w: 0.5, h: 0.5 } },
    { id: "b", type: "text", overlay: true, box: { x: 0.25, y: 0.25, w: 0.5, h: 0.5 } },
  ]);
  assert.equal(crossing.status, "invalid");
  assert.deepEqual(codes(crossing), ["SLOT_OVERLAY_NOT_CONTAINED"]);
  assert.equal(only(crossing, "SLOT_OVERLAY_NOT_CONTAINED")[0].actual.overlap_kind, "crossing");

  // A declaration on the outer box does not describe a layer either.
  const outerDeclaration = audit([{ ...plate, overlay: true }, label]);
  assert.equal(outerDeclaration.status, "invalid");
  assert.deepEqual(codes(outerDeclaration), ["SLOT_OVERLAY_NOT_CONTAINED"]);

  // Stale declaration: nothing to layer onto.
  const unused = audit([label, { id: "chip", type: "text", overlay: true, box: { x: 0.8, y: 0.85, w: 0.1, h: 0.05 } }]);
  assert.equal(unused.status, "valid");
  assert.deepEqual(codes(unused), ["SLOT_OVERLAY_UNUSED"]);
  assert.equal(unused.declared_overlay_count, 0);
});

test("layout audit reports schema, identity, geometry, ordering, preview, and theme defects", () => {
  const invalidLayout = {
    id: "bad-id",
    category: "broken",
    variant_index: 1,
    slots: [
      { id: "same", type: "title", box: { x: 0.9, y: 0.9, w: 0.2, h: 0 }, pptx_in: { x: 0, y: 0, w: 0, h: 0 } },
      { id: "same", type: "text", box: { x: 0, y: 0, w: 0.5, h: 0.5 } },
      { id: "omitted", type: "text", box: { x: 0, y: 0, w: 0.5, h: 0.5 }, pptx_in: { x: 0, y: 0, w: 6.6665, h: 3.75 } },
    ],
    reading_order: ["same", "same", "unknown"],
    content_profile: { dominant_visual_slot: "missing" },
  };
  const result = auditLayoutLibrary({
    layoutsPayload: {
      meta: { layout_count: 2, category_count: 2, theme_count: 2, slide_size_in: { w: 13.333, h: 7.5 } },
      layouts: [invalidLayout, structuredClone(invalidLayout)],
    },
    themesPayload: {
      meta: { theme_count: 3 },
      themes: [
        { id: "same", bg: "bad" },
        { id: "same", bg: "#FFFFFF" },
      ],
    },
    layoutSchema: { type: "object", required: ["required_field"], additionalProperties: true },
    previewIds: ["orphan"],
  });
  const codes = new Set(result.issues.map((item) => item.code));
  for (const code of [
    "LAYOUT_SCHEMA_INVALID",
    "INVALID_LAYOUT_ID",
    "DUPLICATE_LAYOUT_ID",
    "DUPLICATE_SLOT_ID",
    "NON_POSITIVE_SLOT_SIZE",
    "SLOT_OUT_OF_BOUNDS",
    "PPTX_COORDINATE_MISMATCH",
    "MISSING_PPTX_COORDINATES",
    "DUPLICATE_READING_ORDER_SLOT",
    "UNKNOWN_READING_ORDER_SLOT",
    "MISSING_READING_ORDER_SLOT",
    "UNKNOWN_DOMINANT_VISUAL_SLOT",
    "CATEGORY_VARIANT_SET_INVALID",
    "DUPLICATE_THEME_ID",
    "THEME_COUNT_MISMATCH",
    "INVALID_THEME_COLOR",
    "MISSING_LAYOUT_PREVIEW",
    "ORPHAN_LAYOUT_PREVIEW",
  ]) assert.ok(codes.has(code), `missing ${code}`);
  assert.equal(result.status, "invalid");
  assert.equal(result.issue_count, result.issues.length);
});

test("layout audit supports metadata-only calls without preview comparison", () => {
  const result = auditLayoutLibrary({
    layoutsPayload: { meta: { layout_count: 0, category_count: 0, theme_count: 0 }, layouts: [] },
    themesPayload: { meta: { theme_count: 0 }, themes: [] },
    layoutSchema: {},
  });
  assert.equal(result.status, "valid");
  assert.equal(result.preview_count, undefined);
});

test("layout audit reports missing theme IDs and all metadata count drift", () => {
  const result = auditLayoutLibrary({
    layoutsPayload: { meta: { layout_count: 1, category_count: 1, theme_count: 2 }, layouts: [] },
    themesPayload: { meta: { theme_count: 0 }, themes: [{ bg: "#FFFFFF" }] },
    layoutSchema: null,
    previewIds: [],
  });
  const codes = new Set(result.issues.map((item) => item.code));
  for (const code of ["LAYOUT_COUNT_MISMATCH", "CATEGORY_COUNT_MISMATCH", "LAYOUT_THEME_COUNT_MISMATCH", "THEME_COUNT_MISMATCH", "MISSING_THEME_ID"]) {
    assert.ok(codes.has(code), `missing ${code}`);
  }
});

test("layout audit validates declared theme-token usage contracts", () => {
  const result = auditLayoutLibrary({
    layoutsPayload: { meta: { layout_count: 0, category_count: 0, theme_count: 0 }, layouts: [] },
    themesPayload: {
      meta: {
        theme_count: 0,
        token_contract_version: "1.0.0",
        token_usage_constraints: {
          bg: { allowed_usage: ["background"], forbidden_usage: ["background"] },
        },
      },
      themes: [],
    },
    layoutSchema: {},
  });
  const codes = new Set(result.issues.map((item) => item.code));
  assert.ok(codes.has("CONFLICTING_THEME_USAGE_CONSTRAINT"));
  assert.ok(codes.has("MISSING_THEME_USAGE_CONSTRAINT"));
});
