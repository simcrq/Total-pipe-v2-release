export const DESIGN_QA_VERSION = "1.0.0";

export const DESIGN_QA_CODES = Object.freeze([
  "EXCESSIVE_CARDIFICATION",
  "REPEATED_CONTAINER_LANGUAGE",
  "REPEATED_TREATMENT",
  "REPEATED_COMPOSITION",
  "REPEATED_TAKEAWAY_BAR",
  "LOW_VISUAL_HIERARCHY",
  "LOW_VISUAL_FOCUS",
  "LOW_WHITESPACE",
  "UNBALANCED_VISUAL_WEIGHT",
  "LOW_DECK_RHYTHM",
]);

const asArray = (value) => (Array.isArray(value) ? value : []);
const average = (values) => values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : 0;
const round = (value) => Number(value.toFixed(3));

function issue(code, slideIndexes, message) {
  return {
    code,
    severity: "warning",
    recoverable: true,
    recommended_action: code.startsWith("REPEATED_") || code === "EXCESSIVE_CARDIFICATION" ? "change_treatment_or_decoration" : "review_design_candidate",
    slide_indexes: slideIndexes,
    message,
  };
}

function repeatedWindows(slides, selector, code, message) {
  const issues = [];
  for (let index = 2; index < slides.length; index += 1) {
    const window = slides.slice(index - 2, index + 1);
    const values = window.map(selector);
    if (values[0] && values.every((value) => value === values[0])) issues.push(issue(code, window.map((slide) => slide.index), message));
  }
  return issues;
}

export function evaluateDeckDesign(slides = []) {
  const values = asArray(slides);
  const issues = [];
  issues.push(...repeatedWindows(values, (slide) => slide.visual_treatment, "REPEATED_TREATMENT", "Three consecutive slides use the same visual treatment."));
  issues.push(...repeatedWindows(values, (slide) => slide.layout_family ?? slide.category, "REPEATED_COMPOSITION", "Three consecutive slides use the same composition family."));
  issues.push(...repeatedWindows(values, (slide) => slide.decoration_profile?.container, "REPEATED_CONTAINER_LANGUAGE", "Three consecutive slides use the same container language."));
  issues.push(...repeatedWindows(values, (slide) => slide.decoration_profile?.id === "takeaway_bar" ? "takeaway_bar" : null, "REPEATED_TAKEAWAY_BAR", "Three consecutive slides repeat a takeaway bar."));

  for (const slide of values) {
    const components = slide.aesthetic_score?.components ?? {};
    if (slide.decoration_profile?.container === "card" || Number(slide.container_density) > 0.4) {
      issues.push(issue("EXCESSIVE_CARDIFICATION", [slide.index], "Container area exceeds the v0.5 anti-cardification budget."));
    }
    if (Number(components.hierarchy_fit) < 0.4) issues.push(issue("LOW_VISUAL_HIERARCHY", [slide.index], "The selected candidate has a weak hierarchy proxy."));
    if (Number(components.visual_priority_fit) < 0.35) issues.push(issue("LOW_VISUAL_FOCUS", [slide.index], "The selected layout does not strongly match the requested visual priority."));
    if (Number(components.whitespace_fit) < 0.35) issues.push(issue("LOW_WHITESPACE", [slide.index], "The selected candidate misses the requested whitespace level."));
    if (Number(components.balance_proxy) < 0.35) issues.push(issue("UNBALANCED_VISUAL_WEIGHT", [slide.index], "The selected candidate has a weak balance proxy."));
  }
  const scores = values.map((slide) => Number(slide.aesthetic_score?.score)).filter(Number.isFinite);
  const designScore = scores.length ? average(scores) : 0;
  if (values.length >= 3 && designScore < 0.48) issues.push(issue("LOW_DECK_RHYTHM", values.map((slide) => slide.index), "The deck-level aesthetic score indicates weak visual rhythm."));
  const repeatedContainerWindows = Math.max(0, values.length - 2);
  const repeatedContainerCount = repeatedWindows(values, (slide) => slide.decoration_profile?.container, "REPEATED_CONTAINER_LANGUAGE", "").length;
  const treatments = values.map((slide) => slide.visual_treatment).filter(Boolean);
  const jointChoices = values.map((slide) => `${slide.layout_family ?? slide.category}:${slide.visual_treatment ?? "none"}`);
  return {
    qa_version: DESIGN_QA_VERSION,
    status: issues.length ? "review_recommended" : "pass",
    score: round(designScore),
    issues,
    issue_counts: Object.fromEntries(DESIGN_QA_CODES.map((code) => [code, issues.filter((item) => item.code === code).length])),
    visual_diversity: {
      treatment_diversity: round(treatments.length ? new Set(treatments).size / treatments.length : 0),
      container_repetition: round(repeatedContainerWindows ? repeatedContainerCount / repeatedContainerWindows : 0),
      layout_treatment_joint_diversity: round(jointChoices.length ? new Set(jointChoices).size / jointChoices.length : 0),
      cardification_rate: round(average(values.map((slide) => slide.decoration_profile?.container === "card" ? Number(slide.container_density ?? 0.45) : 0))),
    },
  };
}
