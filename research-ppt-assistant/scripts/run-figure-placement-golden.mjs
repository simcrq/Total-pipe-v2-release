#!/usr/bin/env node

import { runFigurePlacementGolden } from "../server/figure-placement-benchmark.mjs";

const args = process.argv.slice(2);
const unknown = args.find((arg) => arg !== "--require-source");
if (unknown !== undefined) {
  process.stderr.write(`Unknown argument: ${unknown}. Supported: --require-source\n`);
  process.exitCode = 1;
} else {
  const result = await runFigurePlacementGolden({ require_source: args.includes("--require-source") });
  process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
  if (result.status !== "passed") process.exitCode = 1;
}
