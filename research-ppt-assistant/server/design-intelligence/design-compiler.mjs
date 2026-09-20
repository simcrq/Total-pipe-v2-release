export const SLIDE_DESIGN_IR_VERSION = "1.0.0";
export const DESIGN_COMPILER_VERSION = "1.0.0";
export const DISTRIBUTED_ARROW_LIST = "distributed_arrow_list";

const asArray = (value) => (Array.isArray(value) ? value : []);
const text = (value) => (value === undefined || value === null ? "" : String(value).trim());
const number = (value, fallback = 0) => (Number.isFinite(Number(value)) ? Number(value) : fallback);

const ROLE_BY_CATEGORY = Object.freeze({
  cover: "opening_context",
  section: "narrative_navigation",
  agenda: "narrative_navigation",
  weekly: "metric_summary",
  question: "research_question",
  background: "background_context",
  literature: "background_context",
  gap: "literature_gap",
  theory: "mechanism_explanation",
  method_overview: "method_explanation",
  workflow: "workflow_explanation",
  architecture: "method_explanation",
  algorithm: "method_explanation",
  dataset: "evidence_audit",
  experiment: "method_explanation",
  metrics: "metric_summary",
  single_figure: "results_evidence",
  dual_figure: "results_comparison",
  triple_figure: "results_comparison",
  four_panel: "results_comparison",
  chart_takeaway: "metric_summary",
  chart_compare: "results_comparison",
  table: "results_evidence",
  table_chart: "results_comparison",
  qualitative: "results_comparison",
  ablation: "results_comparison",
  baseline: "results_comparison",
  error: "evidence_audit",
  case: "mechanism_explanation",
  failure: "evidence_audit",
  discussion: "discussion",
  limitations: "evidence_audit",
  next_steps: "planning",
  timeline: "planning",
  decision: "planning",
  summary: "summary_synthesis",
  qa: "discussion",
  references: "reference_material",
  appendix: "reference_material",
});

const TREATMENTS_BY_ROLE = Object.freeze({
  opening_context: ["editorial_open", "figure_led"],
  narrative_navigation: ["editorial_open", "summary_synthesis"],
  research_question: ["editorial_open", "summary_synthesis"],
  background_context: ["editorial_open", "figure_led"],
  literature_gap: ["editorial_open", "comparison_structured", "evidence_audit"],
  mechanism_explanation: ["technical_annotation", "mechanism_diagram", "figure_led"],
  method_explanation: ["mechanism_diagram", "technical_annotation", "figure_led"],
  workflow_explanation: ["mechanism_diagram", "technical_annotation"],
  results_evidence: ["figure_led", "metric_focus", "technical_annotation"],
  results_comparison: ["comparison_structured", "figure_led", "technical_annotation"],
  metric_summary: ["metric_focus", "editorial_open"],
  evidence_audit: ["evidence_audit", "comparison_structured"],
  discussion: ["editorial_open", "summary_synthesis"],
  planning: ["summary_synthesis", "editorial_open"],
  summary_synthesis: ["summary_synthesis", "editorial_open", "figure_led"],
  reference_material: ["evidence_audit", "editorial_open"],
});

function densityLevel(brief) {
  const preference = text(brief.density_preference ?? brief.densityPreference);
  if (["高", "dense", "high"].includes(preference)) return "high";
  if (["低", "spacious", "low"].includes(preference)) return "low";
  const chars = number(brief.text_chars ?? brief.textChars);
  if (chars > 170) return "high";
  if (chars > 80) return "medium";
  return "low";
}

function visualCount(brief) {
  return Math.max(
    asArray(brief.visuals).length,
    number(brief.image_count ?? brief.imageCount) + number(brief.chart_count ?? brief.chartCount),
  );
}

function evidenceStatus(brief) {
  const explicit = text(brief.evidence_status ?? brief.evidenceStatus).toLowerCase();
  if (["supported", "partial", "missing", "not_applicable"].includes(explicit)) return explicit;
  if (asArray(brief.evidence_ids ?? brief.evidenceIds).length) return "supported";
  const role = ROLE_BY_CATEGORY[text(brief.category_hint ?? brief.categoryHint ?? brief.category)] ?? "background_context";
  return ["opening_context", "narrative_navigation", "research_question", "planning", "discussion"].includes(role)
    ? "not_applicable"
    : "partial";
}

function compositionFor(role, visuals, density) {
  if (role === "results_comparison") return "comparison";
  if (role === "metric_summary") return "metric";
  if (["mechanism_explanation", "method_explanation", "workflow_explanation"].includes(role)) return visuals ? "asymmetric" : "process";
  if (["evidence_audit", "reference_material"].includes(role)) return "audit";
  if (["summary_synthesis", "planning"].includes(role)) return "synthesis";
  if (["opening_context", "narrative_navigation", "research_question", "background_context", "literature_gap", "discussion"].includes(role)) return "editorial_open";
  if (visuals) return "asymmetric";
  return density === "high" ? "balanced" : "editorial_open";
}

function visualPriorityFor(role, visuals) {
  if (!visuals) return "none";
  if (["results_evidence", "mechanism_explanation", "opening_context"].includes(role)) return "dominant";
  if (["results_comparison", "metric_summary", "method_explanation", "workflow_explanation"].includes(role)) return "coequal";
  return "supporting";
}

function whitespaceFor(role, density) {
  if (density === "high" || ["evidence_audit", "reference_material"].includes(role)) return "low";
  if (["opening_context", "narrative_navigation", "research_question", "discussion", "summary_synthesis"].includes(role)) return "high";
  return density === "low" ? "medium_high" : "medium";
}

function hierarchyFor(brief, role, visuals) {
  const roles = asArray(brief.content_roles ?? brief.contentRoles);
  const visual = roles.find((item) => ["primary_visual", "data_visual"].includes(item));
  const secondary = roles.find((item) => !["headline", visual].includes(item));
  return {
    primary: visuals && ["dominant", "coequal"].includes(visualPriorityFor(role, visuals)) ? (visual || "primary_visual") : "headline",
    secondary: secondary || (visuals ? "supporting_text" : "body_text"),
    tertiary: roles.find((item) => !["headline", visual, secondary].includes(item)) || "supporting_detail",
    takeaway: roles.includes("takeaway") ? "takeaway" : "message_primary",
  };
}

function secondaryMessages(brief) {
  const values = [
    ...asArray(brief.secondary_messages ?? brief.secondaryMessages),
    ...asArray(brief.key_points ?? brief.keyPoints),
  ];
  return [...new Set(values.map(text).filter(Boolean))].slice(0, 8);
}

function stripListPrefix(value) {
  return text(value).replace(/^\s*(?:[-*•●▪◦‣⁃➢▶▷►▸→]|\d+[.)、])\s*/, "");
}

function explicitTextRows(brief) {
  const structured = [
    ...asArray(brief.secondary_messages ?? brief.secondaryMessages),
    ...asArray(brief.key_points ?? brief.keyPoints),
  ].map(stripListPrefix).filter(Boolean);
  if (structured.length >= 2) return [...new Set(structured)];
  return text(brief.body).split(/\r?\n+/).map(stripListPrefix).filter(Boolean);
}

function displayUnits(value) {
  return [...value].reduce((sum, char) => sum + (/^[\u3400-\u9fff]$/.test(char) ? 2 : /\s/.test(char) ? 0 : 1), 0);
}

export function inferTextFlow(brief, semanticRole, visuals) {
  const requested = text((brief.text_flow ?? brief.textFlow) || "auto");
  if (!["auto", "plain", DISTRIBUTED_ARROW_LIST].includes(requested)) {
    throw new TypeError(`Unsupported text_flow: ${requested}`);
  }
  const items = explicitTextRows(brief);
  const total = items.reduce((sum, item) => sum + displayUnits(item), 0);
  const maxItem = Math.max(0, ...items.map(displayUnits));
  const excludedRole = ["reference_material", "results_evidence", "results_comparison", "metric_summary"].includes(semanticRole);
  const explicit = requested === DISTRIBUTED_ARROW_LIST;
  const automatic = requested === "auto"
    && visuals === 0
    && !excludedRole
    && items.length >= 3
    && items.length <= 5
    && maxItem <= 120
    && Math.max(total, number(brief.text_chars ?? brief.textChars)) >= 72;
  const selected = (explicit || automatic) && items.length >= 2 && items.length <= 6;
  return {
    mode: selected ? DISTRIBUTED_ARROW_LIST : "plain",
    source: selected ? (explicit ? "explicit" : "auto") : explicit ? "fallback" : "default",
    bullet_glyph: selected ? "➢" : "",
    item_count: selected ? items.length : 0,
    distribution: selected ? "space_between" : "top",
    container_style: selected ? "soft_panel" : "none",
  };
}

import { normalizePresentationIntent } from './presentation-intent.mjs';

export function compileSlideDesignIR(slideBrief = {}) {
  if (!slideBrief || typeof slideBrief !== "object" || Array.isArray(slideBrief)) throw new TypeError("slideBrief must be an object");
  const category = text(slideBrief.category_hint ?? slideBrief.categoryHint ?? slideBrief.category);
  const semanticRole = ROLE_BY_CATEGORY[category] ?? "background_context";
  const visuals = visualCount(slideBrief);
  const density = densityLevel(slideBrief);
  const visualPriority = visualPriorityFor(semanticRole, visuals);
  const whitespace = whitespaceFor(semanticRole, density);
  const textFlow = inferTextFlow(slideBrief, semanticRole, visuals);
  const treatmentPreferences = textFlow.mode === DISTRIBUTED_ARROW_LIST
    ? ["structured_text", ...TREATMENTS_BY_ROLE[semanticRole].filter((id) => id !== "structured_text")]
    : TREATMENTS_BY_ROLE[semanticRole];
  const annotationLevel = ["mechanism_explanation", "method_explanation", "workflow_explanation"].includes(semanticRole)
    ? "medium_high"
    : ["results_comparison", "evidence_audit", "reference_material"].includes(semanticRole) ? "medium" : "low";
  const containerPolicy = ["evidence_audit", "reference_material"].includes(semanticRole)
    ? "audit_only"
    : ["results_comparison", "workflow_explanation"].includes(semanticRole) ? "structured" : ["opening_context", "narrative_navigation", "research_question", "discussion"].includes(semanticRole) ? "none" : "minimal";
  const composition = compositionFor(semanticRole, visuals, density);
  const presentationIntent = normalizePresentationIntent(slideBrief.metadata?.presentation_intent);

  return {
    schema_version: SLIDE_DESIGN_IR_VERSION,
    ...(presentationIntent ? { presentation_intent: presentationIntent } : {}),
    semantic_role: semanticRole,
    message: {
      primary: presentationIntent?.objective || text(slideBrief.goal) || text(slideBrief.title) || "Establish the slide's primary research message",
      secondary: secondaryMessages(slideBrief),
      evidence_status: evidenceStatus(slideBrief),
    },
    hierarchy: hierarchyFor(slideBrief, semanticRole, visuals),
    text_flow: textFlow,
    composition_intent: {
      family: composition,
      visual_dominance: visualPriority === "dominant" ? "high" : visualPriority === "coequal" ? "medium" : visualPriority === "supporting" ? "low" : "none",
      text_density: density,
      whitespace,
      reading_pattern: composition === "comparison" ? "left_to_right" : composition === "audit" ? "scan_then_detail" : visualPriority === "dominant" ? "visual_then_explanation" : composition === "editorial_open" || composition === "synthesis" ? "single_focus" : "top_to_bottom",
    },
    design_intent: {
      tone: ["mechanism_explanation", "method_explanation", "workflow_explanation"].includes(semanticRole) ? "technical" : composition === "editorial_open" ? "editorial" : "scientific_modern",
      energy: composition === "comparison" ? "comparative" : ["metric", "synthesis"].includes(composition) ? "decisive" : composition === "editorial_open" ? "quiet" : "analytical",
      accent_strength: presentationIntent?.emphasis ?? (["metric", "comparison"].includes(composition) ? "high" : composition === "editorial_open" ? "low" : "medium"),
      treatment_preferences: [...treatmentPreferences],
    },
    visual_priority: visualPriority,
    whitespace,
    container_policy: containerPolicy,
    annotation_level: annotationLevel,
    allowed_transformations: {
      preserve_visual_aspect: true,
      citation_required: asArray(slideBrief.citation_ids ?? slideBrief.citationIds).length > 0,
      allow_split: slideBrief.allow_auto_split ?? slideBrief.allowAutoSplit ?? true,
      allow_semantic_crop: asArray(slideBrief.visuals).some((visual) => visual?.semantic_crop_allowed === true || visual?.crop_policy === "semantic_crop_allowed"),
    },
  };
}
