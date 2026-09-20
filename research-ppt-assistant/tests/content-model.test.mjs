import assert from "node:assert/strict";
import test from "node:test";
import {
  ADAPTATION_LOG_SCHEMA,
  CITATION_SCHEMA,
  CONTENT_MODEL_INPUT_SCHEMA,
  CONTENT_MODEL_VERSION,
  CONTENT_ROLES,
  EVIDENCE_SCHEMA,
  EVIDENCE_TYPES,
  SLIDE_BRIEF_SCHEMA,
  SOURCE_SCHEMA,
  VIOLATION_SCHEMA,
  createAdaptationLogEntry,
  createViolation,
  normalizeContentModel,
  normalizePaperWorkflowV4,
} from "../server/content-model.mjs";

const forbiddenKeys = new Set(["layout_id", "layout", "slot_specs", "slot_assignments"]);

function collectKeys(value, output = []) {
  if (Array.isArray(value)) {
    value.forEach((item) => collectKeys(item, output));
  } else if (value && typeof value === "object") {
    for (const [key, child] of Object.entries(value)) {
      output.push(key);
      collectKeys(child, output);
    }
  }
  return output;
}

test("content normalization is deterministic and preserves first-seen IDs", () => {
  const input = {
    sources: [{ source_id: "SRC0007", source_sha256: "sha-7", title: "  A source  " }],
    citations: [{ citation_id: "CIT0008", source_id: "SRC0007", text: "  location  " }],
    evidence: [{
      evidence_id: "EV0009",
      citation_ids: ["CIT0008"],
      importance: "0",
      must_keep: "false",
      content_role: "primary_claim",
      support_type: "measurement",
      text: "  measured value  ",
    }],
    slide_briefs: [{
      slide_id: "SLIDE0003",
      slide_type: "result",
      title: "  Main\nresult  ",
      goal: "  Show the result  ",
      evidence_ids: ["EV0009", "EV0009"],
      citation_ids: ["CIT0008"],
      claims: ["  claim  "],
    }],
  };
  const first = normalizeContentModel(input);
  const second = normalizeContentModel(input);
  assert.equal(JSON.stringify(first), JSON.stringify(second));
  assert.equal(first.schema_version, CONTENT_MODEL_VERSION);
  assert.equal(first.status, "valid");
  assert.deepEqual(first.sources.map((item) => item.source_id), ["SRC0007"]);
  assert.deepEqual(first.citations.map((item) => item.citation_id), ["CIT0008"]);
  assert.deepEqual(first.evidence.map((item) => item.evidence_id), ["EV0009"]);
  assert.deepEqual(first.slide_briefs.map((item) => item.slide_id), ["SLIDE0003"]);
  assert.equal(first.evidence[0].importance, 1);
  assert.equal(first.evidence[0].must_keep, false);
  assert.equal(first.evidence[0].content_role, "primary_claim");
  assert.deepEqual(first.slide_briefs[0].evidence_ids, ["EV0009"]);
  assert.ok(first.adaptation_log.some((item) => item.action === "deduplicate_exact"));
  assert.ok(first.adaptation_log.some((item) => item.action === "whitespace_cleanup"));
});

test("PaperWorkflow v4 maps EV/S/E and ranges through Citation to Source", () => {
  const workflow = {
    schema_version: 4,
    source: {
      source_sha256: "source-content-sha",
      markdown_sha256: "markdown-sha",
      source_fingerprint: "legacy-fingerprint",
      input_type: "pdf",
      input_path: "/not/read/source.pdf",
    },
    evidence_registry: [{
      evidence_id: "EV0042",
      span_id: "S0012",
      chunk_id: "E003",
      source_lines: { start: 12, end: 13 },
      source_chars: { start: 240, end: 318 },
      modality: "body_text",
      support_type: "direct_observation",
      text: "  The observed result.  ",
      query_ids: ["results", "results"],
      queries: ["  key results  "],
    }],
  };
  const result = normalizePaperWorkflowV4(workflow, {
    slide_briefs: [{
      slide_id: "SLIDE0002",
      title: "Results",
      evidence_ids: ["EV0042"],
      citation_ids: ["CIT0001"],
    }],
  });
  assert.equal(result.status, "valid");
  assert.equal(result.sources.length, 1);
  assert.equal(result.sources[0].source_sha256, "source-content-sha");
  assert.equal(result.sources[0].source_identity, "source-content-sha");
  assert.equal(result.citations.length, 1);
  assert.equal(result.citations[0].citation_id, "CIT0001");
  assert.equal(result.citations[0].source_id, result.sources[0].source_id);
  assert.equal(result.citations[0].evidence_id, "EV0042");
  assert.equal(result.citations[0].span_id, "S0012");
  assert.equal(result.citations[0].chunk_id, "E003");
  assert.deepEqual(result.citations[0].source_lines, { start: 12, end: 13 });
  assert.deepEqual(result.citations[0].source_chars, { start: 240, end: 318 });
  assert.equal(result.citations[0].source_chars_end_exclusive, true);
  assert.equal(result.evidence[0].evidence_id, "EV0042");
  assert.deepEqual(result.evidence[0].citation_ids, ["CIT0001"]);
  assert.deepEqual(result.slide_briefs[0].evidence_ids, ["EV0042"]);
  assert.deepEqual(result.slide_briefs[0].citation_ids, ["CIT0001"]);
  assert.equal(result.sources[0].input_path, "/not/read/source.pdf");
});

test("canonical and upstream records append then deduplicate by first-seen content", () => {
  const upstream = {
    schema_version: 4,
    source: { source_sha256: "same-source" },
    evidence_registry: [{
      evidence_id: "EV0001",
      span_id: "S0001",
      chunk_id: "E001",
      source_chars: { start: 0, end: 5 },
      source_lines: { start: 1, end: 1 },
      support_type: "figure_caption",
      text: "same",
    }],
  };
  const result = normalizeContentModel({
    sources: [{ source_id: "SRC0001", source_sha256: "same-source" }],
    citations: [{ citation_id: "CIT0001", source_id: "SRC0001", evidence_id: "EV0001", span_id: "S0001", chunk_id: "E001", source_chars: { start: 0, end: 5 }, source_lines: { start: 1, end: 1 }, support_type: "figure_caption", text: "same" }],
    evidence: [{ evidence_id: "EV0001", citation_ids: ["CIT0001"], source_id: "SRC0001", span_id: "S0001", chunk_id: "E001", source_chars: { start: 0, end: 5 }, source_lines: { start: 1, end: 1 }, support_type: "figure_caption", text: "same", content_role: "supporting_evidence" }],
    paperworkflow_v4: upstream,
  });
  assert.equal(result.status, "valid");
  assert.equal(result.sources.length, 1);
  assert.equal(result.citations.length, 1);
  assert.equal(result.evidence.length, 1);
  assert.ok(result.adaptation_log.some((item) => item.action === "deduplicate_identity"));
  assert.ok(result.adaptation_log.some((item) => item.action === "deduplicate_exact"));
});

test("conflicting duplicate IDs are invalid and do not silently overwrite the first record", () => {
  const result = normalizeContentModel({
    sources: [
      { source_id: "SRC0001", title: "First" },
      { source_id: "SRC0001", title: "Different" },
    ],
  });
  assert.equal(result.status, "invalid");
  assert.deepEqual(result.sources.map((item) => item.source_id), ["SRC0001", "SRC0002"]);
  assert.ok(result.violations.some((item) => item.code === "INVALID_INPUT" && item.field === "sources[1].source_id"));
  assert.ok(result.adaptation_log.some((item) => item.action === "reassign_generated_id"));
});

test("traceability failures are fixed-schema INVALID_INPUT violations", () => {
  const result = normalizeContentModel({
    sources: [{ source_id: "SRC0001", source_sha256: "sha" }],
    citations: [{ citation_id: "CIT0001", source_id: "SRC9999" }],
    evidence: [{ evidence_id: "EV0001", citation_ids: ["CIT9999"] }],
    slide_briefs: [{ slide_id: "SLIDE0001", evidence_ids: ["EV9999"], citation_ids: ["CIT9999"] }],
  });
  assert.equal(result.status, "invalid");
  for (const path of [
    "citations[0].source_id",
    "evidence[0].citation_ids[0]",
    "slide_briefs[0].evidence_ids[0]",
    "slide_briefs[0].citation_ids[0]",
  ]) assert.ok(result.violations.some((item) => item.path === path));
  assert.ok(result.violations.every((item) => item.code === "INVALID_INPUT"));
  assert.ok(result.violations.every((item) => Object.keys(item).every((key) => Object.hasOwn(VIOLATION_SCHEMA.properties, key))));
});

test("visual traceability refs are validated and included in coverage", () => {
  const invalid = normalizeContentModel({
    sources: [{ source_id: "SRC0001" }],
    citations: [{ citation_id: "CIT0001", source_id: "SRC0001", text: "来源" }],
    evidence: [{ evidence_id: "EV0001", citation_ids: ["CIT0001"], must_keep: true, text: "证据" }],
    slide_briefs: [{
      slide_id: "SLIDE0001",
      title: "结果",
      visuals: [{
        visual_id: "VISUAL0001",
        visual_type: "simple_plot",
        evidence_ids: ["EV9999"],
        citation_ids: ["CIT9999"],
      }],
    }],
  });
  assert.equal(invalid.status, "invalid");
  assert.ok(invalid.violations.some((item) => item.path === "slide_briefs[0].visuals[0].evidence_ids[0]"));
  assert.ok(invalid.violations.some((item) => item.path === "slide_briefs[0].visuals[0].citation_ids[0]"));

  const valid = normalizeContentModel({
    sources: [{ source_id: "SRC0001" }],
    citations: [{ citation_id: "CIT0001", source_id: "SRC0001", text: "来源" }],
    evidence: [{ evidence_id: "EV0001", citation_ids: ["CIT0001"], must_keep: true, text: "证据" }],
    slide_briefs: [{
      slide_id: "SLIDE0001",
      title: "结果",
      visuals: [{
        visual_id: "VISUAL0001",
        visual_type: "simple_plot",
        evidence_ids: ["EV0001"],
        citation_ids: ["CIT0001"],
      }],
    }],
  });
  assert.equal(valid.status, "valid");
  assert.deepEqual(valid.coverage.orphan_must_keep_evidence, []);
  assert.deepEqual(valid.coverage.unused_citations, []);
});

test("visual source pixel dimensions survive content normalization", () => {
  const result = normalizeContentModel({
    slide_briefs: [{
      slide_id: "SLIDE0001",
      title: "像素尺寸",
      visuals: [{
        visual_id: "VISUAL0001",
        visual_type: "simple_plot",
        source_width_px: 1600,
        source_height_px: 900,
      }],
    }],
  });
  assert.equal(result.status, "valid");
  assert.equal(result.slide_briefs[0].visuals[0].source_width_px, 1600);
  assert.equal(result.slide_briefs[0].visuals[0].source_height_px, 900);
});

test("importance, must_keep, content_role, and evidence type are normalized without semantic repair", () => {
  const result = normalizeContentModel({
    evidence: [
      { evidence_id: "EV0001", importance: -2.4, must_keep: "yes", content_role: "primary_evidence", support_type: "simulation", text: "  unchanged units: 2 mm  " },
      { evidence_id: "EV0002", importance: "3.6", must_keep: "0", content_role: "optional_visual", evidence_type: "fit", text: "x" },
    ],
  });
  assert.equal(result.status, "valid");
  assert.equal(result.evidence[0].importance, 1);
  assert.equal(result.evidence[0].must_keep, true);
  assert.equal(result.evidence[0].content_role, "primary_evidence");
  assert.equal(result.evidence[0].support_type, "simulation");
  assert.equal(result.evidence[0].text, "unchanged units: 2 mm");
  assert.equal(result.evidence[1].importance, 4);
  assert.equal(result.evidence[1].must_keep, false);
  assert.equal(result.evidence[1].content_role, "optional_visual");
  assert.equal(result.evidence[1].evidence_type, "fit");
  assert.deepEqual(CONTENT_ROLES, ["primary_claim", "primary_evidence", "supporting_evidence", "caption", "context", "optional_visual"]);
  assert.deepEqual(EVIDENCE_TYPES, ["direct_observation", "measurement", "simulation", "fit", "author_inference", "reviewer_inference", "extrapolation", "method_protocol", "figure_caption"]);
});

test("violation and adaptation factories expose only their fixed contract keys", () => {
  const violation = createViolation({ code: "INVALID_INPUT", field: "evidence[0]", actual: "x", capacity: "y", recommended_action: "fix", message: "bad", ignored: true });
  assert.deepEqual(Object.keys(violation), ["code", "field", "actual", "capacity", "severity", "recoverable", "recommended_action", "message"]);
  assert.equal(violation.severity, "error");
  assert.equal(violation.recoverable, true);
  assert.throws(() => createViolation({ code: "INVALID_INPUT", field: "x" }), /recommended_action/);

  const adaptation = createAdaptationLogEntry({ action: "whitespace_cleanup", content_id: "EV0001", reason: "cleanup", before_chars: 4, after_chars: 2, before: " x ", after: "x", details: { field: "text" }, ignored: true });
  assert.deepEqual(Object.keys(adaptation), ["action", "content_id", "reason", "before_chars", "after_chars", "before", "after", "details"]);
  assert.throws(() => createAdaptationLogEntry({ action: "x", content_id: "EV0001" }), /reason/);
});

test("schemas are frozen fixed contracts and normalizer never emits planning fields", () => {
  for (const schema of [SOURCE_SCHEMA, CITATION_SCHEMA, EVIDENCE_SCHEMA, SLIDE_BRIEF_SCHEMA, VIOLATION_SCHEMA, ADAPTATION_LOG_SCHEMA, CONTENT_MODEL_INPUT_SCHEMA]) {
    assert.equal(Object.isFrozen(schema), true);
    assert.equal(schema.additionalProperties, false);
    assert.ok((schema.required?.length ?? 0) > 0 || schema === CONTENT_MODEL_INPUT_SCHEMA);
  }
  const schemaKeys = collectKeys([SOURCE_SCHEMA, CITATION_SCHEMA, EVIDENCE_SCHEMA, SLIDE_BRIEF_SCHEMA, VIOLATION_SCHEMA, ADAPTATION_LOG_SCHEMA, CONTENT_MODEL_INPUT_SCHEMA]);
  for (const key of forbiddenKeys) assert.equal(schemaKeys.includes(key), false, `schema unexpectedly exposes ${key}`);
  assert.equal(Object.hasOwn(SLIDE_BRIEF_SCHEMA.properties.visuals.items.properties, "slot_id"), false);
  assert.equal(CONTENT_MODEL_INPUT_SCHEMA.properties.sources.items.required, undefined);
  assert.equal(CONTENT_MODEL_INPUT_SCHEMA.properties.slide_briefs.items.required, undefined);

  const result = normalizeContentModel({
    layout_id: "RM-NOT-A-LAYOUT",
    layout: { id: "ignored" },
    slot_specs: [{ slot_id: "ignored" }],
    slot_assignments: { title: { type: "text" } },
    sources: [{ source_id: "SRC0001", metadata: { layout: "ignored", slot_assignments: {} } }],
    slide_briefs: [{ slide_id: "SLIDE0001", title: "Title", visuals: [{ caption: "Caption", layout_id: "ignored", slot_id: "figure" }] }],
  });
  const outputKeys = collectKeys(result);
  for (const key of forbiddenKeys) assert.equal(outputKeys.includes(key), false, `normalizer emitted ${key}`);
  assert.equal(outputKeys.includes("slot_id"), false, "normalizer emitted a visual slot assignment");
  assert.ok(result.adaptation_log.some((item) => item.reason === "normalizer_does_not_assign_slots"));
  assert.equal(Object.keys(result).join(","), "schema_version,status,sources,citations,evidence,slide_briefs,violations,coverage,adaptation_log");
});

test("slide brief normalization preserves every structural collection for replanning", () => {
  const result = normalizeContentModel({
    slide_briefs: [{
      slide_id: "SLIDE0001",
      title: "结构化内容",
      timeline_events: [{ id: "t1", text: "里程碑" }],
      comparison_dimensions: [{ id: "d1", text: "准确率" }],
      experiment_groups: [{ id: "g1", text: "对照组" }],
      data_series: [{ id: "s1", text: "实验曲线" }],
    }],
  });
  assert.equal(result.status, "valid");
  assert.deepEqual(result.slide_briefs[0].timeline_events.map((item) => item.id), ["t1"]);
  assert.deepEqual(result.slide_briefs[0].comparison_dimensions.map((item) => item.id), ["d1"]);
  assert.deepEqual(result.slide_briefs[0].experiment_groups.map((item) => item.id), ["g1"]);
  assert.deepEqual(result.slide_briefs[0].data_series.map((item) => item.id), ["s1"]);
});

test("normalize surfaces orphan must-keep evidence and unused citations in coverage", () => {
  const result = normalizeContentModel({
    sources: [{ source_id: "SRC0001", title: "论文" }],
    citations: [
      { citation_id: "CIT0001", source_id: "SRC0001", text: "引用一" },
      { citation_id: "CIT0002", source_id: "SRC0001", text: "引用二" },
    ],
    evidence: [
      { evidence_id: "EV0001", citation_ids: ["CIT0001"], must_keep: true, text: "证据一" },
      { evidence_id: "EV0002", citation_ids: ["CIT0001"], must_keep: true, text: "证据二" },
    ],
    slide_briefs: [
      { slide_id: "SLIDE0001", slide_type: "cover", title: "封面", claims: [], evidence_ids: ["EV0001"], citation_ids: [] },
    ],
  });
  assert.equal(result.status, "valid");
  assert.ok(result.coverage.orphan_must_keep_evidence.includes("EV0002"));
  assert.ok(!result.coverage.orphan_must_keep_evidence.includes("EV0001"));
  assert.ok(result.coverage.unused_citations.includes("CIT0002"));
  assert.ok(!result.coverage.unused_citations.includes("CIT0001"));
});

test("normalize preserves body, text-flow hints, and evidence_texts on slide briefs", () => {
  const result = normalizeContentModel({
    sources: [{ source_id: "SRC0001", title: "论文" }],
    citations: [{ citation_id: "CIT0001", source_id: "SRC0001" }],
    evidence: [{ evidence_id: "EV0001", citation_ids: ["CIT0001"], must_keep: true, text: "证据原文" }],
    slide_briefs: [
      {
        slide_id: "SLIDE0001", slide_type: "theory", title: "方法", claims: ["软模"],
        body: "全部计算在 VASP 中完成，声子用位移法计算。",
        key_points: ["边界条件明确", "机制证据一致", "下一步实验可判别"],
        secondary_messages: ["保留段落顺序"],
        text_flow: "distributed_arrow_list",
        evidence_texts: [{ evidence_id: "EV0001", text: "证据原文" }],
        evidence_ids: ["EV0001"], citation_ids: [],
      },
    ],
  });
  assert.equal(result.status, "valid");
  assert.equal(result.slide_briefs[0].body, "全部计算在 VASP 中完成，声子用位移法计算。");
  assert.deepEqual(result.slide_briefs[0].key_points, ["边界条件明确", "机制证据一致", "下一步实验可判别"]);
  assert.deepEqual(result.slide_briefs[0].secondary_messages, ["保留段落顺序"]);
  assert.equal(result.slide_briefs[0].text_flow, "distributed_arrow_list");
  assert.deepEqual(result.slide_briefs[0].evidence_texts, [{ evidence_id: "EV0001", text: "证据原文" }]);
});
