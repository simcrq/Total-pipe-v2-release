import assert from "node:assert/strict";
import test from "node:test";
import {
  planSlideClosedLoop,
  splitSlideBrief,
} from "../server/planning-loop.mjs";

function processLayout(id = "WORKFLOW-5") {
  return {
    id,
    slot_specs: [
      { slot_id: "title", slot_type: "text", required: true, capacity: { max_chars: 60 }, priority: 5 },
      ...Array.from({ length: 5 }, (_, index) => ({
        slot_id: `step${index + 1}`,
        slot_type: "process",
        required: true,
        capacity: { max_chars: 60 },
        priority: 2,
      })),
    ],
  };
}

function brief(stepCount = 10) {
  return {
    slide_id: "SLIDE0001",
    title: "十步流程",
    process_steps: Array.from({ length: stepCount }, (_, index) => ({ id: `step-${index + 1}`, text: `步骤 ${index + 1}` })),
  };
}

test("splitSlideBrief creates deterministic order-preserving children", () => {
  const source = { ...brief(), process_step_count: 10, text_chars: 101, text_chars_by_role: { process: 81 }, duration_weight: 2 };
  const children = splitSlideBrief(source, { process_capacity: 5 });
  assert.equal(children.length, 2);
  assert.deepEqual(children.map((child) => child.slide_id), ["SLIDE0001-part-1", "SLIDE0001-part-2"]);
  assert.deepEqual(children.map((child) => child.title), ["十步流程（1/2）", "十步流程（2/2）"]);
  assert.deepEqual(children.flatMap((child) => child.process_steps.map((step) => step.id)), Array.from({ length: 10 }, (_, index) => `step-${index + 1}`));
  assert.deepEqual(children.map((child) => child.process_step_count), [5, 5]);
  assert.deepEqual(children.map((child) => child.text_chars), [50, 51]);
  assert.deepEqual(children.map((child) => child.text_chars_by_role.process), [40, 41]);
  assert.equal(children.reduce((sum, child) => sum + child.duration_weight, 0), 2);
});

test("closed loop auto-splits ten steps into two legal ordered slides", async () => {
  const calls = [];
  const result = await planSlideClosedLoop(
    { slide_brief: brief(), allow_auto_split: true, max_replan_attempts: 2 },
    {
      searchLayouts: async (query) => {
        calls.push(query);
        return { results: [processLayout()] };
      },
    },
  );
  assert.equal(result.status, "success");
  assert.equal(result.planning_decision, "split");
  assert.equal(result.slides.length, 2);
  assert.deepEqual(result.slides.flatMap((slide) => slide.slide_brief.process_steps.map((step) => step.id)), Array.from({ length: 10 }, (_, index) => `step-${index + 1}`));
  assert.ok(result.slides.every((slide) => slide.status === "success" && slide.contract_valid));
  assert.equal(calls[0].process_step_count, 10);
});

test("allow_auto_split false keeps the overloaded brief intact", async () => {
  const result = await planSlideClosedLoop(
    { slide_brief: brief(), allow_auto_split: false, max_replan_attempts: 0 },
    { searchLayouts: async () => ({ results: [processLayout()] }) },
  );
  assert.equal(result.status, "needs_replan");
  assert.equal(result.planning_decision, "single");
  assert.equal(result.slides.length, 0);
  assert.equal(result.unplanned_slide_briefs.length, 1);
  assert.equal(result.unplanned_slide_briefs[0].process_steps.length, 10);
  assert.equal(result.unplanned_slide_briefs[0].metadata?.planning_split_count, undefined);
});

test("replan excludes a rejected layout and never binds it again", async () => {
  const calls = [];
  const bad = { id: "BAD", slot_specs: [{ slot_id: "title", slot_type: "text", required: true, capacity: { max_chars: 60 } }] };
  const good = { id: "GOOD", slot_specs: [{ slot_id: "title", slot_type: "text", required: true, capacity: { max_chars: 60 } }] };
  const result = await planSlideClosedLoop(
    { slide_brief: { slide_id: "SLIDE0001", title: "重规划" }, max_replan_attempts: 2 },
    {
      searchLayouts: async (query) => {
        calls.push(query);
        return { results: query.exclude_ids.includes("BAD") ? [good] : [bad] };
      },
      bindSlide: async ({ layout_spec }) => layout_spec.id === "BAD"
        ? { status: "needs_replan", layout_id: "BAD", slot_assignments: {}, adaptation_log: [], violations: [{ code: "SLOT_CAPACITY_EXCEEDED", field: "title", actual: 99, capacity: 1, severity: "error", recoverable: true, recommended_action: "replan_or_split" }] }
        : { status: "success", layout_id: "GOOD", slot_assignments: { title: { type: "text", text: "重规划", content_id: "SLIDE0001:title:1" } }, adaptation_log: [], violations: [] },
    },
  );
  assert.equal(result.status, "success");
  assert.equal(result.slides[0].layout_id, "GOOD");
  assert.deepEqual(result.replan_context.rejected_layout_ids, ["BAD"]);
  assert.ok(calls[1].exclude_ids.includes("BAD"));
});

test("replan exhaustion is explicit and bounded", async () => {
  const boundIds = [];
  const result = await planSlideClosedLoop(
    { slide_brief: { slide_id: "SLIDE0001", title: "无法规划" }, max_replan_attempts: 1 },
    {
      searchLayouts: async () => ({ results: [{ id: "BAD", slot_specs: [{ slot_id: "title", slot_type: "text", required: true, capacity: { max_chars: 60 } }] }] }),
      bindSlide: async ({ layout_spec }) => {
        boundIds.push(layout_spec.id);
        return { status: "needs_replan", layout_id: layout_spec.id, slot_assignments: {}, adaptation_log: [], violations: [{ code: "SLOT_CAPACITY_EXCEEDED", field: "title", actual: 99, capacity: 1, severity: "error", recoverable: true, recommended_action: "replan_or_split" }] };
      },
    },
  );
  assert.equal(result.status, "needs_replan");
  assert.ok(result.replan_context.violations.some((issue) => issue.code === "REPLAN_EXHAUSTED"));
  assert.deepEqual(boundIds, ["BAD"]);
  assert.equal(result.replan_context.replan_attempt, 1);
});

test("a successful adapter result without assignments is rejected by the contract", async () => {
  const result = await planSlideClosedLoop(
    { slide_brief: { slide_id: "SLIDE0001", title: "非法成功" }, max_replan_attempts: 0 },
    {
      searchLayouts: async () => ({ results: [{ id: "BAD", slot_specs: [{ slot_id: "title", slot_type: "text", required: true, capacity: { max_chars: 60 } }] }] }),
      bindSlide: async () => ({ status: "success", layout_id: "BAD", adaptation_log: [], violations: [] }),
    },
  );
  assert.equal(result.status, "needs_replan");
  assert.ok(result.replan_context.violations.some((issue) => issue.code === "INVALID_SLOT_ASSIGNMENTS"));
});
