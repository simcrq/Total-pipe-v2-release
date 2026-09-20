import assert from "node:assert/strict";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { loadBenchmarkDataset, runBenchmark } from "../server/benchmark.mjs";

test("stability benchmark covers required scenarios and emits all quality rates", async () => {
  const dataset = await loadBenchmarkDataset();
  const tags = new Set(dataset.cases.flatMap((item) => item.tags));
  for (const tag of ["historical_bug", "multilingual_title", "scientific_figure", "paper_table", "10_plus_steps", "complex_timeline", "mixed_language", "formula", "code", "high_image_density", "low_content_density"]) {
    assert.ok(tags.has(tag), `missing benchmark tag ${tag}`);
  }

  const result = await runBenchmark({ dataset, iterations: 2 });
  assert.equal(result.status, "passed");
  assert.equal(result.dataset.case_count, 11);
  assert.equal(result.determinism.passed, true);
  assert.equal(result.determinism.first_digest, result.determinism.second_digest);
  assert.ok(result.performance.single_slide_p95_ms < 50);
  for (const name of ["top_1_valid_rate", "top_k_valid_rate", "replan_rate", "auto_split_rate", "contract_failure_rate", "preflight_failure_rate", "render_qa_failure_rate"]) {
    assert.equal(typeof result.metrics[name].rate, "number", name);
  }
  assert.equal(result.metrics.auto_split_rate.passed, 1);
  assert.equal(result.metrics.contract_failure_rate.passed, 0);
  assert.equal(result.expectation_failures.length, 0);
  assert.deepEqual(result.visual_quality_foundation.map((probe) => probe.id), [
    "non_square_visual_center",
    "render_pixel_out_of_bounds",
    "partial_telemetry_not_evaluable",
    "cover_text_image_protection_not_evaluable",
    "meta_assembly_visual_fit_blocked",
    "intentional_whitespace_not_false_failed",
    "semantic_crop_routes_to_region_resolution",
  ]);
  assert.ok(result.visual_quality_foundation.every((probe) => probe.passed));
  assert.ok(result.checks.some((check) => check.name === "visual_quality_foundation" && check.passed));
  assert.equal(result.relation_fit_foundation.length, 8);
  assert.ok(result.relation_fit_foundation.every((probe) => probe.passed));
  assert.equal(result.relation_metrics.conflict_detection_precision, 1);
  assert.equal(result.relation_metrics.conflict_detection_recall, 1);
  assert.equal(result.relation_metrics.layout_churn_rate_on_v045_good.rate, 0);
  assert.ok(result.relation_metrics.credits_per_deck_ratio <= 1.1);
  assert.ok(result.checks.some((check) => check.name === "relation_fit_foundation" && check.passed));
});

test("benchmark failure is explicit when a case expectation regresses", async () => {
  const dataset = await loadBenchmarkDataset();
  const benchmarkCase = structuredClone(dataset.cases[0]);
  benchmarkCase.expect = { auto_split: true, preflight_failure: false, render_qa_failure: false };
  const result = await runBenchmark({
    dataset: {
      schema_version: "test",
      name: "failing fixture",
      thresholds: {
        top_1_valid_rate_min: 0,
        top_k_valid_rate_min: 0,
        contract_failure_rate_max: 1,
        preflight_failure_rate_max: 1,
        single_slide_p95_ms_max: 50
      },
      cases: [benchmarkCase],
    },
    include_performance: false,
    iterations: 1,
  });
  assert.equal(result.status, "failed");
  assert.equal(result.performance, undefined);
  assert.deepEqual(result.expectation_failures.map((item) => item.field), ["auto_split", "preflight_failure", "render_qa_failure"]);
  assert.ok(result.checks.some((item) => item.name === "case_expectations" && !item.passed));
});

test("benchmark dataset loader rejects an empty dataset", async (t) => {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), "rpa-benchmark-"));
  t.after(() => fs.rm(directory, { recursive: true, force: true }));
  const file = path.join(directory, "empty.json");
  await fs.writeFile(file, JSON.stringify({ cases: [] }));
  await assert.rejects(() => loadBenchmarkDataset(file), /at least one case/);
  await assert.rejects(() => runBenchmark({ dataset: { cases: [] } }), /at least one case/);
});

test("benchmark defaults optional thresholds and rejects invalid iteration counts", async () => {
  const dataset = await loadBenchmarkDataset();
  const result = await runBenchmark({
    dataset: { schema_version: "test", name: "default thresholds", cases: [dataset.cases[0]] },
    include_performance: false,
    iterations: 1,
  });
  assert.equal(result.status, "passed");
  assert.equal(result.thresholds.single_slide_p95_ms_max, 50);
  for (const iterations of [0, 1.5, 201, "many"]) {
    await assert.rejects(() => runBenchmark({ dataset, iterations }), /integer from 1 to 200/);
  }
});

test("benchmark accepts sparse optional case fields and can load its default dataset", async () => {
  const dataset = await loadBenchmarkDataset();
  const benchmarkCase = structuredClone(dataset.cases[0]);
  delete benchmarkCase.acceptable_categories;
  delete benchmarkCase.expect;
  delete benchmarkCase.query.k;
  delete benchmarkCase.slide_brief.category_hint;
  const sparse = await runBenchmark({
    dataset: { schema_version: "test", name: "sparse optionals", cases: [benchmarkCase] },
    iterations: 1,
  });
  assert.equal(sparse.status, "passed");
  assert.equal(sparse.performance.iterations, 1);
  assert.ok(sparse.cases[0].candidate_count > 0);

  const bundled = await runBenchmark({ include_performance: false, iterations: 1 });
  assert.equal(bundled.dataset.case_count, 11);
  assert.equal(bundled.performance, undefined);
});
