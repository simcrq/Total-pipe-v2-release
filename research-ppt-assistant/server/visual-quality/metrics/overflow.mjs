const includedRole = (role, includeDecoration) => role === "content" || (includeDecoration && role === "decoration");

// Text-fit heuristics used by the render-time overflow gate.
// In the v1.2.0 telemetry contract `text.font_size` is expressed in points:
// legacy adapters map legacy `font_pt` straight onto it (legacy-adapter.mjs), and
// the viewing profiles compare it against pt-scale floors (body_fail: 16, title_minimum: 35).
const LINE_HEIGHT_FACTOR = 1.20;
const PADDING_X_PT = 8;
const PADDING_Y_PT = 4;
const PT_PER_INCH = 72;
// The contract carries `font_size` but not `line-height`, and in-box padding is not
// reported either, so the estimate has to assume both. Real renderers vary (1.15 is
// as common as 1.2), and a tight but valid title can land a few percent over a naive
// estimate without ever being clipped. Absorb that with an explicit assumption margin
// so the gate only fails on overflow that is real: clipped text typically overruns by
// a whole line (20%+) whereas assumption noise stays in the low single digits.
const ASSUMPTION_MARGIN_RATIO = 0.10;
const ASSUMPTION_MARGIN_PT = 1;

function assertSlide(slide) {
  if (!slide || typeof slide !== "object" || !Number.isFinite(slide.width) || !Number.isFinite(slide.height) || slide.width <= 0 || slide.height <= 0) {
    throw new TypeError("slide width and height must be positive finite numbers");
  }
}

// How many geometry units make up one inch. When rendered pixels are reported we
// work in `render_bbox_px`; otherwise `bbox` shares the slide's native unit.
function unitsPerInch(slide, useRenderPixels) {
  if (!useRenderPixels) return 1;
  const ratio = slide.render_width_px / slide.width;
  return Number.isFinite(ratio) && ratio > 0 ? ratio : 1;
}

function isFullWidthCode(code) {
  return (
    (code >= 0x1100 && code <= 0x115f)
    || (code >= 0x2e80 && code <= 0xa4cf)
    || (code >= 0xac00 && code <= 0xd7a3)
    || (code >= 0xf900 && code <= 0xfaff)
    || (code >= 0xfe30 && code <= 0xfe4f)
    || (code >= 0xff00 && code <= 0xff60)
    || (code >= 0xffe0 && code <= 0xffe6)
  );
}

// Advance width of one character, in points. Full-width (CJK) glyphs occupy one
// em; Latin glyphs average well below that, which is why a single Latin-biased
// factor systematically over-estimates how much Chinese text fits on a line.
function charAdvancePt(char, fontPt) {
  const code = char.codePointAt(0);
  if (isFullWidthCode(code)) return fontPt;
  if (char === " ") return fontPt * 0.30;
  return fontPt * 0.55;
}

function estimateLineCount(content, fontPt, innerWidthPt) {
  const text = String(content ?? "");
  if (!text || !(innerWidthPt > 0)) return 0;
  let lines = 0;
  for (const paragraph of text.split(/\r?\n/)) {
    if (!paragraph) {
      lines += 1;
      continue;
    }
    let width = 0;
    let wrapped = 1;
    for (const char of paragraph) {
      const advance = charAdvancePt(char, fontPt);
      if (width > 0 && width + advance > innerWidthPt) {
        wrapped += 1;
        width = advance;
      } else {
        width += advance;
      }
    }
    lines += wrapped;
  }
  return lines;
}

// Measure whether a text element's declared content can fit inside its own box,
// using only fields the v1.2.0 contract already requires. This does not depend on
// the renderer honestly reporting `text.overflow`, which is what made the gate
// blind to clipped text whenever the downstream renderer neither shrank nor
// flagged it. Returns null when the element cannot be measured.
export function measureTextOverflow(element, box, slide, options = {}) {
  const text = element?.text;
  if (!text || typeof text.content !== "string" || !text.content) return null;
  const fontPt = text.font_size;
  if (!Number.isFinite(fontPt) || fontPt <= 0) return null;
  if (!box || !Number.isFinite(box.width) || !Number.isFinite(box.height)) return null;
  const scale = Number.isFinite(options.unitsPerInch) && options.unitsPerInch > 0 ? options.unitsPerInch : 1;
  const innerWidth = (box.width * PT_PER_INCH) / scale - 2 * PADDING_X_PT;
  const innerHeight = (box.height * PT_PER_INCH) / scale - 2 * PADDING_Y_PT;
  if (!(innerWidth > 0) || !(innerHeight > 0)) return null;
  const lines = estimateLineCount(text.content, fontPt, innerWidth);
  if (!lines) return null;
  const needed = lines * fontPt * LINE_HEIGHT_FACTOR;
  const margin = Math.max(ASSUMPTION_MARGIN_PT, innerHeight * ASSUMPTION_MARGIN_RATIO);
  return {
    needed,
    available: innerHeight,
    margin,
    lines,
    overflow: needed > innerHeight + margin,
  };
}

export function computeOverflow(elements = [], slide, options = {}) {
  assertSlide(slide);
  if (!Array.isArray(elements)) throw new TypeError("elements must be an array");
  const includeDecoration = options.include_decoration === true;
  const textOverflows = [];
  const overflowingIds = new Set();
  const outOfBounds = [];
  let declaredKnownCount = 0;
  let coveredTextCount = 0;
  let textExpectedCount = 0;
  let geometryKnownCount = 0;
  let geometryExpectedCount = 0;
  const useRenderPixels = Number.isFinite(slide.render_width_px) && slide.render_width_px > 0
    && Number.isFinite(slide.render_height_px) && slide.render_height_px > 0;
  const geometryBounds = useRenderPixels
    ? { width: slide.render_width_px, height: slide.render_height_px }
    : { width: slide.width, height: slide.height };
  const coordinateSpace = useRenderPixels ? "render_bbox_px" : "bbox";
  const measurementScale = unitsPerInch(slide, useRenderPixels);
  // A consumer may declare that it could not expose a box. Honour that instead of
  // pretending we can derive a text fit from geometry it says it does not have.
  const unavailableFields = new Set(
    (Array.isArray(options.unavailable) ? options.unavailable : []).map((item) => String(item?.field ?? "")),
  );
  const geometryUnavailable = (index) => unavailableFields.has(`elements[${index}].bbox`)
    || unavailableFields.has(`elements[${index}].render_bbox_px`);

  for (const [index, element] of elements.entries()) {
    if (!element || typeof element !== "object" || !includedRole(element.quality_role, includeDecoration)) continue;
    geometryExpectedCount += 1;
    const box = useRenderPixels ? element.render_bbox_px : element.bbox;
    if (box) geometryKnownCount += 1;

    if (element.type === "text") {
      textExpectedCount += 1;
      const declared = element.text?.overflow;
      const declaredKnown = declared !== null && declared !== undefined;
      if (declaredKnown) declaredKnownCount += 1;
      // Only measure when the renderer has not already admitted an overflow, so a
      // truthful `true` is never replaced by a coarser estimate. Note that a missing
      // `overflow` flag is exactly the gap this closes: geometry plus font metrics
      // plus content is enough to derive the fit without trusting the renderer.
      const measured = declared === true || geometryUnavailable(index)
        ? null
        : measureTextOverflow(element, box, slide, { unitsPerInch: measurementScale });
      if (declaredKnown || measured) coveredTextCount += 1;
      if ((declared === true || measured?.overflow === true) && !overflowingIds.has(element.element_id)) {
        overflowingIds.add(element.element_id);
        textOverflows.push({ element_id: element.element_id, overflow: true });
      }
    }

    if (!box) continue;
    const edges = {
      left: Math.max(0, -box.x),
      top: Math.max(0, -box.y),
      right: Math.max(0, box.x + box.width - geometryBounds.width),
      bottom: Math.max(0, box.y + box.height - geometryBounds.height),
    };
    if (Object.values(edges).some((value) => value > 0)) {
      outOfBounds.push({ element_id: element.element_id, coordinate_space: coordinateSpace, bbox: { ...box }, overflow: edges });
    }
  }

  // The gate is actionable whenever every text element is covered, either because
  // the renderer declared `overflow` or because we could measure it ourselves.
  const overflowComplete = textExpectedCount > 0 && coveredTextCount === textExpectedCount;
  const geometryComplete = geometryExpectedCount > 0 && geometryKnownCount === geometryExpectedCount;

  return {
    text_overflow: {
      measurable: overflowComplete,
      count: textOverflows.length,
      observed_count: coveredTextCount,
      expected_count: textExpectedCount,
      elements: textOverflows,
      ...(overflowComplete ? {} : { unavailable_reason: "text_overflow_telemetry_incomplete" }),
    },
    element_out_of_bounds: {
      measurable: geometryComplete,
      count: outOfBounds.length,
      observed_count: geometryKnownCount,
      expected_count: geometryExpectedCount,
      coordinate_space: coordinateSpace,
      elements: outOfBounds,
      ...(geometryComplete ? {} : { unavailable_reason: `${coordinateSpace}_telemetry_incomplete` }),
    },
  };
}
