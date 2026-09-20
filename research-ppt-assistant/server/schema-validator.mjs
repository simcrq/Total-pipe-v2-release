export const SCHEMA_VALIDATOR_VERSION = "1.0.0";

function valueType(value) {
  if (value === null) return "null";
  if (Array.isArray(value)) return "array";
  if (Number.isInteger(value)) return "integer";
  if (typeof value === "number") return "number";
  return typeof value;
}

function matchesType(value, expected) {
  if (expected === "null") return value === null;
  if (expected === "array") return Array.isArray(value);
  if (expected === "object") return value !== null && typeof value === "object" && !Array.isArray(value);
  if (expected === "integer") return Number.isFinite(value) && Number.isInteger(value);
  if (expected === "number") return Number.isFinite(value);
  return typeof value === expected;
}

function sameValue(left, right) {
  if (Object.is(left, right)) return true;
  if (left === null || right === null || typeof left !== "object" || typeof right !== "object") return false;
  if (Array.isArray(left) !== Array.isArray(right)) return false;
  if (Array.isArray(left)) {
    return left.length === right.length && left.every((item, index) => sameValue(item, right[index]));
  }
  const leftKeys = Object.keys(left);
  const rightKeys = Object.keys(right);
  return leftKeys.length === rightKeys.length
    && leftKeys.every((key) => Object.hasOwn(right, key) && sameValue(left[key], right[key]));
}

function childPath(path, key) {
  if (typeof key === "number") return `${path}[${key}]`;
  return /^[A-Za-z_$][\w$]*$/.test(key) ? `${path}.${key}` : `${path}[${JSON.stringify(key)}]`;
}

function pushError(errors, keyword, path, message, expected, actual) {
  errors.push({
    keyword,
    path,
    message,
    ...(expected === undefined ? {} : { expected }),
    ...(actual === undefined ? {} : { actual }),
  });
}

function validateNode(schema, value, path, errors) {
  if (schema === true || schema === undefined) return;
  if (schema === false) {
    pushError(errors, "falseSchema", path, "Value is not permitted by this schema.");
    return;
  }
  if (!schema || typeof schema !== "object" || Array.isArray(schema)) {
    throw new TypeError(`Invalid JSON Schema at ${path}`);
  }

  if (Array.isArray(schema.allOf)) {
    for (const branch of schema.allOf) validateNode(branch, value, path, errors);
  }
  if (Array.isArray(schema.anyOf)) {
    const valid = schema.anyOf.some((branch) => {
      const branchErrors = [];
      validateNode(branch, value, path, branchErrors);
      return branchErrors.length === 0;
    });
    if (!valid) pushError(errors, "anyOf", path, "Value must match at least one allowed schema.");
  }
  if (Array.isArray(schema.oneOf)) {
    const matchCount = schema.oneOf.filter((branch) => {
      const branchErrors = [];
      validateNode(branch, value, path, branchErrors);
      return branchErrors.length === 0;
    }).length;
    if (matchCount !== 1) pushError(errors, "oneOf", path, "Value must match exactly one allowed schema.", 1, matchCount);
  }
  if (schema.not !== undefined) {
    const branchErrors = [];
    validateNode(schema.not, value, path, branchErrors);
    if (branchErrors.length === 0) pushError(errors, "not", path, "Value matches a forbidden schema.");
  }

  if (schema.const !== undefined && !sameValue(value, schema.const)) {
    pushError(errors, "const", path, "Value must equal the declared constant.", schema.const, value);
  }
  if (Array.isArray(schema.enum) && !schema.enum.some((candidate) => sameValue(value, candidate))) {
    pushError(errors, "enum", path, "Value is not one of the allowed values.", schema.enum, value);
  }

  if (schema.type !== undefined) {
    const expectedTypes = Array.isArray(schema.type) ? schema.type : [schema.type];
    if (!expectedTypes.some((type) => matchesType(value, type))) {
      pushError(errors, "type", path, `Expected ${expectedTypes.join(" or ")}, received ${valueType(value)}.`, expectedTypes, valueType(value));
      return;
    }
  }

  if (typeof value === "string") {
    const length = [...value].length;
    if (Number.isInteger(schema.minLength) && length < schema.minLength) {
      pushError(errors, "minLength", path, `String must contain at least ${schema.minLength} characters.`, schema.minLength, length);
    }
    if (Number.isInteger(schema.maxLength) && length > schema.maxLength) {
      pushError(errors, "maxLength", path, `String must contain at most ${schema.maxLength} characters.`, schema.maxLength, length);
    }
    if (typeof schema.pattern === "string" && !new RegExp(schema.pattern).test(value)) {
      pushError(errors, "pattern", path, `String must match ${schema.pattern}.`, schema.pattern, value);
    }
  }

  if (typeof value === "number" && Number.isFinite(value)) {
    if (typeof schema.minimum === "number" && value < schema.minimum) {
      pushError(errors, "minimum", path, `Number must be at least ${schema.minimum}.`, schema.minimum, value);
    }
    if (typeof schema.maximum === "number" && value > schema.maximum) {
      pushError(errors, "maximum", path, `Number must be at most ${schema.maximum}.`, schema.maximum, value);
    }
    if (typeof schema.exclusiveMinimum === "number" && value <= schema.exclusiveMinimum) {
      pushError(errors, "exclusiveMinimum", path, `Number must be greater than ${schema.exclusiveMinimum}.`, schema.exclusiveMinimum, value);
    }
    if (typeof schema.exclusiveMaximum === "number" && value >= schema.exclusiveMaximum) {
      pushError(errors, "exclusiveMaximum", path, `Number must be less than ${schema.exclusiveMaximum}.`, schema.exclusiveMaximum, value);
    }
  }

  if (Array.isArray(value)) {
    if (Number.isInteger(schema.minItems) && value.length < schema.minItems) {
      pushError(errors, "minItems", path, `Array must contain at least ${schema.minItems} items.`, schema.minItems, value.length);
    }
    if (Number.isInteger(schema.maxItems) && value.length > schema.maxItems) {
      pushError(errors, "maxItems", path, `Array must contain at most ${schema.maxItems} items.`, schema.maxItems, value.length);
    }
    if (schema.uniqueItems === true) {
      for (let index = 0; index < value.length; index += 1) {
        if (value.slice(0, index).some((item) => sameValue(item, value[index]))) {
          pushError(errors, "uniqueItems", childPath(path, index), "Array items must be unique.");
        }
      }
    }
    if (schema.items !== undefined) {
      value.forEach((item, index) => validateNode(schema.items, item, childPath(path, index), errors));
    }
  }

  if (value !== null && typeof value === "object" && !Array.isArray(value)) {
    const properties = schema.properties && typeof schema.properties === "object" ? schema.properties : {};
    const required = Array.isArray(schema.required) ? schema.required : [];
    for (const key of required) {
      if (!Object.hasOwn(value, key)) {
        pushError(errors, "required", childPath(path, key), `Required property ${key} is missing.`, key);
      }
    }
    for (const [key, item] of Object.entries(value)) {
      if (Object.hasOwn(properties, key)) {
        validateNode(properties[key], item, childPath(path, key), errors);
      } else if (schema.additionalProperties === false) {
        pushError(errors, "additionalProperties", childPath(path, key), `Property ${key} is not allowed.`, Object.keys(properties), key);
      } else if (schema.additionalProperties && typeof schema.additionalProperties === "object") {
        validateNode(schema.additionalProperties, item, childPath(path, key), errors);
      }
    }
    const propertyCount = Object.keys(value).length;
    if (Number.isInteger(schema.minProperties) && propertyCount < schema.minProperties) {
      pushError(errors, "minProperties", path, `Object must contain at least ${schema.minProperties} properties.`, schema.minProperties, propertyCount);
    }
    if (Number.isInteger(schema.maxProperties) && propertyCount > schema.maxProperties) {
      pushError(errors, "maxProperties", path, `Object must contain at most ${schema.maxProperties} properties.`, schema.maxProperties, propertyCount);
    }
  }
}

export function validateJsonSchema(schema, value, options = {}) {
  const errors = [];
  validateNode(schema, value, options.path ?? "$", errors);
  return {
    status: errors.length ? "invalid" : "valid",
    valid: errors.length === 0,
    errors,
  };
}

export class McpInputSchemaError extends TypeError {
  constructor(toolName, errors) {
    const summary = errors.slice(0, 3).map((error) => `${error.path}: ${error.message}`).join("; ");
    super(`Invalid input for ${toolName}: ${summary}${errors.length > 3 ? `; plus ${errors.length - 3} more error(s)` : ""}`);
    this.name = "McpInputSchemaError";
    this.code = "MCP_INPUT_SCHEMA_ERROR";
    this.schemaErrors = errors;
  }
}

export function assertJsonSchema(schema, value, options = {}) {
  const result = validateJsonSchema(schema, value, options);
  if (!result.valid) throw new McpInputSchemaError(options.toolName ?? "tool", result.errors);
  return value;
}
