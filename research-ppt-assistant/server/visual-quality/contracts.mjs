import { REPAIR_PLAN_SCHEMA, REPAIR_STATUSES, VISUAL_OBSERVATION_SCHEMA, DESIGN_OBSERVATION_STATUSES } from "../perceptual-loop/contracts.mjs";

const deepFreeze = (value) => {
  if (!value || typeof value !== "object" || Object.isFrozen(value)) return value;
  for (const child of Object.values(value)) deepFreeze(child);
  return Object.freeze(value);
};

export const VISUAL_QUALITY_VERSION = "0.6.0";
export const RENDER_TELEMETRY_VERSION = "1.4.0";
export const SUPPORTED_RENDER_TELEMETRY_VERSIONS = deepFreeze(["1.0.0", "1.1.0", "1.2.0", "1.3.0", RENDER_TELEMETRY_VERSION]);
export const QUALITY_PROFILE_VERSION = "1.4.0";
export const QA_REPORT_VERSION = "1.4.0";

export const QUALITY_STATUSES = deepFreeze(["pass", "warning", "fail", "not_evaluable"]);
export const QUALITY_ROLES = deepFreeze(["content", "decoration", "background", "ignore"]);

const nullableString = { type: ["string", "null"] };
const nullableNumber = { type: ["number", "null"] };
const nullableInteger = { type: ["integer", "null"], minimum: 0 };
const nullableBoolean = { type: ["boolean", "null"] };

const boxSchema = {
  type: "object",
  properties: {
    x: { type: "number" },
    y: { type: "number" },
    width: { type: "number", minimum: 0 },
    height: { type: "number", minimum: 0 },
  },
  required: ["x", "y", "width", "height"],
  additionalProperties: false,
};

const textTelemetrySchema = {
  type: "object",
  properties: {
    content: nullableString,
    language: nullableString,
    script: nullableString,
    font_family: nullableString,
    font_size: { ...nullableNumber, exclusiveMinimum: 0, description: "Effective font size in points (1/72 inch), never CSS pixels." },
    font_weight: { type: ["number", "string", "null"] },
    line_count: nullableInteger,
    overflow: nullableBoolean,
    foreground_color: nullableString,
    local_contrast_ratio: { ...nullableNumber, minimum: 1 },
    intended_single_line: nullableBoolean,
    role: nullableString,
  },
  required: ["content", "language", "script", "font_family", "font_size", "font_weight", "line_count", "overflow", "foreground_color", "intended_single_line", "role"],
  additionalProperties: false,
};

const imageTelemetrySchema = {
  type: "object",
  properties: {
    display_bbox: { ...boxSchema, type: ["object", "null"] },
    source_width_px: { ...nullableInteger, exclusiveMinimum: 0 },
    source_height_px: { ...nullableInteger, exclusiveMinimum: 0 },
    visual_id: nullableString,
    content_id: nullableString,
    slot_id: nullableString,
    visual_type: nullableString,
    panel_count: nullableInteger,
    has_embedded_text: nullableBoolean,
    min_display_width: { ...nullableNumber, minimum: 0, maximum: 1 },
    allocated_bbox: { ...boxSchema, type: ["object", "null"] },
    container_bbox: { ...boxSchema, type: ["object", "null"] },
    rendered_embedded_text_px: { ...nullableNumber, minimum: 0 },
    source_region_bbox: { ...boxSchema, type: ["object", "null"] },
    visual_parent_id: nullableString,
    relation: {
      type: ["object", "null"],
      properties: { type: { const: "visual_child" } },
      required: ["type"],
      additionalProperties: false,
    },
    effective_source_region: { ...boxSchema, type: ["object", "null"] },
    effective_placement: { ...boxSchema, type: ["object", "null"] },
    source_region_coordinate_space: { enum: ["source_normalized_0_1", "source_pixels", null] },
    effective_fit_mode: { enum: ["contain", "cover", "stretch", null] },
    actual_letterbox_ratio: { ...nullableNumber, minimum: 0, maximum: 1 },
    visible_region_ids: { type: ["array", "null"], items: { type: "string" }, uniqueItems: true },
    visible_label_ids: { type: ["array", "null"], items: { type: "string" }, uniqueItems: true },
    geometry_provenance: { enum: ["renderer_reported", "profile_derived", null] },
    renderer_profile_id: nullableString,
    expected_asset_sha256: nullableString,
    rendered_asset_sha256: nullableString,
    asset_identity_provenance: { enum: ["renderer_reported_sha256", "asset_registry", "renderer_hash_identifier", null] },
    crop_mode: { enum: ["full_figure", "preprocessed_fixed_region", null] },
    parent_asset_sha256: nullableString,
    parent_source_region: { ...boxSchema, type: ["object", "null"] },
    parent_source_region_coordinate_space: { enum: ["source_normalized_0_1", "source_pixels", null] },
    derived_asset_sha256: nullableString,
    group_id: nullableString,
    sibling_index: nullableInteger,
  },
  required: ["display_bbox", "source_width_px", "source_height_px"],
  additionalProperties: false,
};

const visualContainerSchema = {
  type: "object",
  properties: {
    container_id: { type: "string", minLength: 1 },
    role: { enum: ["image_only", "image_caption", "image_annotation", "workflow_region", "comparison_region", "decorative_exhibit"] },
    outer_bbox: boxSchema,
    content_bbox: boxSchema,
    content_inset: {
      type: "object",
      properties: {
        left: { type: "number", minimum: 0 },
        right: { type: "number", minimum: 0 },
        top: { type: "number", minimum: 0 },
        bottom: { type: "number", minimum: 0 },
      },
      required: ["left", "right", "top", "bottom"],
      additionalProperties: false,
    },
    child_visual_ids: { type: "array", minItems: 1, uniqueItems: true, items: { type: "string", minLength: 1 } },
    fit_policy: { enum: ["contain", "cover"] },
    crop_policy: { enum: ["full_figure", "semantic_crop_allowed", "fixed_region"] },
    whitespace_policy: { enum: ["minimal", "intentional", "reserved"] },
    mismatch_policy: { enum: ["replan", "resolve_region", "resize_container", "allow_whitespace", "change_fit_policy"] },
    max_letterbox_ratio: { type: "number", minimum: 0, maximum: 1 },
    inference_source: { type: "string" },
  },
  required: ["container_id", "role", "outer_bbox", "content_bbox", "content_inset", "child_visual_ids", "fit_policy", "crop_policy", "whitespace_policy", "mismatch_policy"],
  additionalProperties: false,
};

const themeTokenSchema = {
  type: "object",
  properties: {
    color: nullableString,
    allowed_usage: { type: "array", items: { type: "string" }, uniqueItems: true },
    forbidden_usage: { type: "array", items: { type: "string" }, uniqueItems: true },
  },
  required: ["color", "allowed_usage", "forbidden_usage"],
  additionalProperties: false,
};

const legacyVisualMetricSchema = {
  type: "object",
  properties: {
    visual_type: { type: "string" },
    panel_count: nullableInteger,
    has_embedded_text: { type: "boolean" },
    min_display_width: nullableNumber,
    display_width_norm: nullableNumber,
    display_height_norm: nullableNumber,
    rendered_embedded_text_px: nullableNumber,
  },
  required: ["visual_type", "panel_count", "has_embedded_text", "min_display_width", "display_width_norm", "display_height_norm", "rendered_embedded_text_px"],
  additionalProperties: false,
};

const providedMetricsSchema = {
  type: "object",
  properties: {
    content_footprint: nullableNumber,
    largest_empty_band: nullableNumber,
    content_center_x: nullableNumber,
    content_center_y: nullableNumber,
    intentional_whitespace: { type: "boolean" },
    visuals: { type: "array", items: legacyVisualMetricSchema },
  },
  additionalProperties: false,
};

const renderEvidenceIssueSchema = {
  type: "object",
  properties: {
    status: { enum: ["fail", "blocked"] },
    code: { type: "string", minLength: 1 },
    field: { type: "string", minLength: 1 },
    message: { type: "string", minLength: 1 },
    reason: { type: "string", minLength: 1 },
    responsible_party: { type: "string", minLength: 1 },
    source: { const: "render_evidence_gate" },
    visual_key: nullableString,
    group_id: nullableString,
    details: {},
  },
  required: ["status", "code", "field", "message", "reason", "responsible_party", "source", "visual_key", "group_id", "details"],
  additionalProperties: false,
};

const visualGroupTelemetrySchema = {
  type: "object",
  properties: {
    group_id: { type: "string", minLength: 1 },
    relation_type: { type: "string", minLength: 1 },
    expected_sibling_count: { type: "integer", minimum: 1 },
    actual_sibling_count: { type: "integer", minimum: 0 },
    reading_order: { type: "array", items: { type: "string", minLength: 1 }, uniqueItems: true },
    actual_reading_order: { type: "array", items: { type: "string", minLength: 1 }, uniqueItems: true },
    shared_baseline: { enum: ["none", "top", "center", "bottom"] },
    baseline_tolerance: { type: "number", minimum: 0, maximum: 1 },
    baseline_spread: nullableNumber,
    child_visual_ids: { type: "array", items: { type: "string", minLength: 1 }, uniqueItems: true },
  },
  required: ["group_id", "relation_type", "expected_sibling_count", "actual_sibling_count", "reading_order", "actual_reading_order", "shared_baseline", "baseline_tolerance", "baseline_spread", "child_visual_ids"],
  additionalProperties: false,
};

export const RENDER_TELEMETRY_SCHEMA = deepFreeze({
  $id: "RenderTelemetry",
  type: "object",
  properties: {
    telemetry_version: { enum: SUPPORTED_RENDER_TELEMETRY_VERSIONS },
    slide_id: { type: "string", minLength: 1 },
    renderer: { type: "string", minLength: 1 },
    slide: {
      type: "object",
      properties: {
        width: { type: "number", exclusiveMinimum: 0 },
        height: { type: "number", exclusiveMinimum: 0 },
        render_width_px: { type: ["integer", "null"], exclusiveMinimum: 0 },
        render_height_px: { type: ["integer", "null"], exclusiveMinimum: 0 },
        background: {
          type: "object",
          properties: {
            kind: { enum: ["solid", "image", "gradient", "transparent", "unknown"] },
            color: nullableString,
          },
          required: ["kind", "color"],
          additionalProperties: false,
        },
        layout_id: nullableString,
        category: nullableString,
      },
      required: ["width", "height", "render_width_px", "render_height_px", "background"],
      additionalProperties: false,
    },
    elements: {
      type: "array",
      items: {
        type: "object",
        properties: {
          element_id: { type: "string", minLength: 1 },
          type: { enum: ["text", "image", "shape", "chart", "table", "group", "other"] },
          quality_role: { enum: QUALITY_ROLES },
          z_index: nullableNumber,
          opacity: { ...nullableNumber, minimum: 0, maximum: 1 },
          bbox: { ...boxSchema, type: ["object", "null"] },
          render_bbox_px: { ...boxSchema, type: ["object", "null"] },
          text: { ...textTelemetrySchema, type: ["object", "null"] },
          image: { ...imageTelemetrySchema, type: ["object", "null"] },
          fill_color: nullableString,
          background_color: nullableString,
          theme_token: nullableString,
          theme_usage: nullableString,
          geometry_kind: nullableString,
          relation: {
            type: ["object", "null"],
            properties: {
              type: { enum: ["title_rule", "container_border", "flow_connector", "annotation", "decorative_peer", "baseline_preserved"] },
              target_id: { type: "string", minLength: 1 },
              source: { enum: ["renderer", "adapter_inferred", "baseline"] },
            },
            required: ["type", "target_id", "source"],
            additionalProperties: false,
          },
          source_element_id: nullableString,
        },
        required: ["element_id", "type", "quality_role", "bbox", "render_bbox_px", "text", "image", "fill_color", "background_color", "theme_token", "theme_usage"],
        additionalProperties: false,
      },
    },
    visual_containers: { type: "array", items: visualContainerSchema },
    visual_groups: { type: "array", items: visualGroupTelemetrySchema },
    render_evidence: {
      type: "object",
      properties: {
        evidence_contract_version: { const: "0.4.7" },
        manifest_schema_version: nullableString,
        telemetry_schema_version: { const: "0.4.7" },
        producer_version: nullableString,
        deck_id: nullableString,
        renderer_profile_id: { type: "string", minLength: 1 },
        status: { enum: ["pass", "fail", "manual_review_required", "blocked"] },
        issues: { type: "array", items: renderEvidenceIssueSchema },
        manual_review: { type: "array", items: { type: "object", additionalProperties: true } },
      },
      required: ["evidence_contract_version", "manifest_schema_version", "telemetry_schema_version", "producer_version", "deck_id", "renderer_profile_id", "status", "issues", "manual_review"],
      additionalProperties: false,
    },
    theme: {
      type: ["object", "null"],
      properties: {
        id: nullableString,
        tokens: { type: "object", additionalProperties: themeTokenSchema },
      },
      required: ["id", "tokens"],
      additionalProperties: false,
    },
    unavailable: {
      type: "array",
      items: {
        type: "object",
        properties: {
          field: { type: "string", minLength: 1 },
          reason: { type: "string", minLength: 1 },
        },
        required: ["field", "reason"],
        additionalProperties: false,
      },
    },
    provided_metrics: providedMetricsSchema,
  },
  required: ["telemetry_version", "slide_id", "renderer", "slide", "elements", "theme", "unavailable", "provided_metrics"],
  additionalProperties: false,
});

export const QUALITY_PROFILE_SCHEMA = deepFreeze({
  $id: "VisualQualityProfile",
  type: "object",
  properties: {
    profile_id: { type: "string", minLength: 1 },
    profile_version: { type: "string", minLength: 1 },
    extends: nullableString,
    rules: {
      type: "object",
      additionalProperties: {
        type: "object",
        properties: {
          enabled: { type: "boolean" },
          metric: { type: "string", minLength: 1 },
          operator: { enum: ["maximum", "minimum", "truthy", "count", "text_image_protection"] },
          warning: nullableNumber,
          fail: nullableNumber,
          warning_code: nullableString,
          fail_code: nullableString,
          not_evaluable_code: nullableString,
          reason: { type: "string", minLength: 1 },
          recommended_action: { type: "string", minLength: 1 },
          criteria: {
            type: "object",
            properties: {
              local_contrast_min: { type: "number", minimum: 1 },
              overlay_coverage_min: { type: "number", minimum: 0, maximum: 1 },
              overlay_opacity_min: { type: "number", minimum: 0, maximum: 1 },
            },
            required: ["local_contrast_min", "overlay_coverage_min", "overlay_opacity_min"],
            additionalProperties: false,
          },
        },
        required: ["enabled", "metric", "operator", "warning", "fail", "warning_code", "fail_code", "reason", "recommended_action"],
        additionalProperties: false,
      },
    },
    visual_fit_rules: {
      type: "object",
      properties: {
        scientific_figure: {
          type: "object",
          properties: {
            visual_types: { type: "array", minItems: 1, uniqueItems: true, items: { type: "string", minLength: 1 } },
            aspect_mismatch_warning: { type: "number", minimum: 1 },
            aspect_mismatch_fail: { type: "number", minimum: 1 },
            minimum_axis_fill_warning: { type: "number", minimum: 0, maximum: 1 },
            minimum_axis_fill_fail: { type: "number", minimum: 0, maximum: 1 },
            gap_symmetry_tolerance: { type: "number", minimum: 0, maximum: 1 },
          },
          required: ["visual_types", "aspect_mismatch_warning", "aspect_mismatch_fail", "minimum_axis_fill_warning", "minimum_axis_fill_fail", "gap_symmetry_tolerance"],
          additionalProperties: false,
        },
        // RPA-2: 不受 scientific_figure 管辖的 visual_type（如 schematic）的宽松几何下限
        ungoverned_visual_types: {
          type: "object",
          properties: {
            minimum_area_fill_warning: { type: "number", minimum: 0, maximum: 1 },
            aspect_mismatch_warning: { type: "number", minimum: 1 },
          },
          required: ["minimum_area_fill_warning", "aspect_mismatch_warning"],
          additionalProperties: false,
        },
      },
      required: ["scientific_figure"],
      additionalProperties: false,
    },
    relation_fit_rules: {
      type: "object",
      properties: {
        group_fit: {
          type: "object",
          properties: {
            minimum_child_fill_warning: { type: "number", minimum: 0, maximum: 1 },
            minimum_child_fill_fail: { type: "number", minimum: 0, maximum: 1 },
            fit_equity_warning: { type: "number", minimum: 0, maximum: 1 },
            fit_equity_fail: { type: "number", minimum: 0, maximum: 1 },
            group_fill_variance_warning: { type: "number", minimum: 0 },
          },
          required: ["minimum_child_fill_warning", "minimum_child_fill_fail", "fit_equity_warning", "fit_equity_fail", "group_fill_variance_warning"],
          additionalProperties: false,
        },
        arbitration: {
          type: "object",
          properties: {
            minimum_gain: { type: "number", minimum: 0 },
            maximum_visual_weight_deviation: { type: "number", minimum: 0 },
            max_relation_replan_attempts: { type: "integer", minimum: 0, maximum: 2 },
            template_gap_ratio: { type: "number", minimum: 0, maximum: 0.2 },
          },
          required: ["minimum_gain", "maximum_visual_weight_deviation", "max_relation_replan_attempts", "template_gap_ratio"],
          additionalProperties: false,
        },
        credits: {
          type: "object",
          properties: { maximum_regression_ratio: { type: "number", minimum: 1 } },
          required: ["maximum_regression_ratio"],
          additionalProperties: false,
        },
      },
      required: ["group_fit", "arbitration", "credits"],
      additionalProperties: false,
    },
    legacy_rules: { type: "object", additionalProperties: true },
  },
  required: ["profile_id", "profile_version", "extends", "rules"],
  additionalProperties: false,
});

const thresholdSchema = {
  type: "object",
  properties: {
    warning: nullableNumber,
    fail: nullableNumber,
    triggered: nullableNumber,
  },
  required: ["warning", "fail", "triggered"],
  additionalProperties: false,
};

const checkSchema = {
  type: "object",
  properties: {
    rule_id: { type: "string", minLength: 1 },
    metric: { type: "string", minLength: 1 },
    status: { enum: QUALITY_STATUSES },
    actual: nullableNumber,
    threshold: thresholdSchema,
    code: nullableString,
    reason: { type: "string", minLength: 1 },
    recommended_action: { type: "string", minLength: 1 },
    evidence: {},
    disabled: { type: "boolean" },
    blocking: { type: "boolean" },
    review_required: { type: "boolean" },
  },
  required: ["rule_id", "metric", "status", "actual", "threshold", "code", "reason", "recommended_action", "evidence", "disabled"],
  additionalProperties: false,
};

const violationSchema = {
  type: "object",
  properties: {
    code: { type: "string", minLength: 1 },
    field: { type: "string", minLength: 1 },
    actual: {},
    capacity: {},
    severity: { enum: ["error", "warning", "info"] },
    recoverable: { type: "boolean" },
    recommended_action: { type: "string", minLength: 1 },
    message: { type: "string", minLength: 1 },
    suggestion: { type: "string", minLength: 1 },
    path: { type: "string", minLength: 1 },
    details: {},
  },
  required: ["code", "field", "actual", "capacity", "severity", "recoverable", "recommended_action"],
  additionalProperties: false,
};

const pointSchema = {
  type: ["object", "null"],
  properties: { x: { type: "number" }, y: { type: "number" } },
  required: ["x", "y"],
  additionalProperties: false,
};

const gapSchema = {
  type: "object",
  properties: {
    start: { type: "number" },
    end: { type: "number" },
    size: { type: "number", minimum: 0 },
    ratio: { type: "number", minimum: 0 },
    kind: { enum: ["margin", "internal"] },
  },
  required: ["start", "end", "size", "ratio", "kind"],
  additionalProperties: false,
};

const axisSchema = {
  type: "object",
  properties: {
    axis: { enum: ["x", "y"] },
    largest_gap: nullableNumber,
    largest_gap_ratio: nullableNumber,
    gaps: { type: "array", items: gapSchema },
  },
  required: ["axis", "largest_gap", "largest_gap_ratio", "gaps"],
  additionalProperties: false,
};

const overflowElementSchema = {
  type: "object",
  properties: {
    element_id: { type: "string" },
    coordinate_space: { enum: ["bbox", "render_bbox_px"] },
    bbox: boxSchema,
    overflow: {
      type: "object",
      properties: { left: { type: "number" }, top: { type: "number" }, right: { type: "number" }, bottom: { type: "number" } },
      required: ["left", "top", "right", "bottom"],
      additionalProperties: false,
    },
  },
  required: ["element_id", "coordinate_space", "bbox", "overflow"],
  additionalProperties: false,
};

const textOverflowElementSchema = {
  type: "object",
  properties: { element_id: { type: "string" }, overflow: { const: true } },
  required: ["element_id", "overflow"],
  additionalProperties: false,
};

const textOverflowFactSchema = {
  type: "object",
  properties: {
    measurable: { type: "boolean" },
    count: { type: "integer", minimum: 0 },
    observed_count: { type: "integer", minimum: 0 },
    expected_count: { type: "integer", minimum: 0 },
    elements: { type: "array", items: textOverflowElementSchema },
    unavailable_reason: { type: "string" },
  },
  required: ["measurable", "count", "observed_count", "expected_count", "elements"],
  additionalProperties: false,
};

const outOfBoundsFactSchema = {
  type: "object",
  properties: {
    measurable: { type: "boolean" },
    count: { type: "integer", minimum: 0 },
    observed_count: { type: "integer", minimum: 0 },
    expected_count: { type: "integer", minimum: 0 },
    coordinate_space: { enum: ["bbox", "render_bbox_px"] },
    elements: { type: "array", items: overflowElementSchema },
    unavailable_reason: { type: "string" },
  },
  required: ["measurable", "count", "observed_count", "expected_count", "coordinate_space", "elements"],
  additionalProperties: false,
};

const themeUsageRecordSchema = {
  type: "object",
  properties: {
    element_id: { type: "string" },
    token: { type: "string" },
    usage: { type: "string" },
    result: { enum: ["allowed", "forbidden", "not_allowed", "unknown_token"] },
  },
  required: ["element_id", "token", "usage", "result"],
  additionalProperties: false,
};

const textImageOverlaySchema = {
  type: "object",
  properties: {
    element_id: { type: "string" },
    z_index: { type: "number" },
    coverage_ratio: { type: "number", minimum: 0, maximum: 1 },
    opacity: { ...nullableNumber, minimum: 0, maximum: 1 },
    fill_color: { type: "string" },
  },
  required: ["element_id", "z_index", "coverage_ratio", "opacity", "fill_color"],
  additionalProperties: false,
};

const textImageIntersectionSchema = {
  type: "object",
  properties: {
    text_element_id: { type: "string" },
    image_element_id: { type: "string" },
    text_bbox: boxSchema,
    image_bbox: boxSchema,
    overlap_ratio: { type: "number", minimum: 0, maximum: 1 },
    text_z_index: { type: "number" },
    image_z_index: nullableNumber,
    local_contrast_ratio: { ...nullableNumber, minimum: 1 },
    overlays: { type: "array", items: textImageOverlaySchema },
  },
  required: ["text_element_id", "image_element_id", "text_bbox", "image_bbox", "overlap_ratio", "text_z_index", "image_z_index", "local_contrast_ratio", "overlays"],
  additionalProperties: false,
};

const visualReadabilityObservationSchema = {
  type: "object",
  properties: {
    element_id: { type: "string" },
    visual_id: nullableString,
    slot_id: nullableString,
    visual_type: nullableString,
    panel_count: nullableNumber,
    has_embedded_text: nullableBoolean,
    min_display_width: nullableNumber,
    display_width_norm: nullableNumber,
    display_height_norm: nullableNumber,
    fill_ratio: nullableNumber,
    letterbox_ratio: nullableNumber,
    rendered_embedded_text_px: nullableNumber,
  },
  required: ["element_id", "visual_id", "slot_id", "visual_type", "panel_count", "has_embedded_text", "min_display_width", "display_width_norm", "display_height_norm", "fill_ratio", "letterbox_ratio", "rendered_embedded_text_px"],
  additionalProperties: false,
};

const visualFitMetricsSchema = {
  type: "object",
  properties: {
    content_bbox: boxSchema,
    child_display_bbox: boxSchema,
    fit_policy: { type: "string" },
    source_aspect_ratio: { type: "number", exclusiveMinimum: 0 },
    allocated_aspect_ratio: { type: "number", exclusiveMinimum: 0 },
    aspect_mismatch_factor: { type: "number", minimum: 1 },
    predicted_display_bbox: boxSchema,
    visual_fill: {
      type: "object",
      properties: { width_ratio: { type: "number", minimum: 0 }, height_ratio: { type: "number", minimum: 0 }, area_ratio: { type: "number", minimum: 0 } },
      required: ["width_ratio", "height_ratio", "area_ratio"],
      additionalProperties: false,
    },
    unused_space: {
      type: "object",
      properties: { horizontal_ratio: { type: "number" }, vertical_ratio: { type: "number" } },
      required: ["horizontal_ratio", "vertical_ratio"],
      additionalProperties: false,
    },
    gaps: {
      type: "object",
      properties: {
        left: { type: "number", minimum: 0 }, right: { type: "number", minimum: 0 }, top: { type: "number", minimum: 0 }, bottom: { type: "number", minimum: 0 },
        left_ratio: { type: "number", minimum: 0 }, right_ratio: { type: "number", minimum: 0 }, top_ratio: { type: "number", minimum: 0 }, bottom_ratio: { type: "number", minimum: 0 },
        gap_symmetry: {
          type: "object",
          properties: { horizontal_delta_ratio: { type: "number", minimum: 0 }, vertical_delta_ratio: { type: "number", minimum: 0 } },
          required: ["horizontal_delta_ratio", "vertical_delta_ratio"],
          additionalProperties: false,
        },
      },
      required: ["left", "right", "top", "bottom", "left_ratio", "right_ratio", "top_ratio", "bottom_ratio", "gap_symmetry"],
      additionalProperties: false,
    },
    effective_source_scale: nullableNumber,
  },
  required: ["content_bbox", "child_display_bbox", "fit_policy", "source_aspect_ratio", "allocated_aspect_ratio", "aspect_mismatch_factor", "predicted_display_bbox", "visual_fill", "unused_space", "gaps", "effective_source_scale"],
  additionalProperties: false,
};

const visualContainerObservationSchema = {
  type: "object",
  properties: {
    container_id: { type: "string" }, visual_id: { type: "string" }, element_id: { type: "string" }, visual_type: nullableString,
    container_role: { type: "string" }, fit_policy: { type: "string" }, crop_policy: { type: "string" }, whitespace_policy: { type: "string" }, mismatch_policy: { type: "string" },
    metrics: visualFitMetricsSchema,
  },
  required: ["container_id", "visual_id", "element_id", "visual_type", "container_role", "fit_policy", "crop_policy", "whitespace_policy", "mismatch_policy", "metrics"],
  additionalProperties: false,
};

const reportMetricsSchema = {
  type: "object",
  properties: {
    element_union: {
      type: "object",
      properties: {
        measurable: { type: "boolean" }, union_area: nullableNumber, slide_area: { type: "number", exclusiveMinimum: 0 },
        element_area_ratio: nullableNumber, rectangle_count: { type: "integer", minimum: 0 }, unavailable_reason: { type: "string" },
      },
      required: ["measurable", "union_area", "slide_area", "element_area_ratio", "rectangle_count"],
      additionalProperties: false,
    },
    whitespace: {
      type: "object",
      properties: { measurable: { type: "boolean" }, horizontal: axisSchema, vertical: axisSchema, element_count: { type: "integer", minimum: 0 }, unavailable_reason: { type: "string" } },
      required: ["measurable", "horizontal", "vertical", "element_count"],
      additionalProperties: false,
    },
    visual_center: {
      type: "object",
      properties: { measurable: { type: "boolean" }, center: pointSchema, normalized_center: pointSchema, offset: nullableNumber, element_count: { type: "integer", minimum: 0 }, unavailable_reason: { type: "string" } },
      required: ["measurable", "center", "normalized_center", "offset", "element_count"],
      additionalProperties: false,
    },
    overflow: {
      type: "object",
      properties: { text_overflow: textOverflowFactSchema, element_out_of_bounds: outOfBoundsFactSchema },
      required: ["text_overflow", "element_out_of_bounds"],
      additionalProperties: false,
    },
    theme_usage: {
      type: "object",
      properties: {
        measurable: { type: "boolean" }, usage_count: { type: "integer", minimum: 0 }, violation_count: { type: "integer", minimum: 0 },
        usages: { type: "array", items: themeUsageRecordSchema }, violations: { type: "array", items: themeUsageRecordSchema }, unavailable_reason: { type: "string" },
      },
      required: ["measurable", "usage_count", "violation_count", "usages", "violations"],
      additionalProperties: false,
    },
    contrast: {
      type: "array",
      items: {
        type: "object",
        properties: {
          element_id: { type: "string" }, measurable: { type: "boolean" }, contrast_ratio: nullableNumber,
          foreground_color: nullableString, background_color: nullableString, unavailable_reason: { type: "string" },
        },
        required: ["element_id", "measurable", "contrast_ratio", "foreground_color", "background_color"],
        additionalProperties: false,
      },
    },
    text_image_occlusion: {
      type: "object",
      properties: {
        measurable: { type: "boolean" },
        applicable: { type: "boolean" },
        coordinate_space: { enum: ["bbox", "render_bbox_px"] },
        text_count: { type: "integer", minimum: 0 },
        image_count: { type: "integer", minimum: 0 },
        intersection_count: { type: "integer", minimum: 0 },
        intersections: { type: "array", items: textImageIntersectionSchema },
        missing_fields: { type: "array", items: { type: "string" }, uniqueItems: true },
        unavailable_reason: { type: "string" },
      },
      required: ["measurable", "applicable", "coordinate_space", "text_count", "image_count", "intersection_count", "intersections", "missing_fields"],
      additionalProperties: false,
    },
    visual_readability: {
      type: "object",
      properties: {
        measurable: { type: "boolean" },
        applicable: { type: "boolean" },
        element_count: { type: "integer", minimum: 0 },
        observations: { type: "array", items: visualReadabilityObservationSchema },
        missing_fields: { type: "array", items: { type: "string" }, uniqueItems: true },
        measurement_gaps: {
          type: "array",
          items: {
            type: "object",
            properties: { field: { type: "string" }, state: { enum: ["not_measured", "measurement_failed"] }, reason: { type: "string" } },
            required: ["field", "state", "reason"],
            additionalProperties: false,
          },
        },
        unavailable_reason: { type: "string" },
      },
      required: ["measurable", "applicable", "element_count", "observations", "missing_fields", "measurement_gaps"],
      additionalProperties: false,
    },
    visual_container_fit: {
      type: "object",
      properties: {
        measurable: { type: "boolean" },
        applicable: { type: "boolean" },
        observation_count: { type: "integer", minimum: 0 },
        observations: { type: "array", items: visualContainerObservationSchema },
        missing_fields: { type: "array", items: { type: "string" }, uniqueItems: true },
        unavailable_reason: { type: "string" },
      },
      required: ["measurable", "applicable", "observation_count", "observations", "missing_fields"],
      additionalProperties: false,
    },
    element_relations: {
      type: "object",
      properties: {
        measurable: { type: "boolean" }, applicable: { type: "boolean" }, candidate_count: { type: "integer", minimum: 0 },
        related_count: { type: "integer", minimum: 0 }, issue_count: { type: "integer", minimum: 0 },
        candidates: { type: "array", items: { type: "object", additionalProperties: true } },
        issues: { type: "array", items: { type: "object", additionalProperties: true } },
        missing_element_ids: { type: "array", items: { type: "string" } }, unavailable_reason: { type: "string" },
        content_region: { ...boxSchema, type: ["object", "null"] },
      },
      required: ["measurable", "applicable", "candidate_count", "related_count", "issue_count", "candidates", "issues", "missing_element_ids"],
      additionalProperties: false,
    },
    layout_regression: {
      type: "object",
      properties: {
        measurable: { type: "boolean" }, applicable: { type: "boolean" }, compared_visual_count: { type: "integer", minimum: 0 },
        issue_count: { type: "integer", minimum: 0 }, issues: { type: "array", items: { type: "object", additionalProperties: true } },
      },
      required: ["measurable", "applicable", "compared_visual_count", "issue_count", "issues"],
      additionalProperties: false,
    },
  },
  required: ["element_union", "whitespace", "visual_center", "overflow", "theme_usage", "contrast", "text_image_occlusion", "visual_readability", "visual_container_fit", "element_relations", "layout_regression"],
  additionalProperties: false,
};

export const QA_REPORT_SCHEMA = deepFreeze({
  $id: "VisualQualityReport",
  type: "object",
  properties: {
    report_version: { const: QA_REPORT_VERSION },
    telemetry_version: { enum: SUPPORTED_RENDER_TELEMETRY_VERSIONS },
    profile_id: { type: "string" },
    profile_version: { type: "string" },
    slide_id: { type: "string" },
    renderer: { type: "string" },
    status: { enum: QUALITY_STATUSES },
    production_status: { enum: QUALITY_STATUSES },
    design_status: { enum: DESIGN_OBSERVATION_STATUSES },
    repair_status: { enum: REPAIR_STATUSES },
    design_observation: VISUAL_OBSERVATION_SCHEMA,
    repair_plan: REPAIR_PLAN_SCHEMA,
    checks: { type: "object", additionalProperties: checkSchema },
    metrics: reportMetricsSchema,
    violations: { type: "array", items: violationSchema },
    recommended_action: { type: "string" },
    reasons: { type: "array", items: { type: "string" } },
    manual_review: {
      type: "array",
      items: {
        type: "object",
        properties: {
          rule_id: { type: "string" }, code: nullableString, reason: { type: "string" }, recommended_action: { type: "string" },
        },
        required: ["rule_id", "code", "reason", "recommended_action"],
        additionalProperties: false,
      },
    },
  },
  required: ["report_version", "telemetry_version", "profile_id", "profile_version", "slide_id", "renderer", "status", "production_status", "design_status", "repair_status", "design_observation", "repair_plan", "checks", "metrics", "violations", "recommended_action", "reasons", "manual_review"],
  additionalProperties: false,
});
