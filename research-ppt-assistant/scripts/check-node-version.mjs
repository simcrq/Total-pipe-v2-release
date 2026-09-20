#!/usr/bin/env node

import { MINIMUM_NODE_MAJOR, assertSupportedNodeVersion } from "../server/runtime.mjs";

try {
  assertSupportedNodeVersion();
  process.stdout.write(`Node.js runtime check passed: ${process.versions.node} (>=${MINIMUM_NODE_MAJOR})\n`);
} catch (error) {
  process.stderr.write(`${error.name}: ${error.message}\n`);
  process.exitCode = 1;
}
