import assert from "node:assert/strict";
import test from "node:test";
import {
  bindSlideToLayout,
  truncateTextDeterministically,
  validateSlotBindingContract,
} from "../server/slot-binding.mjs";

function slot(slot_id, slot_type, { required = false, max_chars = 80, priority = 1 } = {}) {
  return { slot_id, slot_type, required, capacity: { max_chars }, priority };
}

function layout(id, slots) {
  return { id, slot_specs: slots };
}

test("trimming prefers a sentence boundary and hard-cuts with a bounded ellipsis", () => {
  assert.equal(truncateTextDeterministically("1234567。abcdefghijkl", 10), "1234567。");
  assert.equal(truncateTextDeterministically("abcdefghijk", 8), "abcde...");
  assert.equal([...truncateTextDeterministically("😀😀😀😀😀", 4)].length, 4);
});

test("safe body trimming is logged and returns adapted", () => {
  const result = bindSlideToLayout({
    slide_brief: { slide_id: "SLIDE0001", title: "标题", notes: "1234567。abcdefghijkl" },
    layout_spec: layout("TEXT", [
      slot("title", "text", { required: true, max_chars: 20, priority: 5 }),
      slot("body", "text", { required: true, max_chars: 10, priority: 2 }),
    ]),
  });
  assert.equal(result.status, "adapted");
  assert.equal(result.slot_assignments.body.text, "1234567。");
  assert.ok(result.adaptation_log.some((entry) => entry.action === "truncate_text" && entry.content_id === "SLIDE0001:notes:1"));
  assert.ok(result.contract_valid);
});

test("parallel key points bind as one ordered multiline text group", () => {
  const result = bindSlideToLayout({
    slide_brief: {
      slide_id: "SLIDE0001",
      title: "适用边界",
      key_points: ["第一条边界", "第二条证据", "第三条实验"],
      text_flow: "distributed_arrow_list",
    },
    layout_spec: layout("TEXT-FLOW", [
      slot("title", "text", { required: true, max_chars: 20, priority: 5 }),
      slot("body", "text", { required: true, max_chars: 80, priority: 2 }),
    ]),
  });
  assert.equal(result.status, "success");
  assert.equal(result.slot_assignments.body.text, "第一条边界\n第二条证据\n第三条实验");
  assert.deepEqual(result.slot_assignments.body.items, ["第一条边界", "第二条证据", "第三条实验"]);
});

test("unknown explicit slot fails without falling back", () => {
  const result = bindSlideToLayout({
    slide_brief: { slide_id: "SLIDE0001", title: "标题", claims: [{ id: "claim-1", text: "不能回退", slot_id: "missing" }] },
    layout_spec: layout("TEXT", [
      slot("title", "text", { required: true, max_chars: 20, priority: 5 }),
      slot("body", "text", { required: false, max_chars: 80, priority: 1 }),
    ]),
  });
  assert.equal(result.status, "failed");
  assert.ok(result.violations.some((issue) => issue.code === "INVALID_EXPLICIT_SLOT"));
  assert.equal(result.slot_assignments.body, undefined);
});

test("explicit incompatible slot fails instead of using another compatible slot", () => {
  const result = bindSlideToLayout({
    slide_brief: {
      slide_id: "SLIDE0001",
      title: "标题",
      visuals: [{ visual_id: "v1", asset_uri: "figure.png", slot_id: "title" }],
    },
    layout_spec: layout("FIGURE", [
      slot("title", "text", { required: true, max_chars: 20, priority: 5 }),
      slot("figure", "image", { required: false, max_chars: 80, priority: 1 }),
    ]),
  });
  assert.equal(result.status, "failed");
  assert.ok(result.violations.some((issue) => issue.code === "SLOT_TYPE_MISMATCH"));
  assert.equal(result.slot_assignments.figure, undefined);
});

test("binding rejects a layout spec whose id differs from the selected layout", () => {
  const result = bindSlideToLayout({
    layout_id: "EXPECTED",
    slide_brief: { slide_id: "SLIDE0001", title: "标题" },
    layout_spec: layout("OTHER", [slot("title", "text", { required: true, max_chars: 20, priority: 5 })]),
  });
  assert.equal(result.status, "failed");
  assert.ok(result.violations.some((issue) => issue.code === "INVALID_LAYOUT_SPEC" && issue.details?.expected_layout_id === "EXPECTED"));
});

test("ten process steps against five process slots require replanning", () => {
  const result = bindSlideToLayout({
    slide_brief: {
      slide_id: "SLIDE0001",
      title: "十步流程",
      process_steps: Array.from({ length: 10 }, (_, index) => ({ id: `step-${index + 1}`, text: `步骤 ${index + 1}` })),
    },
    layout_spec: layout("WORKFLOW-5", [
      slot("title", "text", { required: true, max_chars: 40, priority: 5 }),
      ...Array.from({ length: 5 }, (_, index) => slot(`step${index + 1}`, "process", { required: true, max_chars: 40, priority: 2 })),
    ]),
  });
  assert.equal(result.status, "needs_replan");
  assert.ok(result.violations.some((issue) => issue.code === "PROCESS_CAPACITY_EXCEEDED"));
  assert.equal(result.slot_assignments.step1.content_id, "step-1");
  assert.equal(result.slot_assignments.step5.content_id, "step-5");
  assert.equal(result.slot_assignments.step6, undefined);
});

test("must-keep visual overflow replans and never logs a silent drop", () => {
  const result = bindSlideToLayout({
    slide_brief: {
      slide_id: "SLIDE0001",
      title: "结果",
      visuals: [
        { visual_id: "v1", asset_uri: "one.png", must_keep: true, importance: 1 },
        { visual_id: "v2", asset_uri: "two.png", must_keep: true, importance: 2 },
      ],
    },
    layout_spec: layout("FIGURE-1", [
      slot("title", "text", { required: true, max_chars: 40, priority: 5 }),
      slot("figure", "image", { required: false, max_chars: 40, priority: 1 }),
    ]),
  });
  assert.equal(result.status, "needs_replan");
  assert.ok(result.violations.some((issue) => issue.code === "FIGURE_CAPACITY_EXCEEDED"));
  assert.equal(result.adaptation_log.some((entry) => entry.action === "drop_optional_visual"), false);
});

test("optional visuals use must-keep, importance, then stable input order", () => {
  const result = bindSlideToLayout({
    slide_brief: {
      slide_id: "SLIDE0001",
      title: "视觉选择",
      visuals: [
        { visual_id: "v1", asset_uri: "one.png", must_keep: true, importance: 3 },
        { visual_id: "v2", asset_uri: "two.png", importance: 1 },
        { visual_id: "v3", asset_uri: "three.png", importance: 1 },
        { visual_id: "v4", asset_uri: "four.png", importance: 2 },
      ],
    },
    layout_spec: layout("FIGURE-2", [
      slot("title", "text", { required: true, max_chars: 40, priority: 5 }),
      slot("figure1", "image", { required: false, max_chars: 40, priority: 2 }),
      slot("figure2", "image", { required: false, max_chars: 40, priority: 1 }),
    ]),
  });
  assert.equal(result.status, "adapted");
  assert.equal(result.slot_assignments.figure1.content_id, "v1");
  assert.equal(result.slot_assignments.figure2.content_id, "v2");
  assert.deepEqual(
    result.adaptation_log.filter((entry) => entry.action === "drop_optional_visual").map((entry) => entry.content_id),
    ["v3", "v4"],
  );
});

test("a legal binding passes the contract validator round-trip", () => {
  const brief = {
    slide_id: "SLIDE0001",
    title: "流程",
    process_steps: [{ id: "step-1", text: "输入" }],
    visuals: [{ visual_id: "v1", asset_uri: "figure.png" }],
  };
  const spec = layout("ROUNDTRIP", [
    slot("title", "text", { required: true, max_chars: 40, priority: 5 }),
    slot("step1", "process", { required: true, max_chars: 40, priority: 3 }),
    slot("figure", "image", { required: false, max_chars: 40, priority: 1 }),
  ]);
  const binding = bindSlideToLayout({ slide_brief: brief, layout_spec: spec });
  const validation = validateSlotBindingContract({
    slide_brief: brief,
    layout_spec: spec,
    slot_specs: binding.slot_specs,
    slot_assignments: binding.slot_assignments,
    adaptation_log: binding.adaptation_log,
  });
  assert.equal(binding.status, "success");
  assert.equal(validation.valid, true);
  assert.equal(validation.status, "valid");
});

test("mandatory citations and evidence share one traceability slot without loss", () => {
  const brief = {
    slide_id: "SLIDE0001",
    title: "可追踪结果",
    citation_ids: ["CIT0001", "CIT0002"],
    evidence_ids: ["EV0001", "EV0002"],
  };
  const spec = layout("TRACE", [
    slot("title", "text", { required: true, max_chars: 40, priority: 5 }),
    slot("reference", "text", { required: true, max_chars: 80, priority: 1 }),
  ]);
  const binding = bindSlideToLayout({ slide_brief: brief, layout_spec: spec });
  assert.equal(binding.status, "success");
  assert.deepEqual(binding.slot_assignments.reference.citation_ids, ["CIT0001", "CIT0002"]);
  assert.deepEqual(binding.slot_assignments.reference.evidence_ids, ["EV0001", "EV0002"]);
  assert.equal(binding.contract_valid, true);
});

test("visual traceability refs can repeat in a caption without duplicate ownership", () => {
  const brief = {
    slide_id: "SLIDE0001",
    title: "可追踪图表",
    visuals: [{
      visual_id: "v1",
      visual_type: "simple_plot",
      asset_uri: "figure.png",
      evidence_ids: ["EV0001"],
      citation_ids: ["CIT0001"],
    }],
    evidence_ids: ["EV0001"],
    citation_ids: ["CIT0001"],
  };
  const spec = layout("TRACE_FIGURE", [
    slot("title", "text", { required: true, max_chars: 40, priority: 5 }),
    slot("figure", "image", { required: false, max_chars: 80, priority: 2 }),
    slot("caption", "text", { required: false, max_chars: 80, priority: 1 }),
  ]);
  const binding = bindSlideToLayout({ slide_brief: brief, layout_spec: spec });
  assert.equal(binding.status, "success");
  assert.equal(binding.contract_valid, true);
  assert.deepEqual(binding.slot_assignments.figure.visual.evidence_ids, ["EV0001"]);
  assert.deepEqual(binding.slot_assignments.caption.evidence_ids, ["EV0001"]);
  assert.deepEqual(binding.slot_assignments.caption.citation_ids, ["CIT0001"]);
});

test("duplicate primary content ownership across slots remains blocked", () => {
  const spec = layout("DUPLICATE", [
    slot("left", "text"),
    slot("right", "text"),
  ]);
  const validation = validateSlotBindingContract({
    layout_spec: spec,
    slot_assignments: {
      left: { type: "text", content_id: "claim-1", text: "同一主内容" },
      right: { type: "text", content_id: "claim-1", text: "同一主内容" },
    },
  });
  assert.equal(validation.valid, false);
  assert.ok(validation.violations.some((issue) => issue.code === "DUPLICATE_SLOT_OWNERSHIP" && issue.actual === "claim-1"));
});

test("the same visual remains exclusive when assignments use different content ids", () => {
  const spec = layout("DUPLICATE_VISUAL", [
    slot("left", "image"),
    slot("right", "image"),
  ]);
  const validation = validateSlotBindingContract({
    layout_spec: spec,
    slot_assignments: {
      left: { type: "image", content_id: "content-left", visual_id: "visual-1", asset_uri: "one.png" },
      right: { type: "image", content_id: "content-right", visual_id: "visual-1", asset_uri: "one.png" },
    },
  });
  assert.equal(validation.valid, false);
  assert.ok(validation.violations.some((issue) => issue.code === "DUPLICATE_SLOT_OWNERSHIP" && issue.actual === "visual-1"));
});
