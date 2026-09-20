import fs from "node:fs/promises";
import crypto from "node:crypto";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { runFigurePlacement } from "./figure-placement.mjs";

const MODULE_DIR = path.dirname(fileURLToPath(import.meta.url));
const DEFAULT_FIXTURE_PATH = path.resolve(MODULE_DIR, "..", "benchmarks", "figure-placement-golden.json");

export async function runFigurePlacementGolden({ fixture_path = DEFAULT_FIXTURE_PATH, require_source = false } = {}) {
  if (typeof require_source !== "boolean") throw new TypeError("require_source must be a boolean");
  const dataset = JSON.parse(await fs.readFile(fixture_path, "utf8"));
  const sourcePath = path.resolve(MODULE_DIR, "..", dataset.source_deck);
  let sourceIntegrity = { available: false, status: "not_evaluable", expected_sha256: dataset.source_deck_sha256, actual_sha256: null };
  try {
    const source = await fs.readFile(sourcePath);
    const actual = crypto.createHash("sha256").update(source).digest("hex");
    sourceIntegrity = { available: true, status: actual === dataset.source_deck_sha256 ? "passed" : "failed", expected_sha256: dataset.source_deck_sha256, actual_sha256: actual };
  } catch (error) {
    if (error?.code !== "ENOENT") throw error;
  }
  const cases = dataset.fixtures.map((fixture) => {
    const output = runFigurePlacement(fixture.input);
    const actualCodes = output.artifacts["qa_report.json"].violations.map((item) => item.code);
    const missingCodes = fixture.expected.codes.filter((code) => !actualCodes.includes(code));
    const statusMatches = output.status === fixture.expected.status;
    const actionMatches = !fixture.expected.recommended_action || output.artifacts["qa_report.json"].recommended_action === fixture.expected.recommended_action;
    return {
      fixture_id: fixture.fixture_id,
      status: statusMatches && actionMatches && !missingCodes.length ? "passed" : "failed",
      expected_status: fixture.expected.status,
      actual_status: output.status,
      expected_codes: fixture.expected.codes,
      actual_codes: actualCodes,
      missing_codes: missingCodes,
      recommended_action: output.artifacts["qa_report.json"].recommended_action,
      trace_id: output.trace_id,
      metrics: output.metrics,
    };
  });
  const fixturesPassed = cases.length > 0 && cases.every((item) => item.status === "passed");
  const sourcePassed = sourceIntegrity.status === "passed";
  return {
    benchmark_version: dataset.fixture_version,
    validation_mode: require_source ? "source_backed" : "fixtures",
    fixture_status: fixturesPassed ? "passed" : "failed",
    verified_checks: [
      ...(fixturesPassed ? ["fixture_regressions"] : []),
      ...(sourcePassed ? ["source_deck_sha256"] : []),
    ],
    status: fixturesPassed && sourceIntegrity.status !== "failed" && (!require_source || sourcePassed) ? "passed" : "failed",
    source_deck: dataset.source_deck,
    source_deck_sha256: dataset.source_deck_sha256,
    fixture_count: cases.length,
    passed_count: cases.filter((item) => item.status === "passed").length,
    source_integrity: sourceIntegrity,
    cases,
  };
}
