import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { auditBundledLayoutLibrary, auditLayoutLibrary } from "../server/layout-audit.mjs";
import {
  applyDerivedLayoutFields,
  boxContains,
  boxToPptxInches,
  deriveContentProfile,
  deriveMinVisualArea,
  derivePreferredVisualAspectRatio,
  findSlotOverlaps,
  isDeclaredOverlayPair,
  isOverlaySlot,
  isTextSlotType,
  isVisualSlotType,
  MIN_VISUAL_AREA_RATIO,
  overlapKind,
  resolveOverlayDeclaration,
  resolveSlotOverlaps,
  round3,
  slideSizeOf,
  VISUAL_AREA_CAP,
} from "../server/layout-geometry.mjs";
import { generatePreviews } from "../scripts/gen-layout-previews.mjs";
import { normalizeLayoutLibrary, serializeLayouts } from "../scripts/fix-layout-overlaps.mjs";

const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const LIBRARY_DIR = path.join(REPO_ROOT, "assets", "layout-library");
const layoutsPayload = () => JSON.parse(fs.readFileSync(path.join(LIBRARY_DIR, "layouts.json"), "utf8"));

test("round3 matches the library's decimal grid including exact halves", () => {
  // Exact binary half: ties go to even, so this must NOT become 0.563.
  assert.equal(round3(0.5625), 0.562);
  // The double nearest 6.6665 is strictly above the tie, so it must round up.
  assert.equal(round3(6.6665), 6.667);
  assert.equal(round3(1.3675), 1.367);
  assert.equal(round3(0.137), 0.137);
  assert.equal(round3(0), 0);
  assert.equal(round3(0.4), 0.4);
});

test("slot type classification matches the library's capacity contract", () => {
  for (const type of ["chart", "code", "figure", "formula", "process", "table"]) {
    assert.equal(isVisualSlotType(type), true, `${type} should be visual`);
  }
  for (const type of ["title", "text", "callout", "caption", "meta", "metric", "timeline"]) {
    assert.equal(isVisualSlotType(type), false, `${type} should not be visual`);
  }
  // `title` is excluded from the text count, but `metric` and `timeline` are counted as text.
  assert.equal(isTextSlotType("title"), false);
  assert.equal(isTextSlotType("metric"), true);
  assert.equal(isTextSlotType("timeline"), true);
  assert.equal(isTextSlotType("chart"), false);
});

test("derived profile fields follow the documented area caps", () => {
  const slots = [
    { id: "title", type: "title", box: { x: 0.05, y: 0.05, w: 0.9, h: 0.1 } },
    { id: "figure", type: "figure", box: { x: 0.05, y: 0.2, w: 0.5, h: 0.5 } },
    { id: "table", type: "table", box: { x: 0.6, y: 0.2, w: 0.35, h: 0.5 } },
    { id: "text", type: "text", box: { x: 0.05, y: 0.75, w: 0.9, h: 0.15 } },
  ];
  const profile = deriveContentProfile(slots, { dominant_visual_slot: "figure" });
  assert.equal(profile.image_capacity, 1);
  assert.equal(profile.chart_capacity, 0);
  assert.equal(profile.table_capacity, 1);
  assert.equal(profile.visual_slot_count, 2);
  assert.equal(profile.text_slot_count, 2);
  assert.equal(profile.figure_area_capacity, 0.25);
  assert.equal(profile.table_area_capacity, 0.175);
  assert.equal(profile.media_area_capacity, 0.425);
  assert.equal(profile.visual_area_capacity, 0.425);

  const huge = [{ id: "figure", type: "figure", box: { x: 0, y: 0, w: 1, h: 1 } }];
  assert.equal(deriveContentProfile(huge, {}).visual_area_capacity, VISUAL_AREA_CAP);
  assert.equal(deriveMinVisualArea(huge), round3(MIN_VISUAL_AREA_RATIO * VISUAL_AREA_CAP));

  const layout = { slots, content_profile: { dominant_visual_slot: "figure" } };
  const slideSize = slideSizeOf(undefined);
  assert.equal(derivePreferredVisualAspectRatio(layout, slideSize), round3((0.5 * 13.333) / (0.5 * 7.5)));
  assert.deepEqual(boxToPptxInches({ x: 0, y: 0, w: 1, h: 1 }, { w: 13.333, h: 7.5 }), { x: 0, y: 0, w: 13.333, h: 7.5 });
});

test("resolveSlotOverlaps clears nested and staircase collisions and is idempotent", () => {
  const slots = [
    { id: "block", type: "text", box: { x: 0.055, y: 0.2, w: 0.56, h: 0.65 } },
    { id: "bar", type: "callout", box: { x: 0.055, y: 0.72, w: 0.56, h: 0.13 } },
    { id: "chip", type: "callout", box: { x: 0.7, y: 0.05, w: 0.11, h: 0.08 } },
    { id: "title", type: "title", box: { x: 0.055, y: 0.045, w: 0.89, h: 0.1 } },
  ];
  const edits = resolveSlotOverlaps(slots);
  assert.ok(edits.length >= 2, "expected the nested bar and the title chip to be resolved");
  assert.deepEqual(findSlotOverlaps({ slots }), []);
  assert.equal(slots[0].box.h, 0.52, "tall block should stop where the bottom bar starts");
  assert.equal(slots[3].box.w, 0.645, "title should stop where the chip starts");
  assert.deepEqual(resolveSlotOverlaps(slots), [], "resolving twice must be a no-op");
});

test("slot overlap detection reports overlap geometry and tiny slivers are ignored", () => {
  const layout = {
    slots: [
      { id: "a", type: "text", box: { x: 0, y: 0, w: 0.5, h: 0.5 } },
      { id: "b", type: "text", box: { x: 0.25, y: 0.25, w: 0.5, h: 0.5 } },
    ],
  };
  const hits = findSlotOverlaps(layout);
  assert.equal(hits.length, 1);
  assert.equal(hits[0].first_slot_id, "a");
  assert.equal(hits[0].second_slot_id, "b");
  assert.deepEqual(hits[0].rect, { x: 0.25, y: 0.25, w: 0.25, h: 0.25 });
  assert.equal(hits[0].overlap_area, 0.062);

  const touching = {
    slots: [
      { id: "a", type: "text", box: { x: 0, y: 0, w: 0.5, h: 0.5 } },
      { id: "b", type: "text", box: { x: 0.5, y: 0, w: 0.5, h: 0.5 } },
    ],
  };
  assert.deepEqual(findSlotOverlaps(touching), []);
});

test("bundled library only intersects through declared overlays and has consistent derived fields", () => {
  const payload = layoutsPayload();
  const slideSize = slideSizeOf(payload.meta);
  assert.equal(payload.layouts.length, 320);
  let declaredPairs = 0;
  for (const layout of payload.layouts) {
    const slots = Array.isArray(layout.slots) ? layout.slots : [];
    // The invariant is no longer "nothing may intersect" but "nothing may intersect *undeclared*":
    // a stack is legal once the contained slot carries `overlay: true`, and it must really be a
    // stack (containment), never a crossing pair wearing a declaration.
    for (const hit of findSlotOverlaps(layout, { includeOptional: true })) {
      const first = slots[hit.first_index];
      const second = slots[hit.second_index];
      assert.ok(
        isDeclaredOverlayPair(first, second),
        `${layout.id}: "${hit.first_slot_id}"/"${hit.second_slot_id}" intersect without a declaration`,
      );
      assert.equal(
        overlapKind(first.box, second.box),
        "contained",
        `${layout.id}: a declared overlay must be fully contained by its host`,
      );
      declaredPairs += 1;
    }
    const before = JSON.stringify([
      layout.content_profile,
      layout.min_visual_area,
      layout.preferred_visual_aspect_ratio,
      layout.slots.map((slot) => slot.pptx_in),
    ]);
    applyDerivedLayoutFields(layout, slideSize);
    const after = JSON.stringify([
      layout.content_profile,
      layout.min_visual_area,
      layout.preferred_visual_aspect_ratio,
      layout.slots.map((slot) => slot.pptx_in),
    ]);
    assert.equal(after, before, `${layout.id} derived fields drifted from slot geometry`);
  }
  assert.equal(declaredPairs, 38, "the bundled library ships 38 declared overlay pairs");
});

test("bundled library payload round-trips byte-for-byte through the migration serializer", () => {
  const raw = fs.readFileSync(path.join(LIBRARY_DIR, "layouts.json"), "utf8");
  assert.equal(serializeLayouts(JSON.parse(raw)), raw);
});

test("layout generator reproduces every shipped SVG preview", () => {
  const previews = generatePreviews(layoutsPayload());
  assert.equal(previews.size, 320);
  for (const [id, svg] of previews) {
    const shipped = fs.readFileSync(path.join(LIBRARY_DIR, "svg", `${id}.svg`), "utf8");
    assert.equal(svg, shipped, `${id}.svg drifted from layouts.json geometry`);
  }
});

test("audit blocks mandatory slot overlap and warns when an optional slot is involved", async () => {
  const bundle = await auditBundledLayoutLibrary();
  assert.equal(bundle.status, "valid");
  assert.equal(bundle.issue_counts.SLOT_OVERLAP, undefined);

  const slideSize = { w: 13.333, h: 7.5 };
  // A synthetic category must still satisfy the "variants 1..8" contract; otherwise the audit
  // reports an unrelated CATEGORY_VARIANT_SET_INVALID that would mask the overlap assertion.
  // The interesting slots go into variant 1, the other seven are minimal placeholders.
  const syntheticLibrary = (variantOneSlots) => {
    const layouts = Array.from({ length: 8 }, (_, index) => {
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
    });
    return {
      meta: { layout_count: 8, category_count: 1, theme_count: 0, slide_size_in: slideSize },
      layouts,
    };
  };
  const auditSynthetic = (variantOneSlots) =>
    auditLayoutLibrary({
      layoutsPayload: syntheticLibrary(variantOneSlots),
      themesPayload: { meta: { theme_count: 0 }, themes: [] },
      layoutSchema: {},
    });

  const overlapping = auditSynthetic([
    { id: "a", type: "text", box: { x: 0, y: 0, w: 0.5, h: 0.5 } },
    { id: "b", type: "text", box: { x: 0.25, y: 0.25, w: 0.5, h: 0.5 } },
  ]);
  assert.equal(overlapping.status, "invalid");
  assert.equal(overlapping.error_count, 1);
  assert.equal(overlapping.issue_counts.SLOT_OVERLAP, 1);
  const blocked = overlapping.issues.find((item) => item.code === "SLOT_OVERLAP");
  assert.equal(blocked.severity, "error");
  assert.equal(blocked.actual.overlap_type, "text_text");

  const optionalInvolved = auditSynthetic([
    { id: "figure", type: "figure", box: { x: 0, y: 0, w: 0.5, h: 0.5 } },
    { id: "chip", type: "text", optional: true, box: { x: 0.1, y: 0.1, w: 0.2, h: 0.2 } },
  ]);
  assert.equal(optionalInvolved.status, "valid", "optional-slot overlap must not block CI");
  assert.equal(optionalInvolved.error_count, 0);
  assert.equal(optionalInvolved.warning_count, 1);
  assert.equal(optionalInvolved.issue_counts.SLOT_OVERLAP_OPTIONAL, 1);
  const warned = optionalInvolved.issues.find((item) => item.code === "SLOT_OVERLAP_OPTIONAL");
  assert.equal(warned.severity, "warning");
  assert.equal(warned.actual.overlap_type, "text_visual");
});

test("normalizeLayoutLibrary is a no-op on the bundled library", () => {
  const payload = layoutsPayload();
  const snapshot = JSON.stringify(payload);
  const { edits } = normalizeLayoutLibrary(payload);
  assert.deepEqual(edits, []);
  assert.equal(JSON.stringify(payload), snapshot);
});

test("overlapKind separates a stack from a crossing collision", () => {
  const outer = { x: 0.04, y: 0.04, w: 0.92, h: 0.92 };
  const inner = { x: 0.08, y: 0.52, w: 0.62, h: 0.18 };
  // Overhangs the outer box's right/bottom edge, so neither contains the other.
  const crossing = { x: 0.8, y: 0.8, w: 0.4, h: 0.4 };
  assert.equal(overlapKind(outer, inner), "contained");
  assert.equal(overlapKind(inner, outer), "contained");
  assert.equal(overlapKind(outer, crossing), "crossing");
  assert.equal(overlapKind(inner, { x: 0.9, y: 0.9, w: 0.05, h: 0.05 }), null);
  assert.equal(boxContains(outer, inner), true);
  assert.equal(boxContains(inner, outer), false);
});

test("an overlay declaration only counts when the declaring slot is the contained one", () => {
  const plate = { id: "plate", type: "figure", box: { x: 0.04, y: 0.04, w: 0.92, h: 0.92 } };
  const title = { id: "title", type: "title", box: { x: 0.08, y: 0.52, w: 0.62, h: 0.18 } };
  assert.deepEqual(resolveOverlayDeclaration({ ...title, overlay: true }, plate), {
    overlay_slot_id: "title",
    host_slot_id: "plate",
  });
  assert.deepEqual(resolveOverlayDeclaration(plate, { ...title, overlay: true }), {
    overlay_slot_id: "title",
    host_slot_id: "plate",
  });
  // No declaration at all.
  assert.equal(resolveOverlayDeclaration(title, plate), null);
  // Declared on the outer box: it is not layering onto anything, so the pair is not accepted.
  assert.equal(resolveOverlayDeclaration({ ...plate, overlay: true }, title), null);
  // Declared but crossing instead of contained: still not a layer.
  const crossing = { id: "b", type: "text", overlay: true, box: { x: 0.5, y: 0.5, w: 0.4, h: 0.4 } };
  assert.equal(resolveOverlayDeclaration({ id: "a", type: "text", box: { x: 0.04, y: 0.04, w: 0.6, h: 0.6 } }, crossing), null);
  assert.equal(isOverlaySlot({ overlay: true }), true);
  assert.equal(isOverlaySlot({ overlay: false }), false);
  assert.equal(isOverlaySlot({}), false);
});

test("resolveSlotOverlaps flattens crossings but never flattens a declared stack", () => {
  const plate = { id: "plate", type: "figure", box: { x: 0.04, y: 0.04, w: 0.5, h: 0.5 } };
  const title = { id: "title", type: "title", overlay: true, box: { x: 0.08, y: 0.3, w: 0.3, h: 0.1 } };
  const a = { id: "a", type: "text", box: { x: 0.6, y: 0.1, w: 0.35, h: 0.3 } };
  const b = { id: "b", type: "text", box: { x: 0.8, y: 0.25, w: 0.15, h: 0.3 } };

  const edits = resolveSlotOverlaps([plate, title, a, b]);
  assert.equal(edits.length, 1, "only the crossing pair needs resolving");
  assert.equal(edits[0].slot_id, "a");
  assert.equal(edits[0].action, "height");
  assert.ok(!edits.some((edit) => edit.slot_id === "title"), "a declared stack must be left untouched");

  // The stack survives intact; only the crossing pair is gone.
  assert.deepEqual(findSlotOverlaps({ slots: [plate, title] }), [
    {
      first_slot_id: "plate",
      second_slot_id: "title",
      first_index: 0,
      second_index: 1,
      first_type: "figure",
      second_type: "title",
      rect: { x: 0.08, y: 0.3, w: 0.3, h: 0.1 },
      overlap_area: 0.03,
      smaller_slot_ratio: 1,
    },
  ]);
  assert.deepEqual(findSlotOverlaps({ slots: [a, b] }), []);
  assert.deepEqual(resolveSlotOverlaps([plate, title, a, b]), [], "second pass is a no-op");
});
