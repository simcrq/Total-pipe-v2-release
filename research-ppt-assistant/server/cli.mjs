#!/usr/bin/env node

import fs from "node:fs/promises";
import { assertSupportedNodeVersion } from "./runtime.mjs";
import { runBenchmark } from "./benchmark.mjs";
import { normalizeContentModel } from "./content-model.mjs";
import {
  catalogSummary,
  createDeckPlan,
  getLayout,
  runPreflight,
  searchLayouts,
  validateDeckPlan,
  validateRendererInputs,
  validateRenderedDeck,
  validateRenderedSlide,
  validateSlide,
} from "./core.mjs";
import { auditBundledLayoutLibrary } from "./layout-audit.mjs";
import { formatStructuredContent, normalizeDetailLevel } from "./response-format.mjs";
import { evaluateVisualQuality } from "./visual-quality/index.mjs";
import { SUPPORTED_RENDER_TELEMETRY_VERSIONS } from "./visual-quality/contracts.mjs";
import { runFigurePlacement } from "./figure-placement.mjs";
import { runVisualFitPreflight } from "./visual-fit/index.mjs";
import { runGroupFitPreflight } from "./group-fit/index.mjs";
import { adaptRendererTelemetry } from "./renderer-adapters/index.mjs";
import { assembleRenderTelemetry } from "./render-telemetry-assembly.mjs";

assertSupportedNodeVersion();

const BOOLEAN_OPTION_KEYS = new Set([
  "allow_auto_split",
  "include_performance",
  "include_slots",
  "intentional_whitespace",
  "live_watch_requested",
  "project_exists",
  "title_wrap_allowed",
]);

function parseBooleanOption(key, value) {
  if (typeof value === "boolean") return value;
  const normalized = String(value).trim().toLowerCase();
  if (["true", "1", "yes"].includes(normalized)) return true;
  if (["false", "0", "no"].includes(normalized)) return false;
  throw new TypeError(`--${key.replaceAll("_", "-")} expects true/false, 1/0, or yes/no; received ${value}`);
}

function parseArgs(argv) {
  const positionals = [];
  const options = {};
  for (let index = 0; index < argv.length; index += 1) {
    const token = argv[index];
    if (!token.startsWith("--")) {
      positionals.push(token);
      continue;
    }
    const key = token.slice(2).replaceAll("-", "_");
    const next = argv[index + 1];
    if (next === undefined || next.startsWith("--")) options[key] = true;
    else {
      options[key] = next;
      index += 1;
    }
  }
  return { positionals, options };
}

function typedOptions(options) {
  const result = { ...options };
  for (const key of ["text_chars", "title_chars", "image_count", "table_count", "chart_count", "process_step_count", "visual_aspect_ratio", "slide_count", "max_replan_attempts", "iterations", "k", "title_font_pt", "title_line_count", "content_occupancy", "largest_empty_band", "content_center_x", "content_center_y"]) {
    if (result[key] !== undefined) result[key] = Number(result[key]);
  }
  if (typeof result.content_roles === "string") result.content_roles = result.content_roles.split(",").map((item) => item.trim()).filter(Boolean);
  if (typeof result.categories === "string") result.categories = result.categories.split(",").map((item) => item.trim()).filter(Boolean);
  if (typeof result.exclude_ids === "string") result.exclude_ids = result.exclude_ids.split(",").map((item) => item.trim()).filter(Boolean);
  for (const key of BOOLEAN_OPTION_KEYS) {
    if (result[key] !== undefined) result[key] = parseBooleanOption(key, result[key]);
  }
  return result;
}

async function readInput(options) {
  if (options.file) return JSON.parse(await fs.readFile(options.file, "utf8"));
  if (options.json) return JSON.parse(options.json);
  return typedOptions(options);
}

function help() {
  return `Research PPT Assistant CLI

Usage:
  node server/cli.mjs summary
  node server/cli.mjs audit-layouts
  node server/cli.mjs benchmark --iterations 20
  node server/cli.mjs search --text-chars 80 --image-count 2 --k 5 --include-slots
  node server/cli.mjs get RM-DUAL_FIGURE-01 --theme-id paper_blue
  node server/cli.mjs normalize-content --file content-model-input.json
  node server/cli.mjs plan --presentation-type group_meeting --slide-count 12 --topic "研究进展"
  node server/cli.mjs plan --presentation-type group_meeting --allow-auto-split false --max-replan-attempts 3
  node server/cli.mjs validate-slide --layout-id RM-DUAL_FIGURE-01 --text-chars 80 --image-count 2
  node server/cli.mjs validate-deck --file deck-plan.json
  node server/cli.mjs preflight --file preflight-input.json
  node server/cli.mjs validate-renderer --file renderer-inputs.json
  node server/cli.mjs visual-fit-preflight --file visual-fit-input.json
  node server/cli.mjs group-fit-preflight --file group-fit-input.json
  node server/cli.mjs figure-placement --file figure-placement-input.json
  node server/cli.mjs assemble-render-telemetry --file render-evidence-sidecar.json
  node server/cli.mjs visual-quality --file render-telemetry.json
  node server/cli.mjs validate-rendered-slide --file rendered-slide.json
  node server/cli.mjs validate-rendered-deck --file rendered-deck.json

Boolean options accept true/false, 1/0, or yes/no. Bare flags mean true.
Use --detail-level compact|standard|full; CLI defaults to standard.
Use --json '<object>' or --file input.json for structured inputs.`;
}

const COMMAND_TOOL_NAMES = {
  summary: "catalog_summary",
  "audit-layouts": "audit_layout_library",
  benchmark: "run_benchmark",
  search: "search_layouts",
  get: "get_layout",
  "normalize-content": "normalize_content",
  plan: "create_deck_plan",
  "validate-slide": "validate_slide",
  "validate-deck": "validate_deck_plan",
  preflight: "run_preflight",
  "validate-renderer": "validate_renderer_inputs",
  "visual-fit-preflight": "run_visual_fit_preflight",
  "group-fit-preflight": "run_group_fit_preflight",
  "figure-placement": "run_figure_placement",
  "assemble-render-telemetry": "assemble_render_telemetry",
  "visual-quality": "evaluate_visual_quality",
  "validate-rendered-slide": "validate_rendered_slide",
  "validate-rendered-deck": "validate_rendered_deck",
};

async function main() {
  const { positionals, options } = parseArgs(process.argv.slice(2));
  const command = positionals[0] ?? "help";
  const detailLevel = normalizeDetailLevel(options.detail_level, "standard");
  const commandOptions = { ...options };
  delete commandOptions.detail_level;
  let result;
  switch (command) {
    case "summary":
      result = await catalogSummary();
      break;
    case "audit-layouts":
      result = await auditBundledLayoutLibrary();
      break;
    case "benchmark":
      result = await runBenchmark(await readInput(commandOptions));
      break;
    case "search":
      result = await searchLayouts(await readInput(commandOptions));
      break;
    case "get":
      result = await getLayout(positionals[1] ?? commandOptions.layout_id, commandOptions.theme_id, commandOptions.viewing_mode);
      break;
    case "normalize-content":
      result = normalizeContentModel(await readInput(commandOptions));
      break;
    case "plan":
      result = await createDeckPlan(await readInput(commandOptions));
      break;
    case "validate-slide":
      result = await validateSlide(await readInput(commandOptions));
      break;
    case "validate-deck":
      result = await validateDeckPlan(await readInput(commandOptions));
      break;
    case "preflight":
      result = await runPreflight(await readInput(commandOptions));
      break;
    case "validate-renderer":
      result = validateRendererInputs(await readInput(commandOptions));
      break;
    case "visual-fit-preflight":
      result = runVisualFitPreflight(await readInput(commandOptions));
      break;
    case "group-fit-preflight":
      result = runGroupFitPreflight(await readInput(commandOptions));
      break;
    case "figure-placement":
      result = runFigurePlacement(await readInput(commandOptions));
      break;
    case "assemble-render-telemetry":
      result = assembleRenderTelemetry(await readInput(commandOptions));
      break;
    case "visual-quality": {
      const visualInput = await readInput(commandOptions);
      const isCanonicalTelemetry = visualInput
        && typeof visualInput === "object"
        && SUPPORTED_RENDER_TELEMETRY_VERSIONS.includes(visualInput.telemetry_version)
        && typeof visualInput.slide_id === "string"
        && typeof visualInput.renderer === "string"
        && visualInput.slide && typeof visualInput.slide === "object"
        && Array.isArray(visualInput.elements)
        && Array.isArray(visualInput.unavailable)
        && visualInput.provided_metrics && typeof visualInput.provided_metrics === "object";
      const telemetry = visualInput.telemetry
        ?? (visualInput.renderer_output ? adaptRendererTelemetry(visualInput.renderer_output) : isCanonicalTelemetry ? visualInput : adaptRendererTelemetry(visualInput));
      result = await evaluateVisualQuality({ ...visualInput, telemetry });
      break;
    }
    case "validate-rendered-slide":
      result = await validateRenderedSlide(await readInput(commandOptions));
      break;
    case "validate-rendered-deck":
      result = await validateRenderedDeck(await readInput(commandOptions));
      break;
    case "help":
    case "--help":
    case "-h":
      process.stdout.write(`${help()}\n`);
      return;
    default:
      throw new RangeError(`Unknown command: ${command}\n\n${help()}`);
  }
  process.stdout.write(`${JSON.stringify(formatStructuredContent(COMMAND_TOOL_NAMES[command], result, detailLevel), null, 2)}\n`);
}

main().catch((error) => {
  process.stderr.write(`${error.name}: ${error.message}\n`);
  process.exitCode = 1;
});
