/**
 * Shared layout-geometry contract.
 *
 * Single source of truth for:
 *   - which slot types count as "visual" vs "text" (drives content_profile capacities),
 *   - how normalized `box` geometry maps to `pptx_in`,
 *   - every derived field on a layout (`preferred_visual_aspect_ratio`, `min_visual_area`,
 *     `content_profile.*`) so the bundled library can be regenerated deterministically,
 *   - pairwise slot-rectangle intersection, used by the blocking layout audit and by the
 *     one-time overlap migration script,
 *   - whether two intersecting slots are *stacked on purpose* rather than colliding.
 *
 * The library contract is: a slot `box` is the real placeholder rectangle the renderer uses, so
 * two boxes that CROSS (neither contains the other) guarantee a content collision — the shared
 * region belongs to neither slot. `auditLayoutLibrary` blocks on that.
 *
 * Stacking is different. A slot that sits entirely INSIDE another one is a layer: a cover plate
 * with its title on top, a figure with pinned annotations, a reference block with a QR badge.
 * That is a legitimate design, but it must be *declared* (`overlay: true` on the contained slot)
 * before the audit accepts it, so intent is recorded instead of inferred. Undeclared stacking
 * still fails, with a message telling the author which of the two remedies to apply.
 *
 * Pure Node ESM, no dependencies, no OS-specific paths or commands.
 */

export const LAYOUT_GEOMETRY_VERSION = "1.1.0";

/** Supported renderer target: 16:9, used to express normalized geometry in PowerPoint inches. */
export const DEFAULT_SLIDE_SIZE_IN = Object.freeze({ w: 13.333, h: 7.5 });

/** Slot types that represent media/visual content rather than prose. */
export const VISUAL_SLOT_TYPES = Object.freeze(["chart", "code", "figure", "formula", "process", "table"]);

/** Slot types that are neither visual content nor the slide title. */
export const NON_TEXT_SLOT_TYPES = Object.freeze(["chart", "figure", "title"]);

const VISUAL_TYPE_SET = new Set(VISUAL_SLOT_TYPES);
const NON_TEXT_TYPE_SET = new Set(NON_TEXT_SLOT_TYPES);

/** Visual media may not claim more than this fraction of the slide. */
export const VISUAL_AREA_CAP = 0.82;

/** `min_visual_area` is this fraction of the (capped) visual area capacity. */
export const MIN_VISUAL_AREA_RATIO = 0.72;

/** Normalized overlap deeper than this (in either axis) counts as a real intersection. */
export const OVERLAP_EPSILON = 0.002;

/** Smallest acceptable normalized width/height for a repaired slot. */
export const MIN_SLOT_EXTENT = 0.03;

export function isVisualSlotType(type) {
  return VISUAL_TYPE_SET.has(type);
}

export function isTextSlotType(type) {
  return !NON_TEXT_TYPE_SET.has(type);
}

/**
 * Round to the library's 3-decimal grid the way the bundled library was generated: correct
 * decimal rounding of the *exact* double value, with ties resolved to even.
 *
 * Neither `toFixed(3)` nor scaled arithmetic reproduces this. `0.5625` is an exact tie and must
 * stay `0.562`, while `0.5 * 13.333` is the double 6.666500000000000135… which is strictly above
 * the tie and must become `6.667`. Only the full expansion distinguishes the two, so the digits
 * are inspected as a decimal string.
 */
export function round3(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return n;
  const sign = n < 0 ? -1 : 1;
  const [intPart, fracPart = ""] = Math.abs(n).toFixed(20).split(".");
  const keep = fracPart.slice(0, 3).padEnd(3, "0");
  const rest = fracPart.slice(3);
  let result = Number(`${intPart}.${keep}`);
  const lead = rest[0];
  if (lead > "5") {
    result += 0.001;
  } else if (lead === "5") {
    const tie = !/[1-9]/.test(rest.slice(1));
    if (!tie || Number(keep[2]) % 2 !== 0) result += 0.001;
  }
  return sign * Number(result.toFixed(3));
}

export function slideSizeOf(meta) {
  const size = meta?.slide_size_in;
  const w = Number.isFinite(size?.w) && size.w > 0 ? size.w : DEFAULT_SLIDE_SIZE_IN.w;
  const h = Number.isFinite(size?.h) && size.h > 0 ? size.h : DEFAULT_SLIDE_SIZE_IN.h;
  return { w, h };
}

/** Normalized box (0..1) -> PowerPoint-inch rectangle, rounded to the library's 3 decimals. */
export function boxToPptxInches(box, slideSize = DEFAULT_SLIDE_SIZE_IN) {
  return {
    x: round3(box.x * slideSize.w),
    y: round3(box.y * slideSize.h),
    w: round3(box.w * slideSize.w),
    h: round3(box.h * slideSize.h),
  };
}

export function boxArea(box) {
  return box.w * box.h;
}

/**
 * Intersection of two normalized boxes, or null when they only touch.
 * `epsilon` ignores hairline overlaps left behind by 3-decimal rounding.
 */
export function overlapRect(a, b, epsilon = OVERLAP_EPSILON) {
  const x1 = Math.max(a.x, b.x);
  const y1 = Math.max(a.y, b.y);
  const x2 = Math.min(a.x + a.w, b.x + b.w);
  const y2 = Math.min(a.y + a.h, b.y + b.h);
  if (x2 - x1 <= epsilon || y2 - y1 <= epsilon) return null;
  return { x: x1, y: y1, w: x2 - x1, h: y2 - y1 };
}

/** True when `outer` fully covers `inner` (within `epsilon`). Both boxes are normalized. */
export function boxContains(outer, inner, epsilon = OVERLAP_EPSILON) {
  return Boolean(
    outer
      && inner
      && outer.x <= inner.x + epsilon
      && outer.y <= inner.y + epsilon
      && outer.x + outer.w >= inner.x + inner.w - epsilon
      && outer.y + outer.h >= inner.y + inner.h - epsilon,
  );
}

/**
 * Shape of one intersection:
 *   - "contained": one box sits entirely inside the other -> a stackable layer;
 *   - "crossing" : the boxes overlap partially -> the shared region belongs to neither slot;
 *   - null       : they do not intersect (or only touch).
 */
export function overlapKind(first, second, epsilon = OVERLAP_EPSILON) {
  if (!overlapRect(first, second, epsilon)) return null;
  return boxContains(first, second, epsilon) || boxContains(second, first, epsilon)
    ? "contained"
    : "crossing";
}

/** A slot declares itself a deliberate layer with `overlay: true`. */
export function isOverlaySlot(slot) {
  return slot?.overlay === true;
}

/**
 * Resolve a *valid* overlay declaration for one intersecting slot pair.
 *
 * A declaration is valid only when the declaring slot is actually the contained one: "I lie on
 * top of the region I sit inside". A slot that declares `overlay` but is the outer box is not
 * layering anything, and a declared layer that is not contained by its partner is a collision
 * wearing a declaration — both are rejected, so this can never be used as a blanket bypass.
 *
 * Returns `{ overlay_slot_id, host_slot_id }`, or null when the pair carries no valid
 * declaration (including "no declaration at all"). The pair still has to intersect.
 */
export function resolveOverlayDeclaration(first, second, epsilon = OVERLAP_EPSILON) {
  if (!overlapRect(first?.box, second?.box, epsilon)) return null;
  if (isOverlaySlot(first) && boxContains(second.box, first.box, epsilon)) {
    return { overlay_slot_id: first.id, host_slot_id: second.id };
  }
  if (isOverlaySlot(second) && boxContains(first.box, second.box, epsilon)) {
    return { overlay_slot_id: second.id, host_slot_id: first.id };
  }
  return null;
}

export function isDeclaredOverlayPair(first, second, epsilon = OVERLAP_EPSILON) {
  return resolveOverlayDeclaration(first, second, epsilon) !== null;
}

/**
 * All intersecting mandatory slot pairs of a layout, ordered by descending overlap area.
 * `optional` slots are skipped: the renderer may drop them, so they cannot guarantee a collision.
 */
export function findSlotOverlaps(layout, { epsilon = OVERLAP_EPSILON, includeOptional = false } = {}) {
  const slots = Array.isArray(layout?.slots) ? layout.slots : [];
  const hits = [];
  for (let i = 0; i < slots.length; i += 1) {
    for (let j = i + 1; j < slots.length; j += 1) {
      const a = slots[i];
      const b = slots[j];
      if (!includeOptional && (a?.optional === true || b?.optional === true)) continue;
      const boxA = a?.box;
      const boxB = b?.box;
      if (!boxA || !boxB) continue;
      const rect = overlapRect(boxA, boxB, epsilon);
      if (!rect) continue;
      hits.push({
        first_slot_id: a.id,
        second_slot_id: b.id,
        first_index: i,
        second_index: j,
        first_type: a.type,
        second_type: b.type,
        rect: { x: round3(rect.x), y: round3(rect.y), w: round3(rect.w), h: round3(rect.h) },
        overlap_area: round3(rect.w * rect.h),
        smaller_slot_ratio: round3((rect.w * rect.h) / Math.min(boxArea(boxA), boxArea(boxB))),
      });
    }
  }
  hits.sort((left, right) => right.overlap_area - left.overlap_area);
  return hits;
}

export function deriveVisualArea(slots) {
  return slots
    .filter((slot) => isVisualSlotType(slot?.type))
    .reduce((total, slot) => total + boxArea(slot.box), 0);
}

/** `content_profile`, derived purely from slot types and boxes. */
export function deriveContentProfile(slots, existing = {}) {
  const visualArea = deriveVisualArea(slots);
  const figureArea = slots
    .filter((slot) => slot?.type === "figure")
    .reduce((total, slot) => total + boxArea(slot.box), 0);
  const tableArea = slots
    .filter((slot) => slot?.type === "table")
    .reduce((total, slot) => total + boxArea(slot.box), 0);
  const mediaArea = figureArea + tableArea;
  const count = (type) => slots.filter((slot) => slot?.type === type).length;
  return {
    ...existing,
    image_capacity: count("figure"),
    figure_area_capacity: round3(Math.min(figureArea, VISUAL_AREA_CAP)),
    table_area_capacity: round3(Math.min(tableArea, VISUAL_AREA_CAP)),
    media_area_capacity: round3(Math.min(mediaArea, VISUAL_AREA_CAP)),
    chart_capacity: count("chart"),
    table_capacity: count("table"),
    visual_slot_count: slots.filter((slot) => isVisualSlotType(slot?.type)).length,
    text_slot_count: slots.filter((slot) => isTextSlotType(slot?.type)).length,
    visual_area_capacity: round3(Math.min(visualArea, VISUAL_AREA_CAP)),
    dominant_visual_slot: existing?.dominant_visual_slot ?? null,
  };
}

export function deriveMinVisualArea(slots) {
  return round3(MIN_VISUAL_AREA_RATIO * Math.min(deriveVisualArea(slots), VISUAL_AREA_CAP));
}

export function derivePreferredVisualAspectRatio(layout, slideSize = DEFAULT_SLIDE_SIZE_IN) {
  const dominant = layout?.content_profile?.dominant_visual_slot;
  const slots = Array.isArray(layout?.slots) ? layout.slots : [];
  const slot = dominant ? slots.find((candidate) => candidate?.id === dominant) : undefined;
  if (!slot?.box || !(slot.box.w > 0) || !(slot.box.h > 0)) return null;
  const widthIn = slot.box.w * slideSize.w;
  const heightIn = slot.box.h * slideSize.h;
  if (!(heightIn > 0)) return null;
  return round3(widthIn / heightIn);
}

/**
 * Rewrite every geometry-derived field of one layout in place: `pptx_in`, `min_visual_area`,
 * `preferred_visual_aspect_ratio`, and the `content_profile` capacity counters.
 */
export function applyDerivedLayoutFields(layout, slideSize = DEFAULT_SLIDE_SIZE_IN) {
  const slots = Array.isArray(layout?.slots) ? layout.slots : [];
  for (const slot of slots) {
    if (!slot?.box) continue;
    slot.pptx_in = boxToPptxInches(slot.box, slideSize);
  }
  layout.content_profile = deriveContentProfile(slots, layout?.content_profile ?? {});
  layout.min_visual_area = deriveMinVisualArea(slots);
  layout.preferred_visual_aspect_ratio = derivePreferredVisualAspectRatio(layout, slideSize);
  return layout;
}

/**
 * Deterministically remove every mandatory-slot intersection from one layout by shrinking or
 * shifting the *yielding* slot of the offending pair. Verticals are resolved first because the
 * library's grammar is row-stacked; a horizontal trim is used only when a vertical split is
 * impossible or would collapse a slot below `MIN_SLOT_EXTENT`.
 *
 * The yielding slot is picked in this order:
 *   1. the containing slot (it has the slack to give way), otherwise
 *   2. the slot that appears first in z-order / reading order.
 *
 * Returns the list of applied edits. Mutates `slots[i].box` in place. Running it on an already
 * repaired layout returns an empty list (idempotent).
 *
 * Slots joined by a valid overlay declaration are left alone: stacking is a design decision, not
 * a defect, and re-running this migration must never flatten a declared layer.
 */
export function resolveSlotOverlaps(slots, { epsilon = OVERLAP_EPSILON, minExtent = MIN_SLOT_EXTENT } = {}) {
  const edits = [];
  const list = Array.isArray(slots) ? slots : [];

  for (let guard = 0; guard < 400; guard += 1) {
    let worst = null;
    for (let i = 0; i < list.length; i += 1) {
      for (let j = i + 1; j < list.length; j += 1) {
        const a = list[i];
        const b = list[j];
        if (!a?.box || !b?.box) continue;
        if (isDeclaredOverlayPair(a, b, epsilon)) continue;
        const rect = overlapRect(a.box, b.box, epsilon);
        if (!rect) continue;
        const area = rect.w * rect.h;
        if (!worst || area > worst.area + 1e-12) worst = { i, j, area };
      }
    }
    if (!worst) return edits;

    const firstBox = list[worst.i].box;
    const secondBox = list[worst.j].box;
    const secondIsContainer =
      boxContains(secondBox, firstBox, epsilon) && !boxContains(firstBox, secondBox, epsilon);
    const victimRef = secondIsContainer ? list[worst.j] : list[worst.i];
    const anchorBox = secondIsContainer ? firstBox : secondBox;
    const victim = victimRef.box;
    const before = { x: round3(victim.x), y: round3(victim.y), w: round3(victim.w), h: round3(victim.h) };
    let applied = null;

    // 1) Vertical split: clamp the yielding slot's band against the anchor.
    if (victim.y < anchorBox.y - epsilon) {
      const height = anchorBox.y - victim.y;
      if (height >= minExtent) {
        victim.h = round3(height);
        applied = "height";
      } else {
        const top = anchorBox.y + anchorBox.h;
        const remaining = victim.y + victim.h - top;
        if (remaining >= minExtent) {
          victim.y = round3(top);
          victim.h = round3(remaining);
          applied = "shift";
        }
      }
    } else if (anchorBox.y < victim.y - epsilon) {
      const top = anchorBox.y + anchorBox.h;
      const remaining = victim.y + victim.h - top;
      if (remaining >= minExtent) {
        victim.y = round3(top);
        victim.h = round3(remaining);
        applied = "shift";
      } else {
        const height = anchorBox.y - victim.y;
        if (height >= minExtent) {
          victim.h = round3(height);
          applied = "height";
        }
      }
    }

    // 2) Horizontal trim: only when the vertical split is unavailable.
    if (!applied) {
      if (victim.x < anchorBox.x - epsilon) {
        const width = anchorBox.x - victim.x;
        if (width >= minExtent) {
          victim.w = round3(width);
          applied = "width";
        } else {
          const left = anchorBox.x + anchorBox.w;
          const remaining = victim.x + victim.w - left;
          if (remaining >= minExtent) {
            victim.x = round3(left);
            victim.w = round3(remaining);
            applied = "shift-width";
          }
        }
      } else if (anchorBox.x < victim.x - epsilon) {
        const left = anchorBox.x + anchorBox.w;
        const remaining = victim.x + victim.w - left;
        if (remaining >= minExtent) {
          victim.x = round3(left);
          victim.w = round3(remaining);
          applied = "shift-width";
        } else {
          const width = anchorBox.x - victim.x;
          if (width >= minExtent) {
            victim.w = round3(width);
            applied = "width";
          }
        }
      }
    }

    if (!applied) {
      edits.push({
        slot_id: victimRef.id,
        against: list[victimRef === list[worst.i] ? worst.j : worst.i].id,
        action: "unresolved",
        before,
        after: before,
      });
      return edits;
    }
    edits.push({
      slot_id: victimRef.id,
      against: list[victimRef === list[worst.i] ? worst.j : worst.i].id,
      action: applied,
      before,
      after: { x: round3(victim.x), y: round3(victim.y), w: round3(victim.w), h: round3(victim.h) },
    });
  }
  return edits;
}
