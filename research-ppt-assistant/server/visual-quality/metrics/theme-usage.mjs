function unavailableResult(reason, usages = []) {
  return {
    measurable: false,
    usage_count: usages.length,
    violation_count: 0,
    usages,
    violations: [],
    unavailable_reason: reason,
  };
}

export function collectThemeUsage(elements = [], theme, options = {}) {
  if (!Array.isArray(elements)) throw new TypeError("elements must be an array");
  if (!options || typeof options !== "object" || Array.isArray(options)) throw new TypeError("theme usage options must be an object");
  const unavailableFields = new Set((options.unavailable ?? []).map((item) => item?.field).filter(Boolean));
  const tokens = theme?.tokens;
  if (!tokens || typeof tokens !== "object" || Array.isArray(tokens)) {
    return unavailableResult("theme_token_contract_missing");
  }

  const usages = [];
  for (const element of elements) {
    if (!element || typeof element !== "object" || element.quality_role === "ignore") continue;
    if (!element.theme_token && !element.theme_usage) continue;
    if (!element.theme_token || !element.theme_usage) {
      return unavailableResult("theme_usage_telemetry_incomplete", usages);
    }
    const token = tokens[element.theme_token];
    let result = "unknown_token";
    if (token) {
      const prefix = `theme.tokens.${element.theme_token}`;
      if (unavailableFields.has(`${prefix}.allowed_usage`) || unavailableFields.has(`${prefix}.forbidden_usage`)) {
        return unavailableResult("theme_usage_constraints_incomplete", usages);
      }
      const forbidden = token.forbidden_usage ?? [];
      const allowed = token.allowed_usage ?? [];
      if (forbidden.includes(element.theme_usage)) result = "forbidden";
      else if (allowed.length && !allowed.includes(element.theme_usage)) result = "not_allowed";
      else result = "allowed";
    }
    usages.push({
      element_id: element.element_id,
      token: element.theme_token,
      usage: element.theme_usage,
      result,
    });
  }
  const violations = usages.filter((usage) => usage.result !== "allowed");
  if (!usages.length) return unavailableResult("theme_usage_telemetry_missing");
  return {
    measurable: usages.length > 0,
    usage_count: usages.length,
    violation_count: violations.length,
    usages,
    violations,
  };
}
