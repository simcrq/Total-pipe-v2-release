import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const TEST_DIR = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(TEST_DIR, "..");

function runCli(args) {
  return new Promise((resolve, reject) => {
    const child = spawn(process.execPath, ["./server/cli.mjs", ...args], {
      cwd: ROOT,
      stdio: ["ignore", "pipe", "pipe"],
    });
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (chunk) => { stdout += chunk; });
    child.stderr.on("data", (chunk) => { stderr += chunk; });
    child.on("error", reject);
    child.on("close", (code) => resolve({ code, stdout, stderr }));
  });
}

test("CLI parses all documented boolean spellings deterministically", async () => {
  const cases = [
    ["true", true],
    ["1", true],
    ["yes", true],
    ["false", false],
    ["0", false],
    ["no", false],
  ];
  for (const [value, expected] of cases) {
    const result = await runCli(["search", "--allow-auto-split", value, "--k", "1"]);
    assert.equal(result.code, 0, result.stderr);
    assert.equal(JSON.parse(result.stdout).query.allow_auto_split, expected, value);
  }
});

test("CLI treats a bare boolean flag as true", async () => {
  const result = await runCli(["search", "--allow-auto-split", "--k", "1"]);
  assert.equal(result.code, 0, result.stderr);
  assert.equal(JSON.parse(result.stdout).query.allow_auto_split, true);
});

test("CLI rejects invalid boolean values", async () => {
  const result = await runCli(["search", "--allow-auto-split", "sometimes", "--k", "1"]);
  assert.equal(result.code, 1);
  assert.match(result.stderr, /expects true\/false, 1\/0, or yes\/no/);
});

test("CLI exposes deterministic content normalization", async () => {
  const payload = JSON.stringify({
    slide_briefs: [{ title: "  Main   result  ", goal: "Explain the result" }],
  });
  const first = await runCli(["normalize-content", "--json", payload]);
  const second = await runCli(["normalize-content", "--json", payload]);
  assert.equal(first.code, 0, first.stderr);
  assert.equal(second.code, 0, second.stderr);
  assert.equal(first.stdout, second.stdout);
  const normalized = JSON.parse(first.stdout);
  assert.equal(normalized.status, "valid");
  assert.equal(normalized.slide_briefs[0].title, "Main result");
});

test("CLI exposes the figure placement fact chain", async () => {
  const payload = JSON.stringify({
    trace_id: "cli-figure-1",
    visual: { source_width_px: 1000, source_height_px: 500, visual_intent: { selection: { strategy: "full_figure" }, placement: { preferred_fit: "contain" } } },
    allocated_visual_bbox: { x: 1, y: 1, width: 4, height: 2 },
    slide: { width: 10, height: 5, render_width_px: 1000, render_height_px: 500 },
    renderer_result: { effective_placement: { x: 1, y: 1, width: 4, height: 2 }, effective_source_region: { x: 0, y: 0, width: 1, height: 1 }, render_bbox_px: { x: 100, y: 100, width: 400, height: 200 } },
  });
  const result = await runCli(["figure-placement", "--json", payload]);
  assert.equal(result.code, 0, result.stderr);
  const output = JSON.parse(result.stdout);
  assert.equal(output.pipeline_status, "figure_placement_complete");
  assert.equal(output.status, "pass");
});

test("CLI blocks the meta-assembly visual-slot mismatch before rendering", async () => {
  const payload = JSON.stringify({
    visual_id: "extended-data-fig-1",
    source: { width: 1432, height: 1189 },
    source_region: { x: 0, y: 0, width: 1432, height: 1189 },
    visual_intent: { visual_type: "scientific_figure", crop_policy: "full_figure", fit_policy: "contain", whitespace_policy: "minimal" },
    allocated_visual_bbox: { x: 72, y: 156, width: 1136, height: 292 },
    visual_container: { role: "image_only", fit_policy: "contain", crop_policy: "full_figure", whitespace_policy: "minimal", mismatch_policy: "replan" },
  });
  const result = await runCli(["visual-fit-preflight", "--json", payload]);
  assert.equal(result.code, 0, result.stderr);
  const output = JSON.parse(result.stdout);
  assert.equal(output.pipeline_status, "visual_fit_preflight_complete");
  assert.equal(output.status, "fail");
  assert.equal(output.decision, "needs_replan");
  assert.equal(output.recommended_action, "replan");
});

test("CLI exposes relation-aware group fit without changing a compatible baseline", async () => {
  const payload = JSON.stringify({
    visual_group: { group_id: "cli-group", semantic_relation: "parallel", relation_strength: "soft", children: ["a", "b"] },
    layout_relation: { shared_alignment: true, shared_container_style: true, equal_size: true, equal_width: true, equal_height: true, preserve_order: true },
    children: [{ visual_id: "a", source: { width: 200, height: 100 } }, { visual_id: "b", source: { width: 200, height: 100 } }],
    baseline_candidate: {
      layout_id: "CLI-EQUAL-TWO",
      group_bbox: { x: 0, y: 0, width: 8, height: 2 },
      allocations: [
        { visual_id: "a", allocated_visual_bbox: { x: 0, y: 0, width: 3.9, height: 2 } },
        { visual_id: "b", allocated_visual_bbox: { x: 4.1, y: 0, width: 3.9, height: 2 } },
      ],
    },
  });
  const result = await runCli(["group-fit-preflight", "--json", payload]);
  assert.equal(result.code, 0, result.stderr);
  const output = JSON.parse(result.stdout);
  assert.equal(output.pipeline_status, "group_fit_preflight_complete");
  assert.equal(output.decision, "preserve_v045_baseline");
  assert.equal(output.selected_candidate.layout_id, "CLI-EQUAL-TWO");
});

test("CLI exposes the Render Evidence Sidecar readiness gate", async () => {
  const payload = JSON.stringify({
    renderer_output: {
      schema: "openai.presentation.layout/v4",
      slide: { aid: "SLIDE0001", layoutId: "RM-SINGLE_FIGURE-01", layoutType: "evidence", frame: { width: 1280, height: 720 }, backgroundColor: "#FFFFFF" },
      elements: [{ aid: "figure", kind: "image", alt: "rpa:figure-1 | Figure 1", bbox: [80, 100, 1120, 500], imageFit: "contain", assetSha256: "a".repeat(64) }],
    },
  });
  const result = await runCli(["assemble-render-telemetry", "--json", payload, "--detail-level", "compact"]);
  assert.equal(result.code, 0, result.stderr);
  const output = JSON.parse(result.stdout);
  assert.equal(output.pipeline_status, "render_telemetry_assembled");
  assert.equal(output.readiness_status, "blocked");
  assert.ok(output.missing_facts.some((item) => item.field === "visual_manifest"));
});

test("CLI plan runs the structural auto-split loop", async () => {
  const payload = JSON.stringify({
    presentation_type: "custom",
    allow_auto_split: true,
    max_replan_attempts: 0,
    slide_briefs: [{
      slide_id: "SLIDE0001",
      title: "十步流程",
      category_hint: "workflow",
      process_step_count: 10,
      process_steps: Array.from({ length: 10 }, (_, index) => ({ id: `step-${index + 1}`, text: `步骤 ${index + 1}` })),
    }],
  });
  const result = await runCli(["plan", "--json", payload]);
  assert.equal(result.code, 0, result.stderr);
  const plan = JSON.parse(result.stdout);
  assert.equal(plan.status, "adapted");
  assert.equal(plan.slide_count, 2);
  assert.ok(plan.slides.every((slide) => slide.contract_valid));
});

test("CLI supports compact, standard, and full output with standard as its default", async () => {
  const payload = JSON.stringify({ presentation_type: "group_meeting", slide_count: 8, topic: "Compact QA" });
  const standard = await runCli(["plan", "--json", payload]);
  const compact = await runCli(["plan", "--json", payload, "--detail-level", "compact"]);
  const full = await runCli(["plan", "--json", payload, "--detail-level", "full"]);
  assert.equal(standard.code, 0, standard.stderr);
  assert.equal(compact.code, 0, compact.stderr);
  assert.equal(full.code, 0, full.stderr);
  assert.equal(JSON.parse(standard.stdout).detail_level, "standard");
  assert.equal(JSON.parse(compact.stdout).detail_level, "compact");
  assert.equal(JSON.parse(full.stdout).detail_level, "full");
  assert.ok(compact.stdout.length < full.stdout.length * 0.55, `compact=${compact.stdout.length}, full=${full.stdout.length}`);
});

test("CLI rejects unsupported detail levels", async () => {
  const result = await runCli(["summary", "--detail-level", "verbose"]);
  assert.equal(result.code, 1);
  assert.match(result.stderr, /Unsupported detail_level/);
});

test("CLI exposes the blocking layout audit", async () => {
  const result = await runCli(["audit-layouts", "--detail-level", "compact"]);
  assert.equal(result.code, 0, result.stderr);
  const audit = JSON.parse(result.stdout);
  assert.equal(audit.status, "valid");
  assert.equal(audit.layout_count, 320);
  // The library ships declared stacks, so a passing audit means "no errors" rather than "no issues".
  assert.equal(audit.error_count, 0);
  assert.equal(audit.issue_count, audit.declared_overlay_count);
});

test("CLI runs the deterministic benchmark without returning case details in compact mode", async () => {
  const result = await runCli(["benchmark", "--iterations", "1", "--detail-level", "compact"]);
  assert.equal(result.code, 0, result.stderr);
  const benchmark = JSON.parse(result.stdout);
  assert.equal(benchmark.status, "passed");
  assert.equal(benchmark.determinism.passed, true);
  assert.ok(benchmark.performance.single_slide_p95_ms < 50);
  assert.equal("cases" in benchmark, false);
});

test("CLI benchmark parses include-performance as a real boolean", async () => {
  const result = await runCli(["benchmark", "--iterations", "1", "--include-performance", "false", "--detail-level", "compact"]);
  assert.equal(result.code, 0, result.stderr);
  const benchmark = JSON.parse(result.stdout);
  assert.equal(benchmark.status, "passed");
  assert.equal("performance" in benchmark, false);
});

test("CLI evaluates canonical render telemetry through Visual QA", async () => {
  const telemetry = {
    telemetry_version: "1.0.0",
    slide_id: "CLI-SLIDE-1",
    renderer: "slidep",
    slide: { width: 10, height: 10, render_width_px: 1000, render_height_px: 1000, background: { kind: "solid", color: "#fff" } },
    elements: [{
      element_id: "body",
      type: "text",
      quality_role: "content",
      bbox: { x: 1, y: 1, width: 8, height: 8 },
      render_bbox_px: { x: 100, y: 100, width: 800, height: 800 },
      text: { content: "Readable", language: "en", script: "Latin", font_family: "Arial", font_size: 20, font_weight: 400, line_count: 1, overflow: false, foreground_color: "#111", intended_single_line: false, role: "body" },
      image: null,
      fill_color: null,
      background_color: "#fff",
      theme_token: "text",
      theme_usage: "body_text",
    }],
    theme: { id: "fixture", tokens: { text: { color: "#111111", allowed_usage: ["body_text"], forbidden_usage: ["background"] } } },
    unavailable: [],
    provided_metrics: {},
  };
  const result = await runCli(["visual-quality", "--json", JSON.stringify(telemetry), "--detail-level", "compact"]);
  assert.equal(result.code, 0, result.stderr);
  const report = JSON.parse(result.stdout);
  assert.equal(report.status, "pass");
  assert.equal(report.profile_id, "slidep");
});

test("CLI detects raw renderer output by complete shape instead of a telemetry_version collision", async () => {
  const raw = {
    telemetry_version: "1.0.0",
    renderer: "slidep",
    slideId: "raw-cli-slide",
    slide: {
      size: { width: 10, height: 10 },
      renderSize: { width: 1000, height: 1000 },
      background: { kind: "solid", color: "#ffffff" },
      elements: [{
        id: "body",
        type: "text",
        qualityRole: "content",
        bbox: { x: 1, y: 1, width: 8, height: 8 },
        render_bbox: { x: 100, y: 100, width: 800, height: 800 },
        text: {
          content: "Readable", fontFamily: "Arial", fontSize: 20, lineCount: 1,
          overflow: false, foregroundColor: "#111111", role: "body",
        },
        backgroundColor: "#ffffff",
        themeToken: "text",
        themeUsage: "body_text",
      }],
    },
    theme: { id: "fixture", tokens: { text: { color: "#111111", allowed_usage: ["body_text"], forbidden_usage: [] } } },
  };
  const result = await runCli(["visual-quality", "--json", JSON.stringify(raw), "--detail-level", "compact"]);
  assert.equal(result.code, 0, result.stderr);
  assert.equal(JSON.parse(result.stdout).slide_id, "raw-cli-slide");
});
