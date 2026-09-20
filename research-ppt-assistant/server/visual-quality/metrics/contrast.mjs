const HEX_COLOR_PATTERN = /^#(?:[\da-fA-F]{3}|[\da-fA-F]{4}|[\da-fA-F]{6}|[\da-fA-F]{8})$/;

function expandHex(value) {
  return value.length <= 4
    ? value.slice(1).split("").map((digit) => `${digit}${digit}`).join("")
    : value.slice(1);
}

function parseHexColor(value) {
  if (typeof value !== "string") return null;
  const trimmed = value.trim();
  if (!HEX_COLOR_PATTERN.test(trimmed)) return null;
  const hex = expandHex(trimmed);
  const hasAlpha = hex.length === 8;
  const parsed = {
    red: Number.parseInt(hex.slice(0, 2), 16),
    green: Number.parseInt(hex.slice(2, 4), 16),
    blue: Number.parseInt(hex.slice(4, 6), 16),
    alpha: hasAlpha ? Number.parseInt(hex.slice(6, 8), 16) / 255 : 1,
    normalized: `#${hex.toLowerCase()}`,
    hasAlpha,
  };
  return Object.values(parsed).every((item) => typeof item !== "number" || Number.isFinite(item)) ? parsed : null;
}

function backgroundDescriptor(background) {
  if (typeof background === "string") {
    if (background.trim().toLowerCase() === "transparent") return { reason: "background_not_solid" };
    return { kind: "solid", color: background };
  }
  if (!background || typeof background !== "object" || Array.isArray(background)) return { reason: "missing_background" };

  const kind = background.kind ?? background.type;
  if (kind !== "solid") return { reason: "background_not_solid" };
  if (background.color === undefined || background.color === null) return { reason: "missing_background_color" };
  return { kind, color: background.color };
}

function srgbToLinear(channel) {
  const normalized = channel / 255;
  return normalized <= 0.04045
    ? normalized / 12.92
    : ((normalized + 0.055) / 1.055) ** 2.4;
}

function luminance(color) {
  return (0.2126 * srgbToLinear(color.red))
    + (0.7152 * srgbToLinear(color.green))
    + (0.0722 * srgbToLinear(color.blue));
}

function compositeForeground(foreground, background) {
  if (foreground.alpha === 1) return foreground;
  return {
    red: (foreground.red * foreground.alpha) + (background.red * (1 - foreground.alpha)),
    green: (foreground.green * foreground.alpha) + (background.green * (1 - foreground.alpha)),
    blue: (foreground.blue * foreground.alpha) + (background.blue * (1 - foreground.alpha)),
  };
}

function result({ measurable, ratio = null, foregroundColor = null, backgroundColor = null, reason }) {
  return {
    measurable,
    contrast_ratio: ratio,
    foreground_color: foregroundColor,
    background_color: backgroundColor,
    ...(reason ? { unavailable_reason: reason } : {}),
  };
}

/**
 * Compute WCAG relative-luminance contrast for a foreground and a solid
 * background. No readability threshold is applied here.
 */
export function computeSolidContrast(foregroundColor, background) {
  const foreground = parseHexColor(foregroundColor);
  const descriptor = backgroundDescriptor(background);
  const backgroundColor = descriptor.color === undefined ? null : parseHexColor(descriptor.color);

  if (!foreground) {
    return result({
      measurable: false,
      foregroundColor: null,
      backgroundColor: backgroundColor?.normalized ?? null,
      reason: "invalid_foreground_color",
    });
  }
  if (descriptor.reason) {
    return result({
      measurable: false,
      foregroundColor: foreground.normalized,
      reason: descriptor.reason,
    });
  }
  if (!backgroundColor) {
    return result({
      measurable: false,
      foregroundColor: foreground.normalized,
      reason: "invalid_background_color",
    });
  }
  if (backgroundColor.alpha < 1) {
    return result({
      measurable: false,
      foregroundColor: foreground.normalized,
      backgroundColor: backgroundColor.normalized,
      reason: "background_not_opaque",
    });
  }

  const foregroundLuminance = luminance(compositeForeground(foreground, backgroundColor));
  const backgroundLuminance = luminance(backgroundColor);
  const lighter = Math.max(foregroundLuminance, backgroundLuminance);
  const darker = Math.min(foregroundLuminance, backgroundLuminance);
  return result({
    measurable: true,
    ratio: (lighter + 0.05) / (darker + 0.05),
    foregroundColor: foreground.normalized,
    backgroundColor: backgroundColor.normalized,
  });
}
