# Visual Quality Contract

Use this reference when a renderer or downstream workflow prepares RPA 0.6 telemetry or interprets the Visual QA and bounded repair report.

## Layer boundary

Keep the pipeline strictly separated:

```text
Renderer → Render Telemetry → Metrics/Rules → QA Report → Visual Observer → Repair Controller
```

Renderer adapters provide facts only. Metrics calculate values only. Rules interpret values using thresholds from a versioned profile. Planner, Slot Binding, Renderer Adapter, Theme Loader, and Layout Retrieval must not contain Visual QA thresholds.

## Canonical telemetry

Pass one canonical object per rendered slide:

```json
{
  "telemetry_version": "1.4.0",
  "slide_id": "slide-7",
  "renderer": "slidep",
  "slide": {
    "width": 13.333,
    "height": 7.5,
    "render_width_px": 1920,
    "render_height_px": 1080,
    "background": { "kind": "solid", "color": "#F8FAFC" },
    "layout_id": "RM-EVIDENCE-01",
    "category": "evidence"
  },
  "elements": [
    {
      "element_id": "title",
      "type": "text",
      "quality_role": "content",
      "z_index": 2,
      "opacity": 1,
      "bbox": { "x": 0.8, "y": 0.5, "width": 11.4, "height": 0.8 },
      "render_bbox_px": { "x": 115, "y": 72, "width": 1642, "height": 115 },
      "text": {
        "content": "Measured result",
        "language": "en",
        "script": "Latin",
        "font_family": "Arial",
        "font_size": 40,
        "font_weight": 600,
        "line_count": 1,
        "overflow": false,
        "foreground_color": "#0F172A",
        "local_contrast_ratio": 17.8,
        "intended_single_line": true,
        "role": "title"
      },
      "image": null,
      "fill_color": null,
      "background_color": "#F8FAFC",
      "theme_token": "text",
      "theme_usage": "title_text"
    }
  ],
  "visual_containers": [],
  "visual_groups": [],
  "render_evidence": {
    "evidence_contract_version": "0.4.7",
    "manifest_schema_version": "0.4.7",
    "telemetry_schema_version": "0.4.7",
    "producer_version": "deck-builder@0.4.7",
    "deck_id": "deck-1",
    "renderer_profile_id": "artifact-tool/layout-v4@1",
    "status": "pass",
    "issues": [],
    "manual_review": []
  },
  "theme": {
    "id": "paper_blue",
    "tokens": {
      "text": {
        "color": "#0F172A",
        "allowed_usage": ["title_text", "body_text"],
        "forbidden_usage": ["background"]
      }
    }
  },
  "unavailable": [],
  "provided_metrics": {}
}
```

Use `quality_role` as follows:

- `content`: participates in union area, whitespace, visual center, overflow, and contrast.
- `decoration`: excluded from primary content metrics unless a caller explicitly opts in.
- `background`: never inflates content occupancy.
- `ignore`: excluded completely.

Every required but unavailable renderer fact must be `null` and recorded in `unavailable` with an exact field path and reason. Telemetry 1.1 requires `slide.layout_id`, `slide.category`, each element's `z_index` and `opacity`, and each text element's `local_contrast_ratio`. Telemetry 1.2 additionally requires every image element's `visual_id`, `content_id`, `slot_id`, `visual_type`, `panel_count`, `has_embedded_text`, and `allocated_bbox`; images with embedded text also require `rendered_embedded_text_px`. Telemetry 1.3 can add explicit `visual_containers`. Telemetry 1.4 is emitted only after Evidence Closure assembly and additionally carries `render_evidence`, `visual_groups`, verified asset/crop lineage, `container_bbox`, and per-image geometry provenance. Generic renderer adapters cannot claim the 1.4 evidence contract by themselves. An unavailable fact is valid only when its exact path is declared. Slide render width/height must be supplied together. Do not fabricate a bbox, allocated slot, container relationship, layer order, opacity, font measurement, embedded-text size, local contrast, overflow flag, source image size, color, or theme usage constraint.

For scientific images, `bbox` / `image.display_bbox` is the renderer's actual display rectangle and `image.allocated_bbox` is the rectangle allocated by Slot Binding or Figure Placement. Never copy the allocated rectangle into the display rectangle when the renderer letterboxes or shrinks the image. The QA engine derives normalized display width, fill ratio, and letterbox ratio from those two facts.

For artifact-tool output, pass the unmodified `openai.presentation.layout/v4` document as `renderer_output`. The adapter maps element `order`, image and text boxes, and overlay shapes automatically. Never manually collapse a rendered image page into a solid slide background or omit actual elements merely to satisfy the schema.

For artifact-tool scientific images, first call `assemble_render_telemetry` with a production Visual Manifest 0.4.7. The assembler matches a stable deck-unique `visual_key` from a renderer field or exact alt fallback (`rpa:<visual_key> | ...`), resolves containers only by explicit `shape_name`, verifies renderer SHA-256 or an explicit asset registry, and derives display geometry only through the conformance-tested `artifact-tool/layout-v4@1` profile. It never matches by picture order, caption, aid, byte length, nearest geometry, or z-order.

P0 crop evidence supports only `full_figure` and `preprocessed_fixed_region`. A fixed region must record `parent_asset_sha256`, `parent_source_region`, parent dimensions, and `derived_asset_sha256`; the rendered hash must equal the derived hash and the renderer must show the whole derived asset with `contain`. `container_bbox`, `allocated_bbox`, and `display_bbox` remain separate. Per-image `geometry_provenance` is `renderer_reported` or `profile_derived`; only the latter carries the profile ID. Visual groups verify sibling count/index, reading order, independent container/asset policies, and optional shared baseline.

Evidence status is not a generic readiness boolean. `pass` means facts are complete and consistent; `fail` means facts are complete and prove a mismatch; `manual_review_required` means facts are complete but visual quality is algorithmically ambiguous; `blocked` means a mandatory fact or compatible protocol is absent. `readiness_status=ready` can coexist with `status=fail`. Only `status=pass` may be automatically released.

Completeness is evaluated per metric across the full participating element set. A complete element plus an incomplete element never yields a pass from the observed subset. When render width/height are available, `render_bbox_px` is authoritative for out-of-bounds checks; otherwise logical `bbox` is used. `provided_metrics` is a closed legacy compatibility shape and cannot override canonical geometry.

## Metrics and report

RPA 0.4.7 computes exact clipped element union, X/Y projected whitespace gaps, area-weighted visual center, text overflow, out-of-bounds geometry, theme-token usage, solid-background contrast, cover text/image/overlay intersections using bbox plus Z-order, scientific-image display-width/fill/letterbox/embedded-text facts, Visual Container child fill/gap/aspect facts, content-region decoration relations/duplicates, render-evidence closure, and optional baseline layout-relation regression. Baseline protection includes visual parent, sibling group, normalized geometry, reading order, and shared container policies. Visual-center offset is the physical center displacement divided by the slide diagonal, so non-square slides are handled correctly. These metric modules contain no warning/fail thresholds. Relation-aware pre-render Group Fit is a separate contract; read `relation-fit-contract.md` rather than adding group thresholds to renderer metrics.

Before rendering, `run_visual_fit_preflight` predicts contain/cover geometry from Source Region, Visual Intent, inner allocated box, and Visual Container policies. Profile rules—not metric code—decide `VISUAL_SLOT_FIT_INCOMPATIBLE`. After rendering, the same policy family interprets actual child/container metrics and may emit `VISUAL_CONTAINER_CHILD_MISMATCH`. Intentional whitespace and composite container roles must remain exempt from image-only/minimal underfill hard failures.

Text overflow is no longer declaration-only. A renderer-declared `text.overflow === true` is still honoured, but RPA additionally measures every text element from data the v1.2.0 contract already requires: the element box, `text.font_size` (points), and `text.content`. Full-width (CJK) glyphs are measured at one em and latin glyphs below that, because a single latin-biased factor systematically over-estimates how much Chinese fits on a line. Because `line-height` and in-box padding are not part of the contract, the estimate assumes 1.2 line-height with 8pt/4pt padding and allows a 10% assumption margin, so tight-but-valid typography does not fail while genuinely clipped text does. Measurement never overrides a declared `true`, and is skipped for elements whose geometry the consumer listed in `unavailable` — an element stays uncovered unless the renderer declared `overflow` or the box is usable.

For cover text over an underlying image, the default profile accepts either measured local contrast of at least 4.5 or an overlay surface between the image and text layers covering at least 95% of the text bbox with opacity at least 0.85. Known low contrast without a qualifying surface fails as `UNPROTECTED_TEXT_OVER_IMAGE`. Missing contrast, geometry, layer order, or opacity is `TEXT_IMAGE_PROTECTION_NOT_EVALUABLE`; it must never become pass.

Inline Quality Profiles honor `extends` exactly like bundled file profiles, with recursive merge and cycle detection. QA Report checks, metric families, and violations use closed nested schemas; unknown fields are rejected instead of silently becoming part of the public contract.

`evaluate_visual_quality` returns:

```text
status / checks / metrics / violations
profile_id / profile_version
recommended_action / reasons
production_status / design_status / repair_status
design_observation / repair_plan
```

Status meanings:

- `pass`: every enabled, required check is evaluable and within profile thresholds.
- `warning`: a warning threshold is crossed, a measurement fails, or blocking checks are unavailable while others are evaluable.
- `fail`: at least one fail threshold or hard contract rule is crossed.
- `not_evaluable`: no enabled check has enough reliable data.

Complex image, gradient, transparent, or unknown backgrounds make solid contrast `not_evaluable`. Do not substitute a theme average and do not interpret missing data as pass.

The observer measures hierarchy, balance, whitespace, visual focus, and decoration variety from rendered facts plus the optional planner `design_context`. The controller can only select `KEEP`, `REDECORATE`, `CHANGE_TREATMENT`, `RESELECT_LAYOUT`, `REBIND`, `REDUCE_SECONDARY_CONTENT`, `SPLIT_PAGE`, or `ESCALATE`. Pass the returned `repair_lineage` and incremented iteration into the next rendered evaluation. Never execute more than two repair renders; then preserve evidence and escalate. Production status remains an independent hard gate.

An embedded raster-text measurement explicitly declared as not measured is the sole non-blocking `not_evaluable` case: it appears in `manual_review` with an informational `SCIENTIFIC_VISUAL_NOT_EVALUABLE` record and does not by itself promote a slide or deck to warning. A failed OCR/measurement attempt remains blocking. RPA does not perform OCR; extraction and OCR remain upstream or renderer responsibilities.

Primary 0.4.3 violations include `TEXT_VISUAL_OVERFLOW`, `ELEMENT_OUT_OF_BOUNDS`, `EXCESSIVE_WHITESPACE`, `LARGE_HORIZONTAL_VOID`, `LARGE_VERTICAL_VOID`, `VISUAL_CENTER_SHIFTED`, `THEME_USAGE_VIOLATION`, `TEXT_CONTRAST_LOW`, `CONTRAST_NOT_EVALUABLE`, `UNPROTECTED_TEXT_OVER_IMAGE`, `TEXT_IMAGE_PROTECTION_NOT_EVALUABLE`, `DENSE_FIGURE_TOO_SMALL`, `VISUAL_READABILITY_RISK`, `IMAGE_UNDERFILLED_SLOT`, `EMBEDDED_TEXT_TOO_SMALL`, and `SCIENTIFIC_VISUAL_NOT_EVALUABLE`.
