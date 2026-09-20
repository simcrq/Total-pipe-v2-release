#!/usr/bin/env node
/**
 * Deterministic generator for the bundled SVG layout previews.
 *
 * The 320 previews under `assets/layout-library/svg/` are served as the MCP resource
 * `research-ppt://preview/{layout_id}`. They must always mirror `slots[].box`, otherwise the
 * preview silently lies about a layout. The originals were produced by an out-of-tree tool, so
 * this script reproduces that renderer exactly and makes the previews regenerable from
 * `layouts.json` alone.
 *
 * Recovered rendering contract (verified byte-for-byte against all 320 shipped previews):
 *   - 960x540 canvas, inset frame at 18,18 sized 924x504
 *   - slot rect: x = 18 + box.x*924, y = 18 + box.y*504, w = box.w*924, h = box.h*504
 *   - label font-size: clamp(min(0.16*h, 0.065*w), 10, 20)
 *   - label baseline: min(rect.y + 10 + fs, rect.y + rect.h - 8)
 *   - sub line ("type · pN") only when 14 + 2*fs + subFs fits inside the rect
 *   - sub font-size: clamp(fs*0.65, 9, 13)
 *   - optional slots render at fill-opacity 0.16 with a 6 5 dash
 *
 * Cross-platform: pure Node ESM, paths resolved from `import.meta.url`, no shell commands.
 *
 * Usage: node ./scripts/gen-layout-previews.mjs [--check] [--json]
 *   --check  exit 1 when any preview is stale (CI guard), write nothing
 *   --json   emit a machine-readable summary
 */

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const SCRIPT_DIR = path.dirname(fileURLToPath(import.meta.url));
const LIBRARY_DIR = path.resolve(SCRIPT_DIR, "..", "assets", "layout-library");
const LAYOUTS_PATH = path.join(LIBRARY_DIR, "layouts.json");
const SVG_DIR = path.join(LIBRARY_DIR, "svg");

/** Version of the preview rendering contract (bumped when the emitted SVG changes shape). */
export const PREVIEW_GENERATOR_VERSION = "1.1.0";

const CANVAS = Object.freeze({ w: 960, h: 540, inset: 18, frameW: 924, frameH: 504, pad: 10 });
const FONT_MIN = 10;
const FONT_MAX = 20;
const SUB_FONT_MIN = 9;
const SUB_FONT_MAX = 13;
const SUB_FONT_RATIO = 0.65;
const HEIGHT_RATIO = 0.16;
const WIDTH_RATIO = 0.065;
const BASELINE_OFFSET = 10;
const SUB_BASELINE_OFFSET = 14;
const BASELINE_BOTTOM_MARGIN = 8;

/** Stable per-type accent colour used by the shipped previews. */
export const SLOT_TYPE_COLORS = Object.freeze({
  title: "#1D4ED8",
  subtitle: "#3B82F6",
  text: "#64748B",
  callout: "#EF4444",
  meta: "#94A3B8",
  caption: "#A3A3A3",
  reference: "#78716C",
  figure: "#14B8A6",
  chart: "#8B5CF6",
  table: "#F59E0B",
  metric: "#F97316",
  code: "#0F766E",
  formula: "#EC4899",
  process: "#22C55E",
  question: "#C026D3",
  timeline: "#06B6D4",
});

const FALLBACK_COLOR = "#64748B";
const FONT_FAMILY_LABEL = "Arial, Microsoft YaHei, sans-serif";
const FONT_FAMILY_META = "Arial, sans-serif";

function escapeXml(text) {
  return String(text).replace(/&/gu, "&amp;").replace(/</gu, "&lt;").replace(/>/gu, "&gt;");
}

/**
 * Fixed-point formatting with correct decimal rounding of the exact double and ties to even.
 * `toFixed` rounds ties away from zero, which does not match the shipped previews.
 */
export function fixed(value, digits) {
  const n = Number(value);
  if (!Number.isFinite(n)) throw new Error(`non-finite preview coordinate: ${value}`);
  const sign = n < 0 ? "-" : "";
  const [intPart, fracPart = ""] = Math.abs(n).toFixed(20).split(".");
  const keep = fracPart.slice(0, digits).padEnd(digits, "0");
  const rest = fracPart.slice(digits);
  let bump = false;
  if (rest[0] > "5") bump = true;
  else if (rest[0] === "5") {
    const tie = !/[1-9]/u.test(rest.slice(1));
    if (!tie || Number(keep[digits - 1]) % 2 !== 0) bump = true;
  }
  if (!bump) return `${sign}${intPart}.${keep}`;
  const incremented = (BigInt(intPart + keep) + 1n).toString().padStart(digits + 1, "0");
  const intNext = incremented.slice(0, incremented.length - digits) || "0";
  const fracNext = incremented.slice(incremented.length - digits);
  return `${sign}${intNext}.${fracNext}`;
}

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

/** Render one layout to its preview SVG document. */
export function renderLayoutPreview(layout) {
  const parts = [];
  parts.push(
    '<svg xmlns="http://www.w3.org/2000/svg" width="960" height="540" viewBox="0 0 960 540">',
    '<rect width="960" height="540" fill="#F8FAFC"/>',
    '<rect x="18" y="18" width="924" height="504" rx="14" fill="#FFFFFF" stroke="#D8E0E8" stroke-width="2"/>',
  );
  const caption = `${layout.id} · ${layout.category_zh} · ${layout.variant_name_zh}`;
  parts.push(
    `<text x="34" y="510" font-family="${FONT_FAMILY_META}" font-size="12" fill="#94A3B8">${escapeXml(caption)}</text>`,
  );

  for (const slot of Array.isArray(layout.slots) ? layout.slots : []) {
    const box = slot.box;
    const color = SLOT_TYPE_COLORS[slot.type] ?? FALLBACK_COLOR;
    const x = CANVAS.inset + box.x * CANVAS.frameW;
    const y = CANVAS.inset + box.y * CANVAS.frameH;
    const w = box.w * CANVAS.frameW;
    const h = box.h * CANVAS.frameH;
    const fontSize = clamp(Math.min(HEIGHT_RATIO * h, WIDTH_RATIO * w), FONT_MIN, FONT_MAX);
    const optional = slot.optional === true;
    // A declared overlay is a slot stacked on top of the slot that contains it. It needs to read
    // as "elevated" rather than as a stray box inside another one, so it gets a heavier outline
    // and a denser fill. `optional` still drives the dash pattern; the two are independent.
    const overlay = slot.overlay === true;
    const opacity = overlay ? "0.30" : optional ? "0.16" : "0.22";
    const dash = optional ? ' stroke-dasharray="6 5"' : "";
    const strokeWidth = overlay ? "2.5" : "1.5";
    parts.push(
      `<rect x="${fixed(x, 1)}" y="${fixed(y, 1)}" width="${fixed(w, 1)}" height="${fixed(h, 1)}" rx="8" ` +
        `fill="${color}" fill-opacity="${opacity}" stroke="${color}" stroke-width="${strokeWidth}"${dash}/>`,
    );
    const labelBaseline = Math.min(y + BASELINE_OFFSET + fontSize, y + h - BASELINE_BOTTOM_MARGIN);
    parts.push(
      `<text x="${fixed(x + CANVAS.pad, 1)}" y="${fixed(labelBaseline, 1)}" font-family="${FONT_FAMILY_LABEL}" ` +
        `font-size="${fixed(fontSize, 1)}" font-weight="600" fill="${color}">${escapeXml(slot.label_zh)}</text>`,
    );
    const subFontSize = clamp(fontSize * SUB_FONT_RATIO, SUB_FONT_MIN, SUB_FONT_MAX);
    if (SUB_BASELINE_OFFSET + 2 * fontSize + subFontSize <= h) {
      parts.push(
        `<text x="${fixed(x + CANVAS.pad, 1)}" y="${fixed(y + SUB_BASELINE_OFFSET + 2 * fontSize, 1)}" ` +
          `font-family="${FONT_FAMILY_META}" font-size="${fixed(subFontSize, 1)}" fill="${color}" opacity="0.8">` +
          `${slot.type} · p${slot.priority}</text>`,
      );
    }
  }
  parts.push("</svg>");
  return parts.join("");
}

export function generatePreviews(payload) {
  const layouts = Array.isArray(payload?.layouts) ? payload.layouts : [];
  return new Map(layouts.map((layout) => [layout.id, renderLayoutPreview(layout)]));
}

function main() {
  const check = process.argv.includes("--check");
  const asJson = process.argv.includes("--json");
  const payload = JSON.parse(fs.readFileSync(LAYOUTS_PATH, "utf8"));
  const previews = generatePreviews(payload);
  const stale = [];
  const missing = [];

  for (const [id, svg] of previews) {
    const target = path.join(SVG_DIR, `${id}.svg`);
    const current = fs.existsSync(target) ? fs.readFileSync(target, "utf8") : null;
    if (current === null) missing.push(id);
    if (current !== svg) stale.push(id);
    if (!check && current !== svg) fs.writeFileSync(target, svg, "utf8");
  }

  const summary = { generator_version: PREVIEW_GENERATOR_VERSION, layout_count: previews.size, stale, missing };
  if (check && stale.length) {
    process.stderr.write(
      `Layout previews are stale: ${stale.length} of ${previews.size}${missing.length ? ` (${missing.length} missing)` : ""}.\n`,
    );
    if (asJson) process.stderr.write(`${JSON.stringify(summary)}\n`);
    process.exitCode = 1;
    return;
  }
  if (asJson) {
    process.stdout.write(`${JSON.stringify(summary)}\n`);
    return;
  }
  process.stdout.write(
    check
      ? `Layout previews are in sync (${previews.size} files).\n`
      : `Regenerated ${stale.length} of ${previews.size} layout previews.\n`,
  );
}

if (process.argv[1] && path.resolve(process.argv[1]) === path.resolve(fileURLToPath(import.meta.url))) main();
