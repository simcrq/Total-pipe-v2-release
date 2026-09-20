import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { once } from "node:events";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import readline from "node:readline";
import test from "node:test";
import { fileURLToPath } from "node:url";

const TEST_DIR = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(TEST_DIR, "..");

// 这条用例用一个本机临时目录当 project_path，因此渲染器平台必须是宿主平台：
// 写死 win32 会要求盘符绝对路径并让磁盘校验因 platform_mismatch 降级 → 非 Windows 上恒失败。
// 子进程用同一个 node 运行，process.platform 在 Windows 上仍是 "win32"，行为不变。
const HOST_PLATFORM = process.platform;

test("MCP stdio server initializes, lists tools, and calls content/layout tools", async (t) => {
  const child = spawn(process.execPath, ["./server/mcp-server.mjs"], {
    cwd: ROOT,
    stdio: ["pipe", "pipe", "pipe"],
  });
  t.after(() => child.kill());

  const pending = new Map();
  const lines = readline.createInterface({ input: child.stdout, crlfDelay: Infinity });
  lines.on("line", (line) => {
    const message = JSON.parse(line);
    const waiter = pending.get(message.id);
    if (waiter) {
      pending.delete(message.id);
      waiter.resolve(message);
    }
  });

  let nextId = 1;
  function request(method, params = {}) {
    const id = nextId++;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        pending.delete(id);
        reject(new Error(`Timed out waiting for ${method}`));
      }, 5000);
      pending.set(id, {
        resolve: (message) => {
          clearTimeout(timer);
          resolve(message);
        },
      });
      child.stdin.write(`${JSON.stringify({ jsonrpc: "2.0", id, method, params })}\n`);
    });
  }

  const initialized = await request("initialize", {
    protocolVersion: "2025-06-18",
    capabilities: {},
    clientInfo: { name: "test-client", version: "1.0.0" },
  });
  assert.equal(initialized.result.serverInfo.name, "research-ppt-assistant");
  assert.equal(initialized.result.serverInfo.version, "0.6.3-rc1");
  child.stdin.write(`${JSON.stringify({ jsonrpc: "2.0", method: "notifications/initialized" })}\n`);

  const listed = await request("tools/list");
  assert.deepEqual(
    listed.result.tools.map((tool) => tool.name),
    ["catalog_summary", "audit_layout_library", "run_benchmark", "normalize_content", "search_layouts", "get_layout", "create_deck_plan", "validate_slide", "validate_deck_plan", "run_preflight", "validate_renderer_inputs", "run_visual_fit_preflight", "run_group_fit_preflight", "run_figure_placement", "assemble_render_telemetry", "evaluate_visual_quality", "validate_rendered_slide", "validate_rendered_deck"],
  );
  assert.ok(listed.result.tools.every((tool) => tool.inputSchema.properties.detail_level.enum.includes("compact")));

  const layoutAudit = await request("tools/call", { name: "audit_layout_library", arguments: {} });
  assert.equal(layoutAudit.result.isError, false);
  assert.equal(layoutAudit.result.structuredContent.status, "valid");
  assert.equal(layoutAudit.result.structuredContent.layout_count, 320);
  assert.equal(layoutAudit.result.structuredContent.detail_level, "compact");

  const benchmark = await request("tools/call", {
    name: "run_benchmark",
    arguments: { iterations: 1 },
  });
  assert.equal(benchmark.result.isError, false);
  assert.equal(benchmark.result.structuredContent.status, "passed");
  assert.equal(benchmark.result.structuredContent.determinism.passed, true);
  assert.ok(benchmark.result.structuredContent.performance.single_slide_p95_ms < 50);
  assert.equal("cases" in benchmark.result.structuredContent, false);

  const normalized = await request("tools/call", {
    name: "normalize_content",
    arguments: {
      sources: [{ source_id: "SRC0001", title: "Paper", source_sha256: "a".repeat(64) }],
      citations: [{ citation_id: "CIT0001", source_id: "SRC0001", span_id: "S0001", chunk_id: "E001", source_lines: { start: 2, end: 2 }, source_chars: { start: 10, end: 40 } }],
      evidence: [{ evidence_id: "EV0001", evidence: "Measured peak shifted.", citation_ids: ["CIT0001"], content_role: "primary_evidence", importance: 1, must_keep: true }],
      slide_briefs: [{ slide_id: "SLIDE0001", slide_type: "result", title: "Peak shifted", goal: "Present the measurement", evidence_ids: ["EV0001"], citation_ids: ["CIT0001"], visuals: [{ visual_type: "simple_plot", source_width_px: 1600, source_height_px: 900 }] }],
    },
  });
  assert.equal(normalized.result.isError, false);
  assert.equal(normalized.result.structuredContent.detail_level, "compact");
  assert.equal(normalized.result.structuredContent.status, "valid");
  assert.deepEqual(normalized.result.structuredContent.evidence[0].citation_ids, ["CIT0001"]);
  assert.equal(normalized.result.structuredContent.slide_briefs[0].visuals[0].source_width_px, 1600);
  assert.equal(normalized.result.structuredContent.slide_briefs[0].visuals[0].source_height_px, 900);

  const called = await request("tools/call", {
    name: "search_layouts",
    arguments: { text_chars: 80, image_count: 2, k: 1 },
  });
  assert.equal(called.result.isError, false);
  assert.equal(called.result.structuredContent.results[0].id, "RM-DUAL_FIGURE-01");

  const visualQuery = await request("tools/call", {
    name: "search_layouts",
    arguments: { text_chars: 80, image_count: 1, visuals: [{ visual_type: "simple_plot", source_width_px: 1600, source_height_px: 900 }], detail_level: "standard", k: 1 },
  });
  assert.equal(visualQuery.result.isError, false);
  assert.equal(visualQuery.result.structuredContent.query.visuals[0].source_width_px, 1600);
  assert.equal(visualQuery.result.structuredContent.query.visuals[0].source_height_px, 900);

  const metricPlan = await request("tools/call", {
    name: "create_deck_plan",
    arguments: {
      detail_level: "standard",
      presentation_type: "custom",
      max_replan_attempts: 0,
      sources: [{ source_id: "SRC0001", source_sha256: "a".repeat(64) }],
      citations: [{ citation_id: "CIT0001", source_id: "SRC0001", text: "来源" }],
      evidence: [{ evidence_id: "EV0001", evidence: "测量结果", citation_ids: ["CIT0001"], must_keep: true }],
      slide_briefs: [{
        slide_id: "SLIDE0001",
        title: "像素尺寸",
        goal: "展示测量结果",
        category_hint: "single_figure",
        visuals: [{ visual_type: "simple_plot", asset_uri: "figures/result.png", source_width_px: 1600, source_height_px: 900 }],
        evidence_ids: ["EV0001"],
        citation_ids: ["CIT0001"],
      }],
    },
  });
  assert.equal(metricPlan.result.isError, false);
  const plannedVisual = metricPlan.result.structuredContent.slides[0].content_metrics.visuals[0];
  assert.equal(plannedVisual.source_width_px, 1600);
  assert.equal(plannedVisual.source_height_px, 900);

  const planned = await request("tools/call", {
    name: "create_deck_plan",
    arguments: {
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
    },
  });
  assert.equal(planned.result.isError, false);
  assert.equal(planned.result.structuredContent.detail_level, "compact");
  assert.equal(planned.result.structuredContent.pipeline_status, "plan_complete");
  assert.equal(planned.result.structuredContent.status, "adapted");
  assert.equal(planned.result.structuredContent.slide_count, 2);
  assert.ok(planned.result.structuredContent.slides.every((slide) => slide.contract_valid));
  assert.equal(planned.result.content[0].text.trimStart().startsWith("{"), false);
  assert.ok(planned.result.content[0].text.length < JSON.stringify(planned.result.structuredContent).length * 0.2);

  const visualQa = await request("tools/call", {
    name: "evaluate_visual_quality",
    arguments: {
      telemetry: {
        telemetry_version: "1.0.0",
        slide_id: "MCP-SLIDE-1",
        renderer: "slidep",
        slide: { width: 10, height: 10, render_width_px: 1000, render_height_px: 1000, background: { kind: "solid", color: "#FFFFFF" } },
        elements: [{
          element_id: "body",
          type: "text",
          quality_role: "content",
          bbox: { x: 1, y: 1, width: 8, height: 8 },
          render_bbox_px: { x: 100, y: 100, width: 800, height: 800 },
          text: { content: "Readable", language: "en", script: "Latin", font_family: "Arial", font_size: 20, font_weight: 400, line_count: 1, overflow: false, foreground_color: "#111111", intended_single_line: false, role: "body" },
          image: null,
          fill_color: null,
          background_color: "#FFFFFF",
          theme_token: "text",
          theme_usage: "body_text",
        }],
        theme: { id: "fixture", tokens: { text: { color: "#111111", allowed_usage: ["body_text"], forbidden_usage: ["background"] } } },
        unavailable: [],
        provided_metrics: {},
      },
    },
  });
  assert.equal(visualQa.result.isError, false);
  assert.equal(visualQa.result.structuredContent.status, "pass");
  assert.equal(visualQa.result.structuredContent.production_status, "pass");
  assert.equal(visualQa.result.structuredContent.design_status, "pass");
  assert.equal(visualQa.result.structuredContent.repair_status, "keep");
  assert.equal(visualQa.result.structuredContent.repair_plan.action, "KEEP");
  assert.equal(visualQa.result.structuredContent.profile_id, "slidep");
  const adaptedVisualQa = await request("tools/call", {
    name: "evaluate_visual_quality",
    arguments: {
      renderer_output: {
        renderer: "slidep",
        slide_id: "MCP-RAW-1",
        width: 10,
        height: 10,
        render_width_px: 1000,
        render_height_px: 1000,
        background_color: "#FFFFFF",
        elements: [{ id: "shape", type: "shape", quality_role: "content", bbox: { x: 1, y: 1, width: 8, height: 8 } }],
      },
    },
  });
  assert.equal(adaptedVisualQa.result.isError, false);
  assert.equal(adaptedVisualQa.result.structuredContent.renderer, "slidep");

  const artifactVisualQa = await request("tools/call", {
    name: "evaluate_visual_quality",
    arguments: {
      renderer_output: {
        schema: "openai.presentation.layout/v4",
        rpa_layout_id: "RM-COVER-03",
        slide: { aid: "sl/mcp-cover", layoutType: "title", backgroundColor: "#061826", frame: { width: 1280, height: 720 } },
        elements: [
          { order: 1, kind: "image", aid: "im/cover", bbox: [0, 0, 1280, 720] },
          { order: 2, kind: "shape", aid: "sh/subtitle", name: "cover-subtitle", bbox: [100, 520, 600, 50], text: "Unmeasured subtitle", resolvedFontSize: 28, resolvedTextStyle: { color: "#FFFFFF", wrap: "none" }, textLayout: { lineCount: 1, overflow: false } },
        ],
      },
    },
  });
  assert.equal(artifactVisualQa.result.isError, false);
  assert.equal(artifactVisualQa.result.structuredContent.renderer, "artifact-tool");
  assert.equal(artifactVisualQa.result.structuredContent.profile_id, "artifact-tool");
  assert.equal(artifactVisualQa.result.structuredContent.status, "warning");

  const audited = await request("tools/call", {
    name: "validate_rendered_slide",
    arguments: {
      category: "workflow",
      viewing_mode: "projector",
      title_font_pt: 30,
      title_line_count: 2,
      body_font_pts: [14],
      content_occupancy: 0.44,
      largest_empty_band: 0.2,
    },
  });
  assert.equal(audited.result.isError, false);
  assert.equal(audited.result.structuredContent.status, "invalid");
  assert.ok(audited.result.structuredContent.issues.some((issue) => issue.code === "TITLE_WRAPPED"));

  const guarded = await request("tools/call", {
    name: "validate_renderer_inputs",
    arguments: {
      renderer: "slidep",
      renderer_version: "5.4.4",
      platform: "win32",
      project_path: "F:/Workbuddy/deck",
      source_files: ["slides/01_cover.slide", "slides/01_cover.jsx"],
      live_watch_requested: true,
    },
  });
  assert.equal(guarded.result.isError, false);
  assert.equal(guarded.result.structuredContent.status, "invalid");
  assert.ok(guarded.result.structuredContent.issues.some((issue) => issue.code === "DUPLICATE_PAGE_ID"));

  const visualFit = await request("tools/call", {
    name: "run_visual_fit_preflight",
    arguments: {
      visual_id: "extended-data-fig-1",
      source: { width: 1432, height: 1189 },
      source_region: { x: 0, y: 0, width: 1432, height: 1189 },
      visual_intent: { visual_type: "scientific_figure", crop_policy: "full_figure", fit_policy: "contain", whitespace_policy: "minimal" },
      allocated_visual_bbox: { x: 72, y: 156, width: 1136, height: 292 },
      visual_container: {
        container_id: "s4-figure-panel",
        role: "image_only",
        outer_bbox: { x: 64, y: 148, width: 1152, height: 308 },
        content_bbox: { x: 72, y: 156, width: 1136, height: 292 },
        content_inset: { left: 8, right: 8, top: 8, bottom: 8 },
        child_visual_ids: ["extended-data-fig-1"],
        fit_policy: "contain",
        crop_policy: "full_figure",
        whitespace_policy: "minimal",
        mismatch_policy: "replan",
      },
    },
  });
  assert.equal(visualFit.result.isError, false);
  assert.equal(visualFit.result.structuredContent.pipeline_status, "visual_fit_preflight_complete");
  assert.equal(visualFit.result.structuredContent.status, "fail");
  assert.equal(visualFit.result.structuredContent.decision, "needs_replan");

  const groupFit = await request("tools/call", {
    name: "run_group_fit_preflight",
    arguments: {
      visual_group: { group_id: "mcp-group", semantic_relation: "parallel", relation_strength: "soft", children: ["a", "b"] },
      layout_relation: { shared_alignment: true, shared_container_style: true, equal_size: true, equal_width: true, equal_height: true, preserve_order: true },
      children: [{ visual_id: "a", source: { width: 200, height: 100 } }, { visual_id: "b", source: { width: 200, height: 100 } }],
      baseline_candidate: {
        layout_id: "MCP-EQUAL-TWO",
        group_bbox: { x: 0, y: 0, width: 8, height: 2 },
        allocations: [
          { visual_id: "a", allocated_visual_bbox: { x: 0, y: 0, width: 3.9, height: 2 } },
          { visual_id: "b", allocated_visual_bbox: { x: 4.1, y: 0, width: 3.9, height: 2 } },
        ],
      },
    },
  });
  assert.equal(groupFit.result.isError, false);
  assert.equal(groupFit.result.structuredContent.pipeline_status, "group_fit_preflight_complete");
  assert.equal(groupFit.result.structuredContent.decision, "preserve_v045_baseline");
  assert.equal(groupFit.result.structuredContent.selected_candidate.layout_id, "MCP-EQUAL-TWO");

  const figurePlacement = await request("tools/call", {
    name: "run_figure_placement",
    arguments: {
      trace_id: "mcp-figure-1",
      visual: { source_width_px: 1000, source_height_px: 500, visual_intent: { selection: { strategy: "full_figure" }, placement: { preferred_fit: "contain" } } },
      allocated_visual_bbox: { x: 1, y: 1, width: 4, height: 2 },
      slide: { width: 10, height: 5, render_width_px: 1000, render_height_px: 500 },
      renderer_result: {
        effective_placement: { x: 1, y: 1, width: 4, height: 2 },
        effective_source_region: { x: 0, y: 0, width: 1, height: 1 },
        render_bbox_px: { x: 100, y: 100, width: 400, height: 200 },
      },
    },
  });
  assert.equal(figurePlacement.result.isError, false);
  assert.equal(figurePlacement.result.structuredContent.pipeline_status, "figure_placement_complete");
  assert.equal(figurePlacement.result.structuredContent.status, "pass");

  const fullPlan = await request("tools/call", {
    name: "create_deck_plan",
    arguments: {
      detail_level: "full",
      presentation_type: "custom",
      slide_briefs: [{
        title: "核心结论",
        category_hint: "single_figure",
        text_chars: 40,
        image_count: 1,
        visuals: [{ visual_type: "dense_plot", panel_count: 2, has_embedded_text: true, asset_uri: "figures/result.png" }],
      }],
    },
  });
  assert.equal(fullPlan.result.isError, false);
  const deckDir = await fs.mkdtemp(path.join(os.tmpdir(), "rpa-deck-"));
  await fs.mkdir(path.join(deckDir, "slides"), { recursive: true });
  await fs.writeFile(path.join(deckDir, "slides", "01_result.slide"), "");
  const preflight = await request("tools/call", {
    name: "run_preflight",
    arguments: {
      renderer_inputs: {
        requested_renderer: "slidep",
        renderer_version: "5.4.4",
        platform: HOST_PLATFORM,
        project_path: deckDir,
        project_exists: true,
        source_files: ["slides/01_result.slide"],
        live_watch_requested: false,
      },
      deck_plan: {
        theme_id: fullPlan.result.structuredContent.theme.id,
        slides: fullPlan.result.structuredContent.slides,
      },
    },
  });
  await fs.rm(deckDir, { recursive: true, force: true });
  assert.equal(preflight.result.isError, false);
  assert.equal(preflight.result.structuredContent.pipeline_status, "preflight_complete");
  assert.equal(preflight.result.structuredContent.renderer_guard.status, "valid");

  const assembled = await request("tools/call", {
    name: "assemble_render_telemetry",
    arguments: {
      renderer_output: {
        schema: "openai.presentation.layout/v4",
        slide: { aid: "SLIDE0001", layoutId: "RM-SINGLE_FIGURE-01", layoutType: "evidence", frame: { width: 1280, height: 720 }, backgroundColor: "#FFFFFF" },
        elements: [{ aid: "figure", kind: "image", alt: "rpa:figure-1 | Figure 1", bbox: [80, 100, 1120, 500], imageFit: "contain", assetSha256: "a".repeat(64) }],
      },
    },
  });
  assert.equal(assembled.result.isError, false);
  assert.equal(assembled.result.structuredContent.readiness_status, "blocked");
  assert.ok(assembled.result.structuredContent.missing_facts.some((item) => item.field === "visual_manifest"));

  const evidenceClosed = await request("tools/call", {
    name: "assemble_render_telemetry",
    arguments: {
      renderer_output: {
        schema: "openai.presentation.layout/v4",
        slide: { aid: "SLIDE0005", layoutId: "RM-SINGLE_FIGURE-01", layoutType: "evidence", frame: { width: 1280, height: 720 }, backgroundColor: "#FFFFFF" },
        elements: [
          { aid: "frame", kind: "shape", name: "s5-figure-panel", bbox: [80, 100, 1120, 500], order: 1 },
          { aid: "figure", kind: "image", visualKey: "results-fig2a", bbox: [80, 100, 1120, 500], imageFit: "contain", assetSha256: "a".repeat(64), order: 2 },
        ],
      },
      visual_manifest: {
        manifest_schema_version: "0.4.7",
        producer_version: "deck-builder@mcp-test",
        deck_id: "mcp-evidence-deck",
        visuals: [{
          visual_key: "results-fig2a", slide_id: "SLIDE0005", source_visual_id: "fig2a", visual_type: "simple_plot",
          panel_count: 1, has_embedded_text: false, source_width_px: 1120, source_height_px: 500,
          source_region: { x: 0, y: 0, width: 1, height: 1 }, coordinate_space: "source_normalized_0_1",
          slot_id: "figure", container_id: "s5-figure", asset_sha256: "a".repeat(64), crop_mode: "full_figure",
        }],
        containers: [{
          container_id: "s5-figure", shape_name: "s5-figure-panel", role: "image_only", fit_policy: "contain",
          crop_policy: "full_figure", whitespace_policy: "minimal", mismatch_policy: "replan",
        }],
        visual_groups: [],
      },
    },
  });
  assert.equal(evidenceClosed.result.isError, false);
  assert.equal(evidenceClosed.result.structuredContent.status, "pass");
  assert.equal(evidenceClosed.result.structuredContent.telemetry_schema_version, "0.4.7");

  const invalidCases = [
    ["get_layout", {}, "required"],
    ["search_layouts", { k: "one" }, "type"],
    ["validate_rendered_slide", { viewing_mode: "wall" }, "enum"],
    ["evaluate_visual_quality", {}, "oneOf"],
    ["assemble_render_telemetry", { renderer_output: {}, renderer_profile: "slidep" }, "const"],
    ["catalog_summary", { unexpected: true }, "additionalProperties"],
    ["create_deck_plan", { slide_briefs: [{ title: "Nested", unexpected: true }] }, "additionalProperties"],
    ["validate_renderer_inputs", { project_path: "F:/deck", source_files: [123] }, "type"],
    ["run_figure_placement", { trace_id: "x", visual: {}, allocated_visual_bbox: { x: 0, y: 0, width: 1, height: 1 } }, "required"],
    ["run_visual_fit_preflight", { visual_id: "x" }, "required"],
    ["run_group_fit_preflight", { visual_group: {} }, "required"],
    ["run_benchmark", { iterations: 0 }, "minimum"],
  ];
  for (const [name, args, keyword] of invalidCases) {
    const response = await request("tools/call", { name, arguments: args });
    assert.equal(response.result.isError, true, `${name} should reject invalid input`);
    assert.equal(response.result.structuredContent.code, "MCP_INPUT_SCHEMA_ERROR");
    assert.ok(response.result.structuredContent.schema_errors.some((error) => error.keyword === keyword), JSON.stringify(response.result.structuredContent));
  }
});

test("MCP stdio server drains an accepted request after stdin closes", async () => {
  const child = spawn(process.execPath, ["./server/mcp-server.mjs"], {
    cwd: ROOT,
    stdio: ["pipe", "pipe", "pipe"],
  });
  let stdout = "";
  let stderr = "";
  child.stdout.setEncoding("utf8");
  child.stderr.setEncoding("utf8");
  child.stdout.on("data", (chunk) => { stdout += chunk; });
  child.stderr.on("data", (chunk) => { stderr += chunk; });

  const request = {
    jsonrpc: "2.0",
    id: 1,
    method: "tools/call",
    params: {
      name: "create_deck_plan",
      arguments: {
        presentation_type: "custom",
        detail_level: "compact",
        slide_briefs: Array.from({ length: 30 }, (_, index) => ({
          slide_id: `SLIDE${String(index + 1).padStart(4, "0")}`,
          title: `Result ${index + 1}`,
          category_hint: "summary",
          claims: [{ id: `claim-${index + 1}`, text: `Measured result ${index + 1}` }],
        })),
      },
    },
  };
  child.stdin.end(`${JSON.stringify(request)}\n`);

  const [exitCode] = await once(child, "close");
  assert.equal(exitCode, 0, stderr);
  const responses = stdout.trim().split(/\r?\n/u).filter(Boolean).map((line) => JSON.parse(line));
  const response = responses.find((message) => message.id === 1);
  assert.ok(response, `missing response; stderr=${stderr}`);
  assert.equal(response.result.isError, false);
  assert.equal(response.result.structuredContent.pipeline_status, "plan_complete");
  assert.equal(response.result.structuredContent.slide_count, 30);
});
