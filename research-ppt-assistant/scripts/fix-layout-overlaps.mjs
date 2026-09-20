#!/usr/bin/env node
/**
 * One-time (idempotent) migration that removes slot-rectangle intersections from the bundled
 * layout library and re-derives every geometry-dependent field.
 *
 * Why this exists
 * ---------------
 * `slots[].box` is the real placeholder rectangle the renderer uses, so how two boxes meet decides
 * whether they are a defect. 50 of the 320 bundled layouts shipped with intersecting slots, and
 * they split cleanly in two:
 *
 *   - 26 layouts where boxes CROSS (neither contains the other). The shared region belongs to
 *     neither slot, so content is guaranteed to collide. These boxes were shrunk/shifted.
 *   - 24 layouts where one box sits entirely INSIDE another: a cover plate with its title on top,
 *     a figure with pinned annotations, a reference block with a QR badge. These are deliberate
 *     stacks and their geometry was restored, marked `overlay: true` on the contained slot.
 *
 * `auditLayoutLibrary` blocks on `SLOT_OVERLAP` (undeclared collision) and accepts a stack once it
 * is declared. This script is how the shipped geometry was brought to that state, and it is the
 * tool to re-run after any geometry edit.
 *
 * What it does
 * ------------
 *   1. `resolveSlotOverlaps` shrinks/shifts the yielding slot of every offending pair until no
 *      undeclared pair intersects. Pairs joined by a valid overlay declaration are never touched.
 *   2. `applyDerivedLayoutFields` rewrites `pptx_in`, `min_visual_area`,
 *      `preferred_visual_aspect_ratio` and `content_profile` from the corrected boxes.
 *   3. The payload is written back with the library's exact on-disk number formatting so that
 *      untouched layouts stay byte-identical.
 *
 * Running it again on an already normalised library reports zero edits and writes nothing.
 * Cross-platform: pure Node ESM, paths resolved from `import.meta.url`, no shell commands.
 *
 * Usage: node ./scripts/fix-layout-overlaps.mjs [--check] [--json]
 *   --check  exit 1 when the library still needs normalisation (CI guard), write nothing
 *   --json   emit the edit log (plus the retained declared overlays) as JSON
 */

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import {
  applyDerivedLayoutFields,
  findSlotOverlaps,
  isDeclaredOverlayPair,
  resolveSlotOverlaps,
  slideSizeOf,
} from "../server/layout-geometry.mjs";

const SCRIPT_DIR = path.dirname(fileURLToPath(import.meta.url));
const LIBRARY_DIR = path.resolve(SCRIPT_DIR, "..", "assets", "layout-library");
const LAYOUTS_PATH = path.join(LIBRARY_DIR, "layouts.json");

/**
 * Keys whose integer values are rendered with a trailing `.0` on disk (`"y": 6.0`), because the
 * bundled library was generated that way. Everything else drops the decimal for whole numbers.
 */
const ONE_DECIMAL_KEYS = new Set(["x", "y", "w", "h", "min_visual_area"]);

function formatNumber(key, value) {
  if (!Number.isFinite(value)) throw new Error(`non-finite number for key "${key}": ${value}`);
  if (ONE_DECIMAL_KEYS.has(key) && Number.isInteger(value)) return value.toFixed(1);
  return String(value);
}

/** Byte-exact re-serialisation of the layout payload (2-space indent, insertion key order). */
export function serializeLayouts(payload) {
  const encode = (key, value, depth) => {
    const pad = "  ".repeat(depth);
    const inner = "  ".repeat(depth + 1);
    if (value === null) return "null";
    if (typeof value === "string") return JSON.stringify(value);
    if (typeof value === "boolean") return String(value);
    if (typeof value === "number") return formatNumber(key, value);
    if (Array.isArray(value)) {
      if (!value.length) return "[]";
      return `[\n${value.map((item) => inner + encode(null, item, depth + 1)).join(",\n")}\n${pad}]`;
    }
    const keys = Object.keys(value);
    if (!keys.length) return "{}";
    return `{\n${keys.map((k) => `${inner}${JSON.stringify(k)}: ${encode(k, value[k], depth + 1)}`).join(",\n")}\n${pad}}`;
  };
  return `${encode(null, payload, 0)}\n`;
}

export function normalizeLayoutLibrary(payload) {
  const slideSize = slideSizeOf(payload?.meta);
  const layouts = Array.isArray(payload?.layouts) ? payload.layouts : [];
  const edits = [];
  for (const layout of layouts) {
    const slots = Array.isArray(layout?.slots) ? layout.slots : [];
    const applied = resolveSlotOverlaps(slots);
    if (applied.length) {
      edits.push({
        layout_id: layout.id,
        resolved_pairs: applied.length,
        slot_edits: applied,
        unresolved: applied.some((edit) => edit.action === "unresolved"),
      });
    }
    applyDerivedLayoutFields(layout, slideSize);
  }
  return { edits, slideSize };
}

function main() {
  const check = process.argv.includes("--check");
  const asJson = process.argv.includes("--json");
  const raw = fs.readFileSync(LAYOUTS_PATH, "utf8");
  const payload = JSON.parse(raw);
  const before = JSON.stringify(payload);
  const { edits } = normalizeLayoutLibrary(payload);
  const next = serializeLayouts(payload);
  const changed = next !== raw;

  if (check) {
    if (changed) {
      process.stderr.write(`Layout library needs normalisation: ${edits.length} layouts with slot overlaps.\n`);
      process.exitCode = 1;
      return;
    }
    process.stdout.write("Layout library geometry is normalised.\n");
    return;
  }

  if (!changed) {
    process.stdout.write("No layout geometry changes required (already normalised).\n");
    return;
  }

  fs.writeFileSync(LAYOUTS_PATH, next, "utf8");

  const unresolved = edits.filter((edit) => edit.unresolved).map((edit) => edit.layout_id);
  const remaining = [];
  const declared = [];
  for (const layout of payload.layouts) {
    const slots = Array.isArray(layout?.slots) ? layout.slots : [];
    // Enforce the invariant this migration creates: no two slot boxes may intersect at all,
    // optional or not -- EXCEPT pairs joined by a valid overlay declaration, which are the
    // deliberate stacks the library is allowed to keep. `includeOptional` also covers the pairs
    // the audit only warns about.
    const undeclared = findSlotOverlaps(layout, { includeOptional: true }).filter((hit) => {
      const first = slots[hit.first_index];
      const second = slots[hit.second_index];
      if (isDeclaredOverlayPair(first, second)) {
        declared.push({ layout_id: layout.id, overlay_slot: first?.id, host_slot: second?.id });
        return false;
      }
      return true;
    });
    if (undeclared.length) remaining.push({ layout_id: layout.id, overlaps: undeclared.length });
  }

  if (asJson) {
    process.stdout.write(`${JSON.stringify({ changed: true, before_chars: before.length, edits, remaining, declared_overlays: declared }, null, 2)}\n`);
  } else {
    process.stdout.write(`Normalised ${edits.length} layouts.\n`);
    if (declared.length) process.stdout.write(`Kept ${declared.length} declared overlay(s).\n`);
    for (const edit of edits) {
      process.stdout.write(`  ${edit.layout_id}: ${edit.resolved_pairs} pair(s)\n`);
      for (const slot of edit.slot_edits) {
        process.stdout.write(
          `    ${slot.slot_id} ${slot.action} against ${slot.against}: ` +
            `${slot.before.x},${slot.before.y},${slot.before.w},${slot.before.h} -> ` +
            `${slot.after.x},${slot.after.y},${slot.after.w},${slot.after.h}\n`,
        );
      }
    }
  }

  if (unresolved.length) {
    process.stderr.write(`Unresolved overlaps: ${unresolved.join(", ")}\n`);
    process.exitCode = 1;
    return;
  }
  if (remaining.length) {
    process.stderr.write(`Layouts still reporting overlaps after migration: ${JSON.stringify(remaining)}\n`);
    process.exitCode = 1;
  }
}

if (process.argv[1] && path.resolve(process.argv[1]) === path.resolve(fileURLToPath(import.meta.url))) main();
