import { QA_REPORT_VERSION } from "./contracts.mjs";

function reportStatus(checks) {
  const active = Object.values(checks).filter((check) => check?.disabled !== true && check?.blocking !== false);
  if (active.some((check) => check.status === "fail")) return "fail";
  if (active.some((check) => check.status === "warning")) return "warning";
  if (active.length && active.every((check) => check.status === "not_evaluable")) return "not_evaluable";
  if (active.some((check) => check.status === "not_evaluable")) return "warning";
  return "pass";
}

export function createQaReport({ telemetry, profile, checks = {}, metrics = {}, violations = [] }) {
  const status = reportStatus(checks);
  const reasons = [...new Set([
    ...violations.filter((violation) => violation.severity !== "info").map((violation) => violation.code),
    ...Object.values(checks)
      .filter((check) => check?.status === "not_evaluable" && check?.disabled !== true && check?.blocking !== false)
      .map((check) => check.reason ?? "NOT_EVALUABLE"),
  ])];
  const blocking = Object.values(checks).find((check) => check?.status === "fail")
    ?? Object.values(checks).find((check) => check?.status === "warning")
    ?? Object.values(checks).find((check) => check?.status === "not_evaluable" && check?.disabled !== true && check?.blocking !== false);
  const manualReview = Object.values(checks)
    .filter((check) => check?.review_required === true)
    .map((check) => ({ rule_id: check.rule_id, code: check.code, reason: check.reason, recommended_action: check.recommended_action }));
  return {
    report_version: QA_REPORT_VERSION,
    telemetry_version: telemetry.telemetry_version,
    profile_id: profile.profile_id,
    profile_version: profile.profile_version,
    slide_id: telemetry.slide_id,
    renderer: telemetry.renderer,
    status,
    checks,
    metrics,
    violations,
    recommended_action: blocking?.recommended_action ?? (status === "pass" ? "none" : "provide_required_input"),
    reasons,
    manual_review: manualReview,
  };
}
