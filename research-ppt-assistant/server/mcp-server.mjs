#!/usr/bin/env node

import readline from "node:readline";
import { assertSupportedNodeVersion } from "./runtime.mjs";
import { runBenchmark } from "./benchmark.mjs";
import {
  CONTENT_MODEL_INPUT_SCHEMA,
  SLIDE_BRIEF_SCHEMA,
  VISUAL_SOURCE_DIMENSIONS_SCHEMA,
  normalizeContentModel,
} from "./content-model.mjs";
import {
  catalogSummary,
  createDeckPlan,
  getLayout,
  readPreview,
  runPreflight,
  searchLayouts,
  validateDeckPlan,
  validateRendererInputs,
  validateRenderedDeck,
  validateRenderedSlide,
  validateSlide,
} from "./core.mjs";
import { auditBundledLayoutLibrary } from "./layout-audit.mjs";
import { formatStructuredContent, normalizeDetailLevel, summarizeToolResult } from "./response-format.mjs";
import { assertJsonSchema } from "./schema-validator.mjs";
import { evaluateVisualQuality, RENDER_TELEMETRY_SCHEMA } from "./visual-quality/index.mjs";
import { adaptRendererTelemetry } from "./renderer-adapters/index.mjs";
import { assembleRenderTelemetry } from "./render-telemetry-assembly.mjs";
import { runFigurePlacement } from "./figure-placement.mjs";
import { runVisualFitPreflight } from "./visual-fit/index.mjs";
import { GROUP_FIT_INPUT_SCHEMA, runGroupFitPreflight } from "./group-fit/index.mjs";

assertSupportedNodeVersion();

const SERVER_INFO = { name: "research-ppt-assistant", version: "0.6.3-rc1" };
const SUPPORTED_PROTOCOLS = new Set(["2024-11-05", "2025-03-26", "2025-06-18"]);

const readOnlyAnnotations = {
  readOnlyHint: true,
  destructiveHint: false,
  idempotentHint: true,
  openWorldHint: false,
};

const nonNegativeInteger = { type: "integer", minimum: 0 };
const visualSchema = {
  type: "object",
  properties: {
    slot_id: { type: "string" },
    visual_type: {
      enum: ["photo", "schematic", "simple_plot", "dense_plot", "multi_panel_figure", "composite_figure_region", "table_screenshot", "microscopy", "visual_evidence"],
    },
    panel_count: { type: "integer", minimum: 1, maximum: 100, default: 1 },
    has_embedded_text: { type: "boolean", default: false },
    min_display_width: { type: "number", minimum: 0.1, maximum: 1 },
    display_width_norm: { type: "number", minimum: 0, maximum: 1 },
    display_height_norm: { type: "number", minimum: 0, maximum: 1 },
    rendered_embedded_text_px: { type: "number", minimum: 0 },
    visual_aspect_ratio: { type: "number", exclusiveMinimum: 0 },
    embedded_text_density: { type: "number", minimum: 0, maximum: 1 },
    caption_chars: { type: "integer", minimum: 0 },
    ...VISUAL_SOURCE_DIMENSIONS_SCHEMA,
    source_visual_id: { type: "string" },
    region_id: { type: "string" },
    semantic_relation: { enum: ["parallel_evidence", "support", "causal", "comparison", "sequence"] },
  },
  required: ["visual_type"],
  additionalProperties: false,
};

const manifestBoxSchema = {
  type: "object",
  properties: {
    x: { type: "number" }, y: { type: "number" },
    width: { type: "number", exclusiveMinimum: 0 }, height: { type: "number", exclusiveMinimum: 0 },
  },
  required: ["x", "y", "width", "height"],
  additionalProperties: false,
};

const visualManifestEntrySchema = {
  type: "object",
  properties: {
    visual_key: { type: "string", pattern: "^[A-Za-z0-9][A-Za-z0-9._-]*$" },
    slide_id: { type: "string", minLength: 1 },
    source_visual_id: { type: "string", minLength: 1 },
    region_id: { type: "string", minLength: 1 },
    visual_type: { type: "string", minLength: 1 },
    panel_count: { type: "integer", minimum: 1 },
    has_embedded_text: { type: "boolean" },
    source_width_px: { type: "integer", minimum: 1 },
    source_height_px: { type: "integer", minimum: 1 },
    asset_width_px: { type: "integer", minimum: 1 },
    asset_height_px: { type: "integer", minimum: 1 },
    source_region: manifestBoxSchema,
    parent_source_region: manifestBoxSchema,
    coordinate_space: { enum: ["normalized", "source_normalized_0_1", "source_pixels"] },
    parent_coordinate_space: { enum: ["normalized", "source_normalized_0_1", "source_pixels"] },
    parent_source_width_px: { type: "integer", minimum: 1 },
    parent_source_height_px: { type: "integer", minimum: 1 },
    slot_id: { type: "string", minLength: 1 },
    container_id: { type: "string", minLength: 1 },
    asset_sha256: { type: "string", pattern: "^(?:sha256:)?[A-Fa-f0-9]{64}$" },
    parent_asset_sha256: { type: "string", pattern: "^(?:sha256:)?[A-Fa-f0-9]{64}$" },
    derived_asset_sha256: { type: "string", pattern: "^(?:sha256:)?[A-Fa-f0-9]{64}$" },
    crop_mode: { enum: ["full_figure", "preprocessed_fixed_region"] },
    group_id: { type: "string", minLength: 1 },
    sibling_index: { type: "integer", minimum: 0 },
    min_display_width: { type: "number", minimum: 0, maximum: 1 },
    rendered_embedded_text_px: { type: "number", minimum: 0 },
    visible_label_ids: { type: "array", items: { type: "string" }, uniqueItems: true },
    raster_text_measurement: {
      type: "object",
      properties: {
        status: { enum: ["measured", "not_measured", "failed"] },
        min_height_px: { type: "number", minimum: 0 },
        reason: { type: "string" },
      },
      required: ["status"],
      additionalProperties: false,
    },
    semantic: {
      type: "object",
      properties: {
        description: { type: "string" },
        slide_id: { type: "string", minLength: 1 },
        slot_id: { type: "string", minLength: 1 },
        container_id: { type: "string", minLength: 1 },
        group_id: { type: ["string", "null"] },
        sibling_index: { type: ["integer", "null"], minimum: 0 },
      },
      additionalProperties: false,
    },
    source: {
      type: "object",
      properties: {
        source_visual_id: { type: "string", minLength: 1 },
        region_id: { type: "string", minLength: 1 },
        visual_type: { type: "string", minLength: 1 },
        panel_count: { type: "integer", minimum: 1 },
        has_embedded_text: { type: "boolean" },
        source_width_px: { type: "integer", minimum: 1 },
        source_height_px: { type: "integer", minimum: 1 },
        source_region: manifestBoxSchema,
        coordinate_space: { enum: ["normalized", "source_normalized_0_1", "source_pixels"] },
        asset_sha256: { type: "string", pattern: "^(?:sha256:)?[A-Fa-f0-9]{64}$" },
        crop_mode: { enum: ["full_figure", "preprocessed_fixed_region"] },
        parent_asset_sha256: { type: "string", pattern: "^(?:sha256:)?[A-Fa-f0-9]{64}$" },
        parent_source_region: manifestBoxSchema,
        parent_coordinate_space: { enum: ["normalized", "source_normalized_0_1", "source_pixels"] },
        parent_source_width_px: { type: "integer", minimum: 1 },
        parent_source_height_px: { type: "integer", minimum: 1 },
        derived_asset_sha256: { type: "string", pattern: "^(?:sha256:)?[A-Fa-f0-9]{64}$" },
      },
      additionalProperties: false,
    },
  },
  required: ["visual_key"],
  additionalProperties: false,
};

const visualManifestContainerSchema = {
  type: "object",
  properties: {
    container_id: { type: "string", minLength: 1 },
    shape_name: { type: "string", minLength: 1 },
    role: { enum: ["image_only", "image_caption", "image_annotation", "workflow_region", "comparison_region", "decorative_exhibit"] },
    fit_policy: { enum: ["contain", "cover"] },
    crop_policy: { enum: ["full_figure", "semantic_crop_allowed", "fixed_region"] },
    whitespace_policy: { enum: ["minimal", "intentional", "reserved"] },
    mismatch_policy: { enum: ["replan", "resolve_region", "resize_container", "allow_whitespace", "change_fit_policy"] },
    max_letterbox_ratio: { type: "number", minimum: 0, maximum: 1 },
    content_inset: {
      type: "object",
      properties: {
        left: { type: "number", minimum: 0 }, right: { type: "number", minimum: 0 },
        top: { type: "number", minimum: 0 }, bottom: { type: "number", minimum: 0 },
      },
      required: ["left", "right", "top", "bottom"],
      additionalProperties: false,
    },
  },
  required: ["container_id", "shape_name", "role", "fit_policy", "crop_policy", "whitespace_policy", "mismatch_policy"],
  additionalProperties: false,
};

const visualManifestSchema = {
  type: "object",
  properties: {
    manifest_schema_version: { type: "string" },
    producer_version: { type: "string" },
    deck_id: { type: "string" },
    manifest_version: { type: "string" },
    visuals: { type: "array", items: visualManifestEntrySchema },
    containers: { type: "array", items: visualManifestContainerSchema },
    element_annotations: {
      type: "array",
      items: {
        type: "object",
        properties: {
          shape_name: { type: "string", minLength: 1 },
          quality_role: { enum: ["content", "decoration", "background", "ignore"] },
          relation: {
            type: "object",
            properties: {
              type: { enum: ["title_rule", "container_border", "flow_connector", "annotation", "decorative_peer", "baseline_preserved"] },
              target_shape_name: { type: "string", minLength: 1 },
            },
            required: ["type", "target_shape_name"],
            additionalProperties: false,
          },
        },
        required: ["shape_name", "quality_role"],
        additionalProperties: false,
      },
    },
    visual_groups: {
      type: "array",
      items: {
        type: "object",
        properties: {
          group_id: { type: "string", minLength: 1 },
          relation_type: { enum: ["parallel_siblings", "composite_split", "support", "causal", "comparison", "sequence"] },
          expected_sibling_count: { type: "integer", minimum: 1 },
          reading_order: { type: "array", items: { type: "string", minLength: 1 }, uniqueItems: true },
          shared_baseline: { enum: ["none", "top", "center", "bottom"] },
          baseline_tolerance: { type: "number", minimum: 0, maximum: 1 },
          require_unique_containers: { type: "boolean" },
          require_unique_assets: { type: "boolean" },
          shared_parent_asset_sha256: { type: "string", pattern: "^(?:sha256:)?[A-Fa-f0-9]{64}$" },
        },
        required: ["group_id", "relation_type", "expected_sibling_count", "reading_order", "shared_baseline", "baseline_tolerance"],
        additionalProperties: false,
      },
    },
  },
  required: ["visuals", "containers"],
  additionalProperties: false,
};

const slotMetricSchema = {
  type: "object",
  properties: {
    slot_id: { type: "string" },
    role: { type: "string" },
    text_chars: { ...nonNegativeInteger },
    font_pt: { type: "number", exclusiveMinimum: 0 },
    line_count: { ...nonNegativeInteger },
    intended_single_line: { type: "boolean" },
  },
  required: ["slot_id"],
  additionalProperties: false,
};

const slotSpecSchema = {
  type: "object",
  properties: {
    slot_id: { type: "string" },
    slot_type: { type: "string" },
    required: { type: "boolean" },
    capacity: {
      type: "object",
      properties: {
        max_chars: { type: ["integer", "null"], minimum: 0 },
        max_chars_at_absolute_min: { type: ["integer", "null"], minimum: 0 },
        max_lines: { type: ["integer", "null"], minimum: 1 },
        font_pt_hint: { type: ["number", "null"], exclusiveMinimum: 0 },
        min_font_pt: { type: ["number", "null"], exclusiveMinimum: 0 },
        absolute_min_font_pt: { type: ["number", "null"], exclusiveMinimum: 0 },
      },
      required: ["max_chars"],
      additionalProperties: false,
    },
    label_zh: { type: "string" },
    priority: { type: "integer", minimum: 1, maximum: 5 },
    collapse_when_empty: { type: "boolean" },
    box: { type: "object" },
    pptx_in: { type: "object" },
  },
  required: ["slot_id", "slot_type", "required", "capacity"],
  additionalProperties: false,
};

const slotAssignmentSchema = {
  type: "object",
  properties: {
    type: { type: "string", description: "text, image, chart, table, process, timeline, or explicit guidance." },
    text: { type: "string" },
    content: {},
    value: {},
    asset: {},
    asset_uri: { type: "string" },
    data: {},
    steps: { type: "array" },
    items: { type: "array" },
    rows: { type: "array" },
    series: { type: "array" },
    events: { type: "array" },
  },
  required: ["type"],
  additionalProperties: true,
};

const contentMetricsProperties = {
  text_chars: { ...nonNegativeInteger, description: "Visible body-text character count, excluding the slide title." },
  text_chars_by_role: {
    type: "object",
    additionalProperties: { ...nonNegativeInteger },
    description: "Optional per-role character counts; their sum is used when text_chars is omitted.",
  },
  title_chars: { ...nonNegativeInteger, description: "Visible slide-title character count, used to prevent title wrapping at the font floor." },
  image_count: { ...nonNegativeInteger, description: "Number of figures or ordinary images." },
  table_count: { ...nonNegativeInteger, description: "Number of tables." },
  chart_count: { ...nonNegativeInteger, description: "Number of native plots or charts." },
  process_step_count: { ...nonNegativeInteger, description: "Number of distinct process or workflow steps." },
  visual_aspect_ratio: { type: "number", exclusiveMinimum: 0, description: "Dominant visual width divided by height." },
  visual_safety_margin: { type: "number", minimum: 0, maximum: 0.5, default: 0.1, description: "Safety margin added to minimum scientific-visual size during layout retrieval." },
  viewing_mode: { enum: ["projector", "desktop", "handout"], default: "projector", description: "Viewing-distance typography and whitespace profile." },
  density_preference: { enum: ["spacious", "balanced", "dense", "低", "中", "高"], description: "Desired information-density prior." },
  allow_auto_split: { type: "boolean", default: true, description: "Allow the planner to recommend splitting slides that cannot meet readability thresholds." },
  slot_metrics: { type: "array", items: slotMetricSchema, description: "Optional per-slot text counts, actual font sizes, and rendered line counts." },
  visuals: { type: "array", items: visualSchema, description: "Scientific visual complexity, panel count, embedded-text, and display-size metadata." },
  content_roles: {
    type: "array",
    items: { type: "string" },
    description: "Semantic roles such as headline, primary_visual, table, process, timeline, takeaway, or question.",
  },
};

const slideBriefInputSchema = {
  type: "object",
  properties: SLIDE_BRIEF_SCHEMA.properties,
  required: ["title"],
  additionalProperties: false,
};

const deckPlanValidationInputSchema = {
  type: "object",
  properties: {
    theme_id: { type: "string" },
    content_model: {
      type: "object",
      additionalProperties: true,
      description: "Optional normalized content model (normalize_content output). When provided, validate_deck_plan cross-checks each slide's declared metrics against the matching slide brief and reports metric_provenance / cross_check_divergences.",
    },
    slides: {
      type: "array",
      minItems: 1,
      maxItems: 80,
      items: {
        type: "object",
        properties: {
          layout_id: { type: "string" },
          slot_specs: { type: "array", items: slotSpecSchema },
          content_metrics: { type: "object", properties: contentMetricsProperties, additionalProperties: false },
          slot_assignments: { type: "object", additionalProperties: slotAssignmentSchema },
          ...contentMetricsProperties,
        },
        required: ["layout_id"],
        additionalProperties: true,
      },
    },
  },
  required: ["slides"],
  additionalProperties: false,
};

const rendererInputsSchema = {
  type: "object",
  properties: {
    renderer: { enum: ["slidep", "tencent-pptx"], description: "Legacy input alias. Prefer requested_renderer; when both are present they must match." },
    requested_renderer: { enum: ["slidep", "tencent-pptx"], default: "slidep", description: "Canonical requested renderer field; tencent-pptx currently executes through effective_renderer=slidep." },
    renderer_version: { type: "string", description: "Installed renderer version, for example 5.4.4." },
    platform: { enum: ["win32", "windows", "linux", "darwin"], description: "Renderer host platform; defaults to the MCP server platform." },
    project_path: { type: "string", description: "Project path passed to the renderer. On Windows use a drive-letter absolute path, not /f/... MSYS syntax." },
    project_exists: { type: "boolean", description: "Optional result of a caller-side directory existence check." },
    source_files: {
      type: "array",
      minItems: 1,
      items: { type: "string" },
      description: "Page source paths intended for the slides directory. Canonical slidep pages use XX_slug.slide only.",
    },
    live_watch_requested: { type: "boolean", default: false },
  },
  required: ["project_path", "source_files"],
  additionalProperties: false,
};

const placementBoxSchema = {
  type: "object",
  properties: {
    x: { type: "number" },
    y: { type: "number" },
    width: { type: "number", exclusiveMinimum: 0 },
    height: { type: "number", exclusiveMinimum: 0 },
  },
  required: ["x", "y", "width", "height"],
  additionalProperties: false,
};

const visualContainerInputSchema = {
  type: "object",
  properties: {
    container_id: { type: "string", minLength: 1 },
    role: { enum: ["image_only", "image_caption", "image_annotation", "workflow_region", "comparison_region", "decorative_exhibit"] },
    outer_bbox: placementBoxSchema,
    content_bbox: placementBoxSchema,
    content_inset: {
      type: "object",
      properties: { left: { type: "number", minimum: 0 }, right: { type: "number", minimum: 0 }, top: { type: "number", minimum: 0 }, bottom: { type: "number", minimum: 0 } },
      required: ["left", "right", "top", "bottom"],
      additionalProperties: false,
    },
    child_visual_ids: { type: "array", minItems: 1, uniqueItems: true, items: { type: "string", minLength: 1 } },
    fit_policy: { enum: ["contain", "cover"] },
    crop_policy: { enum: ["full_figure", "semantic_crop_allowed", "fixed_region"] },
    whitespace_policy: { enum: ["minimal", "intentional", "reserved"] },
    mismatch_policy: { enum: ["replan", "resolve_region", "resize_container", "allow_whitespace", "change_fit_policy"] },
  },
  required: ["container_id", "role", "outer_bbox", "content_bbox", "content_inset", "child_visual_ids", "fit_policy", "crop_policy", "whitespace_policy", "mismatch_policy"],
  additionalProperties: false,
};

const visualFitIntentSchema = {
  type: "object",
  properties: {
    visual_type: { type: "string" },
    crop_policy: { enum: ["full_figure", "semantic_crop_allowed", "fixed_region"] },
    fit_policy: { enum: ["contain", "cover"] },
    semantic_crop_allowed: { type: "boolean" },
    whitespace_policy: { enum: ["minimal", "intentional", "reserved"] },
    priority: { type: "string" },
  },
  required: ["visual_type", "crop_policy", "fit_policy", "whitespace_policy"],
  additionalProperties: false,
};

const visualFitPreflightInputSchema = {
  type: "object",
  properties: {
    visual_id: { type: "string", minLength: 1 },
    source: {
      type: "object",
      properties: { width: { type: "number", exclusiveMinimum: 0 }, height: { type: "number", exclusiveMinimum: 0 } },
      required: ["width", "height"],
      additionalProperties: false,
    },
    source_region: placementBoxSchema,
    visual_intent: visualFitIntentSchema,
    allocated_visual_bbox: placementBoxSchema,
    visual_container: visualContainerInputSchema,
  },
  required: ["visual_id", "source", "visual_intent", "allocated_visual_bbox", "visual_container"],
  additionalProperties: false,
};

const sourceRegionSchema = {
  ...placementBoxSchema,
  properties: {
    x: { type: "number", minimum: 0, maximum: 1 },
    y: { type: "number", minimum: 0, maximum: 1 },
    width: { type: "number", exclusiveMinimum: 0, maximum: 1 },
    height: { type: "number", exclusiveMinimum: 0, maximum: 1 },
  },
};

const figurePlacementInputSchema = {
  type: "object",
  properties: {
    trace_id: { type: "string", minLength: 1 },
    visual: {
      type: "object",
      properties: {
        id: { type: "string" },
        figure_id: { type: "string" },
        source_width_px: { type: "integer", minimum: 1 },
        source_height_px: { type: "integer", minimum: 1 },
        visual_intent: {
          type: "object",
          properties: {
            purpose: { type: "string" },
            selection: {
              type: "object",
              properties: { strategy: { enum: ["full_figure", "semantic_focus", "panel", "multi_panel", "auto"] }, target: { type: "string" } },
              required: ["strategy"],
              additionalProperties: false,
            },
            crop: { type: "object", properties: { mode: { type: "string" }, focus: { type: "string" }, preserve_labels: { type: "boolean" } }, additionalProperties: false },
            placement: {
              type: "object",
              properties: { desired_prominence: { type: "string" }, preferred_fit: { enum: ["contain", "cover", "maximize", "auto"] }, allow_cover: { type: "boolean" } },
              additionalProperties: false,
            },
            visual_type: { type: "string" },
            crop_policy: { enum: ["full_figure", "semantic_crop_allowed", "fixed_region"] },
            fit_policy: { enum: ["contain", "cover"] },
            semantic_crop_allowed: { type: "boolean" },
            whitespace_policy: { enum: ["minimal", "intentional", "reserved"] },
            priority: { type: "string" },
          },
          required: ["selection"],
          additionalProperties: false,
        },
        recommended_crop: {
          type: "object",
          properties: { region_id: { type: "string" }, focus: { type: "string" }, roi: sourceRegionSchema, confidence: { type: "number", minimum: 0, maximum: 1 } },
          additionalProperties: false,
        },
        crop_candidate: {
          type: "object",
          properties: { ...sourceRegionSchema.properties, region_id: { type: "string" }, coordinate_space: { enum: ["normalized", "source_pixels"] }, confidence: { type: "number", minimum: 0, maximum: 1 } },
          required: sourceRegionSchema.required,
          additionalProperties: false,
        },
        region_candidates: {
          type: "array",
          items: {
            type: "object",
            properties: { region_id: { type: "string" }, aliases: { type: "array", items: { type: "string" } }, roi: { ...sourceRegionSchema, properties: { ...sourceRegionSchema.properties, coordinate_space: { enum: ["normalized", "source_pixels"] } } }, confidence: { type: "number", minimum: 0, maximum: 1 } },
            required: ["region_id", "roi"],
            additionalProperties: false,
          },
        },
      },
      required: ["source_width_px", "source_height_px", "visual_intent"],
      additionalProperties: false,
    },
    allocated_visual_bbox: placementBoxSchema,
    visual_container: visualContainerInputSchema,
    exclusion_bboxes: { type: "array", items: placementBoxSchema },
    slide: {
      type: "object",
      properties: { width: { type: "number", exclusiveMinimum: 0 }, height: { type: "number", exclusiveMinimum: 0 }, render_width_px: { type: "integer", minimum: 1 }, render_height_px: { type: "integer", minimum: 1 } },
      required: ["width", "height", "render_width_px", "render_height_px"],
      additionalProperties: false,
    },
    policy: {
      type: "object",
      properties: {
        epsilon: { type: "number", minimum: 0 },
        padding: { type: "number", minimum: 0 },
        allow_crop: { type: "boolean" },
        max_letterbox_ratio: { type: "number", minimum: 0, maximum: 1 },
        minimum_effective_resolution: {
          type: "object",
          properties: { width_px: { type: "number", minimum: 1 }, height_px: { type: "number", minimum: 1 } },
          required: ["width_px", "height_px"],
          additionalProperties: false,
        },
      },
      additionalProperties: false,
    },
    expectations: {
      type: "object",
      properties: { excluded_region_ids: { type: "array", items: { type: "string" } }, expected_label_ids: { type: "array", items: { type: "string" } } },
      additionalProperties: false,
    },
    renderer_result: {
      type: "object",
      properties: {
        effective_placement: placementBoxSchema,
        effective_source_region: { ...sourceRegionSchema, properties: { ...sourceRegionSchema.properties, coordinate_space: { enum: ["normalized", "source_pixels"] } } },
        render_bbox_px: placementBoxSchema,
        visible_region_ids: { type: "array", items: { type: "string" } },
        visible_label_ids: { type: "array", items: { type: "string" } },
        source_region_coordinate_space: { enum: ["normalized", "source_normalized_0_1", "source_pixels"] },
      },
      additionalProperties: false,
    },
  },
  required: ["trace_id", "visual", "allocated_visual_bbox"],
  additionalProperties: false,
};

const rawTools = [
  {
    name: "catalog_summary",
    title: "Summarize research slide library",
    description: "List the 320-layout library's categories, themes, supported presentation types, and coordinate contract.",
    inputSchema: { type: "object", properties: {}, additionalProperties: false },
    annotations: readOnlyAnnotations,
  },
  {
    name: "audit_layout_library",
    title: "Audit the bundled layout library",
    description: "Run the CI-blocking static audit across all layouts, themes, normalized/PPTX geometry, reading order, schema contracts, and SVG previews.",
    inputSchema: { type: "object", properties: {}, additionalProperties: false },
    annotations: readOnlyAnnotations,
  },
  {
    name: "run_benchmark",
    title: "Run the stability benchmark",
    description: "Evaluate the bundled benchmark dataset and report Top-1/Top-K validity, replan, auto-split, contract, preflight, render-QA, determinism, and pure-logic P95 metrics.",
    inputSchema: {
      type: "object",
      properties: {
        iterations: { type: "integer", minimum: 1, maximum: 200, default: 20 },
        include_performance: { type: "boolean", default: true },
      },
      additionalProperties: false,
    },
    annotations: readOnlyAnnotations,
  },
  {
    name: "normalize_content",
    title: "Normalize evidence and slide briefs",
    description: "Normalize Sources, Citations, Evidence, and Slide Briefs deterministically. Accepts PaperWorkflow v4 objects without running OCR, selecting layouts, or assigning slots.",
    inputSchema: CONTENT_MODEL_INPUT_SCHEMA,
    annotations: readOnlyAnnotations,
  },
  {
    name: "search_layouts",
    title: "Search scientific slide layouts",
    description: "Rank layouts by text, image, table, chart, aspect-ratio, semantic-role, density, and genericity fit. Returns explainable scores and optional slot coordinates.",
    inputSchema: {
      type: "object",
      properties: {
        ...contentMetricsProperties,
        categories: { type: "array", items: { type: "string" }, description: "Optional category allowlist." },
        densities: { type: "array", items: { enum: ["低", "中", "高"] } },
        exclude_ids: { type: "array", items: { type: "string" }, description: "Layout IDs to exclude, useful for deck-level variety." },
        diversity: { enum: ["none", "category", "family"], default: "none" },
        include_slots: { type: "boolean", default: false, description: "Include normalized and PowerPoint-inch slot geometry; geometry is included only in standard or full responses." },
        k: { type: "integer", minimum: 1, maximum: 20, default: 5 },
      },
      additionalProperties: false,
    },
    annotations: readOnlyAnnotations,
  },
  {
    name: "get_layout",
    title: "Get an exact slide layout",
    description: "Return one layout's complete slot geometry, reading order, constraints, capacity, preview URI, and optional theme tokens.",
    inputSchema: {
      type: "object",
      properties: {
        layout_id: { type: "string", pattern: "^RM-[A-Z_]+-[0-9]{2}$" },
        theme_id: { type: "string" },
        viewing_mode: { enum: ["projector", "desktop", "handout"], default: "projector" },
      },
      required: ["layout_id"],
      additionalProperties: false,
    },
    annotations: readOnlyAnnotations,
  },
  {
    name: "create_deck_plan",
    title: "Plan a complete research presentation",
    description: "Compile SlideDesignIR, rank legal layout/treatment/decoration candidates with deck-rhythm penalties, bind content to exact slots, and close the planning loop through legal layout replanning or deterministic structural splitting. Use slide_briefs when real content is available; otherwise a scenario-specific blueprint is generated.",
    inputSchema: {
      type: "object",
      properties: {
        topic: { type: "string" },
        audience: { type: "string" },
        purpose: { type: "string" },
        presentation_type: {
          enum: ["group_meeting", "journal_club", "proposal", "progress_report", "defense", "paper_presentation", "custom"],
          default: "group_meeting",
        },
        slide_count: { type: "integer", minimum: 3, maximum: 40 },
        theme_id: { type: "string", default: "paper_blue" },
        viewing_mode: { enum: ["projector", "desktop", "handout"], default: "projector" },
        density_preference: { enum: ["spacious", "balanced", "dense", "低", "中", "高"], default: "balanced" },
        allow_auto_split: { type: "boolean", default: true },
        max_replan_attempts: { type: "integer", minimum: 0, maximum: 20, default: 3 },
        sources: CONTENT_MODEL_INPUT_SCHEMA.properties.sources,
        citations: CONTENT_MODEL_INPUT_SCHEMA.properties.citations,
        evidence: CONTENT_MODEL_INPUT_SCHEMA.properties.evidence,
        paperworkflow_v4: CONTENT_MODEL_INPUT_SCHEMA.properties.paperworkflow_v4,
        slide_briefs: {
          type: "array",
          minItems: 1,
          maxItems: 40,
          items: slideBriefInputSchema,
          description: "Optional structured slide requirements with Evidence/Citation references. When present, its length determines the plan length.",
        },
      },
      additionalProperties: false,
    },
    annotations: readOnlyAnnotations,
  },
  {
    name: "validate_slide",
    title: "Validate a populated slide specification",
    description: "Check one layout against content capacity, media slots, scientific-visual minimum width, aspect ratio, semantic roles, and required slot assignments.",
    inputSchema: {
      type: "object",
      properties: {
        layout_id: { type: "string" },
        ...contentMetricsProperties,
        slot_specs: {
          type: "array",
          items: slotSpecSchema,
          description: "Canonical layout slot definitions; use slot_id and slot_type.",
        },
        slot_assignments: {
          type: "object",
          additionalProperties: slotAssignmentSchema,
          description: "Map exact slot IDs to structured content objects. Unknown IDs are errors; use type guidance for planner-only generic guidance.",
        },
      },
      required: ["layout_id"],
      additionalProperties: false,
    },
    annotations: readOnlyAnnotations,
  },
  {
    name: "validate_deck_plan",
    title: "Validate a full research deck plan",
    description: "Validate each slide plus deck-level theme, cover, summary, adjacency, and layout-overuse checks.",
    inputSchema: deckPlanValidationInputSchema,
    annotations: readOnlyAnnotations,
  },
  {
    name: "run_preflight",
    title: "Complete renderer and deck preflight",
    description: "Run renderer-input guard checks and full pre-render deck validation as one stage, returning preflight_complete independently from planning and post-render QA.",
    inputSchema: {
      type: "object",
      properties: {
        renderer_inputs: rendererInputsSchema,
        deck_plan: deckPlanValidationInputSchema,
        content_model: {
          type: "object",
          additionalProperties: true,
          description: "Optional normalized content model to cross-check deck metrics against source briefs.",
        },
        verify_filesystem: {
          type: "boolean",
          default: true,
          description: "Verify the renderer project_path and source_files exist on disk during preflight. Disable only for pure logic benchmarks or cross-host runs.",
        },
      },
      required: ["renderer_inputs", "deck_plan"],
      additionalProperties: false,
    },
    annotations: readOnlyAnnotations,
  },
  {
    name: "validate_renderer_inputs",
    title: "Validate slide renderer inputs",
    description: "Run the renderer guard only: validate slidep/tencent-pptx source filenames, page IDs, Windows project paths, and watcher mode. Use run_preflight for the complete pre-render stage.",
    inputSchema: rendererInputsSchema,
    annotations: readOnlyAnnotations,
  },
  {
    name: "run_visual_fit_preflight",
    title: "Preflight visual-to-slot compatibility",
    description: "Predict contain/cover geometry before rendering, separate objective fit metrics from profile rules, and block incompatible scientific-figure/container contracts before renderer input is created.",
    inputSchema: visualFitPreflightInputSchema,
    annotations: readOnlyAnnotations,
  },
  {
    name: "run_group_fit_preflight",
    title: "Preflight relation-aware visual groups",
    description: "Evaluate every child with the v0.4.5 visual-fit baseline, detect relation-versus-fit conflicts, arbitrate only allowed geometry constraints, and deterministically select, shadow, or fall back to the baseline candidate.",
    inputSchema: GROUP_FIT_INPUT_SCHEMA,
    annotations: readOnlyAnnotations,
  },
  {
    name: "run_figure_placement",
    title: "Run scientific figure placement",
    description: "Resolve full-figure or panel-level intent, compute deterministic aspect-preserving placement, reconcile requested/effective renderer geometry, and return completeness-aware Figure QA with a six-stage trace.",
    inputSchema: figurePlacementInputSchema,
    annotations: readOnlyAnnotations,
  },
  {
    name: "assemble_render_telemetry",
    title: "Assemble auditable render telemetry",
    description: "Join artifact-tool layout/v4 facts with a production v0.4.7 Visual Manifest, verify identity/hash/fixed-region lineage/geometry/groups, and return pass, fail, manual_review_required, or blocked without heuristic matching.",
    inputSchema: {
      type: "object",
      properties: {
        renderer_output: { type: "object", additionalProperties: true },
        visual_manifest: { oneOf: [visualManifestSchema, visualManifestEntrySchema] },
        asset_registry: { type: "object", additionalProperties: { type: "string", pattern: "^(?:sha256:)?[A-Fa-f0-9]{64}$" } },
        renderer_profile: { const: "artifact-tool", default: "artifact-tool" },
        baseline_telemetry: RENDER_TELEMETRY_SCHEMA,
      },
      required: ["renderer_output"],
      additionalProperties: false,
    },
    annotations: readOnlyAnnotations,
  },
  {
    name: "evaluate_visual_quality",
    title: "Evaluate rendered visual quality",
    description: "Evaluate canonical telemetry or raw slidep/tencent-pptx/artifact-tool output, observe rendered design quality, and return a deterministic bounded repair plan without weakening production gates.",
    inputSchema: {
      type: "object",
      properties: {
        telemetry: RENDER_TELEMETRY_SCHEMA,
        renderer_output: { type: "object", additionalProperties: true },
        baseline_telemetry: RENDER_TELEMETRY_SCHEMA,
        baseline_renderer_output: { type: "object", additionalProperties: true },
        preserve_layout_relations: { type: "boolean", default: true },
        layout_drift_tolerance: { type: "number", minimum: 0, maximum: 1, default: 0.08 },
        profile_id: { enum: ["default", "slidep", "tencent-pptx", "artifact-tool"] },
        viewing_mode: { enum: ["projector", "desktop", "handout"], default: "projector" },
        category: { type: "string" },
        layout_id: { type: "string" },
        design_context: { type: "object", additionalProperties: true },
        repair_context: { type: "object", additionalProperties: true },
        render_artifact: { type: "object", additionalProperties: true },
      },
      oneOf: [
        { required: ["telemetry"], not: { required: ["renderer_output"] } },
        { required: ["renderer_output"], not: { required: ["telemetry"] } },
      ],
      additionalProperties: false,
    },
    annotations: readOnlyAnnotations,
  },
  {
    name: "validate_rendered_slide",
    title: "Audit a rendered research slide",
    description: "Audit actual renderer telemetry and return separate production/design diagnoses plus the next deterministic bounded repair action.",
    inputSchema: {
      type: "object",
      properties: {
        slide_number: { type: "integer", minimum: 1 },
        layout_id: { type: "string" },
        category: { type: "string" },
        telemetry: RENDER_TELEMETRY_SCHEMA,
        renderer_output: { type: "object", additionalProperties: true },
        baseline_telemetry: RENDER_TELEMETRY_SCHEMA,
        baseline_renderer_output: { type: "object", additionalProperties: true },
        preserve_layout_relations: { type: "boolean", default: true },
        layout_drift_tolerance: { type: "number", minimum: 0, maximum: 1, default: 0.08 },
        quality_profile_id: { enum: ["default", "slidep", "tencent-pptx", "artifact-tool"] },
        quality_profile: { type: "object", additionalProperties: true },
        viewing_mode: { enum: ["projector", "desktop", "handout"], default: "projector" },
        title_font_pt: { type: "number", exclusiveMinimum: 0 },
        title_line_count: { ...nonNegativeInteger },
        title_wrap_allowed: { type: "boolean", default: false },
        body_font_pts: { type: "array", items: { type: "number", exclusiveMinimum: 0 } },
        text_elements: {
          type: "array",
          items: {
            type: "object",
            properties: {
              id: { type: "string" },
              role: { enum: ["title", "subheading", "callout", "question", "body", "caption", "meta", "footer"] },
              font_pt: { type: "number", exclusiveMinimum: 0 },
              line_count: { ...nonNegativeInteger },
              intended_single_line: { type: "boolean" },
            },
            required: ["role", "font_pt"],
            additionalProperties: false,
          },
        },
        content_occupancy: { type: "number", minimum: 0, maximum: 1, description: "Rendered content bounding-envelope area divided by slide area, excluding background decoration." },
        largest_empty_band: { type: "number", minimum: 0, maximum: 1, description: "Largest unintentional horizontal empty band divided by slide height." },
        content_center_x: { type: "number", minimum: 0, maximum: 1 },
        content_center_y: { type: "number", minimum: 0, maximum: 1 },
        intentional_whitespace: { type: "boolean", default: false },
        visuals: { type: "array", items: visualSchema },
        design_context: { type: "object", additionalProperties: true },
        repair_context: { type: "object", additionalProperties: true },
        render_artifact: { type: "object", additionalProperties: true },
      },
      additionalProperties: false,
    },
    annotations: readOnlyAnnotations,
  },
  {
    name: "validate_rendered_deck",
    title: "Audit a rendered research deck",
    description: "Run post-render readability QA across a deck and aggregate small-font, low-occupancy, empty-band, and dense-figure issues by slide.",
    inputSchema: {
      type: "object",
      properties: {
        viewing_mode: { enum: ["projector", "desktop", "handout"], default: "projector" },
        slides: {
          type: "array",
          minItems: 1,
          maxItems: 200,
          items: { type: "object", additionalProperties: true },
        },
      },
      required: ["slides"],
      additionalProperties: false,
    },
    annotations: readOnlyAnnotations,
  },
];

const detailLevelSchema = {
  enum: ["compact", "standard", "full"],
  default: "compact",
  description: "Response detail: compact is the MCP default; standard retains normal API fields; full is for development and audit.",
};

function withDetailLevel(schema) {
  return {
    ...schema,
    properties: {
      ...(schema.properties ?? {}),
      detail_level: detailLevelSchema,
    },
  };
}

const tools = rawTools.map((tool) => ({ ...tool, inputSchema: withDetailLevel(tool.inputSchema) }));
const toolsByName = new Map(tools.map((tool) => [tool.name, tool]));

const toolHandlers = {
  catalog_summary: () => catalogSummary(),
  audit_layout_library: () => auditBundledLayoutLibrary(),
  run_benchmark: (args) => runBenchmark(args),
  normalize_content: (args) => normalizeContentModel(args),
  search_layouts: (args) => searchLayouts(args),
  get_layout: (args) => getLayout(args.layout_id, args.theme_id, args.viewing_mode),
  create_deck_plan: (args) => createDeckPlan(args),
  validate_slide: (args) => validateSlide(args),
  validate_deck_plan: (args) => validateDeckPlan(args),
  run_preflight: (args) => runPreflight(args),
  validate_renderer_inputs: (args) => validateRendererInputs(args),
  run_visual_fit_preflight: (args) => runVisualFitPreflight(args),
  run_group_fit_preflight: (args) => runGroupFitPreflight(args),
  run_figure_placement: (args) => runFigurePlacement(args),
  assemble_render_telemetry: (args) => assembleRenderTelemetry(args),
  evaluate_visual_quality: (args) => evaluateVisualQuality({
    telemetry: args.telemetry ?? adaptRendererTelemetry(args.renderer_output),
    profile_id: args.profile_id,
    design_context: args.design_context,
    repair_context: args.repair_context,
    render_artifact: args.render_artifact,
    context: {
      viewing_mode: args.viewing_mode,
      category: args.category,
      layout_id: args.layout_id,
      baseline_telemetry: args.preserve_layout_relations === false
        ? null
        : args.baseline_telemetry ?? (args.baseline_renderer_output ? adaptRendererTelemetry(args.baseline_renderer_output) : null),
      layout_drift_tolerance: args.layout_drift_tolerance,
    },
  }),
  validate_rendered_slide: (args) => validateRenderedSlide(args),
  validate_rendered_deck: (args) => validateRenderedDeck(args),
};

function write(message) {
  process.stdout.write(`${JSON.stringify(message)}\n`);
}

function success(id, result) {
  write({ jsonrpc: "2.0", id, result });
}

function failure(id, code, message, data) {
  write({ jsonrpc: "2.0", id, error: { code, message, ...(data === undefined ? {} : { data }) } });
}

function toolResult(toolName, payload, detailLevel) {
  return {
    content: [{ type: "text", text: summarizeToolResult(toolName, payload, detailLevel) }],
    structuredContent: formatStructuredContent(toolName, payload, detailLevel),
    isError: false,
  };
}

function toolError(error) {
  const structuredContent = {
    error: error.name,
    message: error.message,
    ...(error.code === undefined ? {} : { code: error.code }),
  };
  if (Array.isArray(error.schemaErrors)) structuredContent.schema_errors = error.schemaErrors;
  if (Array.isArray(error.violations)) structuredContent.violations = error.violations;
  return {
    content: [{ type: "text", text: `${error.name}: ${error.message}` }],
    structuredContent,
    isError: true,
  };
}

async function readResource(uri) {
  if (uri === "research-ppt://catalog") {
    return { uri, mimeType: "application/json", text: JSON.stringify(await catalogSummary(), null, 2) };
  }
  if (uri === "research-ppt://themes") {
    const summary = await catalogSummary();
    return { uri, mimeType: "application/json", text: JSON.stringify(summary.themes, null, 2) };
  }
  if (uri.startsWith("research-ppt://layout/")) {
    const id = decodeURIComponent(uri.slice("research-ppt://layout/".length));
    return { uri, mimeType: "application/json", text: JSON.stringify(await getLayout(id), null, 2) };
  }
  if (uri.startsWith("research-ppt://preview/")) {
    const id = decodeURIComponent(uri.slice("research-ppt://preview/".length));
    return { uri, mimeType: "image/svg+xml", text: await readPreview(id) };
  }
  throw new RangeError(`Unknown resource URI: ${uri}`);
}

async function handle(request) {
  if (!request || request.jsonrpc !== "2.0" || typeof request.method !== "string") {
    if (request?.id !== undefined) failure(request.id, -32600, "Invalid Request");
    return;
  }
  const { id, method, params = {} } = request;
  const isNotification = id === undefined;

  try {
    switch (method) {
      case "initialize": {
        const requested = params.protocolVersion;
        const protocolVersion = SUPPORTED_PROTOCOLS.has(requested) ? requested : "2025-06-18";
        success(id, {
          protocolVersion,
          capabilities: { tools: { listChanged: false }, resources: { subscribe: false, listChanged: false } },
          serverInfo: SERVER_INFO,
          instructions: "Use normalize_content to establish traceable Sources, Citations, Evidence, and Slide Briefs before create_deck_plan. Confirm plan_complete, call run_preflight before rendering, then pass canonical Render Telemetry to evaluate_visual_quality or validate_rendered_deck. MCP responses default to compact; request standard or full only when more detail is required.",
        });
        return;
      }
      case "notifications/initialized":
      case "notifications/cancelled":
        return;
      case "ping":
        if (!isNotification) success(id, {});
        return;
      case "tools/list":
        success(id, { tools });
        return;
      case "tools/call": {
        const handler = toolHandlers[params.name];
        const tool = toolsByName.get(params.name);
        if (!handler || !tool) {
          success(id, toolError(new RangeError(`Unknown tool: ${params.name}`)));
          return;
        }
        try {
          const args = params.arguments ?? {};
          assertJsonSchema(tool.inputSchema, args, { toolName: params.name });
          const detailLevel = normalizeDetailLevel(args.detail_level, "compact");
          const { detail_level: _detailLevel, ...handlerArgs } = args;
          success(id, toolResult(params.name, await handler(handlerArgs), detailLevel));
        } catch (error) {
          success(id, toolError(error));
        }
        return;
      }
      case "resources/list":
        success(id, {
          resources: [
            { uri: "research-ppt://catalog", name: "Research PPT layout catalog", mimeType: "application/json" },
            { uri: "research-ppt://themes", name: "Research PPT themes", mimeType: "application/json" },
          ],
        });
        return;
      case "resources/templates/list":
        success(id, {
          resourceTemplates: [
            { uriTemplate: "research-ppt://layout/{layout_id}", name: "Layout definition", mimeType: "application/json" },
            { uriTemplate: "research-ppt://preview/{layout_id}", name: "Layout SVG preview", mimeType: "image/svg+xml" },
          ],
        });
        return;
      case "resources/read":
        success(id, { contents: [await readResource(params.uri)] });
        return;
      default:
        if (!isNotification) failure(id, -32601, `Method not found: ${method}`);
    }
  } catch (error) {
    if (!isNotification) failure(id, -32603, error.message, { name: error.name });
  }
}

const input = readline.createInterface({ input: process.stdin, crlfDelay: Infinity });
let inputClosed = false;
let activeMessages = 0;

function finishAfterInputClose() {
  if (inputClosed && activeMessages === 0 && !process.stdout.writableEnded) process.stdout.end();
}

input.on("line", (line) => {
  const trimmed = line.trim();
  if (!trimmed) return;
  activeMessages += 1;
  void (async () => {
    try {
      await handle(JSON.parse(trimmed));
    } catch (error) {
      failure(null, -32700, "Parse error", { message: error.message });
    } finally {
      activeMessages -= 1;
      finishAfterInputClose();
    }
  })();
});

input.on("close", () => {
  inputClosed = true;
  finishAfterInputClose();
});
