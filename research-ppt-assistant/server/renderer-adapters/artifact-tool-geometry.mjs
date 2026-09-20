const EPSILON = 1e-9;

function finitePositive(value, field) {
  if (typeof value !== "number" || !Number.isFinite(value) || value <= 0) {
    throw new TypeError(`${field} must be a positive finite number`);
  }
  return value;
}

function normalizeBox(value, field) {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new TypeError(`${field} must be a box`);
  const box = {
    x: Number(value.x),
    y: Number(value.y),
    width: Number(value.width),
    height: Number(value.height),
  };
  if (!Object.values(box).every(Number.isFinite) || box.width <= 0 || box.height <= 0) {
    throw new TypeError(`${field} must contain finite x/y and positive width/height`);
  }
  return box;
}

function clean(value) {
  return Math.abs(value) < EPSILON ? 0 : Number(value.toFixed(9));
}

export function computeArtifactDisplayGeometry({ frame_bbox, asset_width_px, asset_height_px, image_fit }) {
  const frame = normalizeBox(frame_bbox, "frame_bbox");
  const sourceWidth = finitePositive(asset_width_px, "asset_width_px");
  const sourceHeight = finitePositive(asset_height_px, "asset_height_px");
  const fit = String(image_fit ?? "").trim().toLowerCase();
  if (!["contain", "cover"].includes(fit)) throw new RangeError(`Unsupported artifact-tool imageFit: ${image_fit}`);

  if (fit === "cover") {
    const sourceAspect = sourceWidth / sourceHeight;
    const frameAspect = frame.width / frame.height;
    const visibleSourceRegion = sourceAspect > frameAspect
      ? { x: clean((1 - frameAspect / sourceAspect) / 2), y: 0, width: clean(frameAspect / sourceAspect), height: 1 }
      : { x: 0, y: clean((1 - sourceAspect / frameAspect) / 2), width: 1, height: clean(sourceAspect / frameAspect) };
    return {
      display_bbox: frame,
      effective_placement: frame,
      actual_letterbox_ratio: 0,
      profile_effective_source_region: visibleSourceRegion,
      source_visibility_ratio: clean(visibleSourceRegion.width * visibleSourceRegion.height),
      fit_mode: fit,
    };
  }

  const scale = Math.min(frame.width / sourceWidth, frame.height / sourceHeight);
  const width = sourceWidth * scale;
  const height = sourceHeight * scale;
  const display = {
    x: clean(frame.x + (frame.width - width) / 2),
    y: clean(frame.y + (frame.height - height) / 2),
    width: clean(width),
    height: clean(height),
  };
  return {
    display_bbox: display,
    effective_placement: display,
    actual_letterbox_ratio: clean(1 - (display.width * display.height) / (frame.width * frame.height)),
    profile_effective_source_region: { x: 0, y: 0, width: 1, height: 1 },
    source_visibility_ratio: 1,
    fit_mode: fit,
  };
}

function nearlyEqual(left, right, tolerance = 1e-9) {
  return Math.abs(left - right) <= tolerance;
}

function verifyConformanceFixtures() {
  const wide = computeArtifactDisplayGeometry({
    frame_bbox: { x: 0, y: 0, width: 100, height: 100 },
    asset_width_px: 200,
    asset_height_px: 100,
    image_fit: "contain",
  });
  const cover = computeArtifactDisplayGeometry({
    frame_bbox: { x: 5, y: 10, width: 90, height: 60 },
    asset_width_px: 100,
    asset_height_px: 200,
    image_fit: "cover",
  });
  return nearlyEqual(wide.display_bbox.x, 0)
    && nearlyEqual(wide.display_bbox.y, 25)
    && nearlyEqual(wide.display_bbox.width, 100)
    && nearlyEqual(wide.display_bbox.height, 50)
    && nearlyEqual(wide.actual_letterbox_ratio, 0.5)
    && Object.entries(cover.display_bbox).every(([field, value]) => nearlyEqual(value, { x: 5, y: 10, width: 90, height: 60 }[field]))
    && nearlyEqual(cover.actual_letterbox_ratio, 0);
}

export const ARTIFACT_TOOL_GEOMETRY_PROFILE = Object.freeze({
  profile_id: "artifact-tool/layout-v4",
  profile_version: "1.1.0",
  renderer_profile_id: "artifact-tool/layout-v4@1",
  geometry_provenance: "profile_derived",
  supported_fit_modes: Object.freeze(["contain", "cover"]),
  conformance_verified: verifyConformanceFixtures(),
});

if (!ARTIFACT_TOOL_GEOMETRY_PROFILE.conformance_verified) {
  throw new Error("artifact-tool deterministic geometry profile failed its conformance fixtures");
}
