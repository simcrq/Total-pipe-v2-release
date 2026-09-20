import { adaptTelemetryWithMapping, createRendererMapping } from "./common.mjs";
import { assertRenderTelemetry } from "../visual-quality/telemetry.mjs";

export const TENCENT_PPTX_TELEMETRY_MAPPING = createRendererMapping("tencent-pptx", {
  rendererAliases: ["tencent_pptx", "tencentPptx", "tencentPPTX", "pptx"],
  slide: {
    record: ["slide_info", "slideInfo", "page_info", "pageInfo", "pptx_page", "pptxPage", "pageObject", "page_object"],
    id: ["page_key", "pageKey", "slide_key", "slideKey"],
    width: ["pageSize.width", "pageSize.w", "page_size.width", "page_size.w", "pptxSize.width", "pptxSize.w"],
    height: ["pageSize.height", "pageSize.h", "page_size.height", "page_size.h", "pptxSize.height", "pptxSize.h"],
    renderWidthPx: ["rendered_size.width", "renderedSize.width", "rendered_size.w", "renderedSize.w", "output_size.width", "outputSize.width"],
    renderHeightPx: ["rendered_size.height", "renderedSize.height", "rendered_size.h", "renderedSize.h", "output_size.height", "outputSize.height"],
    elements: ["shapes", "shape_list", "shapeList", "page_shapes", "pageShapes", "objects", "shapeTree", "shape_tree"],
    theme: ["pptx_theme", "pptxTheme", "theme_part", "themePart", "presentation_theme_part", "presentationThemePart"],
  },
  element: {
    id: ["shape_id", "shapeId", "sp_id", "spId", "object_id", "objectId", "cNvPr_id", "cNvPrId"],
    type: ["shape_type", "shapeType", "sp_type", "spType", "drawing_type", "drawingType", "object_kind", "objectKind"],
    qualityRole: ["qualityRole", "semanticRole", "layerRole", "pptxRole", "pptx_role"],
    bbox: ["pptx_bbox", "pptxBbox", "shape_bbox", "shapeBbox", "transform", "a:xfrm", "xfrm"],
    renderBboxPx: ["rendered_bbox", "renderedBbox", "render_bbox", "renderBbox", "pixel_bounds", "pixelBounds", "raster_bounds", "rasterBounds"],
    renderDirectSignals: ["renderLeftPx", "renderTopPx", "renderWidthPx", "renderHeightPx", "pixelLeft", "pixelTop", "pixelWidth", "pixelHeight"],
    text: ["text_body", "textBody", "txBody", "tx_body", "text_frame", "textFrame", "tx_body_properties", "txBodyProperties"],
    image: ["blip", "blipFill", "blip_fill", "picture_data", "pictureData", "image_source", "imageSource"],
    imageDisplayBbox: ["picture_bbox", "pictureBbox", "image_bounds", "imageBounds", "crop_box", "cropBox"],
    imageSourceWidth: ["imageWidthPx", "image_width_px", "originalWidthPx", "original_width_px", "blip.width", "blipWidth"],
    imageSourceHeight: ["imageHeightPx", "image_height_px", "originalHeightPx", "original_height_px", "blip.height", "blipHeight"],
    fillColor: ["solidFill", "solid_fill", "spPr.solidFill", "spPr.solid_fill", "shapeFill", "shape_fill"],
    backgroundColor: ["shapeBackgroundColor", "shape_background_color", "backColor", "back_color", "spPr.background", "spPr.backgroundColor"],
    themeToken: ["schemeColor", "scheme_color", "themeColor", "theme_color", "clrSchemeToken", "clr_scheme_token"],
    themeUsage: ["schemeUsage", "scheme_usage", "themeColorUsage", "theme_color_usage", "colorUsage", "color_usage"],
    textFields: {
      content: ["text_body.text", "textBody.text", "txBody.text", "tx_body.text", "runs_text", "runsText"],
      fontFamily: ["font.face", "fontFace", "typefaceName", "typeface_name", "latinTypeface", "latin_typeface"],
      fontSize: ["font.pt", "fontPt", "font_size_pt", "fontSizePt", "runProperties.fontSize", "run_properties.font_size"],
      fontWeight: ["font.bold", "fontBold", "runProperties.bold", "run_properties.bold"],
      lineCount: ["renderedLines", "rendered_lines"],
      overflow: ["textOverflow", "text_overflow", "hasTextOverflow", "has_text_overflow"],
      foregroundColor: ["textFill", "text_fill", "runProperties.color", "run_properties.color"],
      intendedSingleLine: ["noWrap", "no_wrap", "textFrame.noWrap", "text_frame.no_wrap"],
      role: ["textRole", "text_role", "placeholderType", "placeholder_type"],
    },
  },
});

export function adaptTencentPptxTelemetry(input = {}) {
  return assertRenderTelemetry(adaptTelemetryWithMapping(input, TENCENT_PPTX_TELEMETRY_MAPPING));
}

export const adaptTencentPPTXTelemetry = adaptTencentPptxTelemetry;
export const adaptTencentPptx = adaptTencentPptxTelemetry;
