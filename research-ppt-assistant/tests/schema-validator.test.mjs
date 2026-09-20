import assert from "node:assert/strict";
import test from "node:test";
import { assertJsonSchema, McpInputSchemaError, validateJsonSchema } from "../server/schema-validator.mjs";

const schema = {
  type: "object",
  properties: {
    mode: { enum: ["compact", "full"] },
    request: {
      type: "object",
      properties: {
        title: { type: "string", minLength: 1 },
        scores: { type: "array", minItems: 1, items: { type: "number", minimum: 0, maximum: 1 } },
      },
      required: ["title", "scores"],
      additionalProperties: false,
    },
  },
  required: ["mode", "request"],
  additionalProperties: false,
};

test("schema validator accepts nested objects and array items", () => {
  const result = validateJsonSchema(schema, {
    mode: "compact",
    request: { title: "Result", scores: [0, 0.5, 1] },
  });
  assert.equal(result.valid, true);
  assert.deepEqual(result.errors, []);
});

test("schema validator reports required, type, enum, extra, nested, and array-item failures", () => {
  const cases = [
    [{ request: { title: "Result", scores: [0.5] } }, "required", "$.mode"],
    [{ mode: "compact", request: "invalid" }, "type", "$.request"],
    [{ mode: "standard", request: { title: "Result", scores: [0.5] } }, "enum", "$.mode"],
    [{ mode: "compact", request: { title: "Result", scores: [0.5] }, extra: true }, "additionalProperties", "$.extra"],
    [{ mode: "compact", request: { scores: [0.5] } }, "required", "$.request.title"],
    [{ mode: "compact", request: { title: "Result", scores: ["0.5"] } }, "type", "$.request.scores[0]"],
  ];
  for (const [value, keyword, path] of cases) {
    const result = validateJsonSchema(schema, value);
    assert.equal(result.valid, false, `${keyword} should fail`);
    assert.ok(result.errors.some((error) => error.keyword === keyword && error.path === path), JSON.stringify(result.errors));
  }
});

test("assertJsonSchema throws a structured MCP input error", () => {
  assert.throws(
    () => assertJsonSchema(schema, {}, { toolName: "example" }),
    (error) => {
      assert.ok(error instanceof McpInputSchemaError);
      assert.equal(error.code, "MCP_INPUT_SCHEMA_ERROR");
      assert.ok(error.schemaErrors.some((item) => item.keyword === "required"));
      return true;
    },
  );
});

test("schema validator exercises composition, scalar, collection, and property constraints", () => {
  const constrained = {
    allOf: [{ type: "object" }],
    type: "object",
    properties: {
      forbidden: { not: { const: "blocked" } },
      choice: { anyOf: [{ type: "string", pattern: "^ok$" }, { type: "integer", minimum: 1 }] },
      exclusive: { oneOf: [{ type: "integer" }, { type: "number" }] },
      text: { type: "string", minLength: 2, maxLength: 4, pattern: "^[A-Z]+$" },
      number: { type: "number", minimum: 1, maximum: 5, exclusiveMinimum: 0, exclusiveMaximum: 6 },
      list: { type: "array", minItems: 2, maxItems: 3, uniqueItems: true, items: { type: ["string", "null"] } },
      fixed: { const: { nested: [1, 2] } },
    },
    additionalProperties: { type: "boolean" },
    minProperties: 2,
    maxProperties: 8,
  };
  const invalid = validateJsonSchema(constrained, {
    forbidden: "blocked",
    choice: false,
    exclusive: 2,
    text: "a",
    number: 7,
    list: ["same", "same", 3, null],
    fixed: { nested: [1, 3] },
    extra: "not boolean",
    ninth: true,
  }, { path: "$['root value']" });
  const keywords = new Set(invalid.errors.map((error) => error.keyword));
  for (const keyword of ["not", "anyOf", "oneOf", "minLength", "pattern", "maximum", "uniqueItems", "maxItems", "type", "const", "maxProperties"]) {
    assert.ok(keywords.has(keyword), `missing ${keyword}`);
  }

  const bounds = [
    [{ type: "string", maxLength: 1 }, "AB", "maxLength"],
    [{ type: "number", minimum: 2 }, 1, "minimum"],
    [{ type: "number", exclusiveMinimum: 1 }, 1, "exclusiveMinimum"],
    [{ type: "number", exclusiveMaximum: 1 }, 1, "exclusiveMaximum"],
    [{ type: "array", minItems: 2 }, [], "minItems"],
    [{ type: "object", minProperties: 1 }, {}, "minProperties"],
    [false, "anything", "falseSchema"],
  ];
  for (const [candidateSchema, value, keyword] of bounds) {
    assert.ok(validateJsonSchema(candidateSchema, value).errors.some((error) => error.keyword === keyword));
  }
  assert.equal(validateJsonSchema(true, null).valid, true);
  assert.equal(validateJsonSchema(undefined, null).valid, true);
  assert.throws(() => validateJsonSchema("invalid", 1), /Invalid JSON Schema/);
});
