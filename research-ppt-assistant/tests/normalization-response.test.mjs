import assert from "node:assert/strict";
import test from "node:test";
import { normalizeContentModel } from "../server/content-model.mjs";
import { formatStructuredContent } from "../server/response-format.mjs";

test("compact normalization preserves orphan must-keep evidence findings", () => {
  const normalized = normalizeContentModel({
    sources: [{ source_id: "SRC0001" }],
    citations: [{ citation_id: "CIT0001", source_id: "SRC0001" }],
    evidence: [{ evidence_id: "EV0001", evidence: "Required finding", citation_ids: ["CIT0001"], must_keep: true }],
    slide_briefs: [],
  });
  assert.deepEqual(normalized.coverage.orphan_must_keep_evidence, ["EV0001"]);
  const compact = formatStructuredContent("normalize_content", normalized, "compact");
  assert.deepEqual(compact.coverage, normalized.coverage);
});
