// Generic adapters expose renderer facts only. Render Telemetry 1.4.0 is reserved
// for assemble_render_telemetry after the production evidence contract is joined.
const ADAPTER_TELEMETRY_VERSION = "1.3.0";

const MISSING = Symbol("missing");

export const isRecord = (value) => Boolean(value) && typeof value === "object" && !Array.isArray(value);

const unique = (values) => [...new Set(values)];

function mergeMapping(base, override) {
  if (Array.isArray(base) || Array.isArray(override)) {
    return unique([...(Array.isArray(base) ? base : []), ...(Array.isArray(override) ? override : [])]);
  }
  if (isRecord(base) || isRecord(override)) {
    const output = {};
    for (const key of new Set([...Object.keys(base ?? {}), ...Object.keys(override ?? {})])) {
      output[key] = mergeMapping(base?.[key], override?.[key]);
    }
    return output;
  }
  return override === undefined ? base : override;
}

const BASE_MAPPING = {
  rendererAliases: ["renderer", "renderer_name", "rendererName", "engine", "adapter"],
  slide: {
    record: ["slide", "page", "slide_info", "slideInfo", "page_info", "pageInfo", "canvas"],
    id: ["slide_id", "slideId", "page_id", "pageId", "id", "name", "slide_number", "slideNumber"],
    layoutId: ["layout_id", "layoutId", "rpa_layout_id", "rpaLayoutId", "source_layout_id", "sourceLayoutId"],
    category: ["category", "slide_category", "slideCategory", "layout_type", "layoutType", "page_type", "pageType"],
    width: [
      "width", "slide_width", "slideWidth", "page_width", "pageWidth", "width_in", "widthIn",
      "slide_width_in", "slideWidthIn", "page_width_in", "pageWidthIn", "pptx_width", "pptxWidth",
      "size.width", "size.w", "dimensions.width", "dimensions.w", "slide_size.width", "slide_size.w", "page_size.width", "page_size.w",
      "slideSize.width", "slideSize.w", "pageSize.width", "pageSize.w", "size.0", "dimensions.0", "slide_size.0", "page_size.0", "pptx_in.width", "pptx_in.w",
    ],
    height: [
      "height", "slide_height", "slideHeight", "page_height", "pageHeight", "height_in", "heightIn",
      "slide_height_in", "slideHeightIn", "page_height_in", "pageHeightIn", "pptx_height", "pptxHeight",
      "size.height", "size.h", "dimensions.height", "dimensions.h", "slide_size.height", "slide_size.h", "page_size.height", "page_size.h",
      "slideSize.height", "slideSize.h", "pageSize.height", "pageSize.h", "size.1", "dimensions.1", "slide_size.1", "page_size.1", "pptx_in.height", "pptx_in.h",
    ],
    renderWidthPx: [
      "render_width_px", "renderWidthPx", "slide_render_width_px", "slideRenderWidthPx",
      "render_pixel_width", "renderPixelWidth", "pixel_width", "pixelWidth", "width_px", "widthPx",
      "render_size_px.width", "renderSizePx.width", "render_size.width", "renderSize.width",
      "render_size.width_px", "renderSize.widthPx", "render.width", "pixel_size.width", "pixelSize.width", "output.width", "rendered.width", "renderedWidth",
      "render_size_px.0", "renderSizePx.0", "render_size.0", "renderSize.0", "pixel_size.0", "pixelSize.0",
    ],
    renderHeightPx: [
      "render_height_px", "renderHeightPx", "slide_render_height_px", "slideRenderHeightPx",
      "render_pixel_height", "renderPixelHeight", "pixel_height", "pixelHeight", "height_px", "heightPx",
      "render_size_px.height", "renderSizePx.height", "render_size.height", "renderSize.height",
      "render_size.height_px", "renderSize.heightPx", "render.height", "pixel_size.height", "pixelSize.height", "output.height", "rendered.height", "renderedHeight",
      "render_size_px.1", "renderSizePx.1", "render_size.1", "renderSize.1", "pixel_size.1", "pixelSize.1",
    ],
    background: [
      "background", "slide_background", "slideBackground", "page_background", "pageBackground", "background_fill", "backgroundFill",
      "background_color", "backgroundColor", "bg_color", "bgColor", "canvas_background", "canvasBackground",
    ],
    elements: [
      "elements", "slide_elements", "slideElements", "page_elements", "pageElements", "items", "objects",
      "shapes", "nodes", "children",
    ],
    theme: ["theme", "theme_data", "themeData", "theme_config", "themeConfig", "presentation_theme", "presentationTheme"],
    themeId: ["theme_id", "themeId", "theme_name", "themeName"],
    themeTokens: ["theme_tokens", "themeTokens", "color_tokens", "colorTokens", "token_map", "tokenMap"],
    providedMetrics: ["provided_metrics", "providedMetrics", "metrics", "renderer_metrics", "rendererMetrics", "render_metrics", "renderMetrics", "measurements"],
  },
  element: {
    id: [
      "element_id", "elementId", "id", "object_id", "objectId", "shape_id", "shapeId", "node_id", "nodeId",
      "key", "name", "slot_id", "slotId",
    ],
    type: [
      "type", "element_type", "elementType", "kind", "object_type", "objectType", "shape_type", "shapeType",
      "node_type", "nodeType", "component_type", "componentType", "tag",
    ],
    qualityRole: [
      "quality_role", "qualityRole", "quality-role", "role", "semantic_role", "semanticRole",
      "visual_role", "visualRole", "layer_role", "layerRole", "element_role", "elementRole", "shape_role", "shapeRole", "category",
    ],
    zIndex: ["z_index", "zIndex", "z_order", "zOrder", "order", "layer_index", "layerIndex", "stack_index", "stackIndex"],
    opacity: ["opacity", "fill_opacity", "fillOpacity", "alpha", "style.opacity", "style.fillOpacity"],
    bbox: [
      "bbox", "bounding_box", "boundingBox", "bounds", "box", "rect", "rectangle", "frame", "geometry",
      "position", "layout_box", "layoutBox", "pptx_in", "pptxIn", "box_in", "boxIn", "placement",
    ],
    renderBboxPx: [
      "render_bbox_px", "renderBBoxPx", "render_box_px", "renderBoxPx", "bbox_px", "bboxPx",
      "pixel_bbox", "pixelBBox", "rendered_bbox_px", "renderedBBoxPx", "rendered_bbox", "renderedBBox",
      "rendered_box", "renderedBox", "render_bounds_px", "renderBoundsPx", "render_geometry", "renderGeometry",
      "rendered", "render",
    ],
    renderDirectSignals: [
      "x_px", "y_px", "width_px", "height_px", "w_px", "h_px", "left_px", "top_px", "right_px", "bottom_px",
      "render_x_px", "render_y_px", "render_width_px", "render_height_px", "renderLeftPx", "renderTopPx",
    ],
    text: ["text", "text_data", "textData", "text_info", "textInfo", "text_content", "textContent"],
    image: ["image", "image_data", "imageData", "image_info", "imageInfo", "media", "asset", "picture", "pictureData"],
    imageDisplayBbox: [
      "display_bbox", "displayBBox", "display_box", "displayBox", "display_bounds", "displayBounds",
      "display_bbox_px", "displayBBoxPx", "image_bbox", "imageBBox", "image_box", "imageBox", "placement",
    ],
    imageSourceWidth: [
      "source_width_px", "sourceWidthPx", "source_width", "sourceWidth", "intrinsic_width_px", "intrinsicWidthPx",
      "intrinsic_width", "intrinsicWidth", "natural_width_px", "naturalWidthPx", "natural_width", "naturalWidth",
      "original_width_px", "originalWidthPx", "original_width", "originalWidth", "asset_width_px", "assetWidthPx",
      "width_px", "widthPx", "source_dimensions.width", "sourceDimensions.width", "source.size.width",
      "sourceSize.width", "intrinsic_size.width", "intrinsicSize.width", "natural_size.width", "naturalSize.width",
      "source.width", "width",
    ],
    imageSourceHeight: [
      "source_height_px", "sourceHeightPx", "source_height", "sourceHeight", "intrinsic_height_px", "intrinsicHeightPx",
      "intrinsic_height", "intrinsicHeight", "natural_height_px", "naturalHeightPx", "natural_height", "naturalHeight",
      "original_height_px", "originalHeightPx", "original_height", "originalHeight", "asset_height_px", "assetHeightPx",
      "height_px", "heightPx", "source_dimensions.height", "sourceDimensions.height", "source.size.height",
      "sourceSize.height", "intrinsic_size.height", "intrinsicSize.height", "intrinsicSize.height", "natural_size.height",
      "naturalSize.height", "source.height", "height",
    ],
    fillColor: [
      "fill_color", "fillColor", "fill", "solid_fill", "solidFill", "paint.fill", "style.fill", "color_fill", "colorFill",
    ],
    backgroundColor: [
      "background_color", "backgroundColor", "bg_color", "bgColor", "background", "style.background",
      "style.backgroundColor", "fill_background", "fillBackground",
    ],
    themeToken: [
      "theme_token", "themeToken", "token", "color_token", "colorToken", "theme.token", "themeTokenValue",
      "style.theme_token", "style.themeToken", "style.token",
    ],
    themeUsage: [
      "theme_usage", "themeUsage", "token_usage", "tokenUsage", "usage", "theme.usage", "style.theme_usage",
      "style.themeUsage", "style.tokenUsage",
    ],
    textFields: {
      content: ["content", "value", "plain_text", "plainText", "text", "string", "text_value", "textValue"],
      language: ["language", "lang", "locale", "text_language", "textLanguage"],
      script: ["script", "text_script", "textScript", "unicode_script", "unicodeScript"],
      fontFamily: [
        "font_family", "fontFamily", "font_name", "fontName", "typeface", "font.face", "font.family", "font.name",
        "family",
      ],
      fontSize: [
        "font_size", "fontSize", "font_pt", "fontPt", "font_size_pt", "fontSizePt", "font.size", "font.pt", "size",
      ],
      fontWeight: ["font_weight", "fontWeight", "font_weight_pt", "fontWeightPt", "font.weight", "font.weight_value", "weight", "bold"],
      lineCount: ["line_count", "lineCount", "rendered_line_count", "renderedLineCount", "actual_line_count", "actualLineCount", "lines_count", "linesCount", "lines"],
      overflow: [
        "overflow", "is_overflow", "isOverflow", "text_overflow", "textOverflow", "has_overflow", "hasOverflow", "overflows",
      ],
      foregroundColor: [
        "foreground_color", "foregroundColor", "text_color", "textColor", "color", "font_color", "fontColor",
        "fill_color", "fillColor", "style.color", "font.color",
      ],
      localContrastRatio: ["local_contrast_ratio", "localContrastRatio", "measured_contrast_ratio", "measuredContrastRatio", "image_contrast_ratio", "imageContrastRatio"],
      intendedSingleLine: [
        "intended_single_line", "intendedSingleLine", "single_line", "singleLine", "no_wrap", "noWrap", "nowrap",
        "allow_wrap", "allowWrap", "wrap", "text_wrap", "textWrap",
      ],
      role: ["role", "text_role", "textRole", "semantic_role", "semanticRole", "slot_role", "slotRole"],
    },
    backgroundFlags: ["is_background", "isBackground", "background_element", "backgroundElement"],
    decorationFlags: ["is_decoration", "isDecoration", "decorative", "isDecorative", "decoration"],
    ignoreFlags: ["ignore", "ignored", "isIgnored", "exclude", "excluded", "exclude_from_quality", "excludeFromQuality"],
  },
};

export function createRendererMapping(renderer, overrides = {}) {
  return mergeMapping(BASE_MAPPING, { renderer, ...overrides });
}

export function normalizeRendererName(value) {
  if (typeof value !== "string" || !value.trim()) throw new TypeError("renderer is required");
  return value.trim().toLowerCase().replaceAll("_", "-");
}

function pathParts(path) {
  return Array.isArray(path) ? path : String(path).split(".");
}

export function readAlias(roots, aliases = []) {
  for (const root of roots) {
    if (!isRecord(root)) continue;
    for (const alias of aliases) {
      const parts = pathParts(alias);
      let current = root;
      let valid = true;
      for (const part of parts) {
        if (current === null || current === undefined || !Object.hasOwn(Object(current), part)) {
          valid = false;
          break;
        }
        current = current[part];
      }
      if (valid && current !== undefined) return { found: true, value: current, alias: String(alias) };
    }
  }
  return { found: false, value: MISSING, alias: undefined };
}

function addRoot(output, seen, value) {
  if (!isRecord(value) || seen.has(value)) return;
  seen.add(value);
  output.push(value);
}

export function buildInputRoots(input) {
  if (!isRecord(input)) throw new TypeError("renderer telemetry input must be an object");
  const roots = [];
  const seen = new Set();
  addRoot(roots, seen, input);
  for (const key of ["payload", "data", "telemetry", "result", "output", "renderer_output", "rendererOutput"]) {
    addRoot(roots, seen, input[key]);
  }
  return roots;
}

function addNestedRecordRoots(output, seen, source, keys) {
  if (!isRecord(source)) return;
  for (const key of keys) addRoot(output, seen, source[key]);
}

function recordRoots(primary, roots, nestedKeys) {
  const output = [];
  const seen = new Set();
  addRoot(output, seen, primary);
  for (const root of roots) addRoot(output, seen, root);
  for (const source of [...output]) addNestedRecordRoots(output, seen, source, nestedKeys);
  return output;
}

const ELEMENT_NESTED_KEYS = ["props", "properties", "attributes", "attrs", "style", "metadata", "meta", "layout"];
const TEXT_NESTED_KEYS = ["font", "typography", "style", "text_style", "textStyle", "attributes", "props", "properties"];
const IMAGE_NESTED_KEYS = [
  "source", "intrinsic", "intrinsic_size", "intrinsicSize", "natural", "natural_size", "naturalSize", "original",
  "source_dimensions", "sourceDimensions", "asset", "media", "placement", "display", "geometry", "style",
];

export function buildElementRoots(rawElement) {
  return recordRoots(rawElement, [rawElement], ELEMENT_NESTED_KEYS);
}

function buildFieldRoots(primary, roots, nestedKeys) {
  return recordRoots(primary, roots, nestedKeys);
}

function finiteNumber(value) {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function nullableNumber(roots, aliases) {
  const picked = readAlias(roots, aliases);
  return { found: picked.found, value: picked.found ? finiteNumber(picked.value) : null, raw: picked.value };
}

function nullableInteger(roots, aliases) {
  const picked = nullableNumber(roots, aliases);
  return {
    ...picked,
    value: picked.value !== null && Number.isInteger(picked.value) && picked.value >= 0 ? picked.value : null,
  };
}

function positiveInteger(roots, aliases) {
  const result = nullableInteger(roots, aliases);
  return { ...result, value: result.value !== null && result.value > 0 ? result.value : null };
}

function positiveNumber(roots, aliases) {
  const result = nullableNumber(roots, aliases);
  return { ...result, value: result.value !== null && result.value > 0 ? result.value : null };
}

function nullableString(roots, aliases) {
  const picked = readAlias(roots, aliases);
  return { found: picked.found, value: picked.found && typeof picked.value === "string" ? picked.value : null, raw: picked.value };
}

function nullableBoolean(roots, aliases) {
  const picked = readAlias(roots, aliases);
  if (!picked.found) return { found: false, value: null, raw: picked.value };
  if (typeof picked.value === "boolean") return { found: true, value: picked.value, raw: picked.value };
  if (picked.value === "true") return { found: true, value: true, raw: picked.value };
  if (picked.value === "false") return { found: true, value: false, raw: picked.value };
  return { found: true, value: null, raw: picked.value };
}

function identifier(value) {
  if (typeof value === "string" && value.trim()) return value;
  if (typeof value === "number" && Number.isFinite(value)) return String(value);
  return null;
}

function readIdentifier(roots, aliases) {
  const picked = readAlias(roots, aliases);
  return { found: picked.found, value: picked.found ? identifier(picked.value) : null };
}

function colorValue(value, depth = 0) {
  if (typeof value === "string") return value;
  if (!isRecord(value) || depth > 2) return null;
  for (const key of ["color", "value", "hex", "hex_value", "hexValue", "foreground", "background"]) {
    if (Object.hasOwn(value, key)) {
      const result = colorValue(value[key], depth + 1);
      if (result !== null) return result;
    }
  }
  return null;
}

function readColor(roots, aliases) {
  const picked = readAlias(roots, aliases);
  return { found: picked.found, value: picked.found ? colorValue(picked.value) : null };
}

const BOX_NESTED_KEYS = ["bbox", "bounding_box", "boundingBox", "bounds", "box", "rect", "rectangle", "frame", "geometry", "position", "placement"];
const BOX_COORDINATES = {
  bbox: {
    x: ["x", "left", "x_in", "xIn", "left_in", "leftIn", "l"],
    y: ["y", "top", "y_in", "yIn", "top_in", "topIn", "t"],
    width: ["width", "w", "width_in", "widthIn", "w_in", "wIn"],
    height: ["height", "h", "height_in", "heightIn", "h_in", "hIn"],
    right: ["right", "right_in", "rightIn", "x2"],
    bottom: ["bottom", "bottom_in", "bottomIn", "y2"],
  },
  render: {
    x: ["x_px", "xPx", "render_x_px", "renderXPx", "left_px", "leftPx", "x", "left", "l"],
    y: ["y_px", "yPx", "render_y_px", "renderYPx", "top_px", "topPx", "y", "top", "t"],
    width: ["width_px", "widthPx", "render_width_px", "renderWidthPx", "w_px", "wPx", "width", "w"],
    height: ["height_px", "heightPx", "render_height_px", "renderHeightPx", "h_px", "hPx", "height", "h"],
    right: ["right_px", "rightPx", "render_right_px", "renderRightPx", "right", "x2"],
    bottom: ["bottom_px", "bottomPx", "render_bottom_px", "renderBottomPx", "bottom", "y2"],
  },
};

function directBox(value, mode) {
  if (Array.isArray(value)) {
    if (value.length < 4) return null;
    const numbers = value.slice(0, 4).map(finiteNumber);
    if (numbers.some((item) => item === null) || numbers[2] < 0 || numbers[3] < 0) return null;
    return { x: numbers[0], y: numbers[1], width: numbers[2], height: numbers[3] };
  }
  if (!isRecord(value)) return null;
  const coordinates = BOX_COORDINATES[mode];
  const x = nullableNumber([value], coordinates.x).value;
  const y = nullableNumber([value], coordinates.y).value;
  let width = nullableNumber([value], coordinates.width).value;
  let height = nullableNumber([value], coordinates.height).value;
  if (x === null || y === null) return null;
  if (width === null) {
    const right = nullableNumber([value], coordinates.right).value;
    if (right !== null) width = right - x;
  }
  if (height === null) {
    const bottom = nullableNumber([value], coordinates.bottom).value;
    if (bottom !== null) height = bottom - y;
  }
  if (width === null || height === null || width < 0 || height < 0) return null;
  return { x, y, width, height };
}

export function normalizeBox(value, mode = "bbox", depth = 0) {
  if (depth > 3) return null;
  const direct = directBox(value, mode);
  if (direct) return direct;
  if (!isRecord(value)) return null;
  for (const key of BOX_NESTED_KEYS) {
    if (Object.hasOwn(value, key)) {
      const nested = normalizeBox(value[key], mode, depth + 1);
      if (nested) return nested;
    }
  }
  return null;
}

function boxFromRoots(roots, aliases, mode, directSignals = [], allowDirect = true) {
  const picked = readAlias(roots, aliases);
  if (picked.found) {
    const normalized = normalizeBox(picked.value, mode);
    if (normalized) return { found: true, value: normalized };
  }
  if (mode === "bbox" && allowDirect) {
    for (const root of roots) {
      const normalized = normalizeBox(root, mode);
      if (normalized) return { found: true, value: normalized };
    }
  } else if (directSignals.length) {
    for (const root of roots) {
      if (!readAlias([root], directSignals).found) continue;
      const normalized = normalizeBox(root, mode);
      if (normalized) return { found: true, value: normalized };
    }
  }
  return { found: picked.found, value: null };
}

function addMissing(unavailable, field, reason) {
  unavailable.add(field, reason);
}

export function createUnavailableCollector() {
  const entries = [];
  const seen = new Set();
  return {
    add(field, reason) {
      const key = `${field}\u0000${reason}`;
      if (seen.has(key)) return;
      seen.add(key);
      entries.push({ field, reason });
    },
    values() {
      return entries.map((entry) => ({ ...entry }));
    },
  };
}

function normalizeElementType(value) {
  if (typeof value !== "string") return null;
  const normalized = value.trim().toLowerCase().replace(/[\s_-]+/g, "");
  const aliases = {
    text: "text", textbox: "text", textshape: "text", richtext: "text", paragraph: "text", heading: "text", title: "text",
    subtitle: "text", caption: "text", label: "text", body: "text",
    image: "image", picture: "image", img: "image", photo: "image", photograph: "image", figure: "image", raster: "image", bitmap: "image",
    shape: "shape", rect: "shape", rectangle: "shape", roundedrectangle: "shape", ellipse: "shape", circle: "shape", line: "shape", arrow: "shape", connector: "shape", vector: "shape", svg: "shape", background: "shape",
    chart: "chart", graph: "chart", plot: "chart",
    table: "table", grid: "table",
    group: "group", container: "group", frame: "group",
    other: "other", unknown: "other",
  };
  return aliases[normalized] ?? "other";
}

function normalizeQualityRole(value) {
  if (typeof value !== "string") return null;
  const normalized = value.trim().toLowerCase().replace(/[\s_-]+/g, "");
  const aliases = {
    content: "content", foreground: "content", main: "content", maincontent: "content", ordinary: "content", normal: "content",
    decoration: "decoration", decorative: "decoration", ornament: "decoration", ornamental: "decoration", accent: "decoration", border: "decoration", divider: "decoration",
    background: "background", bg: "background", backdrop: "background", canvas: "background", slidebackground: "background", pagebackground: "background",
    ignore: "ignore", ignored: "ignore", excluded: "ignore", exclude: "ignore", noncontent: "ignore", nonsemantic: "ignore",
  };
  return aliases[normalized] ?? null;
}

function explicitRole(roots, mapping, rawType) {
  const role = readAlias(roots, mapping.element.qualityRole);
  const normalizedRole = role.found ? normalizeQualityRole(role.value) : null;
  if (normalizedRole) return { value: normalizedRole, explicit: true };
  const flag = (aliases, roleValue) => {
    const value = nullableBoolean(roots, aliases);
    return value.value === true ? roleValue : null;
  };
  return {
    value: flag(mapping.element.ignoreFlags, "ignore") ?? flag(mapping.element.backgroundFlags, "background") ?? flag(mapping.element.decorationFlags, "decoration") ?? (normalizeQualityRole(rawType) === "background" ? "background" : null) ?? "content",
    explicit: Boolean(normalizedRole) || flag(mapping.element.ignoreFlags, "ignore") !== null || flag(mapping.element.backgroundFlags, "background") !== null || flag(mapping.element.decorationFlags, "decoration") !== null || normalizeQualityRole(rawType) === "background",
  };
}

function rawElementList(value) {
  if (Array.isArray(value)) return value;
  if (!isRecord(value)) return null;
  for (const key of ["items", "elements", "objects", "shapes", "children", "nodes"]) {
    if (Array.isArray(value[key])) return value[key];
  }
  return Object.keys(value).map((key) => {
    const item = value[key];
    if (!isRecord(item)) return item;
    if (identifier(item.id ?? item.element_id ?? item.elementId ?? item.object_id ?? item.objectId)) return item;
    return { ...item, id: key };
  });
}

function mapText(roots, mapping, index, unavailable) {
  const textPicked = readAlias(roots, mapping.element.text);
  const primary = isRecord(textPicked.value) ? textPicked.value : undefined;
  const textRoots = buildFieldRoots(primary, roots, TEXT_NESTED_KEYS);
  const field = (aliases, normalize, name) => {
    const result = normalize(textRoots, aliases);
    if (result.value === null) addMissing(unavailable, `elements[${index}].text.${name}`, result.found ? "renderer supplied no reliable value for this text field" : "renderer did not expose this text field");
    return result.value;
  };
  const content = field(mapping.element.textFields.content, nullableString, "content");
  const language = field(mapping.element.textFields.language, nullableString, "language");
  const script = field(mapping.element.textFields.script, nullableString, "script");
  const font_family = field(mapping.element.textFields.fontFamily, nullableString, "font_family");
  const font_size = field(mapping.element.textFields.fontSize, positiveNumber, "font_size");
  const fontWeightResult = readAlias(textRoots, mapping.element.textFields.fontWeight);
  let font_weight = null;
  if (fontWeightResult.found && (typeof fontWeightResult.value === "string" || finiteNumber(fontWeightResult.value) !== null)) font_weight = fontWeightResult.value;
  else if (fontWeightResult.found && typeof fontWeightResult.value === "boolean") font_weight = fontWeightResult.value ? "bold" : "normal";
  else addMissing(unavailable, `elements[${index}].text.font_weight`, fontWeightResult.found ? "renderer supplied no reliable value for this text field" : "renderer did not expose this text field");
  const lineResult = readAlias(textRoots, mapping.element.textFields.lineCount);
  let line_count = null;
  if (lineResult.found) {
    if (Array.isArray(lineResult.value)) line_count = lineResult.value.length;
    else if (Number.isInteger(lineResult.value) && lineResult.value >= 0) line_count = lineResult.value;
  }
  if (line_count === null) addMissing(unavailable, `elements[${index}].text.line_count`, lineResult.found ? "renderer supplied no reliable value for this text field" : "renderer did not expose this text field");
  const overflow = field(mapping.element.textFields.overflow, nullableBoolean, "overflow");
  const foreground_color = field(mapping.element.textFields.foregroundColor, readColor, "foreground_color");
  const local_contrast_ratio = field(mapping.element.textFields.localContrastRatio, positiveNumber, "local_contrast_ratio");
  const single = readAlias(textRoots, mapping.element.textFields.intendedSingleLine);
  let intended_single_line = null;
  if (single.found) {
    if (typeof single.value === "boolean") intended_single_line = single.value;
    else if (single.alias === "allow_wrap" || single.alias === "allowWrap") intended_single_line = single.value === false;
    else if (single.alias === "wrap" || single.alias === "text_wrap" || single.alias === "textWrap") intended_single_line = single.value === false;
    else if (single.value === "true") intended_single_line = true;
    else if (single.value === "false") intended_single_line = false;
  }
  if (intended_single_line === null) addMissing(unavailable, `elements[${index}].text.intended_single_line`, single.found ? "renderer supplied no reliable value for this text field" : "renderer did not expose this text field");
  const role = field(mapping.element.textFields.role, nullableString, "role");
  return { content, language, script, font_family, font_size, font_weight, line_count, overflow, foreground_color, local_contrast_ratio, intended_single_line, role };
}

function mapImage(roots, mapping, index, unavailable) {
  const imagePicked = readAlias(roots, mapping.element.image);
  const primary = isRecord(imagePicked.value) ? imagePicked.value : undefined;
  const imageRoots = buildFieldRoots(primary, roots, IMAGE_NESTED_KEYS);
  const display = boxFromRoots(imageRoots, mapping.element.imageDisplayBbox, "bbox", [], false);
  const display_bbox = display.value ?? null;
  if (!display_bbox) addMissing(unavailable, `elements[${index}].image.display_bbox`, display.found ? "renderer supplied no reliable image display box" : "renderer did not expose an image display box");
  const sourceWidth = positiveInteger(imageRoots, mapping.element.imageSourceWidth);
  const sourceHeight = positiveInteger(imageRoots, mapping.element.imageSourceHeight);
  if (sourceWidth.value === null) addMissing(unavailable, `elements[${index}].image.source_width_px`, sourceWidth.found ? "renderer supplied no reliable source width" : "renderer did not expose source width in pixels");
  if (sourceHeight.value === null) addMissing(unavailable, `elements[${index}].image.source_height_px`, sourceHeight.found ? "renderer supplied no reliable source height" : "renderer did not expose source height in pixels");
  const requiredString = (aliases, name) => {
    const result = nullableString(imageRoots, aliases);
    if (result.value === null) addMissing(unavailable, `elements[${index}].image.${name}`, result.found ? `renderer supplied no reliable ${name}` : `renderer did not expose ${name}`);
    return result.value;
  };
  const visual_id = requiredString(["visual_id", "visualId", "figure_id", "figureId", "asset_id", "assetId"], "visual_id");
  const content_id = requiredString(["content_id", "contentId", "rpa_content_id", "rpaContentId"], "content_id");
  const slot_id = requiredString(["slot_id", "slotId", "rpa_slot_id", "rpaSlotId"], "slot_id");
  const visual_type = requiredString(["visual_type", "visualType", "figure_type", "figureType"], "visual_type");
  const panelResult = positiveInteger(imageRoots, ["panel_count", "panelCount", "figure_panel_count", "figurePanelCount"]);
  if (panelResult.value === null) addMissing(unavailable, `elements[${index}].image.panel_count`, panelResult.found ? "renderer supplied no reliable panel count" : "renderer did not expose panel count");
  const embeddedResult = nullableBoolean(imageRoots, ["has_embedded_text", "hasEmbeddedText", "contains_text", "containsText"]);
  if (embeddedResult.value === null) addMissing(unavailable, `elements[${index}].image.has_embedded_text`, embeddedResult.found ? "renderer supplied no reliable embedded-text flag" : "renderer did not expose embedded-text presence");
  const minWidthResult = readAlias(imageRoots, ["min_display_width", "minDisplayWidth", "minimum_display_width", "minimumDisplayWidth"]);
  const min_display_width = boundedRatioValue(minWidthResult.value);
  const allocated = boxFromRoots(imageRoots, ["allocated_bbox", "allocatedBox", "slot_bbox", "slotBox", "requested_bbox", "requestedBox", "full_box", "fullBox"], "bbox", [], false);
  const allocated_bbox = allocated.value ?? null;
  if (!allocated_bbox) addMissing(unavailable, `elements[${index}].image.allocated_bbox`, allocated.found ? "renderer supplied no reliable allocated visual box" : "renderer did not expose allocated visual geometry");
  const embeddedPxResult = readAlias(imageRoots, ["rendered_embedded_text_px", "renderedEmbeddedTextPx", "embedded_text_px", "embeddedTextPx"]);
  const embeddedPx = finiteNumber(embeddedPxResult.value);
  const rendered_embedded_text_px = embeddedPx !== null && embeddedPx >= 0 ? embeddedPx : null;
  if (embeddedResult.value === true && rendered_embedded_text_px === null) {
    addMissing(unavailable, `elements[${index}].image.rendered_embedded_text_px`, embeddedPxResult.found ? "renderer supplied no reliable embedded-text measurement" : "renderer did not measure embedded text height");
  }
  const sourceRegion = boxFromRoots(imageRoots, ["source_region_bbox", "sourceRegionBbox", "source_region", "sourceRegion"], "bbox", [], false);
  const effectiveSourceRegion = boxFromRoots(imageRoots, ["effective_source_region", "effectiveSourceRegion", "actual_source_region", "actualSourceRegion"], "bbox", [], false);
  const effectivePlacement = boxFromRoots(imageRoots, ["effective_placement", "effectivePlacement", "actual_placement", "actualPlacement"], "bbox", [], false);
  const coordinateSpace = nullableString(imageRoots, ["source_region_coordinate_space", "sourceRegionCoordinateSpace"]);
  const effectiveFitMode = nullableString(imageRoots, ["effective_fit_mode", "effectiveFitMode", "fit_mode", "fitMode"]);
  const letterboxResult = nullableNumber(imageRoots, ["actual_letterbox_ratio", "actualLetterboxRatio", "letterbox_ratio", "letterboxRatio"]);
  const visibleRegions = readAlias(imageRoots, ["visible_region_ids", "visibleRegionIds", "visible_panel_ids", "visiblePanelIds"]);
  const visibleLabels = readAlias(imageRoots, ["visible_label_ids", "visibleLabelIds"]);
  const parentResult = nullableString(imageRoots, ["visual_parent_id", "visualParentId", "container_id", "containerId"]);
  const relationResult = nullableString(imageRoots, ["relation.type", "relation_type", "relationType"]);
  return {
    display_bbox,
    source_width_px: sourceWidth.value,
    source_height_px: sourceHeight.value,
    visual_id,
    content_id,
    slot_id,
    visual_type,
    panel_count: panelResult.value,
    has_embedded_text: embeddedResult.value,
    min_display_width,
    allocated_bbox,
    rendered_embedded_text_px,
    ...(sourceRegion.value ? { source_region_bbox: sourceRegion.value } : {}),
    ...(parentResult.value ? { visual_parent_id: parentResult.value } : {}),
    ...(relationResult.value === "visual_child" ? { relation: { type: "visual_child" } } : {}),
    ...(effectiveSourceRegion.value ? { effective_source_region: effectiveSourceRegion.value } : {}),
    ...(effectivePlacement.value ? { effective_placement: effectivePlacement.value } : {}),
    ...(["source_normalized_0_1", "source_pixels"].includes(coordinateSpace.value) ? { source_region_coordinate_space: coordinateSpace.value } : {}),
    ...(["contain", "cover", "stretch"].includes(effectiveFitMode.value) ? { effective_fit_mode: effectiveFitMode.value } : {}),
    ...(letterboxResult.value !== null ? { actual_letterbox_ratio: Math.max(0, Math.min(1, letterboxResult.value)) } : {}),
    ...(Array.isArray(visibleRegions.value) ? { visible_region_ids: unique(visibleRegions.value.map(String)) } : {}),
    ...(Array.isArray(visibleLabels.value) ? { visible_label_ids: unique(visibleLabels.value.map(String)) } : {}),
  };
}

function stringArray(value) {
  if (!Array.isArray(value)) return null;
  if (value.some((item) => typeof item !== "string")) return null;
  return unique(value);
}

function mapTheme(rawTheme, mapping, roots, unavailable) {
  const themePicked = readAlias(roots, mapping.slide.theme);
  const idPicked = readAlias(roots, mapping.slide.themeId);
  const tokensPicked = readAlias(roots, mapping.slide.themeTokens);
  let raw = themePicked.found ? themePicked.value : undefined;
  if (!themePicked.found && (idPicked.found || tokensPicked.found)) raw = { id: idPicked.value, tokens: tokensPicked.value };
  if (raw === undefined || raw === null) {
    addMissing(unavailable, "theme", "renderer did not expose theme metadata");
    return null;
  }
  if (typeof raw === "string") raw = { id: raw, tokens: undefined };
  if (!isRecord(raw)) {
    addMissing(unavailable, "theme", "renderer supplied an unreliable theme value");
    return null;
  }
  const idResult = nullableString([raw], ["id", "theme_id", "themeId", "name", "theme_name", "themeName", "key"]);
  const id = idResult.value;
  if (id === null) addMissing(unavailable, "theme.id", idResult.found ? "renderer supplied no reliable theme id" : "renderer did not expose a theme id");
  const tokenResult = readAlias([raw], ["tokens", "theme_tokens", "themeTokens", "colors", "palette", "color_tokens", "colorTokens", "token_map", "tokenMap"]);
  const tokenSource = tokenResult.found ? tokenResult.value : undefined;
  const tokens = {};
  if (!isRecord(tokenSource)) {
    addMissing(unavailable, "theme.tokens", tokenResult.found ? "renderer supplied no reliable theme token map" : "renderer did not expose theme tokens");
  } else {
    for (const tokenId of Object.keys(tokenSource).sort()) {
      const tokenRaw = tokenSource[tokenId];
      const tokenRoots = isRecord(tokenRaw) ? [tokenRaw] : [];
      const color = colorValue(tokenRaw);
      const allowedPicked = readAlias(tokenRoots, ["allowed_usage", "allowedUsage", "allowed", "allowed_roles", "allowedRoles"]);
      const forbiddenPicked = readAlias(tokenRoots, ["forbidden_usage", "forbiddenUsage", "forbidden", "forbidden_roles", "forbiddenRoles"]);
      const allowed = allowedPicked.found ? stringArray(allowedPicked.value) : [];
      const forbidden = forbiddenPicked.found ? stringArray(forbiddenPicked.value) : [];
      tokens[tokenId] = { color, allowed_usage: allowed ?? [], forbidden_usage: forbidden ?? [] };
      if (color === null) addMissing(unavailable, `theme.tokens.${tokenId}.color`, "renderer did not expose a reliable token color");
      if (!allowedPicked.found || allowed === null) addMissing(unavailable, `theme.tokens.${tokenId}.allowed_usage`, "renderer did not expose allowed token usage");
      if (!forbiddenPicked.found || forbidden === null) addMissing(unavailable, `theme.tokens.${tokenId}.forbidden_usage`, "renderer did not expose forbidden token usage");
    }
  }
  return { id, tokens };
}

function mapBackground(roots, mapping, unavailable) {
  const picked = readAlias(roots, mapping.slide.background);
  if (!picked.found) {
    addMissing(unavailable, "slide.background", "renderer did not expose slide background metadata");
    return { kind: "unknown", color: null };
  }
  const raw = picked.value;
  if (typeof raw === "string") return { kind: "solid", color: raw };
  if (!isRecord(raw)) {
    addMissing(unavailable, "slide.background", "renderer supplied an unreliable slide background value");
    return { kind: "unknown", color: null };
  }
  const kindPicked = readAlias([raw], ["kind", "type", "background_type", "backgroundType"]);
  const kindValue = typeof kindPicked.value === "string" ? kindPicked.value.trim().toLowerCase().replace(/[\s_-]+/g, "") : "";
  const color = colorValue(readAlias([raw], ["color", "background_color", "backgroundColor", "fill", "fillColor", "hex"]).value);
  let kind;
  if (["solid", "color", "solidcolor", "fill"].includes(kindValue)) kind = "solid";
  else if (["image", "picture", "photo", "bitmap", "raster"].includes(kindValue)) kind = "image";
  else if (["gradient", "lineargradient", "radialgradient"].includes(kindValue)) kind = "gradient";
  else if (["transparent", "none", "clear"].includes(kindValue)) kind = "transparent";
  else if (["unknown", "unavailable", "missing"].includes(kindValue)) kind = "unknown";
  else if (readAlias([raw], ["transparent", "isTransparent"]).value === true) kind = "transparent";
  else if (color !== null) kind = "solid";
  else if (readAlias([raw], ["image", "image_url", "imageUrl", "src", "url"]).found) kind = "image";
  else if (readAlias([raw], ["gradient", "stops", "gradientStops"]).found) kind = "gradient";
  else kind = "unknown";
  if (!kindPicked.found && kind === "unknown") addMissing(unavailable, "slide.background.kind", "renderer did not expose a reliable background kind");
  if (kind === "solid" && color === null) addMissing(unavailable, "slide.background.color", "renderer did not expose a solid background color");
  return { kind, color };
}

function mapElement(rawElement, index, mapping, unavailable) {
  const elementRoots = buildElementRoots(rawElement);
  const idResult = readIdentifier(elementRoots, mapping.element.id);
  if (idResult.value === null) throw new TypeError(`elements[${index}] requires a non-empty element id`);
  const typePicked = readAlias(elementRoots, mapping.element.type);
  const type = normalizeElementType(typePicked.value);
  if (!typePicked.found || type === "other" && typeof typePicked.value === "string" && !["other", "unknown"].includes(typePicked.value.trim().toLowerCase())) {
    addMissing(unavailable, `elements[${index}].type`, typePicked.found ? "renderer supplied an unrecognized element type; mapped to other" : "renderer did not expose an element type; mapped to other");
  }
  const roleResult = explicitRole(elementRoots, mapping, typePicked.value);
  if (!roleResult.explicit) addMissing(unavailable, `elements[${index}].quality_role`, "renderer did not expose an explicit quality role; defaulted to content");
  const bboxResult = boxFromRoots(elementRoots, mapping.element.bbox, "bbox");
  if (!bboxResult.value) addMissing(unavailable, `elements[${index}].bbox`, bboxResult.found ? "renderer supplied no reliable element box" : "renderer did not expose an element box");
  const renderResult = boxFromRoots(elementRoots, mapping.element.renderBboxPx, "render", mapping.element.renderDirectSignals);
  if (!renderResult.value) addMissing(unavailable, `elements[${index}].render_bbox_px`, renderResult.found ? "renderer supplied no reliable rendered pixel box" : "renderer did not expose a rendered pixel box");
  const text = type === "text" ? mapText(elementRoots, mapping, index, unavailable) : null;
  const image = type === "image" ? mapImage(elementRoots, mapping, index, unavailable) : null;
  const fill = readColor(elementRoots, mapping.element.fillColor);
  const background = readColor(elementRoots, mapping.element.backgroundColor);
  const themeToken = nullableString(elementRoots, mapping.element.themeToken);
  const themeUsage = nullableString(elementRoots, mapping.element.themeUsage);
  const zIndex = nullableNumber(elementRoots, mapping.element.zIndex);
  const opacityResult = nullableNumber(elementRoots, mapping.element.opacity);
  const opacity = opacityResult.value !== null && opacityResult.value >= 0 && opacityResult.value <= 1 ? opacityResult.value : null;
  const geometryKind = nullableString(elementRoots, ["geometry_kind", "geometryKind", "shape_kind", "shapeKind", "kind"]);
  const rawRelation = readAlias(elementRoots, ["relation"]);
  const relationType = nullableString(isRecord(rawRelation.value) ? [rawRelation.value] : elementRoots, ["type", "relation_type", "relationType"]);
  const relationTarget = nullableString(isRecord(rawRelation.value) ? [rawRelation.value] : elementRoots, ["target_id", "targetId", "relation_target_id", "relationTargetId"]);
  const relationSource = nullableString(isRecord(rawRelation.value) ? [rawRelation.value] : elementRoots, ["source", "relation_source", "relationSource"]);
  const sourceElementId = nullableString(elementRoots, ["source_element_id", "sourceElementId"]);
  if (zIndex.value === null) addMissing(unavailable, `elements[${index}].z_index`, zIndex.found ? "renderer supplied no reliable z-order" : "renderer did not expose element z-order");
  if (opacity === null) addMissing(unavailable, `elements[${index}].opacity`, opacityResult.found ? "renderer supplied no reliable opacity" : "renderer did not expose element opacity");
  if (fill.value === null) addMissing(unavailable, `elements[${index}].fill_color`, fill.found ? "renderer supplied no reliable fill color" : "renderer did not expose fill color");
  if (background.value === null) addMissing(unavailable, `elements[${index}].background_color`, background.found ? "renderer supplied no reliable background color" : "renderer did not expose background color");
  if (themeToken.value === null) addMissing(unavailable, `elements[${index}].theme_token`, themeToken.found ? "renderer supplied no reliable theme token" : "renderer did not expose a theme token");
  if (themeUsage.value === null) addMissing(unavailable, `elements[${index}].theme_usage`, themeUsage.found ? "renderer supplied no reliable theme usage" : "renderer did not expose theme usage");
  return {
    element_id: idResult.value,
    type: type ?? "other",
    quality_role: roleResult.value,
    z_index: zIndex.value,
    opacity,
    bbox: bboxResult.value,
    render_bbox_px: renderResult.value,
    text,
    image,
    fill_color: fill.value,
    background_color: background.value,
    theme_token: themeToken.value,
    theme_usage: themeUsage.value,
    ...(geometryKind.value ? { geometry_kind: geometryKind.value } : {}),
    ...(relationType.value && relationTarget.value ? { relation: { type: relationType.value, target_id: relationTarget.value, source: relationSource.value ?? "renderer" } } : {}),
    ...(sourceElementId.value ? { source_element_id: sourceElementId.value } : {}),
  };
}

function boundedRatioValue(value) {
  const number = finiteNumber(value);
  return number !== null && number >= 0 && number <= 1 ? number : null;
}

function positiveMetricValue(value) {
  const number = finiteNumber(value);
  return number !== null && number > 0 ? number : null;
}

function normalizeProvidedMetrics(raw) {
  if (!isRecord(raw)) return {};
  const output = {};
  const ratioFields = {
    content_footprint: ["content_footprint", "contentFootprint", "content_occupancy", "contentOccupancy"],
    largest_empty_band: ["largest_empty_band", "largestEmptyBand"],
    content_center_x: ["content_center_x", "contentCenterX"],
    content_center_y: ["content_center_y", "contentCenterY"],
  };
  for (const [fieldName, aliases] of Object.entries(ratioFields)) {
    const picked = readAlias([raw], aliases);
    if (picked.found) output[fieldName] = boundedRatioValue(picked.value);
  }
  const intentional = readAlias([raw], ["intentional_whitespace", "intentionalWhitespace"]);
  if (intentional.found && typeof intentional.value === "boolean") output.intentional_whitespace = intentional.value;
  const visualList = readAlias([raw], ["visuals", "visual_metrics", "visualMetrics"]);
  if (visualList.found && Array.isArray(visualList.value)) {
    output.visuals = visualList.value.filter(isRecord).map((visual) => ({
      visual_type: String(readAlias([visual], ["visual_type", "visualType", "type"]).value ?? "visual_evidence"),
      panel_count: Math.max(0, Math.round(finiteNumber(readAlias([visual], ["panel_count", "panelCount"]).value) ?? 1)),
      has_embedded_text: readAlias([visual], ["has_embedded_text", "hasEmbeddedText"]).value === true,
      min_display_width: boundedRatioValue(readAlias([visual], ["min_display_width", "minDisplayWidth"]).value),
      display_width_norm: boundedRatioValue(readAlias([visual], ["display_width_norm", "display_width", "displayWidth"]).value),
      display_height_norm: boundedRatioValue(readAlias([visual], ["display_height_norm", "display_height", "displayHeight"]).value),
      rendered_embedded_text_px: positiveMetricValue(readAlias([visual], ["rendered_embedded_text_px", "embedded_text_px", "embeddedTextPx"]).value),
    }));
  }
  return output;
}

export function adaptTelemetryWithMapping(input, mapping) {
  const roots = buildInputRoots(input);
  const unavailable = createUnavailableCollector();
  const slidePicked = readAlias(roots, mapping.slide.record);
  const slideRecord = isRecord(slidePicked.value) ? slidePicked.value : undefined;
  const slideRoots = recordRoots(slideRecord, roots, ["size", "dimensions", "render_size", "renderSize", "render_size_px", "renderSizePx", "background", "theme"]);
  const idResult = readIdentifier(slideRoots, mapping.slide.id);
  if (idResult.value === null) throw new TypeError("renderer telemetry requires a non-empty slide id");
  const width = nullableNumber(slideRoots, mapping.slide.width).value;
  const height = nullableNumber(slideRoots, mapping.slide.height).value;
  if (width === null || width <= 0 || height === null || height <= 0) throw new TypeError("renderer telemetry requires positive slide width and height");
  const renderWidth = positiveInteger(slideRoots, mapping.slide.renderWidthPx);
  const renderHeight = positiveInteger(slideRoots, mapping.slide.renderHeightPx);
  if (renderWidth.value === null) addMissing(unavailable, "slide.render_width_px", renderWidth.found ? "renderer supplied no reliable render width in pixels" : "renderer did not expose render width in pixels");
  if (renderHeight.value === null) addMissing(unavailable, "slide.render_height_px", renderHeight.found ? "renderer supplied no reliable render height in pixels" : "renderer did not expose render height in pixels");
  const background = mapBackground(slideRoots, mapping, unavailable);
  const layoutId = nullableString(slideRoots, mapping.slide.layoutId);
  const category = nullableString(slideRoots, mapping.slide.category);
  if (layoutId.value === null) addMissing(unavailable, "slide.layout_id", layoutId.found ? "renderer supplied no reliable source layout id" : "renderer did not expose source layout id");
  if (category.value === null) addMissing(unavailable, "slide.category", category.found ? "renderer supplied no reliable slide category" : "renderer did not expose slide category");
  const rawElementsPicked = readAlias(slideRoots, mapping.slide.elements);
  const rawElements = rawElementsPicked.found ? rawElementList(rawElementsPicked.value) : [];
  if (!rawElementsPicked.found || !rawElements) addMissing(unavailable, "elements", "renderer did not expose an element collection");
  const elements = (rawElements ?? []).map((rawElement, index) => mapElement(rawElement, index, mapping, unavailable));
  const themeRoots = recordRoots(slideRecord, roots, ["theme"]);
  const theme = mapTheme(undefined, mapping, themeRoots, unavailable);
  const providedPicked = readAlias(roots, mapping.slide.providedMetrics);
  const provided_metrics = normalizeProvidedMetrics(providedPicked.value);
  const containerPicked = readAlias(slideRoots, ["visual_containers", "visualContainers"]);
  const visual_containers = Array.isArray(containerPicked.value) ? structuredClone(containerPicked.value) : [];
  return {
    telemetry_version: ADAPTER_TELEMETRY_VERSION,
    slide_id: idResult.value,
    renderer: mapping.renderer,
    slide: {
      width,
      height,
      render_width_px: renderWidth.value,
      render_height_px: renderHeight.value,
      background,
      layout_id: layoutId.value,
      category: category.value,
    },
    elements,
    visual_containers,
    theme,
    unavailable: unavailable.values(),
    provided_metrics,
  };
}
