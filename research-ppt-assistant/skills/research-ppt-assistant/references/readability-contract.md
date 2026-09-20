# Readability Contract

Use this reference for the legacy `validate_rendered_slide/deck` readability fields and compatibility issue codes. Prefer canonical RPA 0.4.x telemetry and [visual-quality-contract.md](visual-quality-contract.md) for new renderer integrations.

The compatibility wrappers expose three layers: `readability_status` for legacy checks, `visual_quality_status` for the QA Report, and tri-state `overall_status`. The existing `status` field is an alias of `overall_status`. Deck `invalid_slides` and `warning_slides` aggregate the overall status, so missing Visual QA telemetry cannot be hidden by a passing legacy readability check.

## Default projector thresholds

- Deck title: target 54 pt, minimum 50 pt.
- Slide title: target 40 pt, minimum 35 pt.
- Subheading and callout: minimum 24 pt.
- Body: target 20 pt, viewing minimum 18 pt, absolute minimum 16 pt.
- Caption and metadata: minimum 16 pt.
- Content footprint: normally 0.68–0.90 of slide area; cover, section, and Q&A pages use lower minimums.
- Unintentional horizontal empty band: at most 0.12 of slide height.
- Embedded raster text: at least 14 rendered pixels high.

`content_occupancy` means the area of the smallest bounding envelope containing audience-facing content, divided by slide area. Exclude full-slide backgrounds and purely decorative elements. `largest_empty_band` is the tallest continuous horizontal band between content groups, divided by slide height.

## Rendered slide telemetry

Provide the following fields when available:

```json
{
  "layout_id": "RM-DUAL_FIGURE-01",
  "viewing_mode": "projector",
  "text_elements": [
    { "id": "title", "role": "title", "font_pt": 40, "line_count": 1, "intended_single_line": true },
    { "id": "takeaway", "role": "body", "font_pt": 20, "line_count": 3 }
  ],
  "content_occupancy": 0.76,
  "largest_empty_band": 0.08,
  "content_center_x": 0.50,
  "content_center_y": 0.51,
  "visuals": [
    {
      "visual_type": "multi_panel_figure",
      "panel_count": 6,
      "has_embedded_text": true,
      "display_width_norm": 0.62,
      "rendered_embedded_text_px": 15
    }
  ]
}
```

`display_width_norm` is the rendered visual width divided by slide width. For raster figures with embedded labels, estimate `rendered_embedded_text_px` from OCR boxes or a renderer-side image inspection step.

## Issue handling

- `FONT_FLOOR_VIOLATION`: increase the font; shorten, reflow, change layout, or split if it no longer fits.
- `TITLE_WRAPPED`: shorten the title or widen the title region; do not reduce it below the title floor.
- `LOW_CONTENT_OCCUPANCY`: collapse unused slots and enlarge or redistribute the meaningful content group.
- `UNINTENTIONAL_EMPTY_BAND`: move content groups closer and use the released space to improve readability.
- `DENSE_FIGURE_TOO_SMALL`: enlarge or crop the figure; split multiple dense figures across slides.
- `EMBEDDED_TEXT_TOO_SMALL`: crop, enlarge, or redraw the relevant panel. Changing the surrounding PPT text does not fix raster labels.
- `SPLIT_SLIDE_RECOMMENDED`: let each resulting slide make one evidence claim, carrying only the visual and explanation needed for that claim.
