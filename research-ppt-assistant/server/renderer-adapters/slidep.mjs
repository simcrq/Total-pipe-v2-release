import { adaptTelemetryWithMapping, createRendererMapping } from "./common.mjs";
import { assertRenderTelemetry } from "../visual-quality/telemetry.mjs";

export const SLIDEP_TELEMETRY_MAPPING = createRendererMapping("slidep", {
  slide: {
    record: ["slide_spec", "slideSpec", "page_spec", "pageSpec", "slide_node", "slideNode"],
    width: ["slideSize.width", "slideSize.w", "pageSize.width", "pageSize.w", "canvas_size.width", "canvasSize.width"],
    height: ["slideSize.height", "slideSize.h", "pageSize.height", "pageSize.h", "canvas_size.height", "canvasSize.height"],
    renderWidthPx: ["renderSize.width", "renderSize.w", "render_size_px.w", "pixelSize.w"],
    renderHeightPx: ["renderSize.height", "renderSize.h", "render_size_px.h", "pixelSize.h"],
    elements: ["drawables", "layers", "content", "slideItems", "slide_items"],
    theme: ["theme_spec", "themeSpec", "design_theme", "designTheme"],
  },
  element: {
    id: ["uid", "uuid", "layer_id", "layerId", "drawable_id", "drawableId"],
    type: ["component", "componentKind", "drawable_type", "drawableType", "shape_kind", "shapeKind"],
    bbox: ["pptx", "pptxBox", "layout", "layoutBox", "absolute_box", "absoluteBox"],
    renderBboxPx: ["renderedBoxPx", "rendered_box", "pixelBox", "pixel_box", "raster_bbox_px", "rasterBboxPx"],
    text: ["text_block", "textBlock", "text_props", "textProps", "typography_data", "typographyData"],
    image: ["image_props", "imageProps", "image_asset", "imageAsset", "figure", "figureData"],
    themeToken: ["design_token", "designToken", "themeColorToken", "theme_color_token"],
    themeUsage: ["design_usage", "designUsage", "themeColorUsage", "theme_color_usage"],
  },
});

export function adaptSlidepTelemetry(input = {}) {
  return assertRenderTelemetry(adaptTelemetryWithMapping(input, SLIDEP_TELEMETRY_MAPPING));
}

export const adaptSlidePTelemetry = adaptSlidepTelemetry;
export const adaptSlidep = adaptSlidepTelemetry;
