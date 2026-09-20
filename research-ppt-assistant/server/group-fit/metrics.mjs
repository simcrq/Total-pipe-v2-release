const round = (value, digits = 6) => Number(value.toFixed(digits));

export function computeGroupFitMetrics(childFits = []) {
  if (!Array.isArray(childFits) || childFits.length < 2) throw new RangeError("childFits must contain at least two observations");
  const fills = childFits.map((child, index) => {
    const fill = Number(child?.metrics?.visual_fill?.area_ratio);
    if (!Number.isFinite(fill) || fill < 0) throw new RangeError(`childFits[${index}] requires a non-negative area fill ratio`);
    return fill;
  });
  const areas = childFits.map((child, index) => {
    const box = child?.metrics?.allocated_bbox;
    const area = Number(box?.width) * Number(box?.height);
    if (!Number.isFinite(area) || area <= 0) throw new RangeError(`childFits[${index}] requires a positive allocated area`);
    return area;
  });
  const minimum = Math.min(...fills);
  const maximum = Math.max(...fills);
  const mean = fills.reduce((sum, value) => sum + value, 0) / fills.length;
  const variance = fills.reduce((sum, value) => sum + (value - mean) ** 2, 0) / fills.length;
  const meanArea = areas.reduce((sum, value) => sum + value, 0) / areas.length;
  const weightDeviation = Math.max(...areas.map((area) => Math.abs(area / meanArea - 1)));
  return {
    group_min_fill: round(minimum),
    group_max_fill: round(maximum),
    group_mean_fill: round(mean),
    group_fill_variance: round(variance),
    fit_equity: round(maximum === 0 ? 1 : minimum / maximum),
    visual_weight_deviation: round(weightDeviation),
    child_count: childFits.length,
  };
}

export function computeCandidateGain(baselineMetrics, candidateMetrics) {
  return {
    minimum_fill_gain: round(candidateMetrics.group_min_fill - baselineMetrics.group_min_fill),
    mean_fill_gain: round(candidateMetrics.group_mean_fill - baselineMetrics.group_mean_fill),
    fit_equity_gain: round(candidateMetrics.fit_equity - baselineMetrics.fit_equity),
    fill_variance_reduction: round(baselineMetrics.group_fill_variance - candidateMetrics.group_fill_variance),
  };
}

export function computeCreditsRegression(credits, maximumRatio = 1.1) {
  if (!credits) {
    return {
      measurable: false,
      status: "not_evaluable",
      maximum_ratio: maximumRatio,
      credits_per_deck_ratio: null,
      reason: "credits_telemetry_missing",
    };
  }
  const baseline = credits.v045.median_credits_per_deck;
  const current = credits.v046.median_credits_per_deck;
  const ratio = baseline === 0 ? (current === 0 ? 1 : Infinity) : current / baseline;
  return {
    measurable: true,
    status: ratio <= maximumRatio ? "pass" : "fail",
    maximum_ratio: maximumRatio,
    credits_per_deck_ratio: Number.isFinite(ratio) ? round(ratio) : null,
    v045: credits.v045,
    v046: credits.v046,
    reason: ratio <= maximumRatio ? "credits_regression_within_budget" : "credits_regression_exceeds_budget",
  };
}
