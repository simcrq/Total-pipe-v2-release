export const DETAIL_LEVELS = Object.freeze(["compact", "standard", "full"]);

export function normalizeDetailLevel(value, fallback = "compact") {
  const normalized = String(value ?? fallback).trim().toLowerCase();
  if (!DETAIL_LEVELS.includes(normalized)) {
    throw new RangeError(`Unsupported detail_level: ${value}. Expected compact, standard, or full.`);
  }
  return normalized;
}

function truncateText(value, maximum = 240) {
  if (typeof value !== "string" || [...value].length <= maximum) return value;
  return `${[...value].slice(0, maximum - 1).join("")}…`;
}

function compactAssignment(assignment) {
  if (!assignment || typeof assignment !== "object" || Array.isArray(assignment)) return assignment;
  const result = {
    type: assignment.type,
    ...(assignment.content_id === undefined ? {} : { content_id: assignment.content_id }),
    ...(assignment.text === undefined ? {} : { text: truncateText(assignment.text) }),
    ...(assignment.asset_uri === undefined ? {} : { asset_uri: assignment.asset_uri }),
  };
  for (const key of ["steps", "items", "rows", "series", "events"]) {
    if (Array.isArray(assignment[key])) result[`${key}_count`] = assignment[key].length;
  }
  if (assignment.value !== undefined && typeof assignment.value !== "object") result.value = assignment.value;
  return result;
}

function compactAssignments(assignments) {
  if (!assignments || typeof assignments !== "object" || Array.isArray(assignments)) return {};
  return Object.fromEntries(Object.entries(assignments).map(([slotId, assignment]) => [slotId, compactAssignment(assignment)]));
}

function compactIssue(issue) {
  if (!issue || typeof issue !== "object") return issue;
  return {
    code: issue.code,
    field: issue.field,
    severity: issue.severity,
    recoverable: issue.recoverable,
    recommended_action: issue.recommended_action,
    message: truncateText(issue.message, 180),
    ...(issue.path === undefined ? {} : { path: issue.path }),
    ...(issue.details?.slot_id === undefined ? {} : { slot_id: issue.details.slot_id }),
  };
}

function compactIssues(issues) {
  return Array.isArray(issues) ? issues.map(compactIssue) : [];
}

function compactRepairPlan(plan) {
  if (!plan || typeof plan !== "object") return undefined;
  return {
    status: plan.status,
    action: plan.action,
    iteration: plan.iteration,
    next_iteration: plan.next_iteration,
    max_repair_iterations: plan.max_repair_iterations,
    trigger_codes: plan.trigger_codes ?? [],
    target: plan.target,
    human_escalation: plan.human_escalation,
  };
}

function compactDeckPlan(payload) {
  return {
    detail_level: "compact",
    pipeline_status: payload.pipeline_status,
    status: payload.status,
    production_status: payload.production_status,
    design_status: payload.design_status,
    design_score: payload.design_score,
    deck_title: payload.deck_title,
    presentation_type: payload.presentation_type,
    theme_id: payload.theme?.id ?? payload.theme_id,
    requested_slide_count: payload.requested_slide_count,
    slide_count: payload.slide_count ?? payload.slides?.length ?? 0,
    content_model: payload.content_model ? {
      schema_version: payload.content_model.schema_version,
      status: payload.content_model.status,
      source_count: payload.content_model.sources?.length ?? 0,
      citation_count: payload.content_model.citations?.length ?? 0,
      evidence_count: payload.content_model.evidence?.length ?? 0,
      slide_brief_count: payload.content_model.slide_briefs?.length ?? 0,
      violations: compactIssues(payload.content_model.violations),
    } : undefined,
    slides: (payload.slides ?? []).map((slide) => ({
      index: slide.index,
      slide_id: slide.slide_id,
      title: slide.title,
      category: slide.category,
      layout_id: slide.layout_id,
      visual_treatment: slide.visual_treatment,
      decoration_profile: slide.decoration_profile?.id,
      aesthetic_score: slide.aesthetic_score?.score,
      design_context: slide.design_context ? {
        design_ir: slide.design_context.design_ir,
        visual_treatment: slide.design_context.visual_treatment,
        decoration_profile: slide.design_context.decoration_profile,
        container_density: slide.design_context.container_density,
        deck_state_before: { recent_history: slide.design_context.deck_state_before?.recent_history ?? {} },
      } : undefined,
      binding_status: slide.binding_status,
      contract_valid: slide.contract_valid,
      planning_decision: slide.planning_decision,
      evidence_ids: slide.evidence_ids ?? [],
      citation_ids: slide.citation_ids ?? [],
      slot_assignments: compactAssignments(slide.slot_assignments),
      violations: compactIssues(slide.violations),
      adaptation_count: slide.adaptation_log?.length ?? 0,
    })),
    unplanned_slide_briefs: (payload.unplanned_slide_briefs ?? []).map((brief) => ({
      slide_id: brief.slide_id,
      slide_type: brief.slide_type,
      title: brief.title,
      category_hint: brief.category_hint,
    })),
    warnings: (payload.warnings ?? []).map((warning) => truncateText(warning, 180)),
  };
}

function standardDeckPlan(payload) {
  const { planning_contexts: _planningContexts, ...deck } = payload;
  return {
    detail_level: "standard",
    ...deck,
    slides: (payload.slides ?? []).map((slide) => {
      const { replan_context: _replanContext, alternatives: _alternatives, ...publicSlide } = slide;
      return publicSlide;
    }),
  };
}

function compactSearch(payload) {
  return {
    detail_level: "compact",
    query: payload.query,
    candidate_count: payload.candidate_count ?? payload.compatibility?.candidate_count,
    compatible_count: payload.compatible_count ?? payload.compatibility?.compatible_count,
    results: (payload.results ?? []).map((item) => ({
      id: item.id,
      category: item.category,
      family: item.family,
      density: item.density,
      score: item.score,
      capacity: item.capacity,
      preview_uri: item.preview_uri,
    })),
  };
}

function compactNormalization(payload) {
  return {
    detail_level: "compact",
    schema_version: payload.schema_version,
    status: payload.status,
    source_count: payload.sources?.length ?? 0,
    citation_count: payload.citations?.length ?? 0,
    evidence_count: payload.evidence?.length ?? 0,
    slide_brief_count: payload.slide_briefs?.length ?? 0,
    sources: payload.sources ?? [],
    citations: payload.citations ?? [],
    evidence: payload.evidence ?? [],
    slide_briefs: payload.slide_briefs ?? [],
    coverage: payload.coverage,
    violations: compactIssues(payload.violations),
    adaptation_count: payload.adaptation_log?.length ?? 0,
  };
}

function compactSlideValidation(payload) {
  return {
    detail_level: "compact",
    ...(payload.pipeline_status === undefined ? {} : { pipeline_status: payload.pipeline_status }),
    status: payload.status,
    ...(payload.overall_status === undefined ? {} : { overall_status: payload.overall_status }),
    ...(payload.readability_status === undefined ? {} : { readability_status: payload.readability_status }),
    ...(payload.visual_quality_status === undefined ? {} : { visual_quality_status: payload.visual_quality_status }),
    ...(payload.production_status === undefined ? {} : { production_status: payload.production_status }),
    ...(payload.design_status === undefined ? {} : { design_status: payload.design_status }),
    ...(payload.repair_status === undefined ? {} : { repair_status: payload.repair_status }),
    ...(payload.repair_plan === undefined ? {} : { repair_plan: compactRepairPlan(payload.repair_plan) }),
    slide_number: payload.slide_number,
    layout_id: payload.layout_id,
    category: payload.category,
    issues: compactIssues(payload.issues),
    manual_review: payload.manual_review ?? [],
  };
}

function compactDeckValidation(payload) {
  return {
    detail_level: "compact",
    // RPA-4: summary 与 result_contract 在 compact 档也保留，避免下游为拿统计而切到 full。
    ...(payload.summary === undefined ? {} : { summary: payload.summary }),
    ...(payload.result_contract === undefined ? {} : { result_contract: payload.result_contract }),
    ...(payload.pipeline_status === undefined ? {} : { pipeline_status: payload.pipeline_status }),
    status: payload.status,
    ...(payload.overall_status === undefined ? {} : { overall_status: payload.overall_status }),
    ...(payload.readability_status === undefined ? {} : { readability_status: payload.readability_status }),
    ...(payload.visual_quality_status === undefined ? {} : { visual_quality_status: payload.visual_quality_status }),
    ...(payload.production_status === undefined ? {} : { production_status: payload.production_status }),
    ...(payload.design_status === undefined ? {} : { design_status: payload.design_status }),
    ...(payload.repair_status === undefined ? {} : { repair_status: payload.repair_status }),
    slide_count: payload.slide_count,
    invalid_slides: payload.invalid_slides ?? [],
    warning_slides: payload.warning_slides ?? [],
    manual_review_slides: payload.manual_review_slides ?? [],
    repair_slides: payload.repair_slides ?? [],
    repair_actions: payload.repair_actions ?? {},
    issue_counts: payload.issue_counts,
    deck_issues: compactIssues(payload.deck_issues),
    slides: (payload.slides ?? []).map((slide) => ({
      index: slide.index,
      slide_number: slide.slide_number,
      layout_id: slide.layout_id,
      category: slide.category,
      status: slide.status,
      ...(slide.overall_status === undefined ? {} : { overall_status: slide.overall_status }),
      ...(slide.readability_status === undefined ? {} : { readability_status: slide.readability_status }),
      ...(slide.visual_quality_status === undefined ? {} : { visual_quality_status: slide.visual_quality_status }),
      ...(slide.production_status === undefined ? {} : { production_status: slide.production_status }),
      ...(slide.design_status === undefined ? {} : { design_status: slide.design_status }),
      ...(slide.repair_status === undefined ? {} : { repair_status: slide.repair_status }),
      ...(slide.repair_plan === undefined ? {} : { repair_plan: compactRepairPlan(slide.repair_plan) }),
      issues: compactIssues(slide.issues),
      manual_review: slide.manual_review ?? [],
    })),
    next_action: payload.next_action,
  };
}

function compactRendererGuard(payload) {
  return {
    detail_level: "compact",
    status: payload.status,
    requested_renderer: payload.requested_renderer,
    effective_renderer: payload.effective_renderer,
    compatibility_mode: payload.compatibility_mode,
    project_path: payload.project_path,
    page_count: payload.page_count ?? payload.source_count ?? payload.source_files?.length,
    issues: compactIssues(payload.issues),
  };
}

function compactPreflight(payload) {
  return {
    detail_level: "compact",
    pipeline_status: payload.pipeline_status,
    status: payload.status,
    invalid_slides: payload.invalid_slides ?? [],
    warning_slides: payload.warning_slides ?? [],
    renderer_guard: compactRendererGuard(payload.renderer_guard ?? {}),
    deck_validation: compactDeckValidation(payload.deck_validation ?? {}),
  };
}

function compactLayoutAudit(payload) {
  return {
    detail_level: "compact",
    audit_version: payload.audit_version,
    status: payload.status,
    layout_count: payload.layout_count,
    category_count: payload.category_count,
    theme_count: payload.theme_count,
    preview_count: payload.preview_count,
    issue_count: payload.issue_count,
    // A passing audit can still carry issues: declared stacks are legal and reported. Without the
    // error/warning split, "valid + 38 issues" reads like a contradiction in compact output.
    error_count: payload.error_count,
    warning_count: payload.warning_count,
    ...(payload.declared_overlay_count === undefined
      ? {}
      : { declared_overlay_count: payload.declared_overlay_count }),
    issue_counts: payload.issue_counts,
    issues: (payload.issues ?? []).slice(0, 20),
  };
}

function compactBenchmark(payload) {
  return {
    detail_level: "compact",
    benchmark_version: payload.benchmark_version,
    dataset: payload.dataset,
    status: payload.status,
    metrics: payload.metrics,
    determinism: payload.determinism,
    performance: payload.performance,
    thresholds: payload.thresholds,
    checks: payload.checks,
    expectation_failures: payload.expectation_failures,
    visual_quality_foundation: payload.visual_quality_foundation,
    relation_fit_foundation: payload.relation_fit_foundation,
    relation_metrics: payload.relation_metrics,
  };
}

function compactVisualQuality(payload) {
  return {
    detail_level: "compact",
    report_version: payload.report_version,
    telemetry_version: payload.telemetry_version,
    profile_id: payload.profile_id,
    profile_version: payload.profile_version,
    slide_id: payload.slide_id,
    renderer: payload.renderer,
    status: payload.status,
    production_status: payload.production_status,
    design_status: payload.design_status,
    repair_status: payload.repair_status,
    design_observation: payload.design_observation ? {
      observation_status: payload.design_observation.observation_status,
      design_metrics: payload.design_observation.design_metrics,
      issues: payload.design_observation.issues,
      recommended_actions: payload.design_observation.recommended_actions,
    } : undefined,
    repair_plan: compactRepairPlan(payload.repair_plan),
    checks: Object.fromEntries(Object.entries(payload.checks ?? {}).map(([id, check]) => [id, {
      status: check.status,
      metric: check.metric,
      actual: check.actual,
      threshold: check.threshold,
      code: check.code,
      reason: truncateText(check.reason, 140),
      recommended_action: check.recommended_action,
      ...(check.blocking === undefined ? {} : { blocking: check.blocking }),
      ...(check.review_required === undefined ? {} : { review_required: check.review_required }),
    }])),
    violations: compactIssues(payload.violations),
    recommended_action: payload.recommended_action,
    reasons: payload.reasons,
    manual_review: payload.manual_review ?? [],
  };
}

function compactTelemetryAssembly(payload) {
  return {
    detail_level: "compact",
    pipeline_status: payload.pipeline_status,
    status: payload.status,
    verification_status: payload.verification_status,
    readiness_status: payload.readiness_status,
    manifest_schema_version: payload.manifest_schema_version,
    telemetry_schema_version: payload.telemetry_schema_version,
    producer_version: payload.producer_version,
    deck_id: payload.deck_id,
    slide_id: payload.canonical_telemetry?.slide_id,
    renderer: payload.canonical_telemetry?.renderer,
    matched_visual_count: (payload.match_log ?? []).filter((item) => item.kind === "scientific_visual").length,
    missing_facts: payload.missing_facts ?? [],
    failures: payload.failures ?? [],
    manual_review: payload.manual_review ?? [],
    inspection: payload.inspection ?? [],
    geometry_provenance: payload.geometry_provenance,
    renderer_profile: payload.renderer_profile,
  };
}

function compactFigurePlacement(payload) {
  const report = payload.artifacts?.["qa_report.json"] ?? {};
  return {
    detail_level: "compact",
    pipeline_status: payload.pipeline_status,
    status: payload.status,
    trace_id: payload.trace_id,
    region_status: payload.stages?.region_resolution?.status,
    selected_region: payload.stages?.region_resolution?.selected_region ?? null,
    placement: payload.stages?.placement ? {
      status: payload.stages.placement.status,
      fit_mode: payload.stages.placement.fit_mode,
      source_region: payload.stages.placement.source_region,
      final_placement: payload.stages.placement.final_placement,
    } : null,
    renderer_effective: payload.stages?.renderer_effective ? {
      status: payload.stages.renderer_effective.status,
      placement_modified: payload.stages.renderer_effective.placement_modified,
      modification_reason: payload.stages.renderer_effective.modification_reason,
    } : null,
    metrics: payload.metrics,
    checks: Object.fromEntries(Object.entries(report.checks ?? {}).map(([id, item]) => [id, {
      status: item.status,
      code: item.code,
      recommended_action: item.recommended_action,
    }])),
    violations: compactIssues(report.violations),
    recommended_action: report.recommended_action,
  };
}

function compactVisualFitPreflight(payload) {
  return {
    detail_level: "compact",
    pipeline_status: payload.pipeline_status,
    status: payload.status,
    decision: payload.decision,
    visual_id: payload.visual_id,
    contract: payload.contract,
    metrics: {
      source_aspect_ratio: payload.metrics?.source_aspect_ratio,
      allocated_aspect_ratio: payload.metrics?.allocated_aspect_ratio,
      aspect_mismatch_factor: payload.metrics?.aspect_mismatch_factor,
      visual_fill: payload.metrics?.visual_fill,
      unused_space: payload.metrics?.unused_space,
      predicted_display_bbox: payload.metrics?.predicted_display_bbox,
    },
    issues: compactIssues(payload.issues),
    recommended_action: payload.recommended_action,
    reason: payload.reason,
  };
}

function compactGroupFitPreflight(payload) {
  return {
    detail_level: "compact",
    pipeline_status: payload.pipeline_status,
    status: payload.status,
    decision: payload.decision,
    group_id: payload.group_id,
    selected_candidate: payload.selected_candidate ? {
      layout_id: payload.selected_candidate.layout_id,
      source: payload.selected_candidate.source,
      metrics: payload.selected_candidate.metrics,
      conflict: payload.selected_candidate.conflict,
    } : null,
    fallback_to_v045: payload.fallback_to_v045,
    relation_fit: payload.relation_fit,
    constraint_arbitration: payload.constraint_arbitration,
    credits_regression: payload.credits_regression,
    issues: compactIssues(payload.issues),
    recommended_action: payload.recommended_action,
  };
}

export function formatStructuredContent(toolName, payload, detailLevel = "compact") {
  const detail = normalizeDetailLevel(detailLevel);
  if (detail === "full") return { detail_level: detail, ...payload };
  if (detail === "standard") {
    return toolName === "create_deck_plan" ? standardDeckPlan(payload) : { detail_level: detail, ...payload };
  }
  switch (toolName) {
    case "create_deck_plan": return compactDeckPlan(payload);
    case "search_layouts": return compactSearch(payload);
    case "normalize_content": return compactNormalization(payload);
    case "validate_slide":
    case "validate_rendered_slide": return compactSlideValidation(payload);
    case "validate_deck_plan":
    case "validate_rendered_deck": return compactDeckValidation(payload);
    case "validate_renderer_inputs": return compactRendererGuard(payload);
    case "run_preflight": return compactPreflight(payload);
    case "audit_layout_library": return compactLayoutAudit(payload);
    case "run_benchmark": return compactBenchmark(payload);
    case "evaluate_visual_quality": return compactVisualQuality(payload);
    case "assemble_render_telemetry": return compactTelemetryAssembly(payload);
    case "run_figure_placement": return compactFigurePlacement(payload);
    case "run_visual_fit_preflight": return compactVisualFitPreflight(payload);
    case "run_group_fit_preflight": return compactGroupFitPreflight(payload);
    default: return { detail_level: detail, ...payload };
  }
}

function issueCount(payload) {
  if (Array.isArray(payload.issues)) return payload.issues.length;
  if (Array.isArray(payload.deck_issues)) {
    return payload.deck_issues.length + (payload.slides ?? []).reduce((sum, slide) => sum + (slide.issues?.length ?? 0), 0);
  }
  return 0;
}

export function summarizeToolResult(toolName, payload, detailLevel = "compact") {
  const detail = normalizeDetailLevel(detailLevel);
  switch (toolName) {
    case "catalog_summary":
      return `Catalog ready: ${payload.library?.layout_count ?? payload.layout_count ?? 0} layouts, ${payload.themes?.length ?? 0} themes (${detail}).`;
    case "audit_layout_library":
      return `Layout audit ${payload.status}: ${payload.layout_count ?? 0} layouts, ${payload.issue_count ?? 0} issue(s) (${detail}).`;
    case "run_benchmark":
      return `Benchmark ${payload.status}: ${payload.dataset?.case_count ?? 0} cases, Top-1 ${Math.round((payload.metrics?.top_1_valid_rate?.rate ?? 0) * 100)}%, P95 ${payload.performance?.single_slide_p95_ms ?? "not measured"}ms (${detail}).`;
    case "evaluate_visual_quality":
      return `Visual QA ${payload.status}: ${payload.violations?.length ?? 0} violation(s), profile ${payload.profile_id ?? "default"} (${detail}).`;
    case "assemble_render_telemetry":
      return `Render evidence ${payload.status ?? payload.readiness_status}: ${(payload.failures ?? []).length} mismatch(es), ${(payload.missing_facts ?? []).length} missing fact(s), ${(payload.manual_review ?? []).length} manual review item(s) (${detail}).`;
    case "run_figure_placement":
      return `Figure placement ${payload.status}: ${payload.artifacts?.["qa_report.json"]?.violations?.length ?? 0} violation(s), trace ${payload.trace_id ?? "unknown"} (${detail}).`;
    case "run_visual_fit_preflight":
      return `Visual fit preflight ${payload.status}: ${payload.decision}, action ${payload.recommended_action} (${detail}).`;
    case "run_group_fit_preflight":
      return `Group fit preflight ${payload.status}: ${payload.decision}, selected ${payload.selected_candidate?.layout_id ?? "none"} (${detail}).`;
    case "normalize_content":
      return `Content normalization ${payload.status}: ${payload.sources?.length ?? 0} sources, ${payload.evidence?.length ?? 0} evidence items, ${payload.slide_briefs?.length ?? 0} slide briefs (${detail}).`;
    case "search_layouts":
      return `Layout search returned ${payload.results?.length ?? 0} ranked result(s) (${detail}).`;
    case "get_layout":
      return `Layout ${payload.layout?.id ?? payload.layout_id ?? "unknown"} loaded (${detail}).`;
    case "create_deck_plan":
      return `Planning ${payload.pipeline_status ?? "complete"}: ${payload.status}; ${payload.slide_count ?? payload.slides?.length ?? 0}/${payload.requested_slide_count ?? 0} slide(s) planned (${detail}).`;
    case "run_preflight":
      return `Preflight ${payload.pipeline_status ?? "complete"}: ${payload.status}; ${(payload.invalid_slides ?? []).length} invalid slide(s) (${detail}).`;
    case "validate_deck_plan":
    case "validate_rendered_deck":
      return `${toolName} ${payload.pipeline_status ?? "complete"}: ${payload.status}; ${(payload.invalid_slides ?? []).length} invalid and ${(payload.warning_slides ?? []).length} warning slide(s) (${detail}).`;
    case "validate_slide":
    case "validate_rendered_slide":
    case "validate_renderer_inputs":
      return `${toolName}: ${payload.status}; ${issueCount(payload)} issue(s) (${detail}).`;
    default:
      return `${toolName} completed (${detail}).`;
  }
}
