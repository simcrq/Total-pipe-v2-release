#!/usr/bin/env node

import { runBenchmark } from "../server/benchmark.mjs";
import { assertSupportedNodeVersion } from "../server/runtime.mjs";

assertSupportedNodeVersion();

const iterationIndex = process.argv.indexOf("--iterations");
const iterations = iterationIndex >= 0 ? Number(process.argv[iterationIndex + 1]) : 20;
if (!Number.isInteger(iterations) || iterations < 1 || iterations > 200) {
  throw new RangeError("--iterations must be an integer from 1 to 200.");
}

const result = await runBenchmark({ iterations });
process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
if (result.status !== "passed") process.exitCode = 1;
